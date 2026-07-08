# LibreSynergy

**Your livestream, your course, your community, your payments — on your own
hardware.** One config file, one command, and a creator (or any community)
has their own sign-in, live streaming, classroom, chat, webinars, and
checkout — behind their own domain, with no Big-Tech dependency.

## Why this exists

If your business lives on Skool, Kajabi, Discord, Twitch, or YouTube, you are
renting it. The platform owns the member list, the stream, the course
material, the message history, and the rules. It can change the price, the
algorithm, the take-rate, or the terms tomorrow — and your audience goes with
it, not with you.

LibreSynergy is the exit. It glues proven free-software projects into one
branded, installable app that runs on a computer you control — a box in your
studio, office, or home — fronted by a $5 VPS that acts as a dumb, blind
pipe. TLS ends on *your* machine. The VPS never sees a single plaintext
byte. Your box needs **zero open ports** and works behind any home router or
CGNAT.

A concrete shape this takes: you stream your onboarding live on your own
domain, viewers sign up in one click, join your community chat, enroll in
your paid course, and pay you by card or crypto — every step on software you
can read and hardware you own.

## The stack

| What you get | Software | Where it lives |
|---|---|---|
| Livestreaming with live chat on the watch page *(profile `stream`)* | [OwnCast](https://owncast.online) — OBS in, HLS out | `https://live.<your-domain>` |
| Classroom: courses, lessons, quizzes | [Frappe LMS](https://frappe.io/lms) | `https://learn.<your-domain>` |
| Community chat rooms and DMs | [Matrix Synapse](https://matrix.org) + [Cinny](https://cinny.in) | `https://chat.<your-domain>` |
| Webinars and video meetings | [Jitsi Meet](https://jitsi.org) | `https://meet.<your-domain>` |
| Payments & premium — card **and** crypto *(profiles `payments`/`btcpay`/`xmr`)* | Stripe + [BTCPay](https://btcpayserver.org) (Bitcoin + [Monero](docs/monero.md)) + USDC on Solana → automatic membership sync | `https://premium.<your-domain>` |
| One account for everything (passwordless email-code sign-in) | [Authentik](https://goauthentik.io) | `https://auth.<your-domain>` |
| The installable branded app that ties it together | first-party PWA shell | `https://app.<your-domain>` |
| Peer-seeded course video — learners seed to each other *(profile `vod`)* | WebTorrent + own tracker | `https://tracker.<your-domain>` |
| Short-video feed, peer-seeded *(profile `reels`)* | first-party | `https://reels.<your-domain>` |
| Admin dashboard: branding, announcements, events *(profile `admin`)* | first-party, behind SSO | `https://admin.<your-domain>` |
| File sharing *(profile `files`)* | Filebrowser | optional |
| The front door | Caddy on your node + WireGuard tunnel + nginx SNI relay on the VPS | `https://<your-domain>` |

Payments meet people where they are: cards for most members (Stripe),
Bitcoin for the self-custody crowd, **Monero for supporters who don't want
their support to be public chain data** — shielded amounts and senders,
validated by your own node, seen by no processor. All three settle into the
same membership group; see [docs/monero.md](docs/monero.md).

Membership is two-tier and automatic: everyone who joins is a **member**
(free); paying supporters become **premium**. Both are just Authentik groups,
so every app in the stack sees the same answer to "who is this person and
what may they use?". An invoice settles — Stripe webhook or on-chain — and
the member is in the premium group, the premium rooms, and the paid courses,
with no manual step. When it lapses, the same loop runs in reverse.

## Quickstart in five steps

Full walkthrough with timings: [docs/quickstart.md](docs/quickstart.md).

1. **Gather the ingredients.** A domain name, a small VPS with a public IPv4
   address, and a machine at home or in the studio (the "node") running a
   recent Debian or Ubuntu.
2. **Prepare the relay.** Clone this repo on the node and run
   `scripts/bootstrap-vps.sh` — it sets up WireGuard and the nginx SNI relay
   on the VPS.
3. **Prepare the node.** Run `scripts/bootstrap-node.sh`, then copy
   `libresynergy.env.example` to `libresynergy.env` and fill in your domain,
   brand name, and admin email.
4. **Initialize and launch.** `./bin/ls init` generates every secret and
   renders your branded pages; `./bin/ls up` starts the stack
   (add `stream payments` for livestreaming and checkout).
5. **Point DNS, verify, and register yourself.** Create the DNS records for
   your subdomains (all pointing at the VPS), run `./bin/ls doctor` until
   everything is green, then open
   `https://auth.<your-domain>/if/flow/community-signup/` and sign up —
   **the first account registered becomes the admin**, verified by an email
   code sent through your own SMTP credentials. No bootstrap passwords, no
   console steps. Point OBS at `rtmp://live.<your-domain>` and go live.

## The sovereign mesh *(optional, `mesh/`)*

Beyond the single node, LibreSynergy grows into a peer-to-peer layer your own
members run — the standard web as the onboarding funnel, P2P as its deep end:

- **Peer-seeded course video** — lessons distributed BitTorrent-style; each
  viewer seeds to the next, from the browser, no install. The origin is
  always a webseed, so an empty swarm still plays. Your audience becomes
  your CDN.
- **Content provenance** — you sign your content with an Ed25519 key; the
  signature travels with the bytes, so any untrusted peer can serve it and
  every viewer verifies it is really yours (no blockchain required).
- **NAT-traversing rendezvous** — a STUN-style coordinator introduces peers
  for direct transfer; it never touches the data.
- **Attested peering** — before two nodes federate, they verify *each other*:
  are you friend or foe (Ed25519 key possession), can I trust you with my data
  (a signed measured-boot / TPM quote), who do you work for (a delegated
  operator + a human present on a YubiKey / passkey). The tunnel comes up only
  if both sides pass. `python3 mesh/attest.py demo --all`.

The tools are readable, dependency-light, and each was proven end-to-end:
see [docs/architecture-mesh.md](docs/architecture-mesh.md),
[docs/attested-peering.md](docs/attested-peering.md) and
[docs/peertube-layer.md](docs/peertube-layer.md).

## Documentation

- [Quickstart](docs/quickstart.md) — two fresh machines to a live community in ~30 minutes
- [Livestreaming](docs/livestreaming.md) — OwnCast setup, OBS, hardening before you announce
- [Architecture](docs/architecture.md) — topology, request path, membership model, data flows
- [Security](docs/security.md) — what is enforced, and what risks remain (both halves, honestly)
- [Operations](docs/operations.md) — backups, updates, secrets rotation, known gotchas
- [Branding](docs/branding-pipeline.md) — one env file drives every page, icon, and email
- [Add a service](docs/add-a-service.md) — route any new web or TCP service through the stack
- [Monero](docs/monero.md) — private payments on your own node (profile `xmr`)
- [USDC on Solana](docs/solana-usdc.md) — non-custodial stablecoin checkout via Solana Pay
- [Course VOD layer](docs/peertube-layer.md) — peer-seeded lessons + browser player embed
- [The mesh](docs/architecture-mesh.md) — web-onboarding → P2P funnel, content signing
- [Roadmap](docs/roadmap.md) · [Changelog](CHANGELOG.md)

## Values

Everything here is free software. Every moving part is a file you can read:
compose files, one Caddyfile, one nginx config, short shell scripts, and
small pure-stdlib services — the code that touches your revenue is a few
hundred readable lines, not a black box. There is no telemetry, no
phone-home, and no account with us — because there is no "us" in your
deployment. If you ever want to leave LibreSynergy itself, your data sits in
standard Postgres/MariaDB databases and plain directories under one data
root, ready to take with you.

The longer version of why: [MANIFESTO.md](MANIFESTO.md).
