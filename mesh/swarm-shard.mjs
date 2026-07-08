// LibreSynergy swarm shard — one of K parallel fetcher processes.
// Each shard opens its own WebRTC data channel to the swarm and downloads
// only files where index % K === I, so K shards saturate a high-RTT path
// that a single SCTP channel cannot (independent congestion windows).
//
//   node swarm-shard.mjs <file.torrent> <data-path> <K>:<I>
//
// Exits 0 when its selection is complete.
import WebTorrent from 'webtorrent'
import { RTCPeerConnection, RTCSessionDescription, RTCIceCandidate } from 'node-datachannel/polyfill'

const [, , torrentPath, dataPath, modSpec] = process.argv
const [K, I] = (modSpec || '').split(':').map(Number)
if (!torrentPath || !dataPath || !(K > 0) || !(I >= 0)) {
  console.error('usage: node swarm-shard.mjs <file.torrent> <data-path> <K>:<I>')
  process.exit(1)
}

const bail = m => { console.error(m); process.exit(1) }
const TRACKER = process.env.SWARM_TRACKER || bail('set SWARM_TRACKER, e.g. wss://tracker.your-domain')
const STUN = process.env.SWARM_STUN || 'stun:stun.nextcloud.com:443'

const client = new WebTorrent({
  tracker: {
    wrtc: { RTCPeerConnection, RTCSessionDescription, RTCIceCandidate },
    rtcConfig: { iceServers: [{ urls: STUN }] }
  }
})
client.on('error', e => console.error(`[s${I}] client error:`, e.message))

const torrent = client.add(torrentPath, { path: dataPath, announce: [TRACKER] })
torrent.on('error', e => console.error(`[s${I}] torrent error:`, e.message))

// High-RTT fix: webtorrent sizes its request pipeline from measured wire
// speed, which death-spirals on slow-start collapse (~90ms RTT paths).
// Floor the reported speed so the pipeline stays deep (~125+ blocks).
const SPEED_FLOOR = Number(process.env.SWARM_SPEED_FLOOR || 4e6)
torrent.on('wire', wire => {
  const orig = wire.downloadSpeed.bind(wire)
  wire.downloadSpeed = () => Math.max(orig(), SPEED_FLOOR)
})

torrent.on('ready', () => {
  torrent.deselect(0, torrent.pieces.length - 1, false)
  let bytes = 0, n = 0
  torrent.files.forEach((f, idx) => {
    if (idx % K === I) { f.select(); bytes += f.length; n++ } else { f.deselect() }
  })
  torrent.shardBytes = bytes
  console.log(`[s${I}] ready: ${n} files, ${(bytes / 1e9).toFixed(2)} GB`)
})

torrent.on('done', () => {
  console.log(`[s${I}] DONE`)
  setTimeout(() => process.exit(0), 2000)
})

setInterval(() => {
  const sel = torrent.files.filter((f, idx) => idx % K === I)
  const got = sel.reduce((a, f) => a + f.downloaded, 0)
  const tot = torrent.shardBytes || 1
  console.log(`[s${I}] peers=${torrent.numPeers} down=${(torrent.downloadSpeed / 1e6).toFixed(2)}MB/s ` +
    `have=${(100 * got / tot).toFixed(1)}%`)
}, 20000)
