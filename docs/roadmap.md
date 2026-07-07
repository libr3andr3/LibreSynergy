# Reels roadmap — from unit to movement

> Strategy in one line: creators don't move for ideology, they move for money
> and reach — so every phase either makes creators money, makes viewers'
> experience faster/safer, or makes the network bigger. Sovereignty is the
> architecture, not the pitch.

Phases are ordered by dependency and risk. **⛔ LAUNCH GATE** marks what must
exist before any public link goes out.

## Phase 1 — Transcode pipeline ✅ (shipped, see below)
Raw phone uploads are 4K HEVC: bad playback compatibility, bad torrent
payloads, and they leak GPS/EXIF metadata. Every upload now goes through an
ffmpeg queue: normalize to ≤720p H.264/AAC (+faststart), **strip all
metadata** (location!), cut at max duration, extract a poster frame, publish
+ seed only when done. See [reels.md](reels.md).

## Phase 2 — Seeding consent + data controls  ⛔ LAUNCH GATE
The swarm exposes viewer IPs; a sovereignty platform must be honest about it
*before* the first privacy researcher is.
- First-seed consent sheet: plain words — "liking re-hosts this video from
  your device; other peers can see your IP".
- Wifi-only seeding default on mobile (Network Information API where
  available, manual toggle everywhere), storage/bandwidth caps.
- "Your contribution" panel; make generosity the status loop (seed streaks,
  "you helped N people watch").

## Phase 3 — Report button + takedown flow  ⛔ LAUNCH GATE
Strangers uploading video = legal exposure from day one.
- Report button → admin queue (admin dashboard already exists).
- Takedown: kill webseed + tracker entry + delist; documented honest story
  for already-seeded copies.
- Register DMCA agent (dmca.copyright.gov, ~$6); notice-and-takedown page.
- CSAM: hash-scan uploads (PhotoDNA-class list via a vendor, or at minimum
  block-on-report + NCMEC reporting procedure written down).
- No licensed music, ever. CC/original audio library instead; "original
  sound" is the culture.

## Phase 4 — Profiles + follow graph
- Creator channel pages (handle, avatar, bio, reel grid) backed by Authentik;
  one-tap passwordless follow — no password is a *better* experience than big
  tech, lean into it.
- "Following" feed beside the algorithmic one; web push notifications (PWA).
- Anti-sybil groundwork: likes from authenticated members weigh more than
  anonymous; per-IP-block seed-count caps in score().

## Phase 5 — Comments + sharing (the participation loop)
- Comments = one Matrix room per reel (Synapse already runs); anonymous read,
  member write. This dogfoods the stack and gives moderation tools for free.
- Deep links `/r/<id>` with OG preview cards so shares unfurl in
  WhatsApp/iMessage/Discord — sharing *into* big tech is the growth loop.
- Download-with-watermark (your brand) for cross-posting to TikTok/IG —
  their audience becomes the funnel.

## Phase 6 — Creator money (the migration engine)
- Tips per reel: Stripe + BTCPay (both already in the stack), platform take
  small and published.
- Premium reels: encrypted torrents with key release after entitlement —
  the design is already proven in the course layer (peertube-layer.md).
- Creator dashboard: earnings + aggregate privacy-preserving analytics.
- Audience ownership as a *button*: export followers/emails, RSS per channel,
  Matrix space per creator.
- Ed25519 provenance surfaced as a "verified original" badge (mesh/
  content_sign.py exists) — the anti-AI-slop differentiator.

## Phase 7 — Search + topics
- Hashtags parsed from titles; topic feeds; simple search (SQLite FTS is
  enough for a long time). One global ranked feed stops scaling ~500 videos.

## Phase 8 — Federation (the actual revolution)
- Instance-to-instance feed subscription over the existing mesh (Ed25519
  instance identity already designed): a creator's own LibreSynergy instance
  *is* their channel; the flagship instance is just the biggest node, not the platform.
- ActivityPub bridge (PeerTube-compatible) so the existing fediverse can
  follow LibreSynergy creators — instant distribution to people who already chose
  open platforms.
- Cross-instance swarms already work: same infohash = same swarm, wherever
  the .torrent came from.

## Continuous (threaded through every phase)
- **Cold start**: ~200 genuinely good videos before any public link; wedge =
  es/fr underserved markets + demonetization-burned creators, not
  English-TikTok head-on.
- **Import over migrate**: one-click mirror of a creator's existing TikTok
  catalog; "post here too" beats "leave there".
- **Speed budget**: first frame < 1s (webseed first, P2P in background,
  preload next reel). If it feels slower than TikTok nothing else matters.
