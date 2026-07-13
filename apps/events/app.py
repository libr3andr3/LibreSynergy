#!/usr/bin/env python3
"""
events — webinar scheduling + auto-announcements for the community.

- GET  /api/events            -> upcoming + live events (public; the app shell renders these)
- POST /api/events            -> create an event (admin: Bearer EVENTS_ADMIN_TOKEN)
- DELETE /api/events/<id>     -> remove an event (admin)
- GET  /api/events/admin      -> a tiny host form to schedule events (token in ?token=)

A background loop posts to the community #general room (community-bot token): an announcement
when an event is scheduled, and a "starting soon" reminder ~15 min before. Pure stdlib.
"""
import json, os, threading, time, urllib.parse, urllib.request, urllib.error, html
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "9102"))
ADMIN_TOKEN = os.environ.get("EVENTS_ADMIN_TOKEN", "")
MATRIX_HS = os.environ.get("MATRIX_HS_URL", "http://127.0.0.1:8008").rstrip("/")
BOT_TOKEN = os.environ.get("MATRIX_BOT_TOKEN", "")
ANNOUNCE_ROOM = os.environ.get("ANNOUNCE_ROOM", "")
DEFAULT_ROOM = os.environ.get("DEFAULT_EVENT_ROOM", "Live")
APP_URL = os.environ.get("APP_URL", "")
STATE_DIR = os.environ.get("STATE_DIR", "/state")
STATE_FILE = os.path.join(STATE_DIR, "events.json")
REMIND_BEFORE = int(os.environ.get("REMIND_BEFORE_MIN", "15")) * 60
CORS = "*"

_lock = threading.Lock()


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), *a, flush=True)


def load():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"events": []}


def save(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, STATE_FILE)


def parse_start(v):
    """Accept epoch seconds or ISO-8601 (assumed UTC if no tz)."""
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def public_events():
    now = time.time()
    out = []
    for e in load().get("events", []):
        end = e["start"] + e.get("duration_min", 60) * 60
        if end < now:
            continue
        live = e["start"] <= now <= end
        out.append({"id": e["id"], "title": e["title"], "desc": e.get("desc", ""),
                    "start": e["start"], "duration_min": e.get("duration_min", 60),
                    "room": e.get("room", DEFAULT_ROOM),
                    "host": e.get("host", ""), "status": "live" if live else "upcoming"})
    out.sort(key=lambda x: (x["status"] != "live", x["start"]))
    return out


def public_announcements(limit=15):
    anns = sorted(load().get("announcements", []), key=lambda a: a.get("ts", 0), reverse=True)
    return [{"id": a["id"], "title": a["title"], "body": a.get("body", ""), "ts": a["ts"]}
            for a in anns[:limit]]


def feed():
    """Combined home feed: live/upcoming events first, then recent announcements."""
    items = []
    for e in public_events():
        items.append({"type": "event", "id": e["id"], "title": e["title"], "body": e.get("desc", ""),
                      "ts": e["start"], "status": e["status"], "room": e["room"]})
    for a in public_announcements():
        items.append({"type": "announcement", "id": a["id"], "title": a["title"],
                      "body": a["body"], "ts": a["ts"]})
    return items


