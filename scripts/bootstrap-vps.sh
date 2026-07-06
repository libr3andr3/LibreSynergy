#!/usr/bin/env bash
# bootstrap-vps.sh — turn a fresh Debian VPS into the LibreSynergy relay:
# a WireGuard hub + an nginx L4 SNI/stream proxy that NEVER decrypts, and a
# locked-down nftables firewall. Idempotent. Run as root ON the VPS.
#
#   sudo ./bootstrap-vps.sh
#
# Prints the relay's WireGuard public key + endpoint; paste those into the
# node's bootstrap. This reproduces the reference relay topology — review the
# values (WG subnet, ports) before running on a box you can't console into.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

WG_HUB_IP="10.0.0.1"; WG_NODE_IP="10.0.0.2"; WG_PORT=51820

echo "▸ installing nginx (stream), wireguard, nftables"
apt-get update -qq
apt-get install -y nginx libnginx-mod-stream wireguard wireguard-tools nftables >/dev/null

echo "▸ WireGuard hub ($WG_HUB_IP, :$WG_PORT)"
umask 077; mkdir -p /etc/wireguard
[ -f /etc/wireguard/vps.key ] || wg genkey | tee /etc/wireguard/vps.key | wg pubkey > /etc/wireguard/vps.pub
if [ ! -f /etc/wireguard/wg0.conf ]; then
  cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = $WG_HUB_IP/24
ListenPort = $WG_PORT
PrivateKey = $(cat /etc/wireguard/vps.key)
# add nodes with:  wg set wg0 peer <NODE_PUBKEY> allowed-ips $WG_NODE_IP/32
EOF
fi
systemctl enable --now wg-quick@wg0 2>/dev/null || wg-quick up wg0 || true

echo "▸ nginx L4 SNI/stream proxy (never decrypts)"
mkdir -p /etc/nginx/stream.d /etc/nginx/certs
[ -f /etc/nginx/certs/fallback.crt ] || openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -subj "/CN=fallback" -keyout /etc/nginx/certs/fallback.key -out /etc/nginx/certs/fallback.crt >/dev/null 2>&1
[ -f /etc/nginx/stream-sni-map.conf ]      || echo "default 127.0.0.1:9443;" > /etc/nginx/stream-sni-map.conf
[ -f /etc/nginx/stream-sni-map-8448.conf ] || echo "default 127.0.0.1:9443;" > /etc/nginx/stream-sni-map-8448.conf
cat > /etc/nginx/nginx.conf <<EOF
user www-data;
worker_processes auto;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;
events { worker_connections 1024; }
stream {
    map \$ssl_preread_server_name \$bk  { include /etc/nginx/stream-sni-map.conf; }
    map \$ssl_preread_server_name \$bk8 { include /etc/nginx/stream-sni-map-8448.conf; }
    server { listen 443;  proxy_protocol on; proxy_pass \$bk;  ssl_preread on; proxy_connect_timeout 10s; proxy_timeout 3600s; }
    server { listen 80;   proxy_protocol on; proxy_pass $WG_NODE_IP:80; proxy_connect_timeout 10s; proxy_timeout 60s; }
    server { listen 8448; proxy_protocol on; proxy_pass \$bk8; ssl_preread on; proxy_connect_timeout 10s; proxy_timeout 3600s; }
    include /etc/nginx/stream.d/*.conf;   # raw-TCP routes (ls-route tcp) land here
}
http {
    include /etc/nginx/mime.types; default_type application/octet-stream;
    server { listen 127.0.0.1:9443 ssl; ssl_certificate /etc/nginx/certs/fallback.crt; ssl_certificate_key /etc/nginx/certs/fallback.key; ssl_reject_handshake on; }
}
EOF
nginx -t && systemctl enable --now nginx && systemctl reload nginx

echo "▸ firewall (nftables): allow 22, 80, 443, 8448 + WG; default drop"
cat > /etc/nftables-hardening.conf <<EOF
table inet filter_hardening {
  chain input {
    type filter hook input priority 0; policy drop;
    iif "lo" accept
    ct state established,related accept
    ct state invalid drop
    iifname "wg0" accept
    ip protocol icmp accept
    ip6 nexthdr ipv6-icmp accept
    udp dport $WG_PORT accept
    tcp dport { 22, 80, 443, 8448 } accept
  }
}
EOF
cat > /etc/systemd/system/nft-hardening.service <<'EOF'
[Unit]
Description=LibreSynergy nftables hardening
After=network-pre.target
[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /etc/nftables-hardening.conf
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now nft-hardening.service

echo
echo "✓ relay ready. Give the node these two values:"
echo "    relay public key : $(cat /etc/wireguard/vps.pub)"
echo "    relay endpoint   : $(curl -s ifconfig.me 2>/dev/null || echo '<this VPS public IP>'):$WG_PORT"
echo "  then add the node as a peer:  wg set wg0 peer <NODE_PUBKEY> allowed-ips $WG_NODE_IP/32"
