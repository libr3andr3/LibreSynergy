#!/usr/bin/env bash
# scaffold-matrix.sh — build the community's Matrix structure on a fresh
# homeserver: register the community bot (appservice token), create the
# community space (+ #general, #welcome), and write the room map the stack
# consumes:
#   ${LS_SECRETS_DIR}/spaces.json   (membership-sync: who belongs where)
#   ANNOUNCE_ROOM in events.env     (events service: where announcements go)
#
# Idempotent-ish: re-running creates new rooms only if the map is missing;
# it never deletes anything. Run once after `ls up`, before inviting anyone.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/libresynergy.env" ] && { set -a; . "$ROOT/libresynergy.env"; set +a; }
SECRETS="${LS_SECRETS_DIR:-$ROOT/secrets}"
SERVER="${LS_MATRIX:?set LS_MATRIX (e.g. matrix.example.com)}"
HS="${LS_MATRIX_INTERNAL:-http://127.0.0.1:8008}"

[ -f "$SECRETS/spaces.json" ] && grep -q '"community_space": *"!' "$SECRETS/spaces.json" && {
  echo "spaces.json already has a community_space — refusing to scaffold twice."
  echo "Delete $SECRETS/spaces.json first if you really want a fresh structure."
  exit 0
}

python3 - "$HS" "$SERVER" "$SECRETS" <<'PYEOF'
import json, sys, urllib.request, urllib.error, os
HS, SERVER, SECRETS = sys.argv[1], sys.argv[2], sys.argv[3]
tok = ""
for line in open(f"{SECRETS}/matrix.env"):
    if line.startswith("MATRIX_BOT_TOKEN="):
        tok = line.strip().split("=", 1)[1]
assert tok and "REPLACE" not in tok, "MATRIX_BOT_TOKEN missing — run gen-secrets + set up the bot appservice first"

def api(method, path, body=None):
    req = urllib.request.Request(HS + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        return {"_status": e.code, **json.loads(e.read() or b"{}")}

r = api("POST", "/_matrix/client/v3/register",
        {"type": "m.login.application_service", "username": "community-bot"})
print("bot:", r.get("user_id") or r.get("errcode"))

def mkroom(name, public=True, space=False, parent=None):
    body = {"name": name, "preset": "public_chat" if public else "private_chat",
            "visibility": "public" if public else "private"}
    if space: body["creation_content"] = {"type": "m.space"}
    rid = api("POST", "/_matrix/client/v3/createRoom", body).get("room_id")
    print(f"  {name}: {rid}")
    if parent and rid:
        api("PUT", f"/_matrix/client/v3/rooms/{parent}/state/m.space.child/{rid}",
            {"via": [SERVER]})
    return rid

cspace  = mkroom("Community", public=True, space=True)
general = mkroom("General", public=True, parent=cspace)
welcome = mkroom("Welcome", public=True, parent=cspace)

out = {"community_space": cspace, "free_rooms": [general, welcome]}
path = f"{SECRETS}/spaces.json"
with open(path, "w") as f:
    json.dump(out, f, indent=2); f.write("\n")
os.chmod(path, 0o600)
print(f"wrote {path}")

ev = f"{SECRETS}/events.env"
if os.path.exists(ev):
    lines = [l for l in open(ev) if not l.startswith("ANNOUNCE_ROOM=")]
    lines.append(f"ANNOUNCE_ROOM={general}\n")
    open(ev, "w").writelines(lines); os.chmod(ev, 0o600)
    print(f"set ANNOUNCE_ROOM in {ev}")
print("Done. Restart the payments profile so the services read the new map:")
print("  ./bin/ls restart")
PYEOF
