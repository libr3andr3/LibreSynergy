// LibreSynergy reels — peer-seeded short-video feed. The swarm IS the algorithm.
//
// TikTok's model inverted: every viewer is infrastructure, every like is a
// vote you back with your own bandwidth. Liking a reel downloads it and seeds
// it from the viewer's browser (WebTorrent), so popular content organically
// gains seeds, streams faster, and ranks higher — a feedback loop owned by
// the audience, not an ad model. The ranking formula is public and served
// with every feed item (see score() below); there are no hidden weights.
//
// This process is the ORIGIN: it serves the UI + API on loopback (Caddy
// fronts ${LS_REELS}), stores uploads under STATE_DIR/media, creates the
// torrent for each reel (announce = our sovereign tracker, webseed = our own
// /media/ URL) and keeps seeding everything, so playback works even with an
// empty swarm — P2P is pure upside, never a point of failure. Swarm health
// (the ranking input) comes from scraping our tracker every SCRAPE_SECS.
//
//   Enable:  ./bin/ls up vod reels        (reels needs the tracker)
//   Route:   ./bin/ls route web reels 9130
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import crypto from 'node:crypto'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import WebTorrent from 'webtorrent'
import Client from 'bittorrent-tracker'
import parseTorrent, { toTorrentFile, toMagnetURI } from 'parse-torrent'

const HOST = process.env.LISTEN_HOST || '127.0.0.1'
const PORT = parseInt(process.env.LISTEN_PORT || '9130', 10)
const STATE = process.env.STATE_DIR || './state'
const PUBLIC_URL = (process.env.REELS_PUBLIC_URL || `http://${HOST}:${PORT}`).replace(/\/$/, '')
const TRACKER_WS = process.env.TRACKER_WS || ''            // wss://tracker.<your-domain> (set by compose/66-reels.yml)
const TRACKER_ANNOUNCE = process.env.TRACKER_ANNOUNCE || ''  // https://tracker.<your-domain>/announce
const TRACKER_SCRAPE = process.env.TRACKER_SCRAPE || TRACKER_ANNOUNCE   // loopback in prod
const MAX_UPLOAD = parseInt(process.env.MAX_UPLOAD_MB || '200', 10) * 1e6
const MAX_SECONDS = parseInt(process.env.MAX_SECONDS || '180', 10)
const REQUIRE_AUTH = process.env.REELS_REQUIRE_AUTH === '1'
const SCRAPE_SECS = parseInt(process.env.SCRAPE_SECS || '30', 10)
const FFMPEG = process.env.FFMPEG || 'ffmpeg'
const FFPROBE = process.env.FFPROBE || 'ffprobe'
const ANNOUNCE = [TRACKER_WS, TRACKER_ANNOUNCE]
const DIR = path.dirname(fileURLToPath(import.meta.url))
const MEDIA = path.join(STATE, 'media')
const INCOMING = path.join(STATE, 'incoming')
const TORRENTS = path.join(STATE, 'torrents')
const DB_FILE = path.join(STATE, 'reels.json')
// Anything ffmpeg can read is accepted; every reel is re-encoded to one
// canonical shape, so the swarm never carries codec roulette.
const EXT = { 'video/mp4': '.mp4', 'video/webm': '.webm', 'video/quicktime': '.mov', 'video/x-matroska': '.mkv' }
const MIME = { '.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime', '.jpg': 'image/jpeg' }

fs.mkdirSync(MEDIA, { recursive: true })
fs.mkdirSync(INCOMING, { recursive: true })
fs.mkdirSync(TORRENTS, { recursive: true })

