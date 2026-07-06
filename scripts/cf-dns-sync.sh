#!/usr/bin/env bash
# cf-dns-sync.sh — idempotently create the DNS records LibreSynergy needs.
#
# Reads LS_* from ../libresynergy.env and CF_API_TOKEN from
# ${LS_SECRETS_DIR}/cloudflare.env. Every record is an A record pointing at the
# relay's public IP, DNS-only (proxied=false — Cloudflare must NOT terminate
# TLS; the whole point of the relay is that certificates live on your node).
#
#   ./scripts/cf-dns-sync.sh          # create/verify all records
#   ./scripts/cf-dns-sync.sh --dry    # show what would be created
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a; . "$ROOT/libresynergy.env"; set +a
SECRETS="${LS_SECRETS_DIR:-$ROOT/secrets}"
. "$SECRETS/cloudflare.env"
: "${CF_API_TOKEN:?no CF_API_TOKEN in $SECRETS/cloudflare.env}"
DOMAIN="${LS_BASE_DOMAIN:?}"
IP="${LS_RELAY_PUBLIC_IP:?}"
DRY="${1:-}"

# -4: IP-allowlisted tokens fail from unexpected IPv6 egress with code 9109
# ("Cannot use the access token from location: …") — that error means wrong
# source IP, NOT a bad token; run this script from the allowlisted machine.
api(){ curl -4 -s -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" "$@"; }

# Sanity: token must verify before we touch anything. Account-owned tokens
# (Account → API Tokens in the dashboard) only verify on the account endpoint;
# the user endpoint answers "Invalid API Token" for them, misleadingly.
if [ -n "${CF_ACCOUNT_ID:-}" ]; then
  VERIFY_URL="https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/tokens/verify"
else
  VERIFY_URL="https://api.cloudflare.com/client/v4/user/tokens/verify"
fi
api "$VERIFY_URL" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['success'] else sys.stderr.write('token invalid: %s\n' % d['errors']) or 1)"

ZONE=$(api "https://api.cloudflare.com/client/v4/zones?name=$DOMAIN" \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r[0]['id'] if r else '')")
[ -n "$ZONE" ] || { echo "zone $DOMAIN not found (token may lack Zone:Read)"; exit 1; }
echo "zone $DOMAIN = $ZONE"

have(){ # have <type> <fqdn> -> prints existing content or nothing
  api "https://api.cloudflare.com/client/v4/zones/$ZONE/dns_records?type=$1&name=$2" \
    | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r[0]['content'] if r else '')"
}

ensure_a(){ # ensure_a <fqdn>
  local cur; cur=$(have A "$1")
  if [ "$cur" = "$IP" ]; then echo "  ok   A $1 -> $IP"; return; fi
  if [ -n "$cur" ]; then echo "  SKIP A $1 exists -> $cur (differs from $IP; not touching)"; return; fi
  if [ "$DRY" = "--dry" ]; then echo "  MAKE A $1 -> $IP"; return; fi
  api -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE/dns_records" \
    --data "{\"type\":\"A\",\"name\":\"$1\",\"content\":\"$IP\",\"ttl\":300,\"proxied\":false}" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('  made A $1 -> $IP' if d['success'] else '  FAIL $1: %s' % d['errors'])"
}

# The full host set: core + optional units. Harmless to create ahead of enabling
# a unit — the relay just has no SNI entry until you run ls-route.
for sub in "" www app auth chat matrix learn meet live premium btcpay rtmp play admin; do
  fqdn="${sub:+$sub.}$DOMAIN"
  ensure_a "$fqdn"
done

# Minecraft SRV so vanilla clients can use play.<domain> without a port.
cur=$(have SRV "_minecraft._tcp.play.$DOMAIN")
if [ -n "$cur" ]; then echo "  ok   SRV _minecraft._tcp.play.$DOMAIN"; elif [ "$DRY" = "--dry" ]; then echo "  MAKE SRV _minecraft._tcp.play.$DOMAIN -> play.$DOMAIN:25565"; else
  api -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE/dns_records" \
    --data "{\"type\":\"SRV\",\"name\":\"_minecraft._tcp.play.$DOMAIN\",\"data\":{\"priority\":0,\"weight\":0,\"port\":25565,\"target\":\"play.$DOMAIN\"},\"ttl\":300}" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('  made SRV -> play.$DOMAIN:25565' if d['success'] else '  FAIL SRV: %s' % d['errors'])"
fi
echo "done."
