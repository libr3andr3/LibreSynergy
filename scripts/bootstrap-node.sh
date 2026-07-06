#!/usr/bin/env bash
# bootstrap-node.sh — prepare THIS machine ("node") to run LibreSynergy:
# Docker, a WireGuard spoke to the relay, and the data tree. Idempotent.
#
#   sudo ./scripts/bootstrap-node.sh <relay_public_ip> [relay_wg_pubkey]
#
# Prints this node's WireGuard public key — paste it into the relay's peer list
# (or run the relay's `add-peer`), then bring the tunnel up.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/libresynergy.env" ] && { set -a; . "$ROOT/libresynergy.env"; set +a; }
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

RELAY_IP="${1:?usage: bootstrap-node.sh <relay_public_ip> [relay_wg_pubkey]}"
RELAY_PUBKEY="${2:-<paste-relay-public-key-then-edit-/etc/wireguard/wg0.conf>}"
WG_IP="${LS_WG_IP:-10.0.0.2}"; RELAY_WG_IP="${LS_RELAY_WG_IP:-10.0.0.1}"

echo "▸ installing docker + wireguard"
if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sh; fi
apt-get install -y wireguard wireguard-tools >/dev/null

echo "▸ configuring WireGuard spoke ($WG_IP -> relay $RELAY_IP)"
umask 077; mkdir -p /etc/wireguard
[ -f /etc/wireguard/node.key ] || wg genkey | tee /etc/wireguard/node.key | wg pubkey > /etc/wireguard/node.pub
if [ ! -f /etc/wireguard/wg0.conf ]; then
  cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = $WG_IP/24
PrivateKey = $(cat /etc/wireguard/node.key)

[Peer]
PublicKey = $RELAY_PUBKEY
Endpoint = $RELAY_IP:51820
AllowedIPs = $RELAY_WG_IP/32
PersistentKeepalive = 25
EOF
  echo "  wrote /etc/wireguard/wg0.conf"
fi
systemctl enable --now wg-quick@wg0 2>/dev/null || wg-quick up wg0 || true

echo "▸ creating data tree under ${LS_DATA_DIR:-$ROOT/data}"
install -d -m 755 "${LS_DATA_DIR:-$ROOT/data}"/{caddy,authentik,matrix,frappe,jitsi,minecraft,files,jobs}

echo
echo "✓ node ready. This node's WireGuard public key:"
echo "    $(cat /etc/wireguard/node.pub)"
echo "  → add it as a peer on the relay (AllowedIPs $WG_IP/32), then: ./bin/ls up"
