// verypowerful course VOD — create / seed / download over our sovereign swarm.
//
// PeerTube model for teaching content: static course files distributed by
// BitTorrent/WebTorrent. Free learners stream-and-seed from the browser; the
// origin is a permanent webseed so content is always available with an empty
// swarm. BitTorrent gives per-piece integrity for free; we add an Ed25519
// signature over the infohash (see content_sign.py) for CREATOR PROVENANCE,
// which BitTorrent alone does not provide.
//
//   node course.mjs create <file> <webseedURL>   -> .torrent + magnet + infohash
//   node course.mjs seed   <file> <torrent>       -> seed (stays up)
//   node course.mjs download <torrentOrMagnet> <destDir>
import WebTorrent from 'webtorrent'
import fs from 'fs'

const ANNOUNCE = [
  'wss://tracker.yaya.sh',            // browser (WebRTC) peers
  'https://tracker.yaya.sh/announce', // classic (TCP/uTP) peers
]
const [cmd, arg1, arg2] = process.argv.slice(2)

function fmt(t) { return `${t.name} | infoHash ${t.infoHash} | ${t.length}B | pieces ${t.pieces.length}` }

if (cmd === 'create') {
  const client = new WebTorrent()
  client.seed(arg1, { announceList: ANNOUNCE.map(a => [a]), urlList: [arg2] }, (t) => {
    fs.writeFileSync(arg1.split('/').pop() + '.torrent', t.torrentFile)
    console.log('CREATED ' + fmt(t))
    console.log('MAGNET ' + t.magnetURI)
    console.log('INFOHASH ' + t.infoHash)
    client.destroy(() => process.exit(0))
  })
} else if (cmd === 'seed') {
  const client = new WebTorrent()
  const t = client.seed(arg1, { announceList: ANNOUNCE.map(a => [a]), urlList: [process.env.WEBSEED || ''].filter(Boolean) }, (t) => {
    console.log('SEEDING ' + fmt(t))
  })
  setInterval(() => console.log(`peers=${t?.numPeers ?? 0} up=${((t?.uploaded||0)/1e6).toFixed(2)}MB`), 5000)
} else if (cmd === 'download') {
  const client = new WebTorrent()
  const start = Date.now()
  const t = client.add(arg1, { path: arg2, announce: ANNOUNCE }, (t) => {
    console.log('ADDED ' + fmt(t))
  })
  let lastPct = -1
  t.on('download', () => {
    const pct = Math.floor(t.progress * 100)
    if (pct >= lastPct + 20) { lastPct = pct; console.log(`progress ${pct}% (peers=${t.numPeers}, ${(t.downloadSpeed/1e6).toFixed(2)}MB/s)`) }
  })
  t.on('done', () => {
    const secs = (Date.now() - start) / 1000
    // fromPeers vs fromWebseed: numPeers>0 and downloaded shows swarm participation
    console.log(`DONE ${t.length}B in ${secs.toFixed(2)}s | peers seen=${t.numPeers} | downloaded=${(t.downloaded/1e6).toFixed(2)}MB`)
    console.log('RESULT ' + JSON.stringify({ infoHash: t.infoHash, bytes: t.length, secs, peers: t.numPeers }))
    client.destroy(() => process.exit(0))
  })
  t.on('error', e => { console.error('ERR', e.message); process.exit(1) })
  setTimeout(() => { console.error('timeout'); process.exit(2) }, 90000)
} else {
  console.error('usage: course.mjs create|seed|download ...'); process.exit(1)
}