# ---- Matrix announce ----
def matrix_send(room, html_body, plain):
    if not (room and BOT_TOKEN):
        return
    txn = str(int(time.time() * 1000))
    rid = urllib.parse.quote(room)
    body = {"msgtype": "m.notice", "format": "org.matrix.custom.html",
            "formatted_body": html_body, "body": plain}
    req = urllib.request.Request(
        f"{MATRIX_HS}/_matrix/client/v3/rooms/{rid}/send/m.room.message/{txn}",
        data=json.dumps(body).encode(), method="PUT",
        headers={"Authorization": f"Bearer {BOT_TOKEN}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        log("matrix_send err", e)


def fmt(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%a %b %-d · %H:%M UTC")


def announce_loop():
    while True:
        try:
            with _lock:
                d = load()
                changed = False
                now = time.time()
                for e in d.get("events", []):
                    if not e.get("announced"):
                        matrix_send(ANNOUNCE_ROOM,
                            f"<h4>📅 New webinar scheduled</h4><b>{html.escape(e['title'])}</b><br>"
                            f"{fmt(e['start'])}<br>{html.escape(e.get('desc',''))}<br>"
                            f"<a href=\"{APP_URL}/#webinars\">Join in the app →</a>",
                            f"📅 New webinar: {e['title']} — {fmt(e['start'])}. Join at {APP_URL}")
                        e["announced"] = True; changed = True
                    elif not e.get("reminded") and 0 < e["start"] - now <= REMIND_BEFORE:
                        matrix_send(ANNOUNCE_ROOM,
                            f"<h4>🔴 Starting soon</h4><b>{html.escape(e['title'])}</b> begins in "
                            f"~{max(1,int((e['start']-now)/60))} min.<br>"
                            f"<a href=\"{APP_URL}/#webinars\">Join now →</a>",
                            f"🔴 Starting soon: {e['title']} — join at {APP_URL}/#webinars")
                        e["reminded"] = True; changed = True
                # broadcast new announcements to chat
                for a in d.get("announcements", []):
                    if not a.get("posted"):
                        matrix_send(ANNOUNCE_ROOM,
                            f"<h4>📣 {html.escape(a['title'])}</h4>{html.escape(a.get('body',''))}<br>"
                            f"<a href=\"{APP_URL}\">Open the app →</a>",
                            f"📣 {a['title']} — {a.get('body','')}")
                        a["posted"] = True; changed = True
                # keep only the most recent 50 announcements
                if len(d.get("announcements", [])) > 50:
                    d["announcements"] = sorted(d["announcements"], key=lambda x: x.get("ts", 0))[-50:]
                    changed = True
                # prune events ended > 2 days ago
                before = len(d.get("events", []))
                d["events"] = [e for e in d.get("events", [])
                               if e["start"] + e.get("duration_min", 60) * 60 > now - 172800]
                if changed or len(d["events"]) != before:
                    save(d)
        except Exception as e:
            log("announce_loop err", e)
        time.sleep(60)


ADMIN_HTML = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Schedule a webinar</title><style>body{{font-family:-apple-system,sans-serif;background:#0b0b12;color:#eef0ff;
max-width:460px;margin:0 auto;padding:28px}}h1{{font-size:22px}}label{{display:block;margin:14px 0 5px;color:#9aa0b5;font-size:13px}}
input,textarea{{width:100%;padding:12px;border-radius:10px;border:1px solid #262633;background:#15151f;color:#eef0ff;font-size:15px}}
button{{margin-top:18px;width:100%;padding:14px;border:0;border-radius:12px;font-weight:800;
background:linear-gradient(135deg,#7c6cff,#ffc15e);color:#0b0b12;font-size:15px}}#m{{margin-top:14px;color:#5ad28a}}</style>
<h1>Schedule a webinar</h1>
<label>Title</label><input id=title placeholder="Live Q&amp;A">
<label>Description</label><textarea id=desc rows=3 placeholder="What's it about?"></textarea>
<label>Start (your local time)</label><input id=start type=datetime-local>
<label>Duration (minutes)</label><input id=dur type=number value=60>
<button onclick=go()>Schedule + announce</button><div id=m></div>
<hr style="border-color:#262633;margin:28px 0">
<h1>Post an announcement</h1>
<label>Title</label><input id=atitle placeholder="Big news!">
<label>Message</label><textarea id=abody rows=3 placeholder="What's happening?"></textarea>
<button onclick=ann()>Post + broadcast to chat</button><div id=am></div>
<script>
function ann(){{
 fetch('/api/announcements',{{method:'POST',headers:{{'Content-Type':'application/json','Authorization':'Bearer '+t}},
  body:JSON.stringify({{title:atitle.value,body:abody.value}})}})
 .then(r=>r.json()).then(d=>{{am.textContent=d.ok?'✅ Posted — broadcast to chat + app home.':'⚠️ '+(d.error||'failed');atitle.value='';abody.value='';}})
 .catch(e=>am.textContent='⚠️ '+e);
}}
</script>
<script>
var t=new URLSearchParams(location.search).get('token')||'';
function go(){{
 var iso=new Date(document.getElementById('start').value).toISOString();
 fetch('/api/events',{{method:'POST',headers:{{'Content-Type':'application/json','Authorization':'Bearer '+t}},
  body:JSON.stringify({{title:title.value,desc:desc.value,start:iso,duration_min:+dur.value}})}})
 .then(r=>r.json()).then(d=>{{m.textContent=d.ok?'✅ Scheduled — announced in chat.':'⚠️ '+(d.error||'failed');}})
 .catch(e=>m.textContent='⚠️ '+e);
}}
</script>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        body = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", CORS)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _admin(self):
        auth = self.headers.get("Authorization", "")
        return ADMIN_TOKEN and auth == f"Bearer {ADMIN_TOKEN}"

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/events":
            self._send(200, {"events": public_events()})
        elif path == "/api/feed":
            self._send(200, {"feed": feed()})
        elif path == "/api/announcements":
            self._send(200, {"announcements": public_announcements()})
        elif path == "/api/events/admin":
            self._send(200, ADMIN_HTML, "text/html; charset=utf-8")
        elif path.startswith("/api/events/health") or path == "/healthz":
            self._send(200, {"ok": True, "count": len(load().get("events", []))})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path not in ("/api/events", "/api/announcements"):
            return self._send(404, {"error": "not found"})
        if not self._admin():
            return self._send(401, {"ok": False, "error": "unauthorized"})
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"ok": False, "error": "bad json"})
        if path == "/api/announcements":
            if not data.get("title"):
                return self._send(400, {"ok": False, "error": "title required"})
            ann = {"id": "an" + str(int(time.time())) + str(os.getpid() % 1000),
                   "title": str(data["title"])[:120], "body": str(data.get("body", ""))[:1000],
                   "ts": int(time.time()), "posted": False}
            with _lock:
                d = load(); d.setdefault("announcements", []).append(ann); save(d)
            log("announced", ann["title"])
            return self._send(200, {"ok": True, "id": ann["id"]})
        start = parse_start(data.get("start"))
        if not data.get("title") or not start:
            return self._send(400, {"ok": False, "error": "title and valid start required"})
        ev = {"id": "ev" + str(int(time.time())) + str(os.getpid() % 1000),
              "title": str(data["title"])[:120], "desc": str(data.get("desc", ""))[:1000],
              "start": start, "duration_min": int(data.get("duration_min", 60)),
              "room": str(data.get("room", DEFAULT_ROOM))[:60],
              "host": str(data.get("host", ""))[:60], "announced": False, "reminded": False}
        with _lock:
            d = load(); d.setdefault("events", []).append(ev); save(d)
        log("scheduled", ev["title"], fmt(start))
        self._send(200, {"ok": True, "id": ev["id"]})

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if not path.startswith("/api/events/"):
            return self._send(404, {"error": "not found"})
        if not self._admin():
            return self._send(401, {"ok": False, "error": "unauthorized"})
        eid = path.rsplit("/", 1)[-1]
        with _lock:
            d = load(); d["events"] = [e for e in d.get("events", []) if e["id"] != eid]; save(d)
        self._send(200, {"ok": True})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    log(f"events service on {LISTEN_HOST}:{LISTEN_PORT} announce_room={ANNOUNCE_ROOM or 'none'}")
    threading.Thread(target=announce_loop, daemon=True).start()
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), H).serve_forever()
