// verypowerful WebTorrent tracker — sovereign peer discovery for course VOD.
//
// A WebSocket tracker: browser (WebTorrent) and desktop peers register here to
// find each other in a swarm. Rides wss://tracker.<domain> over the relay's
// 443/SNI like every other app — no dedicated port, no VPS install. It only
// introduces peers; content bytes flow peer-to-peer, never through it.
import Server from 'bittorrent-tracker/server'

const PORT = parseInt(process.env.TRACKER_PORT || '9120', 10)
const HOST = process.env.TRACKER_HOST || '127.0.0.1'

const server = new Server({
  udp: false, http: true, ws: true,   // http for classic peers, ws for browsers
  stats: true,
  filter: (infoHash, params, cb) => cb(null)   // open swarm; gate here later if wanted
})

server.on('error', (e) => console.error('tracker error:', e.message))
server.on('warning', (e) => console.warn('tracker warn:', e.message))
server.on('listening', () => {
  const ws = server.ws && server.ws.address ? server.ws.address().port : PORT
  console.log(`tracker listening ${HOST}:${PORT} (ws + http)`)
})
let started = 0, completed = 0
server.on('start', () => { started++; })
server.on('complete', () => { completed++; console.log(`swarm complete events: ${completed}`) })

server.listen(PORT, HOST, () => {
  console.log(`verypowerful tracker up on ${HOST}:${PORT}`)
})
