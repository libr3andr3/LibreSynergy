#!/usr/bin/env bash
# preflight — check the environment is ready before (or after) `ls up`.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/libresynergy.env" ] && { set -a; . "$ROOT/libresynergy.env"; set +a; }

pass=0; warn=0; fail=0
ok(){   printf '  \033[0;32m✓\033[0m %s\n' "$*"; pass=$((pass+1)); }
note(){ printf '  \033[1;33m!\033[0m %s\n' "$*"; warn=$((warn+1)); }
bad(){  printf '  \033[0;31m✗\033[0m %s\n' "$*"; fail=$((fail+1)); }

echo "LibreSynergy preflight"

command -v docker >/dev/null && ok "docker present" || bad "docker not found"
docker compose version >/dev/null 2>&1 && ok "docker compose v2 present" || bad "docker compose plugin missing"
command -v wg >/dev/null && ok "wireguard-tools present" || note "wg not found (needed on node/relay, not always locally)"

# WireGuard tunnel handshake (node side)
if command -v wg >/dev/null 2>&1; then
  if wg show all latest-handshakes 2>/dev/null | awk '{print $3}' | grep -qE '^[0-9]+$'; then
    ok "WireGuard has at least one recent handshake"
  else
    note "no WireGuard handshake seen (run on the node; relay may be down)"
  fi
fi

# DNS resolution for each configured subdomain
for host in "${LS_AUTH:-}" "${LS_MATRIX:-}" "${LS_CHAT:-}" "${LS_LEARN:-}" "${LS_MEET:-}" "${LS_APP:-}"; do
  [ -n "$host" ] || continue
  ip="$(getent hosts "$host" 2>/dev/null | awk '{print $1; exit}')"
  if [ -n "$ip" ]; then
    [ "$ip" = "${LS_RELAY_PUBLIC_IP:-}" ] && ok "$host -> $ip (relay)" || note "$host -> $ip (expected relay ${LS_RELAY_PUBLIC_IP:-?})"
  else
    bad "$host does not resolve — create an A record -> ${LS_RELAY_PUBLIC_IP:-<relay ip>}"
  fi
done

# Secrets present?
for f in auth-secrets email matrix frappe jitsi; do
  [ -f "${LS_SECRETS_DIR:-./secrets}/$f.env" ] && ok "secrets/$f.env present" || bad "missing ${LS_SECRETS_DIR:-./secrets}/$f.env (run ./bin/ls init)"
done

echo
printf 'preflight: \033[0;32m%d ok\033[0m, \033[1;33m%d warn\033[0m, \033[0;31m%d fail\033[0m\n' "$pass" "$warn" "$fail"
[ "$fail" -eq 0 ]