// ---------------------------------------------------------------- i18n (JS
// port of apps/i18n/i18n.py — same catalog files, same resolution order:
// ?lang > ls_lang cookie > Accept-Language > LS_DEFAULT_LANG > en).
const LANGS = ['en', 'es', 'fr']
const DEFAULT_LANG = LANGS.includes((process.env.LS_DEFAULT_LANG || 'en').slice(0, 2)) ? (process.env.LS_DEFAULT_LANG || 'en').slice(0, 2) : 'en'
const STRINGS = (() => {
  const catalog = {}
  for (const d of [process.env.LS_I18N_DIR, '/i18n/strings', path.join(DIR, '../i18n/strings')]) {
    if (!d || !fs.existsSync(d)) continue
    for (const f of fs.readdirSync(d).filter(f => f.endsWith('.json')).sort()) {
      try {
        const data = JSON.parse(fs.readFileSync(path.join(d, f), 'utf8'))
        for (const [lang, table] of Object.entries(data || {})) Object.assign(catalog[lang] ??= {}, table)
      } catch { /* a broken file must not brick the UI */ }
    }
    break
  }
  return catalog
})()
const norm = c => (c || '').trim().toLowerCase().slice(0, 2)
function resolveLang (req) {
  const q = new URL(req.url, 'http://x').searchParams.get('lang')
  const cookie = /(?:^|;\s*)ls_lang=([a-z]{2})/.exec(req.headers.cookie || '')?.[1]
  for (const cand of [q, cookie]) if (LANGS.includes(norm(cand))) return { lang: norm(cand), setCookie: LANGS.includes(norm(q)) }
  for (const part of (req.headers['accept-language'] || '').split(','))
    if (LANGS.includes(norm(part.split(';')[0]))) return { lang: norm(part.split(';')[0]), setCookie: false }
  return { lang: DEFAULT_LANG, setCookie: false }
}
// lang -> en -> key, so a missing string is never fatal.
const stringsFor = lang => ({ ...(STRINGS.en || {}), ...(STRINGS[lang] || {}) })

// ---------------------------------------------------------------- store —
// one JSON file, atomic writes; likes are salted hashes of an anonymous
// client id (we can dedupe without knowing who anyone is).
const db = fs.existsSync(DB_FILE) ? JSON.parse(fs.readFileSync(DB_FILE, 'utf8')) : { salt: crypto.randomBytes(16).toString('hex'), videos: {} }
function save () {
  const tmp = DB_FILE + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify(db, null, 1))
  fs.renameSync(tmp, DB_FILE)
}
const likeHash = clientId => crypto.createHash('sha256').update(db.salt + clientId).digest('hex').slice(0, 16)

// ---------------------------------------------------------------- the open
// algorithm. seeds = live swarm seeders from OUR tracker scrape, minus this
// origin process (it always seeds). Freshness halves the score every 48h so
// the feed breathes; +0.5 keeps brand-new uploads from a hard zero. Served
// verbatim with every feed item — "why am I seeing this" is a right.
function score (v, now = Date.now()) {
  const seeds = Math.max(0, (v.scrape?.seeders ?? 0) - 1)
  const likes = (v.likes || []).length
  const fresh = Math.pow(2, -((now - v.createdAt) / 3.6e6) / 48)
  return { seeds, likes, fresh: +fresh.toFixed(4), total: +((seeds * 3 + likes + 0.5) * fresh).toFixed(4) }
}
// Records written before the transcoder existed have no status — they were
// published directly, so they count as live.
const isLive = v => (v.status ?? 'live') === 'live'
function feed () {
  const now = Date.now()
  const all = Object.values(db.videos).filter(isLive).map(v => ({ ...pub(v), score: score(v, now) }))
  all.sort((a, b) => b.score.total - a.score.total)
  // Discovery slots: every 5th position surfaces a random young (<48h),
  // unseeded reel so new creators can bootstrap — no rich-get-richer lock-in.
  const fresh = all.filter(v => now - v.createdAt < 48 * 3.6e6 && v.score.seeds === 0)
  const out = []
  for (const v of all) {
    if (out.length % 5 === 4 && fresh.length) {
      const pick = fresh.splice(crypto.randomInt(fresh.length), 1)[0]
      if (!out.includes(pick)) out.push({ ...pick, discovery: true })
    }
    if (!out.includes(v)) out.push(v)
  }
  return out.slice(0, 200)
}
const pub = v => ({
  id: v.id, title: v.title, creator: v.creator, file: v.file, size: v.size,
  infoHash: v.infoHash, magnet: v.magnet, createdAt: v.createdAt,
  duration: v.duration ?? null, width: v.width ?? null, height: v.height ?? null,
  poster: v.poster ? `/media/${v.id}.jpg` : null,
  likes: (v.likes || []).length,
  seeders: v.scrape?.seeders ?? 0, leechers: v.scrape?.leechers ?? 0, downloads: v.scrape?.downloads ?? 0
})

