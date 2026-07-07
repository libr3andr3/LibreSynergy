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

`1935, 8008, 8100, 8114, 8200, 8300, 8500, 8600, 9092, 9101, 9102, 9110, 9120, 9130, 9443`

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

`ls-route web` applies both ends in one go: it adds the SNI map entry on the
relay (and reloads nginx) and the Caddy vhost on the node (and restarts
caddy). Two classic failure modes to know about, both described in detail in
[operations.md](operations.md):

- *Caddy reload silently fails*: this is why ls-route restarts caddy instead
  of reloading — the restart takes seconds and always applies the config.
- *The SNI-map gotcha*: if the relay's map has no entry for a hostname, the
  node can be perfectly configured and browsers still get a connection reset
  or the wrong certificate. A service that "works on the node but not from
  the internet" is almost always this — `ls doctor` checks map coverage.

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

Example: the RTMP ingest for livestreaming (this is exactly how the `stream`
profile publishes OwnCast's OBS endpoint — see [livestreaming.md](livestreaming.md)).

**1. Define the port — bind the WireGuard address, not loopback.** This is
the crucial difference: Caddy is not involved, so the relay must be able to
reach the port directly across the tunnel:

```yaml
services:
  myservice:
    image: ...
    restart: unless-stopped
    ports:
      - "${LS_WG_IP}:1935:1935"    # WireGuard bind — reachable by the relay only
```

**2. Register the stream route.**

```bash
ls-route tcp rtmp 1935
```

This makes the relay listen on VPS port `1935` and forward the raw stream
to `${LS_WG_IP}:1935`, and opens the port in the VPS firewall. (For
UDP-based protocols, add `--udp`.)

**3. Start and verify.**

```bash
ls up
ls doctor
```

Clients connect to `<your-domain>:1935` (any of your A records works — they
all point at the VPS). No DNS change is needed beyond what you already have.

**A note on exposure.** A stream route is a plain open port on the internet:
there is no TLS termination, no security headers, no SSO in front of it.
Only the service's own protocol protects it — enable its authentication
(e.g. the OwnCast stream key) and read the exposure notes in
[security.md](security.md) before adding one.

## Removing a service

`ls-route list` shows everything currently routed on both ends. To remove a
route, reverse what `ls-route` added:

- **web**: delete the hostname's line from `/etc/nginx/stream-sni-map.conf`
  on the relay (`nginx -s reload`), and its vhost block from the Caddyfile on
  the node (`docker compose restart caddy`).
- **tcp**: delete `/etc/nginx/stream.d/<name>.conf` on the relay and close
  the port in its firewall config, then reload nginx.

Then remove the compose file and, when you are certain, the data directory.
