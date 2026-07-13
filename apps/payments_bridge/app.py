#!/usr/bin/env python3
"""
join-bridge — free membership signup for the community.

The community is free for its members. This bridge does one job:
  POST /join  { email }  →  create (or find) the Authentik account, put it in
  the `members` group, and email a magic sign-in link.

There is no paid tier, no checkout, no card on file. Operators who deploy the
stack monetize the *deployment* (hosting), never the members.

Pure stdlib — no pip deps.
"""
import html, json, os, re, sys, threading, time, urllib.parse, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Shared i18n catalog (mounted read-only at /i18n). Optional by design: if it is
# unavailable the bridge still serves (T() degrades to English via the catalog,
# or to the key as a last resort) — a missing mount must never break signup.
for _p in ("/i18n", "/ls/apps/i18n"):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
        break
try:
    import i18n
except Exception:
    i18n = None

def T(lang, key, **fmt):
    """Translate key for lang; English/key fallback if the catalog is missing."""
    return i18n.t(lang, key, **fmt) if i18n else key

def resolve_lang(handler):
    """(lang, set_cookie) from ?lang= / ls_lang cookie / Accept-Language / default."""
    return i18n.resolve(handler) if i18n else ("en", False)

def lang_switcher(lang):
    return i18n.switcher_html(lang, "") if i18n else ""

def lang_cookie(set_cookie, lang):
    return {"Set-Cookie": f"ls_lang={lang}; Path=/; Max-Age=31536000; SameSite=Lax"} if set_cookie else None

# ---- config ----
def env(k, d=None, required=False):
    v = os.environ.get(k, d)
    if required and not v:
        raise SystemExit(f"missing required env {k}")
    return v

PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", required=True).rstrip("/")
CHAT_URL = env("COMMUNITY_CHAT_URL", required=True)
LISTEN_HOST = env("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(env("LISTEN_PORT", "9092"))

AUTHENTIK_URL = env("AUTHENTIK_URL", "http://127.0.0.1:8300").rstrip("/")
AUTHENTIK_TOKEN = env("AUTHENTIK_TOKEN", required=True)
AUTHENTIK_PUBLIC_HOST = env("AUTHENTIK_PUBLIC_HOST", required=True)
BRAND_NAME = env("BRAND_NAME", "Community")
BRAND_BASE_URL = env("BRAND_BASE_URL", "").rstrip("/")
AUTHENTIK_EMAIL_STAGE = env("AUTHENTIK_EMAIL_STAGE", "")


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


# ---------- authentik ----------
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
    """Every member belongs to the `members` group."""
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
    """Return (user_pk) for email, creating a member account if needed.
    Every member (new or existing) is placed in the `members` group."""
    u = find_user_by_email(email)
    if u:
        add_to_members(u["pk"])
        return u["pk"]
    base = derive_username(email)
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


# ---------- pages ----------
def page(title, body, lang="en"):
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="icon" href="{BRAND_BASE_URL}/brand/favicon.ico" sizes="any">
<link rel="icon" type="image/svg+xml" href="{BRAND_BASE_URL}/brand/app-icon.svg">
<link rel="stylesheet" href="{BRAND_BASE_URL}/brand/system.css">
<meta name="theme-color" content="#0d0d12">
<style>
:root{{--bg:var(--ls-ink);--card:var(--ls-surface);--accent:var(--ls-brand);--text:var(--ls-text);--muted:var(--ls-muted)}}
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;
background:radial-gradient(900px 500px at 50% -10%,#1c1740,#0d0d12);color:var(--text);
min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{background:var(--card);border:1px solid #262636;border-radius:20px;max-width:440px;width:100%;
padding:36px;box-shadow:0 20px 60px #0008}}
h1{{margin:0 0 6px;font-size:26px}}p.sub{{color:var(--muted);margin:0 0 24px}}
a.btn,button.btn{{display:block;width:100%;text-align:center;border:0;border-radius:12px;padding:15px;
font-size:16px;font-weight:700;cursor:pointer;text-decoration:none;margin-top:12px}}
.btn-card{{background:var(--accent);color:#fff}}
.note{{color:var(--muted);font-size:13px;margin-top:18px;text-align:center}}
.muted{{color:var(--muted)}}.ok{{color:#5ad28a}}
.brandlogo{{display:block;height:34px;margin:0 auto 20px;filter:drop-shadow(0 4px 18px rgba(124,92,255,.4))}}
.poweredby{{text-align:center;color:#6a6f88;font-size:12px;margin-top:24px}}.poweredby a{{color:#8a8fb0}}
</style></head><body><div class="card">
<img class="brandlogo" src="{BRAND_BASE_URL}/brand/logo.svg" alt="{BRAND_NAME}">
{body}
<div class="poweredby">{T(lang,'bridge.powered_by')} <a href="https://libresynergy.org">LibreSynergy</a></div>
{lang_switcher(lang)}
</div></body></html>"""


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

    def _redirect(self, loc):
        self.send_response(302)
        self.send_header("Location", loc)
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/healthz":
            return self._send(200, json.dumps({"ok": True}), "application/json")
        # membership is free — anything else lands on the community itself
        return self._redirect(BRAND_BASE_URL or CHAT_URL)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/join":
            return self._send(404, json.dumps({"error": "not found"}), "application/json")
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
        lang, _ = resolve_lang(self)
        if len(email) > MAX_EMAIL_LEN or not EMAIL_RE.match(email):
            if wants_json:
                return self._send(400, json.dumps({"ok": False, "error": "invalid email"}), "application/json")
            return self._send(400, page(T(lang,"bridge.title_invalid_email"), f"<h1>{T(lang,'bridge.hmm')}</h1><p class='sub'>{T(lang,'bridge.invalid_email_body')}</p>", lang))
        if not join_allowed(email):
            # Rate-limited: create nothing, mail nothing. Return the SAME generic
            # response as success so /join can neither bomb an inbox nor be used to
            # enumerate which addresses already have accounts.
            log("join rate-limited:", email)
            if wants_json:
                return self._send(200, json.dumps({"ok": True}), "application/json")
            return self._send(200, page(T(lang,"bridge.title_check_email"), f"""
<h1 class="ok">{T(lang,"bridge.check_email_heading")}</h1>
<p class="sub">{T(lang,"bridge.link_on_its_way")}<br><b>{html.escape(email)}</b>.</p>
<p class="note">{T(lang,"bridge.links_expire_spam")}</p>""", lang))
        try:
            pk = ensure_user(email)
            ok = bool(pk) and send_magic_link(pk)
        except Exception as e:
            log("join err", e); ok = False
        if wants_json:
            return self._send(200 if ok else 502, json.dumps({"ok": ok}), "application/json")
        if not ok:
            return self._send(502, page(T(lang,"bridge.title_try_again"), f"<h1>{T(lang,'bridge.something_wrong')}</h1><p class='sub'>{T(lang,'bridge.couldnt_send')}</p>", lang))
        retry_link = f'<a class="muted" href="{PUBLIC_BASE_URL}">{T(lang,"bridge.try_again_link")}</a>'
        return self._send(200, page(T(lang,"bridge.title_check_email"), f"""
<h1 class="ok">{T(lang,"bridge.check_email_heading")}</h1>
<p class="sub">{T(lang,"bridge.we_sent_link")}<br><b>{html.escape(email)}</b>.</p>
<p class="note">{T(lang,"bridge.success_note", link=retry_link)}</p>""", lang))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    log(f"join-bridge starting on {LISTEN_HOST}:{LISTEN_PORT} (membership is free)")
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), H).serve_forever()