// ---------------------------------------------------------------- origin
// seeder: one WebTorrent client seeds every published reel from disk, so the
// swarm always has ≥1 seed on top of the HTTPS webseed baked into the torrent.
const wt = new WebTorrent()
wt.on('error', e => console.error('webtorrent:', e.message))
function seedVideo (v, cb) {
  // The origin announces on ONE transport only, so it shows up as exactly one
  // seeder in scrapes and score() can subtract it cleanly ("organic seeds" =
  // real people). The .torrent handed to clients still carries both trackers
  // (wss for browsers, https for classic peers) — announce URLs aren't part
  // of the infohash, so patching them in changes nothing about integrity.
  wt.seed(path.join(MEDIA, v.file), {
    announceList: [[TRACKER_ANNOUNCE]],
    urlList: [`${PUBLIC_URL}/media/${v.file}`]
  }, async t => {
    const pt = await parseTorrent(t.torrentFile)
    pt.announce = [...ANNOUNCE]
    v.infoHash = t.infoHash
    v.magnet = toMagnetURI(pt)
    fs.writeFileSync(path.join(TORRENTS, v.id + '.torrent'), toTorrentFile(pt))
    console.log(`seeding ${v.id} "${v.title}" infoHash=${t.infoHash}`)
    cb?.(t)
  })
}
// ------------------------------------------------------------- transcode
// queue. Every upload is normalized before it touches the swarm:
//   - ≤720p H.264 main / AAC stereo, +faststart (plays everywhere, sane
//     torrent payload — a 4K HEVC phone clip is neither)
//   - ALL metadata + chapters stripped: phone uploads carry GPS coordinates
//     in EXIF/QuickTime tags; a sovereignty platform must not seed people's
//     home addresses to a public swarm
//   - hard cut at MAX_SECONDS, poster frame extracted for instant feed paint
// One job at a time (ffmpeg saturates cores by itself); publish + seed only
// on success, so the feed never shows a reel that can't play.
const run = (bin, args) => new Promise((resolve, reject) => {
  const p = spawn(bin, args, { stdio: ['ignore', 'pipe', 'pipe'] })
  let out = '', err = ''
  p.stdout.on('data', d => out += d)
  p.stderr.on('data', d => err += d)
  p.on('error', reject)
  p.on('close', code => code === 0 ? resolve(out) : reject(new Error(err.trim().split('\n').pop() || `${bin} exit ${code}`)))
})
const probe = async file => JSON.parse(await run(FFPROBE, ['-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', file]))

