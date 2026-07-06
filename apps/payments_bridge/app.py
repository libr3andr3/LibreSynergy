#!/usr/bin/env python3
"""
payments-bridge — the $20/mo Premium checkout for the community.

Flow:
  1. User hits /upgrade. If not logged in, we run OIDC against Authentik so we know who
     they are, then show the upgrade page (Card via Stripe / Crypto via BTCPay).
  2. /checkout/stripe creates a Stripe subscription Checkout Session.
     /checkout/btcpay creates a BTCPay (BTC/Monero) invoice.
  3. /webhook/stripe and /webhook/btcpay are signature-verified. On payment we set the
     user's desired-premium state and reconcile it to the Authentik `premium` group
     (the single source of truth), then ping membership-sync for an instant Matrix sync.

Premium state (per user) is tracked in STATE_DIR/state.json:
  { "<username>": {"stripe": true/false, "btcpay_until": <epoch|null>} }
A user is premium if stripe is active OR btcpay_until is in the future. A sweeper thread
revokes premium once all rails have lapsed. Authentik group membership is reconciled to
match. Pure stdlib — no pip deps.
"""
import base64, hashlib, hmac, html, json, os, threading, time, urllib.parse, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- config ----
def env(k, d=None, required=False):
    v = os.environ.get(k, d)
    if required and not v:
        raise SystemExit(f"missing required env {k}")
    return v

OIDC_AUTHORIZE_URL = env("OIDC_AUTHORIZE_URL", required=True)
OIDC_TOKEN_URL = env("OIDC_TOKEN_URL", required=True)
OIDC_USERINFO_URL = env("OIDC_USERINFO_URL", required=True)
OIDC_CLIENT_ID = env("OIDC_CLIENT_ID", required=True)
OIDC_CLIENT_SECRET = env("OIDC_CLIENT_SECRET", required=True)
OIDC_REDIRECT_URI = env("OIDC_REDIRECT_URI", required=True)
SESSION_SECRET = env("SESSION_SECRET", required=True).encode()
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "https://premium.yaya.sh").rstrip("/")
CHAT_URL = env("COMMUNITY_CHAT_URL", "https://chat.yaya.sh")
MEMBERSHIP_SYNC_URL = env("MEMBERSHIP_SYNC_URL", "http://127.0.0.1:9101/reconcile")
PRICE_USD = env("PREMIUM_PRICE_USD", "20")
LISTEN_HOST = env("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(env("LISTEN_PORT", "9092"))
STATE_DIR = env("STATE_DIR", "/state")

AUTHENTIK_URL = env("AUTHENTIK_URL", "http://127.0.0.1:8300").rstrip("/")
AUTHENTIK_TOKEN = env("AUTHENTIK_TOKEN", required=True)
PREMIUM_GROUP = env("PREMIUM_GROUP", "premium")
AUTHENTIK_PUBLIC_HOST = env("AUTHENTIK_PUBLIC_HOST", "auth.yaya.sh")
AUTHENTIK_EMAIL_STAGE = env("AUTHENTIK_EMAIL_STAGE", "")

STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = env("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", "")
STRIPE_API = "https://api.stripe.com/v1"

BTCPAY_URL = env("BTCPAY_URL", "").rstrip("/")
BTCPAY_API_KEY = env("BTCPAY_API_KEY", "")
BTCPAY_STORE_ID = env("BTCPAY_STORE_ID", "")
BTCPAY_WEBHOOK_SECRET = env("BTCPAY_WEBHOOK_SECRET", "")

# ---- Solana USDC (Solana Pay reference flow) ----
# Non-custodial: one merchant address receives every invoice; each invoice gets a
# unique `reference` pubkey (a read-only marker the payer's wallet includes) so we
# can tell payments apart. A watcher polls a hosted RPC for txs referencing it and
# verifies the USDC amount landed in the merchant's account. Spend keys never touch
# this server. USDC has 6 decimals.
SOLANA_RPC_URL = env("SOLANA_RPC_URL", "")
SOLANA_NETWORK = env("SOLANA_NETWORK", "devnet")           # devnet | mainnet-beta (label only)
SOLANA_MERCHANT_ADDRESS = env("SOLANA_MERCHANT_ADDRESS", "")  # wallet that receives USDC
SOLANA_USDC_MINT = env("SOLANA_USDC_MINT", "")             # mainnet: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
SOLANA_POLL = int(env("SOLANA_POLL_SECONDS", "10"))
SOLANA_INVOICE_FILE = os.path.join(STATE_DIR, "solana_invoices.json")
_sol_lock = threading.Lock()

def solana_ready():
    return bool(SOLANA_RPC_URL and SOLANA_MERCHANT_ADDRESS and SOLANA_USDC_MINT)

STATE_FILE = os.path.join(STATE_DIR, "state.json")
_state_lock = threading.Lock()
_grp_cache = {"pk": None}


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), *a, flush=True)


