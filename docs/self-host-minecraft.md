# Self-hosting Minecraft (and any other TCP service)

This walkthrough gets a Minecraft server running on your LibreSynergy node and
reachable from the public internet at `play.<your-domain>` — world data on your
own disk, players connecting through your relay VPS.

It is also deliberately more than a game server. Minecraft is the
proof-of-concept for the **raw-TCP self-hosting path**, and the recipe below
works unchanged for Postgres, SSH, or any other TCP service you want to expose.

## Why Minecraft is the ideal proof-of-concept

Every other public LibreSynergy service (Authentik, Matrix, chat, classroom,
webinars) is HTTP(S). HTTPS is the *easy* case for a relay: the TLS handshake
carries the hostname in cleartext (SNI), so the VPS edge can multiplex dozens
of services through a single port 443 and route each connection by name.

Minecraft has none of that. Its protocol is a custom binary framing over raw
TCP — no TLS, no SNI, no `Host:` header. The relay cannot inspect the stream
to decide where it goes; it must dedicate a public port and forward the bytes
**verbatim** over the WireGuard tunnel to your node. If that path works
end-to-end — public port → VPS stream forward → WireGuard → service on the
node — then LibreSynergy can self-host *anything that speaks TCP*, because
this is the hardest, most general case. Minecraft just happens to be a fun way
to prove it, with an instantly verifiable client (the game itself).

## How the traffic flows

```
Player ──TCP──▶ VPS public IP :25565        (opened by ls-route)
                  │  stream forward (bytes copied verbatim, no inspection)
                  ▼
         WireGuard tunnel  ${LS_RELAY_WG_IP} ──▶ ${LS_WG_IP}
                  │
                  ▼
         node: minecraft container bound to ${LS_WG_IP}:25565
```

Note the deliberate exception to the LibreSynergy port rules: every other
service binds `127.0.0.1`, but Minecraft binds `${LS_WG_IP}` (default
`10.0.0.2`) so the relay can reach it *over the tunnel*. It is still never
exposed on the node's public interfaces.

## Prerequisites

- A LibreSynergy node with the WireGuard tunnel to the relay up
  (`wg show` should list the relay peer with a recent handshake).
- `LS_DATA_DIR`, `LS_WG_IP`, and `LS_BRAND_NAME` set in your environment file.
- Roughly 2 GB of free RAM on the node (tunable, see below).

## Step 1 — Start the server

Minecraft ships under the optional `games` profile, so it only runs when you
ask for it:

```bash
docker compose --profile games up -d minecraft
```

First boot takes a few minutes: the container downloads PaperMC and generates
the world. Watch it come up:

```bash
docker compose logs -f minecraft     # wait for:  Done (…s)! For help, type "help"
```

World data, plugins, and server config land in `${LS_DATA_DIR}/minecraft/` on
the node — recreating or upgrading the container never touches your world.

Tunables (set in your env file before `up`):

| Variable         | Default | Meaning                                             |
|------------------|---------|-----------------------------------------------------|
| `MC_MEMORY`      | `2G`    | JVM heap. `4G`+ recommended above ~10 players.      |
| `MC_ONLINE_MODE` | `TRUE`  | Verify players against Mojang auth. Keep `TRUE` for public servers. |

The server MOTD (the line players see in their server list) is derived from
`${LS_BRAND_NAME}`.

## Step 2 — Route it through the relay

```bash
ls-route tcp minecraft 25565
```

This one command does both halves of the public plumbing:

1. **Opens the firewall** on the relay VPS for TCP port 25565.
2. **Adds a stream forward** on the VPS: public `:25565` → `${LS_WG_IP}:25565`
   over the WireGuard tunnel.

Verify from any machine *outside* your network:

```bash
nc -vz <VPS-IP> 25565    # should report: succeeded / open
```

## Step 3 — DNS

Two records at your DNS provider:

