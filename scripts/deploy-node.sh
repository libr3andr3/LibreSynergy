#!/usr/bin/env bash
# ============================================================================
#  deploy-node.sh — ship the branded web tree + renderer to the node and apply.
#
#  What it does:
#    1. rsync  www/                    → $NODE_SSH:$NODE_DIR/www/        (additive, never --delete)
#    2. rsync  scripts/apply-branding.sh + libresynergy.env
#                                      → $NODE_SSH:$NODE_DIR/libresynergy/
#       (the node's previous env is kept as libresynergy.env.bak-<ts> when it differs)
#    3. run    apply-branding.sh on the node (renders templates, tokens, icons,
#              Authentik/Frappe/Jitsi propagation)
#    4. force-recreate the caddy container so the edge serves the new tree
#
#  Parameters (env vars; sensible verified defaults):
#    NODE_SSH        ssh alias of the node          (default: $LS_NODE_SSH or "node")
#    NODE_DIR        deploy root on the node        (default: /home/yaya/docker — see below)
#    CADDY_PROJECT   compose project owning caddy   (default: "yaya")
#    PUSH_ENV=0      don't overwrite the node's libresynergy.env
#    SKIP_CADDY=1    don't recreate caddy
#
#  ┌──────────────────────────────────────────────────────────────────────────┐
#  │ NODE_DIR — VERIFIED 2026-07-06 against the live node:                   │
#  │   caddy container:  yaya-caddy-1                                        │
#  │   compose project:  yaya   (working dir /home/yaya/docker)              │
#  │   www bind mount:   /home/yaya/docker/www  →  /srv/www                  │
#  │ If you point this at a different node, verify first with:               │
#  │   ssh <node> docker inspect <caddy> --format '{{json .Mounts}}'         │
#  └──────────────────────────────────────────────────────────────────────────┘
#
#  Safe to re-run: rsync is incremental, apply-branding is idempotent.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
say(){  printf '  • %s\n' "$*"; }
head_(){ printf '\n==> %s\n' "$*"; }

[ -f "$ROOT/libresynergy.env" ] || { echo "ERROR: $ROOT/libresynergy.env missing — copy libresynergy.env.example and edit"; exit 1; }
# Source only to pick up LS_NODE_SSH / LS_BASE_DOMAIN for defaults + smoke test.
set -a; . "$ROOT/libresynergy.env"; set +a

NODE_SSH="${NODE_SSH:-${LS_NODE_SSH:-node}}"
NODE_DIR="${NODE_DIR:-/home/yaya/docker}"          # ← VERIFIED default, see box above
CADDY_PROJECT="${CADDY_PROJECT:-yaya}"

echo "LibreSynergy → deploying to ${NODE_SSH}:${NODE_DIR} (brand: ${LS_BRAND_NAME:-?} @ ${LS_BASE_DOMAIN:-?})"

command -v rsync >/dev/null 2>&1 || { echo "ERROR: rsync not installed locally"; exit 1; }
ssh -o BatchMode=yes "$NODE_SSH" true 2>/dev/null || { echo "ERROR: cannot ssh to '$NODE_SSH' non-interactively"; exit 1; }

head_ "1/4 Sync www/ (additive — node-local content is preserved)"
ssh "$NODE_SSH" "mkdir -p '$NODE_DIR/www' '$NODE_DIR/libresynergy'"
rsync -az --out-format='  • %n' "$ROOT/www/" "$NODE_SSH:$NODE_DIR/www/" | head -40 || true
say "www tree synced"

head_ "2/4 Sync renderer + config"
rsync -az "$ROOT/scripts/apply-branding.sh" "$NODE_SSH:$NODE_DIR/libresynergy/apply-branding.sh"
say "apply-branding.sh → $NODE_DIR/libresynergy/"
if [ "${PUSH_ENV:-1}" = 1 ]; then
  # --backup keeps the node's previous env as libresynergy.env.bak-<ts> when it differs
  rsync -az --backup --suffix=".bak-$(date +%Y%m%d-%H%M%S)" \
    "$ROOT/libresynergy.env" "$NODE_SSH:$NODE_DIR/libresynergy/libresynergy.env"
  say "libresynergy.env → $NODE_DIR/libresynergy/ (previous kept as .bak-* if it differed)"
else
  say "PUSH_ENV=0 — node keeps its own libresynergy.env"
fi

head_ "3/4 Apply branding on the node"
ssh "$NODE_SSH" "bash '$NODE_DIR/libresynergy/apply-branding.sh'"

head_ "4/4 Recreate caddy"
if [ "${SKIP_CADDY:-0}" = 1 ]; then
  say "SKIP_CADDY=1 — skipped"
elif ssh "$NODE_SSH" "cd '$NODE_DIR' && docker compose -p '$CADDY_PROJECT' up -d --force-recreate caddy" >/dev/null 2>&1; then
  say "caddy recreated (project '$CADDY_PROJECT')"
else
  echo "  ! compose recreate failed — falling back to docker restart"
  CADDY_C="$(ssh "$NODE_SSH" "docker ps --format '{{.Names}}' | grep -m1 caddy" || true)"
  if [ -n "$CADDY_C" ]; then
    ssh "$NODE_SSH" "docker restart '$CADDY_C'" >/dev/null && say "restarted $CADDY_C"
  else
    echo "  ! no caddy container found on $NODE_SSH — check CADDY_PROJECT/NODE_DIR"; exit 1
  fi
fi

head_ "Deployed"
if [ -n "${LS_APP:-}" ] || [ -n "${LS_BASE_DOMAIN:-}" ]; then
  APP_HOST="${LS_APP:-app.${LS_BASE_DOMAIN}}"
  if command -v curl >/dev/null 2>&1; then
    code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://${APP_HOST}" || echo 'unreachable')"
    say "smoke test: https://${APP_HOST} → HTTP ${code}"
  else
    say "verify: curl -I https://${APP_HOST}"
  fi
fi
say "re-run any time — every step is idempotent"
