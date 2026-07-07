# Reels — the feed where the swarm is the algorithm

> TikTok's model, inverted. Every viewer is infrastructure; every like is a
> vote you back with your own bandwidth. There is no engagement-maximizing
> black box — ranking is a public formula over swarm health, shown in-app.

Short vertical video, snap-scroll feed, browser playback via WebTorrent —
built on the same proven VOD substrate as the course layer
(see [peertube-layer.md](peertube-layer.md)): sovereign tracker, HTTPS origin
webseed, per-piece BitTorrent integrity.

## The core mechanic: a like is a seed

- **Watching** a reel streams it over WebTorrent (service-worker streaming),
  falling back to the origin `/media/` URL instantly if P2P is slow — playback
  never depends on the swarm.
- **Liking** a reel keeps its torrent alive in the viewer's tab *and re-seeds
  it on every future visit* (liked ids persist in `localStorage`). The people
  who like something literally host it.
- **Scrolling past** an unliked reel drops its torrent — you only spend
  bandwidth on what you chose.

## The open algorithm

The origin scrapes **our own tracker** every 30 s for live swarm stats, then:

```
score = (seeds × 3 + likes + 0.5) × 2^(−age_hours / 48)
```

- `seeds` — live seeders from the tracker scrape, minus the origin itself.
  More people liking → more seeds → faster streams → higher rank. The
  feedback loop belongs to the audience, not an ad model.
- Freshness halves the score every 48 h so the feed breathes.
- **Discovery slots**: every 5th feed position is a random reel younger than
  48 h with zero seeds — new creators bootstrap; no rich-get-richer lock-in.
- The formula ships in the API response (`/api/feed → algorithm`) and behind
  the ⓘ button on every reel, with that reel's actual numbers plugged in.
  *"Why am I seeing this?" is a right.*

## Running it

```bash
./bin/ls up vod reels            # reels needs the tracker (peer discovery + scrape)
./bin/ls route web reels 9130    # https://reels.<domain> via the relay
```

The service is `apps/reels/server.mjs` (loopback `9130`): UI + API + `/media/`
(the torrents' HTTPS webseed, with byte-range support) from one origin. State
lives in `${LS_DATA_DIR}/reels/` — `media/` (uploads), `torrents/`,
`reels.json` (metadata + likes). On boot it re-seeds every published reel, so
the swarm always has ≥1 seed on top of the webseed.

## The transcode pipeline

Every upload is normalized before it touches the swarm (ffmpeg, one job at a
time, `status: processing → live | failed`; the frontend polls
`/api/status/:id`). A reel is published + seeded **only on success**, so the
feed never shows something that can't play.

- ≤720p H.264 Main / AAC stereo, `+faststart` — plays everywhere, sane
  torrent payload (a 4K HEVC phone clip is neither).
- **All metadata and chapters stripped** (`-map_metadata -1`): phone videos
  carry GPS coordinates; a sovereignty platform must never seed people's
  home addresses to a public swarm. Verified: input with
  `location=+40.7128-074.0060/` comes out with zero location tags.
- Hard cut at `LS_REELS_MAX_SECONDS` (default 180); poster JPEG extracted
  for instant feed paint (`/media/<id>.jpg`, used as the `<video>` poster).
- Interrupted jobs are re-queued on boot; garbage input → `failed` with a
  path-sanitized error, never a feed entry.

## Uploads & identity

- Open by default (permissionless instance). To restrict to members: set
  `LS_REELS_REQUIRE_AUTH=1` and add the Authentik `forward_auth` block to the
  `{$LS_REELS}` vhost (same as the admin vhost) — the creator handle then
  comes from `X-authentik-username`.
- Viewers have **no accounts**: likes dedupe on a salted hash of a random
  local-only client id. We can count likes without knowing who anyone is.
- `LS_REELS_MAX_UPLOAD_MB` caps upload size (default 200).

## i18n

Full en/es/fr via the shared catalog (`apps/i18n/strings/reels.json`), same
resolution as every sidecar: `?lang` > `ls_lang` cookie > `Accept-Language` >
`LS_DEFAULT_LANG` > `en`.

## Boundaries & next steps

- Browser peers hold pieces in memory; liking many long reels costs RAM. Next:
  an IndexedDB chunk store so seeding survives tab memory pressure.
- Creator provenance (Ed25519 signature over the infohash, as in the course
  layer) is not yet wired into the reels UI — the plumbing exists in
  `mesh/content_sign.py`.
- Cross-NAT browser peers use WebRTC/ICE via the tracker (that's WebTorrent's
  whole point); classic-BT NATed peers fall back to the webseed, by design.
- Seed counts are per-transport announces. Browser peers (the audience) speak
  only wss and count once; the origin announces on one transport by design; a
  hybrid node/desktop WebTorrent peer announcing over both ws *and* http can
  count twice. Acceptable v1 rounding — the signal stays monotone in real
  interest.
