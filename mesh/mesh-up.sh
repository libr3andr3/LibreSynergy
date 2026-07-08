#!/bin/bash
# LibreSynergy p2p mesh — punch a direct UDP path and bring up a WireGuard
# tunnel to a peer, with the community rendezvous as coordinator. Run this
# on BOTH peers at (roughly) the same time; each side discovers the other's
# NAT-reflexive endpoint and comes up pointing straight at it. No relay in
# the data path.
#
# Required env (or edit the defaults below):
#   MESH_RENDEZVOUS  rendezvous host/IP (mesh/rendezvous.py on your VPS)
#   MESH_MY_ID       this peer's name in the swarm        e.g. node
#   MESH_PEER_ID     the other peer's name                e.g. studio
#   MESH_MY_IP       this side's tunnel address           e.g. 10.99.0.2
#   MESH_PEER_IP     other side's tunnel address          e.g. 10.99.0.3
#   MESH_PEER_PUBKEY other side's WireGuard public key
# Optional:
#   MESH_WG_PORT     UDP listen port (default 51888; must match what you punch)
#   MESH_KEY_FILE    private key path (default /etc/wireguard/mesh0.key; created if absent)
#   MESH_NAT_ROUTE   "<peer-nat-ip> <gateway> <dev>" — add a host route so punch
#                    traffic exits a specific uplink. Needed when this host's
#                    default route already rides another tunnel (e.g. the
#                    sovereign relay): without it the "direct" path silently
#                    hairpins through that tunnel's exit.
set -euo pipefail
RENDEZVOUS=${MESH_RENDEZVOUS:?set MESH_RENDEZVOUS}
MY_ID=${MESH_MY_ID:?set MESH_MY_ID}
PEER_ID=${MESH_PEER_ID:?set MESH_PEER_ID}
MY_IP=${MESH_MY_IP:?set MESH_MY_IP}
PEER_IP=${MESH_PEER_IP:?set MESH_PEER_IP}
PEER_PUBKEY=${MESH_PEER_PUBKEY:?set MESH_PEER_PUBKEY}
WG_PORT=${MESH_WG_PORT:-51888}
KEY_FILE=${MESH_KEY_FILE:-/etc/wireguard/mesh0.key}
HERE=$(cd "$(dirname "$0")" && pwd)

if ! sudo test -f "$KEY_FILE"; then
  umask 077
  wg genkey | sudo tee "$KEY_FILE" >/dev/null
  echo "generated $KEY_FILE — public key (give to the peer):"
  sudo cat "$KEY_FILE" | wg pubkey
fi

sudo wg-quick down mesh0 2>/dev/null || true

if [ -n "${MESH_NAT_ROUTE:-}" ]; then
  read -r nat_ip gw dev <<< "$MESH_NAT_ROUTE"
  sudo ip route replace "$nat_ip/32" via "$gw" dev "$dev"
fi

out=$(python3 "$HERE/wg-punch.py" --server "$RENDEZVOUS" --id "$MY_ID" --peer "$PEER_ID" \
      --swarm wgmesh --wg-port "$WG_PORT")
echo "$out"
read -r tag pip pport <<< "$out"
[ "$tag" = "PUNCHED" ] || { echo "punch failed"; exit 1; }

if [ -n "${MESH_NAT_ROUTE:-}" ]; then
  read -r _ gw dev <<< "$MESH_NAT_ROUTE"
  sudo ip route replace "$pip/32" via "$gw" dev "$dev"
fi

sudo install -m 600 /dev/null /etc/wireguard/mesh0.conf
sudo tee /etc/wireguard/mesh0.conf >/dev/null <<EOF
# LibreSynergy p2p mesh — direct hole-punched tunnel to $PEER_ID (no relay in path)
[Interface]
Address = $MY_IP/24
ListenPort = $WG_PORT
PostUp = wg set %i private-key $KEY_FILE

[Peer]
# $PEER_ID
PublicKey = $PEER_PUBKEY
Endpoint = $pip:$pport
AllowedIPs = $PEER_IP/32
PersistentKeepalive = 5
EOF
sudo wg-quick up mesh0
sudo wg show mesh0