async function transcode (v) {
  const inFile = path.join(INCOMING, v.incoming)
  const outFile = path.join(MEDIA, v.id + '.mp4')
  const poster = path.join(MEDIA, v.id + '.jpg')
  const info = await probe(inFile)   // rejects on non-video garbage
  if (!info.streams?.some(s => s.codec_type === 'video')) throw new Error('no video stream')
  await run(FFMPEG, [
    '-y', '-hide_banner', '-loglevel', 'error', '-i', inFile,
    '-t', String(MAX_SECONDS),
    '-map_metadata', '-1', '-map_chapters', '-1',
    '-map', '0:v:0', '-map', '0:a:0?',
    '-vf', "scale='min(720,iw)':-2",
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-profile:v', 'main', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '128k', '-ac', '2',
    '-movflags', '+faststart', outFile
  ])
  try {
    await run(FFMPEG, ['-y', '-hide_banner', '-loglevel', 'error', '-ss', '0.5', '-i', outFile, '-frames:v', '1', '-vf', "scale='min(480,iw)':-2", '-q:v', '4', poster])
  } catch { // clip shorter than the seek point
    await run(FFMPEG, ['-y', '-hide_banner', '-loglevel', 'error', '-i', outFile, '-frames:v', '1', '-vf', "scale='min(480,iw)':-2", '-q:v', '4', poster])
  }
  const outInfo = await probe(outFile)
  const vs = outInfo.streams.find(s => s.codec_type === 'video')
  v.file = v.id + '.mp4'
  v.size = fs.statSync(outFile).size
  v.duration = Math.round(parseFloat(outInfo.format.duration) * 10) / 10
  v.width = vs.width
  v.height = vs.height
  v.poster = true
  fs.rmSync(inFile, { force: true })
  delete v.incoming
}

const tq = []
let transcoding = false
function enqueue (id) { tq.push(id); pump() }
async function pump () {
  if (transcoding) return
  const id = tq.shift()
  if (!id) return
  transcoding = true
  const v = db.videos[id]
  try {
    await transcode(v)
    v.status = 'live'
    seedVideo(v, () => save())
    console.log(`transcoded ${id} "${v.title}" ${v.width}x${v.height} ${v.duration}s ${(v.size / 1e6).toFixed(1)}MB`)
  } catch (e) {
    v.status = 'failed'
    v.error = String(e.message).replaceAll(INCOMING + path.sep, '').slice(0, 300)   // no server paths to clients
    if (v.incoming) { fs.rmSync(path.join(INCOMING, v.incoming), { force: true }); delete v.incoming }
    console.error(`transcode failed ${id}:`, v.error)
  }
  save()
  transcoding = false
  pump()
}

for (const v of Object.values(db.videos)) {
  if (v.status === 'processing') {                 // interrupted by a restart
    if (v.incoming && fs.existsSync(path.join(INCOMING, v.incoming))) enqueue(v.id)
    else { v.status = 'failed'; v.error = 'lost during restart' }
  } else if (isLive(v) && fs.existsSync(path.join(MEDIA, v.file))) seedVideo(v, () => save())
  else if (isLive(v)) console.warn(`missing media for ${v.id}, skipping`)
}

// Swarm scrape loop — the ranking's ground truth, from our own tracker.
let scrapeWarned = false
setInterval(() => {
  const ihs = Object.values(db.videos).map(v => v.infoHash).filter(Boolean)
  if (!ihs.length) return
  Client.scrape({ announce: TRACKER_SCRAPE, infoHash: ihs }, (err, res) => {
    if (err) {
      if (!scrapeWarned) { scrapeWarned = true; console.warn('scrape failed (tracker down?):', err.message) }
      return
    }
    scrapeWarned = false
    const byHash = ihs.length === 1 ? { [ihs[0]]: res } : res
    const now = Date.now()
    for (const v of Object.values(db.videos)) {
      const s = v.infoHash && byHash[v.infoHash]
      if (s) v.scrape = { seeders: s.complete ?? 0, leechers: s.incomplete ?? 0, downloads: s.downloaded ?? 0, at: now }
    }
    save()
  })
}, SCRAPE_SECS * 1000).unref()

// ---------------------------------------------------------------- HTTP
const json = (res, code, body, extra = {}) => {
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', ...extra })
  res.end(JSON.stringify(body))
}
const readBody = (req, limit = 64 * 1024) => new Promise((resolve, reject) => {
  const chunks = []; let n = 0
  req.on('data', c => { n += c.length; if (n > limit) { reject(new Error('too large')); req.destroy() } else chunks.push(c) })
  req.on('end', () => resolve(Buffer.concat(chunks)))
  req.on('error', reject)
})