# ---------- low level http ----------
def http(method, url, headers=None, body=None, form=False, timeout=30):
    data = None
    headers = dict(headers or {})
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body, doseq=True).encode()
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            data = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw}


# ---------- state ----------
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, STATE_FILE)


def is_premium(rec):
    if not rec:
        return False
    if rec.get("stripe"):
        return True
    now = time.time()
    if (rec.get("btcpay_until") or 0) > now:
        return True
    if (rec.get("sol_until") or 0) > now:
        return True
    return False


# ---------- authentik premium group ----------
def premium_group_pk():
    if _grp_cache["pk"]:
        return _grp_cache["pk"]
    st, d = http("GET", f"{AUTHENTIK_URL}/api/v3/core/groups/?name={PREMIUM_GROUP}",
                 {"Authorization": f"Bearer {AUTHENTIK_TOKEN}"})
    if st == 200 and d.get("results"):
        _grp_cache["pk"] = d["results"][0]["pk"]
    return _grp_cache["pk"]


def user_pk(username):
    st, d = http("GET", f"{AUTHENTIK_URL}/api/v3/core/users/?username={urllib.parse.quote(username)}",
                 {"Authorization": f"Bearer {AUTHENTIK_TOKEN}"})
    if st == 200 and d.get("results"):
        return d["results"][0]["pk"]
    return None


def set_group(username, want_premium):
    """Add/remove the user from the Authentik premium group to match want_premium."""
    gpk, upk = premium_group_pk(), user_pk(username)
    if not gpk or not upk:
        log("set_group: missing pk", username, gpk, upk); return False
    action = "add_user" if want_premium else "remove_user"
    st, d = http("POST", f"{AUTHENTIK_URL}/api/v3/core/groups/{gpk}/{action}/",
                 {"Authorization": f"Bearer {AUTHENTIK_TOKEN}"}, {"pk": upk})
    ok = st in (200, 204)
    log(f"authentik {action} {username} -> {st}")
    if want_premium and ok:
        add_to_members(upk)  # premium implies free-tier membership too
    return ok


import re

def _ak(method, path, body=None, public_host=False):
    headers = {"Authorization": f"Bearer {AUTHENTIK_TOKEN}"}
    if public_host:
        headers.update({"Host": AUTHENTIK_PUBLIC_HOST,
                        "X-Forwarded-Host": AUTHENTIK_PUBLIC_HOST,
                        "X-Forwarded-Proto": "https"})
    return http(method, f"{AUTHENTIK_URL}{path}", headers, body)


_members_cache = {"pk": None}

def members_group_pk():
    if _members_cache["pk"]:
        return _members_cache["pk"]
    st, d = _ak("GET", "/api/v3/core/groups/?name=members")
    if st == 200 and d.get("results"):
        _members_cache["pk"] = d["results"][0]["pk"]
    return _members_cache["pk"]

def add_to_members(user_pk):
    """Every member (free tier) belongs to the `members` group."""
    gpk = members_group_pk()
    if gpk and user_pk:
        _ak("POST", f"/api/v3/core/groups/{gpk}/add_user/", {"pk": user_pk})


def derive_username(email):
    local = email.split("@", 1)[0].lower()
    uname = re.sub(r"[^a-z0-9._-]", "", local) or "member"
    return uname[:48]


def find_user_by_email(email):
    st, d = _ak("GET", f"/api/v3/core/users/?email={urllib.parse.quote(email)}")
    if st == 200 and d.get("results"):
        return d["results"][0]
    return None


