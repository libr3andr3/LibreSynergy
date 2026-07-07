#!/usr/bin/env python3
"""
membership-sync — keeps Matrix premium rooms in sync with the Authentik `premium` group.

Source of truth: the Authentik `premium` group. Every user in it is force-joined to the
premium Matrix rooms; everyone else (except the bot/safelist) is kicked. Runs a periodic
reconcile loop AND exposes POST /reconcile so the payments bridge can trigger an instant sync.

Pure stdlib (no pip deps). Talks to:
  - Authentik API  (AUTHENTIK_URL + AUTHENTIK_TOKEN)  -> who is premium
  - Synapse admin  (MATRIX_HS_URL + MATRIX_BOT_TOKEN)  -> invite/join/kick
"""
import json, os, threading, time, urllib.request, urllib.error, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AUTHENTIK_URL = os.environ["AUTHENTIK_URL"].rstrip("/")
AUTHENTIK_TOKEN = os.environ["AUTHENTIK_TOKEN"]
MATRIX_HS_URL = os.environ["MATRIX_HS_URL"].rstrip("/")
MATRIX_BOT_TOKEN = os.environ["MATRIX_BOT_TOKEN"]
SERVER_NAME = os.environ["MATRIX_SERVER_NAME"]  # e.g. matrix.example.com
PREMIUM_GROUP = os.environ.get("PREMIUM_GROUP", "premium")
SPACES_FILE = os.environ.get("SPACES_FILE", "/config/spaces.json")
LISTEN_HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "9101"))
INTERVAL = int(os.environ.get("RECONCILE_INTERVAL", "60"))
BOT_USER = os.environ.get("MATRIX_BOT_USER", f"@community-bot:{SERVER_NAME}")
# never kick these from premium rooms
SAFELIST = {BOT_USER} | {u.strip() for u in os.environ.get("SAFELIST", "").split(",") if u.strip()}

# --- Frappe LMS (premium course enrollment gating) ---
FRAPPE_URL = os.environ.get("FRAPPE_URL", "http://127.0.0.1:8100").rstrip("/")
FRAPPE_API_KEY = os.environ.get("FRAPPE_API_KEY", "")
FRAPPE_API_SECRET = os.environ.get("FRAPPE_API_SECRET", "")
FRAPPE_HOST = os.environ.get("FRAPPE_HOST", "")  # e.g. learn.example.com
FRAPPE_AUTH = f"token {FRAPPE_API_KEY}:{FRAPPE_API_SECRET}" if FRAPPE_API_KEY else None
# never unenroll these from paid courses (instructors/admins)
LMS_SAFELIST = {e.strip().lower() for e in
                os.environ.get("LMS_SAFELIST", "").split(",") if e.strip()}

# --- Welcome bot (DMs new members on arrival) ---
WELCOME_ENABLED = os.environ.get("WELCOME_ENABLED", "1") == "1"
WELCOME_STATE = os.environ.get("WELCOME_STATE", "/state/welcomed.json")
APP_URL = os.environ.get("APP_URL", "")
BRAND_NAME = os.environ.get("BRAND_NAME", "the community")

_lock = threading.Lock()
_last = {"time": 0, "premium": 0, "added": 0, "kicked": 0,
         "lms_granted": 0, "lms_revoked": 0, "welcomed": 0, "error": None}


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


# ---------- Authentik ----------
def premium_mxids():
    """Return set of @localpart:server for every active user in the premium group."""
    mxids = set()
    url = (f"{AUTHENTIK_URL}/api/v3/core/users/"
           f"?groups_by_name={urllib.parse.quote(PREMIUM_GROUP)}&page_size=100")
    while url:
        status, data = _req("GET", url, AUTHENTIK_TOKEN)
        if status != 200:
            raise RuntimeError(f"authentik users list -> {status}: {data}")
        for u in data.get("results", []):
            if not u.get("is_active"):
                continue
            localpart = (u.get("username") or "").strip().lower()
            if localpart:
                mxids.add(f"@{localpart}:{SERVER_NAME}")
        nxt = data.get("pagination", {}).get("next")
        # authentik 'next' is a page number, not a URL
        if nxt:
            base = url.split("&page=")[0]
            url = f"{base}&page={nxt}"
        else:
            url = None
    return mxids


# ---------- Matrix ----------
def room_members(room_id):
    rid = urllib.parse.quote(room_id)
    status, data = _req("GET", f"{MATRIX_HS_URL}/_synapse/admin/v1/rooms/{rid}/members", MATRIX_BOT_TOKEN)
    if status != 200:
        raise RuntimeError(f"room members {room_id} -> {status}: {data}")
    return set(data.get("members", []))


def user_exists(mxid):
    uid = urllib.parse.quote(mxid)
    status, _ = _req("GET", f"{MATRIX_HS_URL}/_synapse/admin/v2/users/{uid}", MATRIX_BOT_TOKEN)
    return status == 200


def force_join(room_id, mxid):
    rid = urllib.parse.quote(room_id)
    status, data = _req("POST", f"{MATRIX_HS_URL}/_synapse/admin/v1/join/{rid}",
                        MATRIX_BOT_TOKEN, {"user_id": mxid})
    return status == 200, data


def kick(room_id, mxid, reason="premium membership ended"):
    rid = urllib.parse.quote(room_id)
    status, data = _req("POST", f"{MATRIX_HS_URL}/_matrix/client/v3/rooms/{rid}/kick",
                        MATRIX_BOT_TOKEN, {"user_id": mxid, "reason": reason})
    return status == 200, data