function serveStatic (res, file, type, cache = 'no-cache') {
  if (!fs.existsSync(file)) return json(res, 404, { error: 'not found' })
  res.writeHead(200, { 'Content-Type': type, 'Cache-Control': cache })
  fs.createReadStream(file).pipe(res)
}

// Byte ranges are mandatory: <video> seeks with them and BitTorrent webseed
// clients fetch individual pieces with them.
function serveMedia (req, res, name) {
  if (!/^[a-f0-9]{16}\.(mp4|webm|mov|jpg)$/.test(name)) return json(res, 400, { error: 'bad name' })
  const file = path.join(MEDIA, name)
  if (!fs.existsSync(file)) return json(res, 404, { error: 'not found' })
  const size = fs.statSync(file).size
  const type = MIME[path.extname(name)]
  const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '')
  if (m && (m[1] || m[2])) {
    const start = m[1] ? parseInt(m[1], 10) : Math.max(0, size - parseInt(m[2], 10))
    const end = m[1] && m[2] ? Math.min(parseInt(m[2], 10), size - 1) : size - 1
    if (start > end || start >= size) return json(res, 416, { error: 'range' }, { 'Content-Range': `bytes */${size}` })
    res.writeHead(206, {
      'Content-Type': type, 'Accept-Ranges': 'bytes',
      'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1
    })
    return fs.createReadStream(file, { start, end }).pipe(res)
  }
  res.writeHead(200, { 'Content-Type': type, 'Accept-Ranges': 'bytes', 'Content-Length': size })
  fs.createReadStream(file).pipe(res)
}

