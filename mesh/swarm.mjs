// LibreSynergy swarm — hybrid CLI peer: seed or fetch a torrent peer-to-peer.
//
// Transports: WebRTC data channels (node-datachannel) hole-punched via the
// community tracker's WebSocket signaling, plus classic TCP/uTP when peers
// are directly reachable. The tracker only introduces peers — content bytes
// flow peer-to-peer. Sovereign STUN default; no Big-Tech dependency.
//
//   node swarm.mjs <file.torrent> <data-path>
//
// If <data-path> already contains the torrent's content it is verified and
// seeded; otherwise it is downloaded there. Runs until killed.
import WebTorrent from 'webtorrent'
import { RTCPeerConnection, RTCSessionDescription, RTCIceCandidate } from 'node-datachannel/polyfill'

const [, , torrentPath, dataPath] = process.argv
if (!torrentPath || !dataPath) {
  console.error('usage: node swarm.mjs <file.torrent> <data-path>')
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
client.on('error', e => console.error('client error:', e.message))

const torrent = client.add(torrentPath, { path: dataPath, announce: [TRACKER] })
torrent.on('error', e => console.error('torrent error:', e.message))

// High-RTT fix: simple-peer pauses writes at 64KB of bufferedAmount, which
// caps each data channel near 64KB/RTT. Wrap the channel so simple-peer sees
// a discounted bufferedAmount and keeps ~1MB in flight per wire.
const SLACK = Number(process.env.SWARM_BUF_SLACK || 960 * 1024)
function unthrottle (conn) {
  const real = conn && conn._channel
  if (!real || real.__unthrottled) return
  real.__unthrottled = true
  conn._channel = new Proxy(real, {
    get (t, p) {
      if (p === 'bufferedAmount') {
        const v = t.bufferedAmount
        return v > SLACK ? v - SLACK : 0
      }
      const val = t[p]
      return typeof val === 'function' ? val.bind(t) : val
    },
    set (t, p, v) { t[p] = v; return true }
  })
}
setInterval(() => {
  for (const peer of Object.values(torrent._peers || {})) unthrottle(peer.conn)
}, 5000)
torrent.on('ready', () =>
  console.log(`ready: ${torrent.name} | ${(torrent.length / 1e9).toFixed(2)} GB | ${torrent.files.length} files`))
torrent.on('verified', () => {})
torrent.on('done', () => console.log(`DONE at ${new Date().toISOString()} — seeding on`))
torrent.on('wire', (wire, addr) =>
  console.log(`peer connected: ${addr || wire.type} (${wire.type})`))

setInterval(() => {
  console.log(`[${new Date().toISOString()}] peers=${torrent.numPeers} ` +
    `down=${(torrent.downloadSpeed / 1e6).toFixed(2)}MB/s up=${(torrent.uploadSpeed / 1e6).toFixed(2)}MB/s ` +
    `have=${(torrent.progress * 100).toFixed(2)}%`)
}, 15000)
