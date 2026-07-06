# Security

This page is in two honest halves: what the stack enforces for you out of
the box, and the risks that remain that no software can remove. Digital
sovereignty includes knowing exactly what you are still trusting.

## What is enforced

**TLS terminates on your node, not the VPS.** The TLS private keys and the
certificates exist only on the node. The VPS relays opaque ciphertext by SNI
hostname; a full compromise of the VPS yields no message content, no
passwords, no session cookies — there is simply no plaintext there to steal.

**The node accepts no inbound connections.** It dials *out* to the relay
over WireGuard. No port forwarding, no public IP, nothing for an internet
scanner to find. It works identically behind home NAT or CGNAT, and its
physical location never appears in DNS.

**Everything binds loopback.** Every service listens on `127.0.0.1` and is
reachable only through Caddy, which fronts it with TLS and security headers
(HSTS, `X-Content-Type-Options: nosniff`, frame-ancestors restrictions,
referrer and permissions policies). The single deliberate exception is a
stream-routed service like Minecraft, which binds the WireGuard address —
and is therefore treated as internet-exposed (see below).

**Admin APIs are blocked at the edge.** The Synapse admin API
(`/_synapse/admin/...`) is never routed publicly — Caddy refuses it before
any request reaches Synapse. Administer the homeserver from the node itself
against `127.0.0.1:8008`. The same edge is the natural place to fence any
future service's admin paths.

**Secrets are generated, not typed.** `ls init` creates every credential
with a proper CSPRNG, writes them to `${LS_SECRETS_DIR}/*.env` with mode
600, and never overwrites existing values. The repository contains only
`*.example` placeholders; nothing secret is ever in git, and compose files
contain no inline credentials.

**One identity, closed by default.** There is no open registration
anywhere. Accounts exist only when an admin invites someone through
Authentik, sign-in is by magic link, and every app trusts only Authentik.
Offboarding one person is one action in one place.

**Unique keys per install.** WireGuard keypairs are generated at bootstrap
on each machine; nothing key-like ships in the distribution.

## What you are still trusting (outstanding risks)

**The VPS sees metadata and controls availability.** It cannot read traffic,
but it sees which hostnames are visited, from which IPs, when, and how much.
Its operator (or anyone who compromises it) can take your community offline
or observe usage patterns. Mitigation: choose the provider and jurisdiction
deliberately; the relay is cheap and stateless, so replacing it is a
15-minute operation (`bootstrap-vps.sh` + DNS change).

**A compromised relay reaches WireGuard-bound services.** The relay holds a
WireGuard key that can reach anything bound to `${LS_WG_IP}` — which is
exactly the stream-routed services (e.g. Minecraft), and only those. Treat
every stream route as directly internet-exposed: no TLS, no SSO, no headers
in front of it, only the service's own protocol security. Enable its native
authentication and keep it updated. Loopback-bound services are not
reachable over the tunnel.

**The node is a single machine in a physical place.** Theft or seizure of
the box is theft of the community's data. Use full-disk encryption on the
node (set it up during OS install — it is the one protection that cannot be
retrofitted easily). There is no high availability; a dead disk without a
backup is an ended community. Backups are the operator's responsibility and
must be encrypted, since an archive contains every secret and every message
— see [operations.md](operations.md).

**No rate limiting at the relay.** The relay forwards streams blindly, so
brute-force and scraping pressure lands on the services themselves.
Authentik applies its own login throttling and magic-link flow (no passwords
to brute-force), but there is no fail2ban-style layer at the edge by
default.

**Supply chain is tag-pinned, not digest-pinned.** Images are pulled by
version tag. A compromised upstream registry or tag is inside your trust
boundary. If your threat model warrants it, pin images by digest in the
compose files and review diffs before updating — the update flow in
operations.md deliberately makes updating a conscious act, never automatic.

**Email is an external dependency.** Magic links travel through your SMTP
provider, which therefore sees who is being invited and when, and a
compromised mailbox can intercept a sign-in link. Use a provider you trust
and encourage members to secure their mailboxes.

**Video calls are transport-encrypted, not end-to-end.** Jitsi media is
encrypted in transit (DTLS-SRTP) and the bridge runs on your node — which is
precisely the point: the trust boundary is your hardware, not a vendor's.
But anyone with root on the node can, in principle, access anything the node
processes. That is the meaning of self-hosting: you trust your operator
instead of a corporation. Choose the operator accordingly.

## Reporting

If you find a vulnerability in LibreSynergy itself, please report it
privately to the project maintainers before disclosing publicly. For issues
in your own instance, your operator's address is `${LS_ADMIN_EMAIL}`.
