# Quickstart: two fresh machines to a live community in ~30 minutes

This guide takes you from nothing to a working LibreSynergy instance. It is
written for the technical operator; the last section hands the keys to the
community admin.

## What you need before starting

- **A domain name** you control (e.g. `acme.studio`), at a registrar where you
  can edit DNS records.
- **A VPS** — the cheapest tier at any provider is fine ($5/month, 1 vCPU,
  512 MB RAM). It needs a public IPv4 address and a fresh Debian 12+ or
  Ubuntu 22.04+ install with root SSH access. It will only ever relay
  encrypted bytes.
- **A node** — the machine that actually runs your community. A mini-PC, an
  old desktop, or an office server. Aim for 8 GB RAM and 100 GB of disk.
  Fresh Debian 12+ or Ubuntu 22.04+. It can sit behind any home/office
  router or CGNAT — **no port forwarding is needed**.
- SSH access to both machines from your laptop.

Time estimates below assume copy-paste-speed typing. DNS propagation happens
in parallel, so the wall-clock total is usually ~30 minutes.

## Step 1 — Clone the repo on the node (2 min)

```bash
ssh you@node
git clone https://libresynergy.org/stack.git libresynergy
cd libresynergy
```

## Step 2 — Bootstrap the VPS relay (5 min)

From the repo on the node:

```bash
scripts/bootstrap-vps.sh root@<VPS_PUBLIC_IP>
```

This connects over SSH and, on the VPS: installs WireGuard and nginx
(stream module), generates the relay's WireGuard keypair, opens ports 80 and
443, and installs the SNI relay config. It prints the relay's WireGuard
public key and endpoint, and records them for the next steps. The script is
idempotent — safe to re-run.

## Step 3 — Bootstrap the node (5 min)

Still on the node:

```bash
scripts/bootstrap-node.sh
```

This installs Docker and WireGuard, generates the node's WireGuard keypair,
brings up the tunnel to the relay (node `10.0.0.2` ↔ relay `10.0.0.1` by
default), and creates the data, www, and secrets directories.

Verify the tunnel before continuing:

```bash
ping -c 3 10.0.0.1
```

## Step 4 — Edit libresynergy.env (5 min)

```bash
cp libresynergy.env.example libresynergy.env
nano libresynergy.env
```

The values you must set:

| Variable | What it is | Example |
|---|---|---|
| `LS_BASE_DOMAIN` | your community's domain | `acme.studio` |
| `LS_ADMIN_EMAIL` | operator email (Let's Encrypt notices, admin account) | `admin@acme.studio` |
| `LS_DATA_DIR` | where all persistent data lives | `/srv/libresynergy/data` |
| `LS_WWW_DIR` | static site / landing pages | `/srv/libresynergy/www` |
| `LS_SECRETS_DIR` | generated secrets (mode 600) | `/srv/libresynergy/secrets` |
| `LS_TZ` | timezone | `America/Lima` |
| `COMPOSE_PROFILES` | optional features to enable | `payments,files` |

Values that have sensible defaults you can leave alone: the subdomain names
(`LS_AUTH=auth.$LS_BASE_DOMAIN`, `LS_MATRIX`, `LS_CHAT`, `LS_LEARN`,
`LS_MEET`, `LS_APP`, `LS_PREMIUM`, `LS_PAY`) and the WireGuard addresses
(`LS_WG_IP=10.0.0.2`, `LS_RELAY_WG_IP=10.0.0.1`). The relay endpoint was
filled in by `bootstrap-vps.sh`.

## Step 5 — Initialize (3 min)

```bash
ls init
```

This generates every secret (database passwords, signing keys, API tokens)
into `${LS_SECRETS_DIR}/*.env` with mode 600 and renders the Caddy and
service configs from your env. `ls init` never overwrites existing secrets,
so it too is safe to re-run. You do not need to note any admin credentials —
the first account you register in step 9 becomes the admin.

## Step 6 — Launch (5 min, mostly waiting on image pulls)

```bash
ls up
```

First launch pulls all images and runs database migrations; give it a few
minutes. `ls up` is a thin wrapper around `docker compose` with the right env
file and compose file list — when in doubt about what it does, read `bin/ls`;
it is short on purpose.

## Step 7 — Create DNS records (2 min + propagation)

At your registrar, create A records **all pointing at the VPS public IP**:

| Record | Type | Value |
|---|---|---|
| `@` (the bare domain) | A | VPS IP |
| `auth` | A | VPS IP |
| `matrix` | A | VPS IP |
| `chat` | A | VPS IP |
| `learn` | A | VPS IP |
| `meet` | A | VPS IP |
| `app` | A | VPS IP |
| `premium` | A | VPS IP |
| `btcpay` *(only with the `payments` profile)* | A | VPS IP |

A single wildcard `*` A record plus the bare-domain record also works. Never
point DNS at your node — the node's location stays private.

Caddy on the node requests certificates automatically and retries until DNS
resolves, so the order of steps 6 and 7 does not matter.

## Step 8 — Verify (2 min)

```bash
ls doctor
```

Doctor checks, end to end: the WireGuard handshake, every service's loopback
port, DNS resolution for every hostname, the relay's SNI map coverage, and a
real TLS connection from the outside for each subdomain. Re-run it until
everything is green; each failure comes with a hint.

## Step 9 — Register yourself. You're the admin. (2 min)

Put your own SMTP credentials in `${LS_SECRETS_DIR}/email.env` (any provider
that gives you an SMTP token works — your mail goes through *your* account,
nobody else's). Then open:

```
https://auth.<your-domain>/if/flow/community-signup/
```

Pick a username, enter your email, and type the code that arrives.
**The first account registered on a fresh instance automatically becomes the
admin** — it lands in the `authentik Admins` group with full control of the
stack. There are no bootstrap passwords to copy and no console steps; the
identity scaffold (signup flow, passwordless email-code login, `members` and
`premium` groups, brand defaults) is applied automatically from
`compose/blueprints/00-community-identity.yaml` when authentik boots.

Then scaffold the community's chat structure (spaces, #general, the premium
lounge) and point the announcement bot at it — one command, run from the repo:

```bash
scripts/scaffold-matrix.sh && ls restart
```

Everyone who registers after you is an ordinary member. From your admin
account:

1. Set your community's name and logo in Authentik's branding settings —
   every login screen across the stack picks it up.
2. Do the first lap: open `https://chat.<your-domain>` and say hello, create
   a first course at `https://learn.<your-domain>`, and start a test meeting
   at `https://meet.<your-domain>`.

From here the community admin invites members from Authentik, and every new
member automatically lands in the `members` group with access to chat,
classroom, and meetings. If you enabled the `payments` profile, paying
supporters are moved to `premium` automatically — see
[architecture.md](architecture.md) for how that works.

## If something is wrong

`ls doctor` is always the first move. The two most common trip-ups are
documented in [operations.md](operations.md): a Caddy reload that silently
does nothing, and a new hostname missing from the relay's SNI map.