def ensure_user(email):
    """Return (user_pk) for email, creating a free member account if needed.
    Every member (new or existing) is placed in the `members` (free tier) group."""
    u = find_user_by_email(email)
    if u:
        add_to_members(u["pk"])
        return u["pk"]
    base = derive_username(email)
    uname = base
    for i in range(0, 50):
        candidate = base if i == 0 else f"{base}{i}"
        st, d = _ak("POST", "/api/v3/core/users/", {
            "username": candidate, "name": email.split("@", 1)[0],
            "email": email, "is_active": True, "path": "users",
        })
        if st in (200, 201):
            add_to_members(d["pk"])
            return d["pk"]
        if st == 400 and "username" in json.dumps(d):
            continue  # taken, try next suffix
        log("ensure_user create err", st, d); break
    # fall back: maybe created concurrently
    u = find_user_by_email(email)
    return u["pk"] if u else None


def send_magic_link(user_pk):
    st, d = _ak("POST",
                f"/api/v3/core/users/{user_pk}/recovery_email/?email_stage={AUTHENTIK_EMAIL_STAGE}",
                public_host=True)
    return st in (200, 204)


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}$")
MAX_EMAIL_LEN = 254

# ---------- /join abuse limiting (email-bombing + account-flood defense) ----------
# The origin-hiding relay (VPS does L4 SNI passthrough) means the real client IP never
# reaches this process — every request appears to come from 10.0.0.1 — so per-IP limiting
# is blind here. We instead throttle on the recipient email (stops bombing one inbox) plus
# a global ceiling (bounds total outbound mail / account creation). Proper per-IP limiting
# + CAPTCHA should be layered on top (recover client IP via PROXY protocol VPS->Caddy).
_join_lock = threading.Lock()
_join_email_hits = {}   # email -> [epoch, ...]
_join_global = []       # [epoch, ...] across all recipients

JOIN_EMAIL_COOLDOWN = 600     # >=10 min between links to the same address
JOIN_EMAIL_DAILY    = 4       # max links to one address per day
JOIN_GLOBAL_PER_MIN = 15      # max links/minute across the whole site
JOIN_GLOBAL_DAILY   = 500     # max links/day across the whole site


def join_allowed(email):
    """Token-bucket gate for /join. Returns True if we may create+mail this address now."""
    now = time.time()
    with _join_lock:
        global _join_global
        _join_global = [t for t in _join_global if now - t < 86400]
        if sum(1 for t in _join_global if now - t < 60) >= JOIN_GLOBAL_PER_MIN:
            return False
        if len(_join_global) >= JOIN_GLOBAL_DAILY:
            return False
        hits = [t for t in _join_email_hits.get(email, []) if now - t < 86400]
        if any(now - t < JOIN_EMAIL_COOLDOWN for t in hits):
            return False
        if len(hits) >= JOIN_EMAIL_DAILY:
            return False
        hits.append(now)
        _join_email_hits[email] = hits
        _join_global.append(now)
        if len(_join_email_hits) > 50000:  # opportunistic prune to bound memory
            for k in [k for k, v in _join_email_hits.items()
                      if not any(now - t < 86400 for t in v)]:
                _join_email_hits.pop(k, None)
        return True


def ping_sync():
    try:
        http("POST", MEMBERSHIP_SYNC_URL, timeout=25)
    except Exception as e:
        log("ping_sync err", e)


def apply_premium(username):
    """Reconcile a single user's premium state to Authentik + trigger Matrix sync."""
    with _state_lock:
        s = load_state()
        want = is_premium(s.get(username))
    set_group(username, want)
    ping_sync()
    log(f"apply_premium {username}: premium={want}")


def grant_stripe(username, active):
    with _state_lock:
        s = load_state()
        rec = s.setdefault(username, {})
        rec["stripe"] = bool(active)
        save_state(s)
    apply_premium(username)


def grant_btcpay(username, days=31):
    with _state_lock:
        s = load_state()
        rec = s.setdefault(username, {})
        rec["btcpay_until"] = max(rec.get("btcpay_until") or 0, time.time() + days * 86400)
        save_state(s)
    apply_premium(username)


def grant_solana(username, days=31):
    with _state_lock:
        s = load_state()
        rec = s.setdefault(username, {})
        rec["sol_until"] = max(rec.get("sol_until") or 0, time.time() + days * 86400)
        save_state(s)
    apply_premium(username)


# ---------- Solana USDC (Solana Pay) ----------
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = len(b) - len(b.lstrip(b"\x00"))
    return "1" * pad + out