async function handleUpload (req, res) {
  // Behind Authentik forward-auth the username header is trustworthy (Caddy
  // strips inbound copies); open mode is for dev / permissionless instances.
  const authUser = req.headers['x-authentik-username']
  if (REQUIRE_AUTH && !authUser) return json(res, 401, { error: 'auth required' })
  const ext = EXT[(req.headers['content-type'] || '').split(';')[0]]
  if (!ext) return json(res, 415, { error: 'send video/mp4, video/webm, video/quicktime or video/x-matroska' })
  if (parseInt(req.headers['content-length'] || '0', 10) > MAX_UPLOAD) return json(res, 413, { error: `max ${MAX_UPLOAD / 1e6}MB` })
  const id = crypto.randomBytes(8).toString('hex')
  const incoming = id + ext
  const tmp = path.join(INCOMING, incoming + '.part')
  const out = fs.createWriteStream(tmp)
  let n = 0, aborted = false
  req.on('data', c => { n += c.length; if (n > MAX_UPLOAD && !aborted) { aborted = true; out.destroy(); fs.rmSync(tmp, { force: true }); json(res, 413, { error: 'too large' }); req.destroy() } })
  req.pipe(out)
  out.on('finish', () => {
    if (aborted) return
    if (!n) { fs.rmSync(tmp, { force: true }); return json(res, 400, { error: 'empty body' }) }
    fs.renameSync(tmp, path.join(INCOMING, incoming))
    const v = {
      id, incoming, status: 'processing',
      title: decodeURIComponent(req.headers['x-reels-title'] || '').slice(0, 140) || 'untitled',
      creator: (authUser || decodeURIComponent(req.headers['x-reels-creator'] || '') || 'anon').slice(0, 60),
      likes: [], createdAt: Date.now()
    }
    db.videos[id] = v
    save()
    enqueue(id)
    json(res, 202, { id, status: 'processing' })
  })
  out.on('error', e => { fs.rmSync(tmp, { force: true }); json(res, 500, { error: e.message }) })
}

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x')
  const p = u.pathname
  try {
    if (p === '/healthz') return json(res, 200, { ok: true, videos: Object.keys(db.videos).length, seeding: wt.torrents.length, transcoding: transcoding ? 1 : 0, queued: tq.length })

    if (p === '/' || p === '/index.html') {
      const { lang, setCookie } = resolveLang(req)
      const html = fs.readFileSync(path.join(DIR, 'public/index.html'), 'utf8')
        .replace('/*__BOOT__*/', `window.__REELS__=${JSON.stringify({
          lang, strings: stringsFor(lang), tracker: TRACKER_WS, publicUrl: PUBLIC_URL, langs: LANGS
        })}`)
      res.writeHead(200, {
        'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-cache',
        ...(setCookie ? { 'Set-Cookie': `ls_lang=${lang}; Path=/; Max-Age=31536000; SameSite=Lax` } : {})
      })
      return res.end(html)
    }
    // Self-hosted vendor bundles (CSP blocks external CDNs); sw.min.js must
    // live at the origin root to get page scope for streamTo().
    if (p === '/vendor/webtorrent.min.js') return serveStatic(res, path.join(DIR, 'node_modules/webtorrent/dist/webtorrent.min.js'), 'application/javascript', 'public, max-age=86400')
    if (p === '/sw.min.js') return serveStatic(res, path.join(DIR, 'node_modules/webtorrent/dist/sw.min.js'), 'application/javascript', 'no-cache')
    if (p === '/manifest.webmanifest') {
      return json(res, 200, {
        name: 'Reels', short_name: 'Reels', start_url: '/', display: 'standalone',
        background_color: '#0b0d12', theme_color: '#0b0d12',
        icons: [{ src: 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="22" fill="#0b0d12"/><text x="50" y="66" font-size="52" text-anchor="middle">▶</text></svg>'), sizes: 'any', type: 'image/svg+xml' }]
      }, { 'Content-Type': 'application/manifest+json' })
    }

    if (p === '/api/feed') return json(res, 200, {
      algorithm: 'score = (seeds*3 + likes + 0.5) * 2^(-age_hours/48); seeds scraped live from our tracker; every 5th slot is a random young unseeded reel (discovery)',
      videos: feed()
    })
    if (p === '/api/upload' && req.method === 'POST') return handleUpload(req, res)

    let sm = /^\/api\/status\/([a-f0-9]{16})$/.exec(p)
    if (sm) {
      const v = db.videos[sm[1]]
      if (!v) return json(res, 404, { error: 'not found' })
      return json(res, 200, { id: v.id, status: v.status ?? 'live', ...(v.error ? { error: v.error } : {}), ...(isLive(v) ? { video: { ...pub(v), score: score(v) } } : {}) })
    }

    let m = /^\/api\/(like|unlike)\/([a-f0-9]{16})$/.exec(p)
    if (m && req.method === 'POST') {
      const v = db.videos[m[2]]
      if (!v) return json(res, 404, { error: 'not found' })
      const { client } = JSON.parse((await readBody(req)).toString() || '{}')
      if (!client || typeof client !== 'string' || client.length > 64) return json(res, 400, { error: 'client id required' })
      const h = likeHash(client)
      v.likes = v.likes || []
      if (m[1] === 'like' && !v.likes.includes(h)) v.likes.push(h)
      if (m[1] === 'unlike') v.likes = v.likes.filter(x => x !== h)
      save()
      return json(res, 200, { likes: v.likes.length })
    }

    m = /^\/t\/([a-f0-9]{16})\.torrent$/.exec(p)
    if (m) return serveStatic(res, path.join(TORRENTS, m[1] + '.torrent'), 'application/x-bittorrent')

    m = /^\/media\/(.+)$/.exec(p)
    if (m) return serveMedia(req, res, m[1])

    json(res, 404, { error: 'not found' })
  } catch (e) {
    console.error(p, e)
    json(res, 500, { error: 'internal' })
  }
})

server.listen(PORT, HOST, () => {
  console.log(`reels up on ${HOST}:${PORT} | ${Object.keys(db.videos).length} reels | tracker ${TRACKER_ANNOUNCE} | auth=${REQUIRE_AUTH ? 'required' : 'open'}`)
})
