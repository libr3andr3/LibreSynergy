# Add a service

LibreSynergy routes two kinds of traffic, and adding your own service is a
short, repeatable runbook for either:

- **web** — anything spoken over HTTPS in a browser. Routed by *hostname*:
  the relay matches the TLS SNI, Caddy terminates TLS and proxies to a
  loopback port on the node.
- **tcp** — anything that is not a website: a game server, an MQTT broker, a
  Git SSH endpoint. Routed by *port*: the relay forwards a public port as a
  raw stream over WireGuard to a service bound on the node's WireGuard
  address.

The `ls-route` helper does the mechanical work for both. It edits the Caddy
site config and regenerates the relay's nginx maps, so the two ends never
drift apart by hand-editing.

## Before you start: pick a free port

These ports are reserved by the core stack — pick anything else:

`3000, 4000, 8008, 8100, 8114, 8200, 8300, 8500, 9091, 9092, 9101, 9102, 9443, 25565`

## Runbook A: a web service (SNI-routed)

Example: adding a wiki at `wiki.<your-domain>` on port `8123`.

**1. Define the container.** Create a compose file in `compose/` following
the house style — loopback bind, data under the data root, timezone from env:

```yaml
services:
  wiki:
    image: someorg/somewiki:stable
    restart: unless-stopped
    ports:
      - "127.0.0.1:8123:80"          # loopback ONLY — Caddy is the front door
    volumes:
      - ${LS_DATA_DIR}/wiki:/data     # same convention as everything else
    environment:
      TZ: ${LS_TZ:-UTC}
```

If it needs credentials, put them in `${LS_SECRETS_DIR}/wiki.env`, reference
it with `env_file:`, and add a `secrets/wiki.env.example` to the repo.

**2. Register the route.**

```bash
ls-route web wiki 8123
```

This adds a Caddy vhost for `wiki.${LS_BASE_DOMAIN}` proxying to
`127.0.0.1:8123` (inheriting the standard security headers), and adds the
hostname to the relay's SNI map.

**3. Push the relay config and reload both ends.**

```bash
ls-route push                 # installs the regenerated map on the VPS, reloads nginx
docker compose restart caddy  # yes, restart — see the gotcha below
```

Two classic failure modes live right here, both described in detail in
[operations.md](operations.md):

- *Caddy reload silently fails*: prefer `docker compose restart caddy` over
  `caddy reload` — the restart takes seconds and always applies the config.
- *The SNI-map gotcha*: if you skip `ls-route push`, the node is perfectly
  configured but the relay has never heard of the new hostname, and browsers
  get a connection reset or the wrong certificate. The service "works on the
  node but not from the internet" — that is almost always this.

**4. DNS.** Add an A record `wiki -> VPS IP` (already covered if you use a
wildcard).

**5. Start and verify.**

```bash
ls up
ls doctor
```

Doctor will confirm DNS, SNI map coverage, and a live TLS handshake for the
new hostname.

**Optional: require sign-in.** To put the service behind community SSO even
if it has no login of its own, front it with Authentik forward-auth — create
a Proxy Provider in Authentik and add the forward-auth snippet to the vhost.
The existing vhosts are the reference examples.

## Runbook B: a TCP service (stream-routed)

Example: the Minecraft server that ships with LibreSynergy as a proof of
concept (compose profile `games`).

**1. Define the container — bind the WireGuard address, not loopback.** This
is the crucial difference: Caddy is not involved, so the relay must be able
to reach the port directly across the tunnel:

```yaml
services:
  minecraft:
    image: itzg/minecraft-server
    restart: unless-stopped
    profiles: ["games"]
    ports:
      - "${LS_WG_IP}:25565:25565"    # WireGuard bind — reachable by the relay only
    volumes:
      - ${LS_DATA_DIR}/minecraft:/data
    environment:
      TZ: ${LS_TZ:-UTC}
      EULA: "TRUE"
```

**2. Register the stream route.**

```bash
ls-route tcp minecraft 25565
```

This makes the relay listen on VPS port `25565` and forward the raw stream
to `${LS_WG_IP}:25565`, and opens the port in the VPS firewall. (For
UDP-based protocols, add `--udp`.)

**3. Push and verify.**

```bash
ls-route push
ls up
ls doctor
```

Players connect to `<your-domain>:25565` (any of your A records works — they
all point at the VPS). No DNS change is needed beyond what you already have.

**A note on exposure.** A stream route is a plain open port on the internet:
there is no TLS termination, no security headers, no SSO in front of it.
Only the service's own protocol protects it — enable its authentication
(e.g. Minecraft online mode / allowlist) and read the exposure notes in
[security.md](security.md) before adding one.

## Removing a service

```bash
ls-route rm <name>
ls-route push
docker compose restart caddy
```

Then remove the compose file and, when you are certain, the data directory.
`ls-route list` shows everything currently routed on both ends.