def load_sol():
    try:
        with open(SOLANA_INVOICE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_sol(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = SOLANA_INVOICE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, SOLANA_INVOICE_FILE)


def sol_rpc(method, params):
    try:
        st, d = http("POST", SOLANA_RPC_URL, {"Content-Type": "application/json"},
                     {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    except Exception as e:
        log("sol_rpc unreachable", method, e)
        return None
    if st != 200 or not isinstance(d, dict):
        return None
    if d.get("error"):
        log("sol_rpc error", method, d["error"])
        return None
    return d.get("result")


def solana_new_invoice(username):
    ref = b58encode(os.urandom(32))
    amt_base = int(round(float(PRICE_USD) * 1_000_000))  # USDC = 6 decimals
    inv = {"username": username, "amount_base": amt_base, "created": time.time(),
           "expires": time.time() + 30 * 60, "paid": False, "sig": None}
    with _sol_lock:
        d = load_sol()
        d[ref] = inv
        save_sol(d)
    return ref, inv


def solana_pay_uri(ref):
    q = urllib.parse.urlencode({
        "amount": PRICE_USD, "spl-token": SOLANA_USDC_MINT, "reference": ref,
        "label": "Yaya Premium", "message": "Premium membership — one month",
    })
    return f"solana:{SOLANA_MERCHANT_ADDRESS}?{q}"


def solana_check(ref, inv):
    """Return the signature if a confirmed USDC payment to the merchant exists."""
    sigs = sol_rpc("getSignaturesForAddress", [ref, {"limit": 10}]) or []
    for s in sigs:
        if s.get("err"):
            continue
        sig = s.get("signature")
        tx = sol_rpc("getTransaction",
                     [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0,
                            "commitment": "confirmed"}])
        if not tx or (tx.get("meta") or {}).get("err"):
            continue
        meta = tx["meta"]
        pre = {(b.get("owner"), b.get("mint")): int(b["uiTokenAmount"]["amount"])
               for b in meta.get("preTokenBalances", [])}
        for b in meta.get("postTokenBalances", []):
            if b.get("owner") == SOLANA_MERCHANT_ADDRESS and b.get("mint") == SOLANA_USDC_MINT:
                delta = int(b["uiTokenAmount"]["amount"]) - pre.get((b.get("owner"), b.get("mint")), 0)
                if delta >= inv["amount_base"]:
                    return sig
    return None


def solana_watcher():
    if not solana_ready():
        log("solana watcher: not configured, idle")
        return
    log(f"solana watcher: watching {SOLANA_NETWORK} for USDC to {SOLANA_MERCHANT_ADDRESS[:8]}…")
    while True:
        time.sleep(SOLANA_POLL)
        try:
            with _sol_lock:
                d = load_sol()
            now = time.time()
            changed = False
            for ref, inv in list(d.items()):
                if inv.get("paid"):
                    if now - inv.get("created", 0) > 86400:
                        d.pop(ref, None); changed = True
                    continue
                if now > inv.get("expires", 0):
                    d.pop(ref, None); changed = True
                    continue
                sig = solana_check(ref, inv)
                if sig:
                    inv["paid"] = True; inv["sig"] = sig; changed = True
                    log(f"solana payment confirmed ref={ref[:8]}… sig={sig} user={inv['username']}")
                    grant_solana(inv["username"], days=31)
            if changed:
                with _sol_lock:
                    save_sol(d)
        except Exception as e:
            log("solana_watcher err", e)


def qr_svg(data):
    """Optional QR (segno if available); empty string if not installed."""
    try:
        import io, segno
        buf = io.BytesIO()
        segno.make(data, error="m").save(buf, kind="svg", scale=5, border=2,
                                         dark="#0d0d12", light="#ffffff")
        return buf.getvalue().decode()
    except Exception:
        return ""


def sweeper():
    while True:
        time.sleep(3600)
        try:
            with _state_lock:
                s = load_state()
            for username, rec in list(s.items()):
                if not is_premium(rec):
                    set_group(username, False)
            ping_sync()
        except Exception as e:
            log("sweeper err", e)


# ---------- session cookie (HMAC signed) ----------
def sign(payload: bytes) -> str:
    mac = hmac.new(SESSION_SECRET, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + \
        base64.urlsafe_b64encode(mac).decode().rstrip("=")


def unsign(token: str):
    try:
        p_b64, m_b64 = token.split(".")
        payload = base64.urlsafe_b64decode(p_b64 + "=" * (-len(p_b64) % 4))
        mac = base64.urlsafe_b64decode(m_b64 + "=" * (-len(m_b64) % 4))
        if not hmac.compare_digest(mac, hmac.new(SESSION_SECRET, payload, hashlib.sha256).digest()):
            return None
        return json.loads(payload)
    except Exception:
        return None


def make_session(user):
    return sign(json.dumps({"u": user["username"], "e": user.get("email", ""),
                            "exp": int(time.time()) + 86400}).encode())


def read_session(cookie_header):
    for part in (cookie_header or "").split(";"):
        if part.strip().startswith("sess="):
            data = unsign(part.strip()[5:])
            if data and data.get("exp", 0) > time.time():
                return data
    return None


# ---------- OIDC ----------
def oidc_authorize_redirect():
    state = base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("=")
    q = urllib.parse.urlencode({
        "response_type": "code", "client_id": OIDC_CLIENT_ID,
        "redirect_uri": OIDC_REDIRECT_URI, "scope": "openid email profile groups",
        "state": state,
    })
    return f"{OIDC_AUTHORIZE_URL}?{q}", state


def oidc_exchange(code):
    st, tok = http("POST", OIDC_TOKEN_URL, body={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": OIDC_REDIRECT_URI,
        "client_id": OIDC_CLIENT_ID, "client_secret": OIDC_CLIENT_SECRET,
    }, form=True)
    if st != 200 or "access_token" not in tok:
        log("token exchange failed", st, tok); return None
    st, ui = http("GET", OIDC_USERINFO_URL, {"Authorization": f"Bearer {tok['access_token']}"})
    if st != 200:
        log("userinfo failed", st, ui); return None
    username = ui.get("preferred_username") or ui.get("nickname") or ui.get("sub")
    return {"username": username, "email": ui.get("email", "")}


# ---------- pages ----------
def page(title, body):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="icon" href="https://yaya.sh/brand/favicon.ico" sizes="any">
<link rel="icon" type="image/svg+xml" href="https://yaya.sh/brand/app-icon.svg">
<link rel="stylesheet" href="https://yaya.sh/brand/system.css">
<meta name="theme-color" content="#0d0d12">
<style>
:root{{--bg:var(--ls-ink);--card:var(--ls-surface);--accent:var(--ls-brand);--text:var(--ls-text);--muted:var(--ls-muted)}}
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;
background:radial-gradient(900px 500px at 50% -10%,#1c1740,#0d0d12);color:var(--text);
min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{background:var(--card);border:1px solid #262636;border-radius:20px;max-width:440px;width:100%;
padding:36px;box-shadow:0 20px 60px #0008}}
h1{{margin:0 0 6px;font-size:26px}}p.sub{{color:var(--muted);margin:0 0 24px}}
.price{{font-size:44px;font-weight:800;margin:8px 0}}.price span{{font-size:16px;color:var(--muted);font-weight:500}}
ul{{list-style:none;padding:0;margin:18px 0 26px}}li{{padding:7px 0;color:#cdd}}li::before{{content:"✓ ";color:#5ad28a;font-weight:700}}
a.btn,button.btn{{display:block;width:100%;text-align:center;border:0;border-radius:12px;padding:15px;
font-size:16px;font-weight:700;cursor:pointer;text-decoration:none;margin-top:12px}}
.btn-card{{background:var(--accent);color:#fff}}.btn-crypto{{background:#f7931a;color:#1a1a1a}}
.btn-usdc{{background:#2775ca;color:#fff}}
.btn-ghost{{background:transparent;border:1px solid #333;color:var(--muted)}}
.note{{color:var(--muted);font-size:13px;margin-top:18px;text-align:center}}
.muted{{color:var(--muted)}}.ok{{color:#5ad28a}}
.brandlogo{{display:block;height:34px;margin:0 auto 20px;filter:drop-shadow(0 4px 18px rgba(124,92,255,.4))}}
.poweredby{{text-align:center;color:#6a6f88;font-size:12px;margin-top:24px}}.poweredby a{{color:#8a8fb0}}
</style></head><body><div class="card">
<img class="brandlogo" src="https://yaya.sh/brand/logo.svg" alt="Yaya">
{body}
<div class="poweredby">Powered by <a href="https://libresynergy.org">LibreSynergy</a></div>
</div></body></html>"""


def upgrade_page(sess, msg=""):
    stripe_ready = bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID)
    btcpay_ready = bool(BTCPAY_URL and BTCPAY_API_KEY and BTCPAY_STORE_ID)
    card_btn = ('<form method="post" action="/checkout/stripe"><button class="btn btn-card">Pay with card</button></form>'
                if stripe_ready else '<a class="btn btn-ghost">Card — coming soon</a>')
    crypto_btn = ('<form method="post" action="/checkout/btcpay"><button class="btn btn-crypto">Pay with Bitcoin / Monero</button></form>'
                  if btcpay_ready else '<a class="btn btn-ghost">Crypto — syncing, available soon</a>')
    solana_btn = ('<form method="post" action="/checkout/solana"><button class="btn btn-usdc">Pay with USDC (Solana)</button></form>'
                  if solana_ready() else '')
    banner = f'<p class="ok">{msg}</p>' if msg else ""
    return page("Upgrade to Premium", f"""
{banner}
<h1>Premium</h1>
<p class="sub">Signed in as <b>{html.escape(sess['u'])}</b></p>
<div class="price">${PRICE_USD}<span>/month</span></div>
<ul><li>Premium chat rooms (Lounge + Vault)</li><li>Paid courses in the Classroom</li>
<li>Live member events</li><li>Cancel anytime</li></ul>
{card_btn}
{crypto_btn}
{solana_btn}
<p class="note">Already premium? <a class="muted" href="{CHAT_URL}">Go to the community →</a></p>
""")


def solana_pay_page(sess, ref):
    uri = solana_pay_uri(ref)
    qr = qr_svg(uri)
    qr_block = (f'<div style="background:#fff;border-radius:14px;padding:12px;width:210px;margin:8px auto 0">{qr}</div>'
                if qr else '<p class="note">Scan-to-pay QR unavailable — use the button or copy the details below.</p>')
    net = "" if SOLANA_NETWORK.startswith("mainnet") else f'<p class="note" style="color:#f7a">⚠ {html.escape(SOLANA_NETWORK)} — test network</p>'
    return page("Pay with USDC", f"""
<h1>Pay with USDC</h1>
<p class="sub">${PRICE_USD} in USDC on Solana · <b>{html.escape(sess['u'])}</b></p>
{net}
{qr_block}
<a class="btn btn-usdc" href="{html.escape(uri)}">Open in Solana wallet</a>
<p class="note">Or send exactly <b>{PRICE_USD} USDC</b> to:</p>
<div style="background:#0d0d12;border:1px solid #262636;border-radius:10px;padding:10px;font:12px/1.5 monospace;word-break:break-all;color:#cdd">
<b class="muted">Address</b><br>{html.escape(SOLANA_MERCHANT_ADDRESS)}<br>
<b class="muted">Reference (include this)</b><br>{html.escape(ref)}</div>
<p class="note" id="stat">Waiting for payment… this page updates automatically.</p>
<script>
var ref={json.dumps(ref)};
var t=setInterval(function(){{
  fetch("/checkout/solana/status?ref="+encodeURIComponent(ref)).then(r=>r.json()).then(function(d){{
    if(d.paid){{clearInterval(t);document.getElementById("stat").innerHTML="✅ Payment received — activating premium…";
      setTimeout(function(){{location.href="{PUBLIC_BASE_URL}/done?ok=1"}},1500);}}
  }}).catch(function(){{}});
}},4000);
</script>
""")


# ---------- stripe ----------
def stripe_create_checkout(username, email):
    body = {
        "mode": "subscription",
        "line_items[0][price]": STRIPE_PRICE_ID,
        "line_items[0][quantity]": "1",
        "client_reference_id": username,
        "customer_email": email,
        "metadata[authentik_username]": username,
        "subscription_data[metadata][authentik_username]": username,
        "success_url": f"{PUBLIC_BASE_URL}/done?ok=1",
        "cancel_url": f"{PUBLIC_BASE_URL}/upgrade",
    }
    st, d = http("POST", f"{STRIPE_API}/checkout/sessions",
                 {"Authorization": f"Bearer {STRIPE_SECRET_KEY}"}, body, form=True)
    if st == 200 and d.get("url"):
        return d["url"]
    log("stripe checkout err", st, d); return None


def stripe_verify(payload: bytes, sig_header: str) -> bool:
    if not STRIPE_WEBHOOK_SECRET:
        return False
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(","))
        t, v1 = parts["t"], parts["v1"]
        expected = hmac.new(STRIPE_WEBHOOK_SECRET.encode(),
                            f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1) and abs(time.time() - int(t)) < 600
    except Exception as e:
        log("stripe_verify err", e); return False


def handle_stripe_event(event):
    typ = event.get("type")
    obj = event.get("data", {}).get("object", {})
    meta = obj.get("metadata", {}) or {}
    username = meta.get("authentik_username") or obj.get("client_reference_id")
    if not username:
        log("stripe event without username", typ); return
    if typ in ("checkout.session.completed", "customer.subscription.created",
               "customer.subscription.updated", "invoice.paid"):
        status = obj.get("status")
        active = status in (None, "active", "trialing", "complete", "paid")
        grant_stripe(username, active)
    elif typ in ("customer.subscription.deleted", "invoice.payment_failed"):
        grant_stripe(username, False)


# ---------- btcpay ----------
def btcpay_create_invoice(username, email):
    body = {"amount": str(PRICE_USD), "currency": "USD",
            "metadata": {"authentik_username": username, "buyerEmail": email,
                         "orderId": f"premium-{username}-{int(time.time())}"},
            "checkout": {"redirectURL": f"{PUBLIC_BASE_URL}/done?ok=1"}}
    st, d = http("POST", f"{BTCPAY_URL}/api/v1/stores/{BTCPAY_STORE_ID}/invoices",
                 {"Authorization": f"token {BTCPAY_API_KEY}"}, body)
    if st in (200, 201) and d.get("checkoutLink"):
        return d["checkoutLink"]
    log("btcpay invoice err", st, d); return None


def btcpay_verify(payload: bytes, sig_header: str) -> bool:
    if not BTCPAY_WEBHOOK_SECRET or not sig_header:
        return False
    expected = "sha256=" + hmac.new(BTCPAY_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header)


def handle_btcpay_event(event):
    if event.get("type") not in ("InvoiceSettled", "InvoicePaymentSettled"):
        return
    meta = event.get("metadata") or {}
    username = meta.get("authentik_username")
    if username:
        grant_btcpay(username, days=31)


# ---------- HTTP handler ----------
class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, loc, cookies=None):
        self.send_response(302)
        self.send_header("Location", loc)
        for c in (cookies or []):
            self.send_header("Set-Cookie", c)
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    def _session(self):
        return read_session(self.headers.get("Cookie"))

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if path == "/healthz":
            return self._send(200, json.dumps({"ok": True,
                "stripe": bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID),
                "btcpay": bool(BTCPAY_URL and BTCPAY_API_KEY),
                "solana": solana_ready(), "solana_network": SOLANA_NETWORK}), "application/json")
        if path == "/checkout/solana/status":
            ref = (qs.get("ref") or [""])[0]
            with _sol_lock:
                inv = load_sol().get(ref)
            return self._send(200, json.dumps({"paid": bool(inv and inv.get("paid"))}), "application/json")
        if path in ("/", "/upgrade"):
            sess = self._session()
            if not sess:
                loc, state = oidc_authorize_redirect()
                return self._redirect(loc, [f"oidc_state={state}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=600"])
            return self._send(200, upgrade_page(sess))
        if path == "/auth/callback":
            code = (qs.get("code") or [None])[0]
            state = (qs.get("state") or [None])[0]
            cookie_state = None
            for part in (self.headers.get("Cookie") or "").split(";"):
                if part.strip().startswith("oidc_state="):
                    cookie_state = part.strip()[11:]
            if not code or not state or state != cookie_state:
                return self._send(400, page("Error", "<h1>Login failed</h1><p>Invalid state.</p>"))
            user = oidc_exchange(code)
            if not user:
                return self._send(502, page("Error", "<h1>Login failed</h1><p>Could not verify identity.</p>"))
            return self._redirect(f"{PUBLIC_BASE_URL}/upgrade",
                                  [f"sess={make_session(user)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=86400",
                                   "oidc_state=; Path=/; Max-Age=0"])
        if path == "/done":
            return self._send(200, page("Thanks!", f"""<h1 class="ok">You're in 🎉</h1>
<p class="sub">Payment received. Your premium access is being activated.</p>
<a class="btn btn-card" href="{CHAT_URL}">Enter the community →</a>"""))
        return self._send(404, page("Not found", "<h1>404</h1>"))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/join":
            raw = self._body().decode("utf-8", "replace")
            ctype = self.headers.get("Content-Type", "")
            email = ""
            if "application/json" in ctype:
                try:
                    email = (json.loads(raw).get("email") or "").strip().lower()
                except Exception:
                    email = ""
            else:
                email = (urllib.parse.parse_qs(raw).get("email", [""])[0]).strip().lower()
            wants_json = "application/json" in (self.headers.get("Accept", ""))
            if len(email) > MAX_EMAIL_LEN or not EMAIL_RE.match(email):
                if wants_json:
                    return self._send(400, json.dumps({"ok": False, "error": "invalid email"}), "application/json")
                return self._send(400, page("Invalid email", "<h1>Hmm 🤔</h1><p class='sub'>That doesn't look like a valid email. Go back and try again.</p>"))
            if not join_allowed(email):
                # Rate-limited: create nothing, mail nothing. Return the SAME generic
                # response as success so /join can neither bomb an inbox nor be used to
                # enumerate which addresses already have accounts.
                log("join rate-limited:", email)
                if wants_json:
                    return self._send(200, json.dumps({"ok": True}), "application/json")
                return self._send(200, page("Check your email", f"""
<h1 class="ok">Check your email ✉️</h1>
<p class="sub">If you have an account, a one-click sign-in link is on its way to<br><b>{html.escape(email)}</b>.</p>
<p class="note">Links expire in 15 minutes. Check spam if you don't see it.</p>"""))
            try:
                pk = ensure_user(email)
                ok = bool(pk) and send_magic_link(pk)
            except Exception as e:
                log("join err", e); ok = False
            if wants_json:
                return self._send(200 if ok else 502, json.dumps({"ok": ok}), "application/json")
            if not ok:
                return self._send(502, page("Try again", "<h1>Something went wrong</h1><p class='sub'>We couldn't send your link. Please try again in a minute.</p>"))
            return self._send(200, page("Check your email", f"""
<h1 class="ok">Check your email ✉️</h1>
<p class="sub">We sent a one-click sign-in link to<br><b>{html.escape(email)}</b>.</p>
<p class="note">It expires in 15 minutes. Didn't get it? Check spam, or
<a class="muted" href="{PUBLIC_BASE_URL.replace('premium.','')}">try again</a>.</p>"""))
        if path == "/webhook/stripe":
            payload = self._body()
            if not stripe_verify(payload, self.headers.get("Stripe-Signature", "")):
                return self._send(400, json.dumps({"error": "bad signature"}), "application/json")
            try:
                handle_stripe_event(json.loads(payload))
            except Exception as e:
                log("stripe handler err", e)
            return self._send(200, json.dumps({"received": True}), "application/json")
        if path == "/webhook/btcpay":
            payload = self._body()
            if not btcpay_verify(payload, self.headers.get("BTCPay-Sig", "")):
                return self._send(400, json.dumps({"error": "bad signature"}), "application/json")
            try:
                handle_btcpay_event(json.loads(payload))
            except Exception as e:
                log("btcpay handler err", e)
            return self._send(200, json.dumps({"received": True}), "application/json")
        # checkout routes require a session
        sess = self._session()
        if not sess:
            return self._redirect(f"{PUBLIC_BASE_URL}/upgrade")
        if path == "/checkout/stripe":
            url = stripe_create_checkout(sess["u"], sess.get("e", ""))
            return self._redirect(url or f"{PUBLIC_BASE_URL}/upgrade")
        if path == "/checkout/btcpay":
            url = btcpay_create_invoice(sess["u"], sess.get("e", ""))
            return self._redirect(url or f"{PUBLIC_BASE_URL}/upgrade")
        if path == "/checkout/solana":
            if not solana_ready():
                return self._redirect(f"{PUBLIC_BASE_URL}/upgrade")
            ref, _ = solana_new_invoice(sess["u"])
            return self._send(200, solana_pay_page(sess, ref))
        return self._send(404, json.dumps({"error": "not found"}), "application/json")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    log(f"payments-bridge starting on {LISTEN_HOST}:{LISTEN_PORT} "
        f"(stripe={'on' if STRIPE_SECRET_KEY else 'off'}, btcpay={'on' if BTCPAY_API_KEY else 'off'}, "
        f"solana={'on:'+SOLANA_NETWORK if solana_ready() else 'off'})")
    threading.Thread(target=sweeper, daemon=True).start()
    threading.Thread(target=solana_watcher, daemon=True).start()
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), H).serve_forever()
