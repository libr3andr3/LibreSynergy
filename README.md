# LibreSynergy

**Your community, on your own hardware.** One config file, one command, and a
neighborhood association, a small municipality, or an online community has its
own sign-in, chat, classroom, webinars, and payments — behind its own domain,
with no Big-Tech dependency.

## Why this exists

If your community lives on Skool, Discord, or Facebook, you are renting it.
The platform owns the member list, the message history, the course material,
and the rules. It can change the price, the algorithm, or the terms tomorrow.

LibreSynergy is the exit. It glues proven free-software projects into one
branded, installable app that runs on a computer you control — a box in your
office, a shelf in the community hall — fronted by a $5 VPS that acts as a
dumb, blind pipe. TLS ends on *your* machine. The VPS never sees a single
plaintext byte. Your home box needs **zero open ports**.

This is built for two people working together:

- **the community admin** — a junta vecinal president, a municipal clerk, a
  course creator — who invites members, runs classes, and hosts meetings;
- **the technical operator** — a volunteer or contractor who spends about
  thirty minutes installing it and a few minutes a month keeping it healthy.

## The stack

| What your community gets | Software | Where it lives |
|---|---|---|
| One account for everything (passwordless email-code sign-in) | [Authentik](https://goauthentik.io) | `https://auth.<your-domain>` |
| Chat rooms and DMs — federates with the whole Matrix network | [Matrix Synapse](https://matrix.org) + [Cinny](https://cinny.in) | `https://chat.<your-domain>` |
| Classroom: courses, lessons, quizzes | [Frappe LMS](https://frappe.io/lms) | `https://learn.<your-domain>` |
| Webinars and video meetings | [Jitsi Meet](https://jitsi.org) | `https://meet.<your-domain>` |
| Livestreaming with live chat *(profile `stream`)* | [OwnCast](https://owncast.online) | `https://live.<your-domain>` |
| Peer-seeded course video — learners seed to each other *(profile `vod`)* | WebTorrent + own tracker | `https://tracker.<your-domain>` |
| Payments & premium — card **and** crypto *(profile `payments`/`btcpay`)* | Stripe + [BTCPay](https://btcpayserver.org) (BTC + Monero) + **USDC on Solana** → membership sync | `https://premium.<your-domain>` |
| Admin dashboard: branding, sponsors, announcements *(profile `admin`)* | first-party, behind SSO | `https://admin.<your-domain>` |
| File sharing *(optional)* | Filebrowser | profile `files` |
| Community game server *(optional)* | Minecraft | profile `games` |
| The front door | Caddy on your node + WireGuard + nginx SNI relay on the VPS | `https://<your-domain>` |

Membership is two-tier and automatic: everyone who joins is a **member**
(free); paying supporters become **premium**. Both are just Authentik groups,
so every app in the stack sees the same answer to "who is this person and
what may they use?".

## Quickstart in five steps

Full walkthrough with timings: [docs/quickstart.md](docs/quickstart.md).

1. **Gather the ingredients.** A domain name, a small VPS with a public IPv4
   address, and a machine at home or in the office (the "node") running a
   recent Debian or Ubuntu.
2. **Prepare the relay.** Clone this repo on the node and run
   `scripts/bootstrap-vps.sh` — it sets up WireGuard and the nginx SNI relay
   on the VPS.
3. **Prepare the node.** Run `scripts/bootstrap-node.sh`, then copy
   `libresynergy.env.example` to `libresynergy.env` and fill in your domain,
   admin email, and data directories.
4. **Initialize and launch.** `ls init` generates every secret and renders
   every config; `ls up` starts the stack.
5. **Point DNS and verify.** Create the DNS records for your subdomains
   (all pointing at the VPS), then run `ls doctor` until everything is green.

## The sovereign mesh *(optional, `mesh/`)*

Beyond the single node, LibreSynergy grows into a peer-to-peer layer your own
members run — standard web as the onboarding funnel, P2P as its deep end:

- **Peer-seeded course video** — static lessons distributed BitTorrent-style;
  free learners stream a lesson and seed it to the next, from the browser, no
  install. The origin is always a webseed, so an empty swarm still plays.
- **Content provenance** — creators sign their content with an Ed25519 key; the
  signature travels with the bytes, so any untrusted peer can serve it and every
  viewer verifies authorship (the sovereign answer to an "NFT", no blockchain).
- **NAT-traversing rendezvous** — a STUN-style coordinator introduces peers for
  direct transfer; it never touches the data.

The tools are readable, dependency-light, and each was proven end-to-end:
`mesh/tracker.mjs`, `mesh/course.mjs`, `mesh/content_sign.py`,
`mesh/rendezvous.py`, `mesh/peer.py`, `mesh/segment_relay.py`. Design and
measured overhead: [docs/architecture-mesh.md](docs/architecture-mesh.md) and
[docs/peertube-layer.md](docs/peertube-layer.md).

## Documentation

- [Quickstart](docs/quickstart.md) — two fresh machines to a live community in ~30 minutes
- [Architecture](docs/architecture.md) — topology, request path, membership model, data flows
- [The mesh](docs/architecture-mesh.md) — web-onboarding → P2P funnel, content signing, measured crypto overhead
- [Course VOD layer](docs/peertube-layer.md) — PeerTube-style peer-seeded lessons + browser player embed
- [Livestreaming](docs/livestreaming.md) — OwnCast setup, OBS, hardening
- [USDC on Solana](docs/solana-usdc.md) — non-custodial stablecoin checkout via Solana Pay
- [Add a service](docs/add-a-service.md) — route any new web or TCP service through the stack
- [Operations](docs/operations.md) — backups, updates, secrets rotation, known gotchas
- [Security](docs/security.md) — what is enforced, and what risks remain
- [Changelog](CHANGELOG.md)

## Operator tooling *(optional, `tools/`)*

`tools/verypowerful-mcp.py` is a [Model Context Protocol](https://modelcontextprotocol.io)
server that exposes the whole edge — Cloudflare DNS, the relay's SNI/L4 routes,
and node Caddy vhosts — as one tool surface for an AI operator. It reads its
Cloudflare token from the gitignored `secrets/cloudflare.env` at runtime.

## Values

Everything here is free software. Every moving part is a file you can read:
compose files, one Caddyfile, one nginx config, short shell scripts. There is
no telemetry, no phone-home, and no account with us — because there is no
"us" in your deployment. If you ever want to leave LibreSynergy itself, your
data sits in standard Postgres/MariaDB databases and plain directories under
one data root, ready to take with you.
