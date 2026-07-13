# The VOD / course layer — PeerTube-style, on your own stack

> Live P2P fights latency; **VOD is where P2P wins.** Course files are static,
> so BitTorrent's model applies cleanly: free learners stream a lesson and seed
> it to the next learner straight from the browser tab — zero install.

This is the teaching-content distribution layer. It does **not** replace the
livestream (that stays origin-served HLS); it offloads on-demand course video.

## Why BitTorrent/WebTorrent, not a custom protocol
BitTorrent already solves the two hard problems, hardened over 20 years:
- **Integrity** — every piece is SHA-hashed; the infohash is the merkle root.
- **Peer discovery** — the tracker introduces peers into a swarm.

WebTorrent is BitTorrent over WebRTC, so **browsers are full peers**: a learner
watching a lesson simultaneously seeds it to others, no download, no install —
exactly PeerTube's design. We add the one thing BitTorrent lacks: an **Ed25519
signature over the infohash** = *creator provenance* (BT proves the bytes are
intact; the signature proves the creator authored them).

## The pieces (all built + proven)

| Piece | What | Where |
|-------|------|-------|
| Sovereign tracker | WebSocket + HTTP tracker, wss://tracker.<domain> over 443/SNI | `mesh/tracker.mjs`, node `tracker_yaya_sh` |
| Course tool | create / seed / download torrents (announce + webseed) | `mesh/course.mjs` |
| Provenance | Ed25519 signature over the infohash | `mesh/content_sign.py` |
| Origin webseed | the file on the origin's HTTPS server = always-available fallback | Caddy `/vod/` |

## The always-available origin (critical)
Every course torrent carries a **webseed** (`urlList`) pointing at the origin's
HTTPS copy (e.g. `https://<domain>/vod/lesson.mp4`). With a full swarm, learners
serve each other and origin bandwidth drops toward zero; with an **empty** swarm,
the webseed still delivers the whole file. Content is never unavailable — P2P is
pure upside, never a single point of failure.

## Proven (2026-07-05, real 3.2 MB lesson video)
- Cross-network download via the `.torrent`: origin webseed delivered the file,
  our tracker introduced the peer, BitTorrent verified all 197 pieces, md5
  matched source, and the **Ed25519 infohash signature verified** to the
  creator — one signature authenticates the whole file (merkle root).
- Local two-peer swarm with **no webseed**: 2 MB moved *peer-to-peer* through our
  tracker, integrity matched — the data could only have come from the peer.
- Boundary: cross-NAT peer-to-peer *data* needs WebRTC/ICE (what browsers do via
  WebTorrent) or the hole-punch layer (`mesh/rendezvous.py`); classic-BT between
  two NATed hosts falls back to the webseed, which is by design.

## Publishing a course video
```bash
# 1) place the file where the origin serves it (the webseed)
cp lesson-01.mp4  www/vod/lesson-01.mp4        # -> https://<domain>/vod/lesson-01.mp4

# 2) make the torrent (announce to our tracker + webseed the origin)
node mesh/course.mjs create www/vod/lesson-01.mp4 https://<domain>/vod/lesson-01.mp4
#    -> lesson-01.mp4.torrent  + magnet + INFOHASH

# 3) sign the infohash for creator provenance
echo -n "<INFOHASH>" > ih.txt
python3 mesh/content_sign.py sign ih.txt --key creator.key --media application/x-bittorrent

# 4) seed from the origin so there is always at least one seed
WEBSEED=https://<domain>/vod/lesson-01.mp4 node mesh/course.mjs seed www/vod/lesson-01.mp4
```

## Browser player embed (stream + seed, zero install)
Drop this on a course/lesson page. The learner streams the lesson **and** seeds
it to other learners while the tab is open; the origin webseed guarantees
playback even when the learner is the only one there.

```html
<!-- self-host webtorrent.min.js under /vod/ (CSP blocks external CDNs) -->
<script src="/vod/webtorrent.min.js"></script>
<video id="lesson" controls style="width:100%;border-radius:12px"></video>
<p id="swarm" style="font:13px system-ui;color:#9aa0b5"></p>
<script>
  const client = new WebTorrent()
  // .torrent (or magnet) for this lesson; announce list + webseed are inside it
  client.add('/vod/lesson-01.mp4.torrent', (torrent) => {
    const file = torrent.files.find(f => f.name.endsWith('.mp4'))
    file.streamTo(document.getElementById('lesson'))
    setInterval(() => {
      document.getElementById('swarm').textContent =
        `▲ seeding to ${torrent.numPeers} learner(s) · ↓ ${(torrent.downloadSpeed/1e6).toFixed(2)} MB/s ` +
        `· ↑ ${(torrent.uploadSpeed/1e6).toFixed(2)} MB/s · you are part of the swarm`
    }, 1000)
  })
</script>
```

Optionally verify the creator signature client-side before playing (fetch the
signed manifest, check the infohash signature) so a learner's browser refuses
content not signed by the course's creator.
