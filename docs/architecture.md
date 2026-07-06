# Architecture

## Topology: two machines, one trust decision

```
                    Internet
                       |
              +--------v---------+   public IPv4; ports 80/443 (+ optional game ports)
              |    VPS  relay    |   nginx stream (SNI peek) + WireGuard
              |  "the dumb pipe" |   sees ONLY ciphertext and hostnames
              +--------+---------+
                       |  WireGuard tunnel
                       |  10.0.0.1 (relay)  <->  10.0.0.2 (node)
              +--------v---------+
              |     the node     |   Caddy terminates TLS here
              |  home/office box |   every service bound to 127.0.0.1
              +------------------+   all data lives here, under ${LS_DATA_DIR}
```

The design (the "VeryPowerful" relay pattern) splits the job in two:

- **The VPS** owns nothing but a public IP. nginx's stream module peeks at
  the TLS SNI of each incoming connection — the hostname the client asks
  for — and forwards the still-encrypted stream over WireGuard to the node.
  It cannot decrypt anything: the TLS private keys never leave the node.
- **The node** runs Caddy, which terminates TLS and reverse-proxies each
  hostname to a service on `127.0.0.1`. The node makes only *outbound*
  connections (the WireGuard tunnel), so it needs no port forwarding and
  works behind home NAT or CGNAT, and its physical location is never in DNS.

## The request path

1. A member opens `https://chat.mibarrio.pe`.
2. DNS resolves to the VPS. The browser starts a TLS handshake to VPS:443.
3. nginx on the VPS reads the SNI (`chat.mibarrio.pe`), finds it in its SNI
   map, and pipes the raw bytes over WireGuard to the node.
4. Caddy on the node completes the handshake (it holds the certificate),
   applies security headers and edge rules, and proxies to the Cinny chat
   client on `127.0.0.1:8114`.
5. The response travels back the same way. The VPS relayed everything and
   understood nothing.

Certificates are issued and renewed by Caddy on the node via Let's Encrypt;
the ACME traffic flows through the relay like any other request.

TCP services that are not websites (a game server, for instance) skip Caddy:
nginx forwards the port as a raw stream to the service's WireGuard-bound
address on the node. See [add-a-service.md](add-a-service.md).

## The canonical port map

These loopback ports are fixed by convention across every LibreSynergy
install — scripts, docs, and support all assume them. Do not renumber.

| Service | Bind | Port(s) | Public hostname |
|---|---|---|---|
| Authentik (SSO) | 127.0.0.1 | 8300 (+9443 TLS) | `${LS_AUTH}` |
| Synapse (Matrix homeserver) | 127.0.0.1 | 8008 | `${LS_MATRIX}` |
| Cinny (chat client) | 127.0.0.1 | 8114 | `${LS_CHAT}` |
| Frappe LMS (classroom) | 127.0.0.1 | 8100 | `${LS_LEARN}` |
| Jitsi web (webinars) | 127.0.0.1 | 8200 | `${LS_MEET}` |
| Open WebUI (AI workspace) | 127.0.0.1 | 3000 | `${LS_APP}` |
| LiteLLM (AI gateway) | 127.0.0.1 | 4000 | internal only |
| Landing bundle (public site, member and premium portals) | 127.0.0.1 | 9091 / 9092 / 9102 | `${LS_BASE_DOMAIN}`, `${LS_PREMIUM}` |
| BTCPay Server *(profile: payments)* | 127.0.0.1 | 8500 | `${LS_PAY}` |
| membership-sync *(profile: payments)* | 127.0.0.1 | 9101 | internal only |
| Minecraft *(profile: games)* | `${LS_WG_IP}` | 25565 | VPS:25565 (raw TCP) |

Note the one deliberate exception: Minecraft binds the node's WireGuard
address instead of loopback, precisely so the relay can reach it as a stream.

## Identity, membership, and entitlements

**One account.** Authentik is the single source of truth for who exists.
Sign-in is by magic link — members click a link in their email; there are no
passwords to forget or reuse. Every application delegates authentication to
Authentik via OIDC (or forward-auth for apps without native OIDC), so
disabling a person in one place disables them everywhere.

**Two groups.** Membership tiers are just Authentik groups:

- `members` — everyone who accepts an invite. Free. Grants chat, classroom,
  and meetings.
- `premium` — paying supporters. Grants whatever the community defines:
  premium courses, the premium portal, extra AI usage.

Applications read group membership from the OIDC token claims at login, so
an entitlement change takes effect the next time the app refreshes the
session.

**Payments close the loop** (profile `payments`):

```
supporter pays invoice
        |
  BTCPay Server (8500) --settled webhook--> payments bridge
                                                 |
                                       membership-sync (9101)
                                                 |
                              Authentik API: add user to `premium`
                                       (and remove on expiry)
```

The bridge and sync services are small and auditable by design: an invoice
settles, a group changes, nothing else. Downgrades work the same way in
reverse when a subscription lapses.

## Data flows and storage

Everything persistent lives under `${LS_DATA_DIR}`, one subdirectory per
service, so "back up the community" means "back up one directory plus the
env and secrets" (see [operations.md](operations.md)):

| Path | Contents |
|---|---|
| `${LS_DATA_DIR}/authentik/postgres` | accounts, groups, SSO config |
| `${LS_DATA_DIR}/synapse/` | message history, media, homeserver keys |
| `${LS_DATA_DIR}/frappe/` | courses, lessons, enrollment |
| `${LS_DATA_DIR}/jitsi/` | meeting config |
| `${LS_DATA_DIR}/btcpay/` | invoices, store config |
| `${LS_DATA_DIR}/caddy/` | TLS certificates and ACME state |
| `${LS_WWW_DIR}` | the static landing site |
| `${LS_SECRETS_DIR}` | generated credentials, mode 600 |

These subpaths are stable across LibreSynergy versions, so upgrades and
migrations keep your data where it is.

A few flows worth knowing:

- **Matrix discovery.** The landing service on the bare domain serves
  `/.well-known/matrix/client` and `/server`, delegating Matrix to
  `${LS_MATRIX}`. Synapse runs as a closed homeserver for your community;
  federation with the wider Matrix network is off by default.
- **Jitsi media.** Signaling is HTTPS through the normal web path; the
  audio/video media itself (encrypted RTP over UDP) is forwarded by the
  relay's stream config over WireGuard to the node's videobridge.
- **AI.** Open WebUI talks only to LiteLLM on loopback; LiteLLM is the one
  place model providers (local or remote) are configured, so the AI data
  path is auditable in a single config.
- **Email.** Authentik sends magic links through the SMTP account you
  configure in `${LS_SECRETS_DIR}/smtp.env`. This is the stack's only
  required outbound dependency.
