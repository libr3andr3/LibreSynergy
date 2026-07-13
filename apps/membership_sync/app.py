#!/usr/bin/env python3
"""
membership-sync — community welcome bot.

Membership is free; there are no gated rooms or paid courses to reconcile.
What remains is hospitality: every brand-new Matrix account gets one welcome
DM from the community bot pointing at the app. Runs a periodic loop AND
exposes POST /reconcile for an instant pass.

Pure stdlib (no pip deps). Talks to:
  - Synapse admin  (MATRIX_HS_URL + MATRIX_BOT_TOKEN)  -> list users, send DMs
"""
import json, os, threading, time, urllib.request, urllib.error, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MATRIX_HS_URL = os.environ["MATRIX_HS_URL"].rstrip("/")
MATRIX_BOT_TOKEN = os.environ["MATRIX_BOT_TOKEN"]
SERVER_NAME = os.environ["MATRIX_SERVER_NAME"]  # e.g. matrix.example.com
LISTEN_HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "9101"))
INTERVAL = int(os.environ.get("RECONCILE_INTERVAL", "60"))
BOT_USER = os.environ.get("MATRIX_BOT_USER", f"@community-bot:{SERVER_NAME}")

# --- Welcome bot (DMs new members on arrival) ---
WELCOME_ENABLED = os.environ.get("WELCOME_ENABLED", "1") == "1"
WELCOME_STATE = os.environ.get("WELCOME_STATE", "/state/welcomed.json")
APP_URL = os.environ.get("APP_URL", "")
BRAND_NAME = os.environ.get("BRAND_NAME", "the community")

_lock = threading.Lock()
_last = {"time": 0, "welcomed": 0, "error": None}


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), *a, flush=True)


def _req(method, url, token, body=None, tries=0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        if e.code == 429 and tries < 8:
            try:
                wait = json.loads(raw).get("retry_after_ms", 1500) / 1000.0
            except Exception:
                wait = 1.5
            time.sleep(wait + 0.3)
            return _req(method, url, token, body, tries + 1)
        return e.code, {"error": raw}


# ---------- Welcome bot ----------
def list_matrix_users():
    users, start = [], 0
    while True:
        st, d = _req("GET", f"{MATRIX_HS_URL}/_synapse/admin/v2/users?from={start}&limit=100"
                            f"&guests=false&deactivated=false", MATRIX_BOT_TOKEN)
        if st != 200:
            break
        for u in d.get("users", []):
            if not u.get("deactivated") and not u.get("user_type"):  # skip bots/support
                users.append(u["name"])
        nt = d.get("next_token")
        if nt is None:
            break
        start = nt
    return users


def load_welcomed():
    try:
        with open(WELCOME_STATE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_welcomed(s):
    os.makedirs(os.path.dirname(WELCOME_STATE), exist_ok=True)
    tmp = WELCOME_STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sorted(s), f)
    os.replace(tmp, WELCOME_STATE)


def dm_send(mxid, html_body, plain):
    st, d = _req("POST", f"{MATRIX_HS_URL}/_matrix/client/v3/createRoom", MATRIX_BOT_TOKEN,
                 {"preset": "trusted_private_chat", "is_direct": True, "invite": [mxid]})
    room = d.get("room_id") if st == 200 else None
    if not room:
        return False
    txn = str(int(time.time() * 1000))
    rid = urllib.parse.quote(room)
    st, _ = _req("PUT", f"{MATRIX_HS_URL}/_matrix/client/v3/rooms/{rid}/send/m.room.message/{txn}",
                 MATRIX_BOT_TOKEN, {"msgtype": "m.text", "format": "org.matrix.custom.html",
                                    "formatted_body": html_body, "body": plain})
    return st == 200


def welcome_new_members():
    if not WELCOME_ENABLED:
        return 0
    users = list_matrix_users()
    first_run = not os.path.exists(WELCOME_STATE)
    welcomed = load_welcomed()
    if first_run:
        save_welcomed(set(users))  # seed: don't spam existing members; welcome only future joiners
        log(f"welcome: seeded {len(users)} existing members (no DM)")
        return 0
    n = 0
    for mxid in users:
        if mxid == BOT_USER or mxid in welcomed:
            continue
        name = mxid.split(":")[0].lstrip("@")
        html_body = (f"<h3>👋 Welcome to {BRAND_NAME}, {name}!</h3>So glad you're here. Here's how to dive in:<br><br>"
                     f"💬 <b>Say hi</b> in the community rooms<br>"
                     f"🎓 <b>Browse courses</b> in the Classroom<br>"
                     f"🎥 <b>Join live webinars</b> right in the app<br><br>"
                     f'Everything here is free for members. Open the app → <a href="{APP_URL}">{APP_URL}</a>')
        plain = (f"Welcome to {BRAND_NAME}, {name}! Say hi in the rooms, browse courses, join live webinars. "
                 f"Everything here is free for members. Open the app: {APP_URL}")
        if dm_send(mxid, html_body, plain):
            welcomed.add(mxid); n += 1; log("WELCOMED", mxid)
    if n:
        save_welcomed(welcomed)
    return n


# ---------- reconcile ----------
def reconcile():
    with _lock:
        try:
            welcomed = welcome_new_members()
            _last.update(time=int(time.time()), welcomed=welcomed, error=None)
            log(f"reconcile done: welcomed={welcomed}")
        except Exception as e:
            _last.update(time=int(time.time()), error=str(e))
            log("RECONCILE ERROR:", e)
        return dict(_last)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"ok": True, "last": _last})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.startswith("/reconcile"):
            self._send(200, reconcile())
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


def loop():
    while True:
        reconcile()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    log(f"membership-sync (welcome bot) starting; interval={INTERVAL}s "
        f"listen={LISTEN_HOST}:{LISTEN_PORT}")
    threading.Thread(target=loop, daemon=True).start()
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()