1. **A record** — points the friendly name at the relay:

   ```
   play.<your-domain>.    A    <VPS public IP>
   ```

2. **SRV record** — tells Minecraft clients which port to use, so players can
   type just `play.<your-domain>` with no `:port` suffix:

   ```
   _minecraft._tcp.play.<your-domain>.    SRV    0 5 25565 play.<your-domain>.
   ```

   (Priority `0`, weight `5`, port `25565`, target = your A record. In most
   DNS panels: Service `_minecraft`, Protocol `_tcp`, Name `play`.)

Since we use Minecraft's default port 25565 the SRV record is technically
optional, but it future-proofs you: if you ever move to a nonstandard public
port (e.g. to run a second server), players' saved address keeps working.

## Step 4 — Connect and play

In Minecraft: **Multiplayer → Add Server → Address:** `play.<your-domain>`.

You should see your `${LS_BRAND_NAME}` MOTD in the server list — that ping
alone proves the whole path (DNS → VPS → WireGuard → node → container).

No DNS yet, or still waiting on propagation? Connect directly with
`<VPS-IP>:25565`. Raw TCP doesn't need a hostname — that's the point.

## Day-2 operations

```bash
# Server console (RCON) — op a player, change settings live, etc.
# RCON is never published outside the container; the image generates its own
# credentials and rcon-cli picks them up automatically from inside.
docker compose exec minecraft rcon-cli
> op YourPlayerName
> whitelist on

# Health (the container healthcheck pings the server like a game client)
docker ps --filter name=minecraft    # look for (healthy)

# Backup: flush the world to disk, then archive the data dir
docker compose exec minecraft rcon-cli save-all
tar -C "${LS_DATA_DIR}" -czf minecraft-backup-$(date +%F).tar.gz minecraft

# Stop it (the games profile means it won't come back on a plain `up -d`)
# The unit allows up to 1 minute for a clean world save on shutdown.
docker compose --profile games stop minecraft
```

## The general recipe: self-host any TCP service

Everything above generalizes. To expose *any* TCP service from your node:

1. **Bind it to the WireGuard IP**, not localhost and not a public interface:
   `ports: ["${LS_WG_IP}:<port>:<port>"]`
2. **Route it:** `ls-route tcp <name> <port>`
3. **(Optional) DNS:** an A record pointing at the VPS. Cosmetic — TCP clients
   are equally happy with `<VPS-IP>:<port>`.
4. **Connect** from anywhere.

Examples:

| Service            | Port  | Command                       |
|--------------------|-------|-------------------------------|
| Postgres (remote analytics access) | 5432 | `ls-route tcp postgres 5432` |
| SSH into the node (via a nonstandard public port) | 2222 | `ls-route tcp ssh 2222` |
| Terraria, Factorio (TCP mode), Valheim-style servers | varies | `ls-route tcp <game> <port>` |

For databases and SSH, add the service's own authentication/allowlisting on
top — the relay forwards bytes, it does not authenticate them. The forward is
public once routed, exactly like the Minecraft port.

That's the LibreSynergy promise in miniature: the VPS is a dumb, replaceable
pipe. Your data, your world, and your services live on hardware you own.

## Troubleshooting

| Symptom | Check |
|---|---|
| `nc` to VPS fails | `ls-route` ran on the right relay? VPS provider firewall (security group) also open for 25565? |
| `nc` OK, client times out | Tunnel up? `ping ${LS_RELAY_WG_IP}` from the node; `wg show` handshake age. |
| Connection refused at the node | Container bound to the right IP? `ss -tlnp \| grep 25565` should show `${LS_WG_IP}:25565`, not `127.0.0.1`. |
| Container unhealthy / boot loop | `docker compose logs minecraft` — most common: not enough RAM for `MC_MEMORY`. |
| Players see "Failed to verify username" | `MC_ONLINE_MODE=TRUE` requires outbound internet from the node to Mojang's auth servers. |