def load_premium_rooms():
    with open(SPACES_FILE) as f:
        spaces = json.load(f)
    rooms = list(spaces.get("premium_rooms", []))
    if spaces.get("premium_space"):
        rooms.append(spaces["premium_space"])  # also gate the space itself
    return rooms


# ---------- Frappe LMS ----------
def premium_emails():
    """Emails of every active user in the premium group (for LMS enrollment)."""
    emails = set()
    url = (f"{AUTHENTIK_URL}/api/v3/core/users/"
           f"?groups_by_name={urllib.parse.quote(PREMIUM_GROUP)}&page_size=100")
    while url:
        status, data = _req("GET", url, AUTHENTIK_TOKEN)
        if status != 200:
            break
        for u in data.get("results", []):
            if u.get("is_active") and u.get("email"):
                emails.add(u["email"].strip().lower())
        nxt = data.get("pagination", {}).get("next")
        url = f"{url.split('&page=')[0]}&page={nxt}" if nxt else None
    return emails


def _frappe(method, path, body=None, params=None):
    url = f"{FRAPPE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": FRAPPE_AUTH, "Host": FRAPPE_HOST, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:200]}
    except Exception as e:
        return 0, {"error": str(e)}


def lms_paid_courses():
    st, d = _frappe("GET", "/api/resource/LMS%20Course", params={
        "filters": json.dumps([["paid_course", "=", 1], ["published", "=", 1]]),
        "fields": json.dumps(["name"]), "limit_page_length": "0"})
    return [c["name"] for c in d.get("data", [])] if st == 200 else []


def frappe_user_exists(email):
    st, _ = _frappe("GET", f"/api/resource/User/{urllib.parse.quote(email)}")
    return st == 200


def lms_enrolled(course):
    """Return {member_email: enrollment_name} for a course."""
    st, d = _frappe("GET", "/api/resource/LMS%20Enrollment", params={
        "filters": json.dumps([["course", "=", course]]),
        "fields": json.dumps(["name", "member"]), "limit_page_length": "0"})
    return {r["member"]: r["name"] for r in d.get("data", [])} if st == 200 else {}


def lms_sync(premium):
    """Enroll premium members in paid courses; unenroll those who lapsed."""
    granted = revoked = 0
    if not FRAPPE_AUTH:
        return granted, revoked
    for course in lms_paid_courses():
        enrolled = lms_enrolled(course)
        for email in premium - set(enrolled):
            if not frappe_user_exists(email):
                continue  # no LMS account yet; enrolls on next reconcile after first login
            st, d = _frappe("POST", "/api/resource/LMS%20Enrollment", {"course": course, "member": email})
            if st in (200, 201):
                granted += 1; log("LMS GRANT", email, "->", course)
            else:
                log("ERR lms enroll", email, course, d)
        for email, ename in enrolled.items():
            if email.lower() in premium or email.lower() in LMS_SAFELIST:
                continue
            st, _ = _frappe("DELETE", f"/api/resource/LMS%20Enrollment/{urllib.parse.quote(ename)}")
            if st in (200, 202):
                revoked += 1; log("LMS REVOKE", email, "<-", course)
    return granted, revoked


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
                     f"🎥 <b>Join live webinars</b> right in the app<br>"
                     f"💎 <b>Go Premium</b> ($20/mo) to unlock premium rooms, paid courses & member webinars<br><br>"
                     f'Open the app → <a href="{APP_URL}">{APP_URL}</a>')
        plain = (f"Welcome to {BRAND_NAME}, {name}! Say hi in the rooms, browse courses, join live webinars, "
                 f"and go Premium to unlock everything. Open the app: {APP_URL}")
        if dm_send(mxid, html_body, plain):
            welcomed.add(mxid); n += 1; log("WELCOMED", mxid)
    if n:
        save_welcomed(welcomed)
    return n


# ---------- reconcile ----------
def reconcile():
    with _lock:
        added = kicked = 0
        try:
            premium = premium_mxids()
            rooms = load_premium_rooms()
            for room in rooms:
                try:
                    members = room_members(room)
                except Exception as e:
                    log("ERR members", room, e); continue
                # grant
                for mxid in premium - members:
                    if not user_exists(mxid):
                        log("skip (no matrix acct yet):", mxid); continue
                    ok, data = force_join(room, mxid)
                    if ok:
                        added += 1; log("GRANT", mxid, "->", room)
                    else:
                        log("ERR grant", mxid, room, data)
                # revoke
                for mxid in members - premium - SAFELIST:
                    ok, data = kick(room, mxid)
                    if ok:
                        kicked += 1; log("REVOKE", mxid, "<-", room)
                    else:
                        log("ERR revoke", mxid, room, data)
            # premium course enrollment gating (mirrors the room gating above)
            lms_granted, lms_revoked = lms_sync({e.lower() for e in premium_emails()})
            # DM any brand-new members a welcome
            welcomed = welcome_new_members()
            _last.update(time=int(time.time()), premium=len(premium),
                         added=added, kicked=kicked, lms_granted=lms_granted,
                         lms_revoked=lms_revoked, welcomed=welcomed, error=None)
            log(f"reconcile done: premium={len(premium)} added={added} kicked={kicked} "
                f"lms_granted={lms_granted} lms_revoked={lms_revoked} welcomed={welcomed}")
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
    log(f"membership-sync starting; premium group='{PREMIUM_GROUP}' interval={INTERVAL}s "
        f"listen={LISTEN_HOST}:{LISTEN_PORT}")
    threading.Thread(target=loop, daemon=True).start()
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()
