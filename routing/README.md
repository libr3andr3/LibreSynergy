# Routing — the sovereign relay

LibreSynergy is reachable from the internet **without** handing your traffic to
Cloudflare, Tailscale, or ngrok. TLS terminates on *your* machine; the public
VPS is a dumb L4 pipe that never decrypts. This is the sovereign-relay pattern.

```
                         ┌──────────────────── your community's machine ("node") ──────────────────┐
   user                  │  Caddy (auto-TLS, binds ${LS_WG_IP})                                     │
    │  TLS :443          │    ├─ auth.  → 127.0.0.1:8300   (Authentik)                              │
    ▼                    │    ├─ matrix.→ 127.0.0.1:8008   (Synapse)                                │
 VPS relay (public IP)   │    ├─ chat.  → 127.0.0.1:8114   (web client)                             │
  nginx stream {}        │    ├─ learn. → 127.0.0.1:8100   (Frappe LMS)                             │
  reads SNI, NEVER       │    └─ meet.  → 127.0.0.1:8200   (Jitsi)                                  │
  decrypts ──────────────┼──► WireGuard tunnel ────────────► TLS terminates HERE, on your keys      │
    │                    └──────────────────────────────────────────────────────────────────────────┘
    │  raw TCP :1935 (RTMP ingest, DB, SSH, …) ── separate stream, no TLS ──►
```

## Two kinds of route

| Kind | Command | What it does |
|------|---------|--------------|
| **web** (HTTPS) | `bin/ls-route web <sub> <local_port>` | adds an SNI map entry on the relay + a Caddy vhost on the node. Routed by TLS SNI, so many hosts share port 443. |
| **tcp** (raw) | `bin/ls-route tcp <name> <port>` | opens the firewall on the relay + a dedicated `stream {}` forward to the node. For protocols that don't speak TLS/SNI — one port per service. |

Both print the exact DNS record you must create (an A record → the relay's
public IP; `tcp` game servers also get an optional SRV record).

## Why the VPS never sees plaintext
The relay uses nginx `ssl_preread` — it reads only the **unencrypted SNI field**
of the TLS ClientHello to decide where to forward, then pipes the still-encrypted
bytes over WireGuard to Caddy, which holds the only private key. See
`../docs/security.md`.

## Files
- `templates/home-caddy-site.j2` — a single Caddy vhost block (web routes).
- `templates/vps-nginx-stream-tcp.conf.j2` — a single raw-TCP forward (tcp routes).
- `../bin/ls-route` — the automation that applies them idempotently.
- `../scripts/bootstrap-vps.sh` / `bootstrap-node.sh` — stand up the relay and node from scratch.
