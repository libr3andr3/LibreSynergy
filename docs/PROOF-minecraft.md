# Proof of Concept — self-hosting a server "in the whole sense of the word"

**Date:** 2026-07-03 · **Status:** ✅ live and verified from the public internet

Minecraft is the ideal proof because it is **not** HTTP/TLS — it's a raw TCP protocol on
port 25565. So making it publicly reachable exercises the *general* self-hosting path, not
just the web path: it proves the relay forwards **arbitrary TCP**, and that the same recipe
self-hosts a database, an SSH bastion, or any game server.

## The path a player's connection takes

```
Minecraft client
      │  TCP :25565
      ▼
VPS 103.89.12.145         (public IP; nginx `stream { listen 25565; proxy_pass 10.0.0.2:25565; }`)
      │  raw TCP over WireGuard (no TLS, no decryption)
      ▼
node  10.0.0.2:25565      (itzg/minecraft-server, Paper, bound to the WireGuard IP)
```

Nothing here is Cloudflare-proxied and nothing terminates TLS at the VPS — the VPS is a dumb
L4 pipe. The server runs entirely on hardware the community controls.

## Verification (run from a third, unrelated host)

```
$ nc -zv 103.89.12.145 25565
(UNKNOWN) [103.89.12.145] 25565 (?) open

$ python3 mc_ping.py 103.89.12.145 25565     # a real Server-List-Ping handshake
OK  103.89.12.145:25565
  version : Paper 26.1.2
  players : 0/20
  motd    : Yaya - LibreSynergy: self-hosted, sovereign
```

The MOTD came back through the entire chain — the server is genuinely reachable, not just a
port that happens to be open.

## What was changed on live infrastructure (all reversible)

**node** — `~/docker/apps/minecraft/docker-compose.yml`:
```yaml
name: minecraft
services:
  mc:
    image: itzg/minecraft-server:latest
    restart: unless-stopped
    ports: ["10.0.0.2:25565:25565"]     # bind the WireGuard IP so the relay can reach it
    environment: { EULA: "TRUE", TYPE: "PAPER", VERSION: "LATEST", MEMORY: "2G",
                   ONLINE_MODE: "TRUE", MOTD: "Yaya - LibreSynergy: self-hosted, sovereign" }
    volumes: ["mc_data:/data"]
volumes: { mc_data: {} }
```

**VPS** — raw-TCP relay + firewall:
- `/etc/nginx/stream.d/minecraft.conf` → `server { listen 25565; proxy_pass 10.0.0.2:25565; }`
- added `include /etc/nginx/stream.d/*.conf;` inside the `stream {}` block of `nginx.conf`
- opened `25565/tcp` in `/etc/nftables-hardening.conf` (live rule added + set persisted;
  original conf backed up to `/etc/nftables-hardening.conf.bak`)

## The one remaining step for a friendly name

Players connect at `103.89.12.145:25565` today. To offer `play.<domain>` instead, create:
- `A  play.<domain>  → 103.89.12.145`  (DNS-only / grey-cloud)
- `SRV _minecraft._tcp.play.<domain>  0 0 25565  play.<domain>`  (lets players omit the port)

This needs a **valid Cloudflare API token** — the one provided returned `Invalid API Token`.
Once a working token is set, `routing/ls-route tcp minecraft 25565` automates the firewall +
stream forward, and the DNS records are a one-liner against the CF API.
