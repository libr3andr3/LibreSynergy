# The sovereign mesh — from web onboarding to P2P end-of-funnel

> Standard over-the-web architecture as onboarding; peer-to-peer decentralization
> as the end of the funnel. Creators own their content because they *sign* it.

This is the architecture LibreSynergy grows into: a community that starts on
the open web (zero-friction, works everywhere) and deepens into a peer-to-peer
mesh its own members run — without ever asking permission from a platform.

## The funnel

```
  ┌────────────────────────────────────────────────────────────────────┐
  │  TOP — standard web (onboarding, zero install)                       │
  │  Stranger lands on yaya.sh over normal HTTPS (via the sovereign      │
  │  relay). Watches the livestream (OwnCast HLS), browses content,      │
  │  signs up passwordless. Works on any device, any network.           │
  ├────────────────────────────────────────────────────────────────────┤
  │  MIDDLE — engagement                                                 │
  │  Joins the community: federated chat (Matrix), classroom, webinars.  │
  │  Buys premium — card (Stripe) or crypto (BTCPay: BTC + Monero).      │
  │  Both settle to the SAME Authentik entitlement group.               │
  ├────────────────────────────────────────────────────────────────────┤
  │  BOTTOM — P2P mesh (end of funnel, decentralized)                    │
  │  True members install the lightweight yaya client. It carries the    │
  │  P2P engine: it joins swarms via the rendezvous server, hole-punches │
  │  to other members, and RELAYS signed stream segments peer-to-peer.   │
  │  The community becomes its own CDN. Load leaves the origin.          │
  └────────────────────────────────────────────────────────────────────┘
```

The genius of the funnel: **you never force the hard thing first.** The web
tier converts strangers; the mesh tier is what committed members graduate into.
Nobody has to run a server to participate — but those who do make the whole
thing stronger and more sovereign.

## Why signing is the keystone

In a peer-to-peer swarm you **cannot trust the peer that hands you bytes.** So
the trust cannot live in the transport — it must live in the *content itself.*

Every piece of creator content is signed with an **Ed25519** key. The creator
*is* their public key (identity = `sha256(pubkey)[:16]`). A signed **manifest**
travels with the content and is its *source of truth*:

```
creator signs once  ─►  ANY untrusted peer serves it  ─►  every viewer verifies
```

This is the sovereign equivalent of an "NFT": cryptographic provenance and
authenticity, **with no blockchain and no rent.** (If public timestamping is
ever wanted, a manifest hash can be anchored on-chain — optional, never
required.) Verification catches three distinct attacks, all proven in tests:

| Attack | Caught by |
|--------|-----------|
| Peer flips bytes in transit | content `sha256` ≠ manifest hash |
| Impostor re-signs tampered content as themselves | viewer pins the creator_id; wrong key rejected |
| Forged identity (claim a pubkey isn't yours) | creator_id must equal `sha256(embedded pubkey)` |

### Livestreams as a verifiable source of truth
Each HLS segment is signed as it is produced, carrying `seq` and the previous
segment's signature (`prev_sig`). The ordered chain of segment manifests is the
stream's tamper-evident source of truth: a viewer pulling segment 42 from a
random peer can prove it is genuinely the creator's segment 42, in order,
unaltered — even though the origin server never touched that transfer.

## The three trust roots (distinct, don't conflate)

1. **Content authenticity** — the *creator's* Ed25519 key signs content/segments.
2. **Binary integrity** — a **maintainer quorum** (threshold signatures) signs
   every mesh client release. Only quorum-signed code runs on the mesh.
3. **Transport** — TLS still terminates on the community's own node for the web
   tier; the mesh tier is authenticated by content signatures, not TLS.

## Coordination: the rendezvous (STUN) server

`stun.yaya.sh` (a hardened daemon on the public VPS) is a pure coordinator. It
observes each peer's NAT-reflexive address and introduces peers so they can
hole-punch a direct UDP path — then it steps out of the way. It never sees a
stream byte. Cone NATs punch directly; symmetric-NAT peers fall back to a TURN
relay (a mesh member with a public IP can *be* that relay).

## Components (built + proven)

| Piece | Where | Status |
|-------|-------|--------|
| Rendezvous / hole-punch | `verypowerful/rendezvous.py` (VPS), `peer.py` | proven: 64KB direct transfer across two NATs, md5-verified |
| Content signing | `verypowerful/content_sign.py` | proven: honest / tamper / impostor / forgery cases |
| Web tier | OwnCast, Matrix, Frappe, Jitsi, Authentik | live on yaya.sh |
| Payments | Stripe + BTCPay (BTC + Monero) → Authentik group | Stripe live; BTCPay syncing |

## Measured crypto overhead (real 406 KB OwnCast 720p segment)

Proven end-to-end 2026-07-05: creator-signed segment served over a hole-punched
UDP path across two NATs, verified authentic on arrival, md5 identical to source.

**Signing (public streams — integrity/authenticity).** The signature and full
manifest add **427 bytes to a 406 KB segment = 0.105%** (the bare Ed25519
signature is 64 B = 0.016%). Signing happens **once at the origin, amortized
across every viewer**; verification is once per viewer per segment.

| Ed25519 | raw primitive | as-implemented (openssl subprocess/call) |
|---------|---------------|------------------------------------------|
| sign    | 49 µs (20,300/s) | 17 ms |
| verify  | 135 µs (7,400/s) | 11 ms |

The as-implemented cost is ~99% process fork/exec + key parsing, not crypto —
production moves signing in-process (libsodium/PyNaCl) for a ~100–300× drop.
Even at the un-optimized 11 ms, verifying one segment of a multi-second stream
is <0.3% of real time; at the raw 135 µs it is 0.003%.

**Encryption (premium/paid content — confidentiality).** AES-256-GCM runs at
**~3 GB/s** on this box, so a 406 KB segment encrypts/decrypts in **~0.13 ms**
and a full 2.5 Mbps stream is real-time-encrypted using ~0.01% of one core.
Byte overhead is **28 B/segment** (12 B IV + 16 B GCM tag) = 0.007%.

**Bottom line.** Crypto is never the bottleneck: verify (7,400/s) and AES
(3 GB/s) are 1,000–2,000× faster than the demo's paced-UDP transport
(1.5 MB/s). Public segments are signed only; premium segments are signed **and**
encrypted, with the AES key released to a viewer only after the Stripe/BTCPay
entitlement check — sovereignty and paid access from the same primitive.

## What's next
- Combine the two proven halves: sign an OwnCast segment → serve it over the
  hole-punched path → verify on arrival (the segment-relay v0).
- TURN fallback for symmetric NATs.
- The lightweight yaya client that carries the P2P engine (desktop/mobile first,
  engine dormant until the swarm is ready).
- Standardize the message formats into a versioned **protocol** so any client
  can run functions on any member's node.
