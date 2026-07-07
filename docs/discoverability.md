# Discoverability & edge config

How the world finds a LibreSynergy community, and how the hub loads fast once
they do. This layer covers the two "hub" surfaces: the public landing site on
the root domain and the installable PWA shell on `app.<domain>`.

## What was added

| File | What it does |
|------|--------------|
| `www/robots.template.txt` | Crawl policy for the root domain. Renders to `www/robots.txt` at deploy (it needs `__LS_BASE_DOMAIN__` for the absolute sitemap URL, which the robots spec requires). Allows the public landing, disallows the app shell and API paths, points to the sitemap. |
| `www/sitemap.template.xml` | Renders to `www/sitemap.xml`. Public URLs only: `/`, `/join`, the livestream page (`live.`), the course catalog (`learn.`). |
| `routing/templates/edge-hub.caddy` | Importable Caddy config for the root-domain and `app.` vhosts: compression, security headers, PWA plumbing, cache policy, robots/sitemap serving. Replaces the two matching blocks in the root `Caddyfile` (wiring steps below and in the file header). |
| `docs/discoverability.md` | This document. |

The app host (`app.<domain>`) is deliberately **not** in the sitemap and serves
its own deny-all `robots.txt` plus an `X-Robots-Tag: noindex` header, straight
from the edge. The landing page is the SEO surface; the shell is member
territory.

## Cache policy (what the edge promises)

| Path | Cache-Control | Why |
|------|---------------|-----|
| HTML / unmatched | `public, max-age=300, must-revalidate` | content and brand updates go live in minutes |
| page assets (css/js/img/fonts) | `public, max-age=86400` | daily churn budget; bump `?v=` on redesigns |
| `/brand/*` (images, icons, fonts) | `public, max-age=31536000, immutable` | fingerprint-stable brand binaries |
| `/brand/*.css` | `public, max-age=3600, must-revalidate` | `apply-branding.sh` regenerates `tokens.css` **in place** — an immutable copy would pin returning visitors to the old palette for a year |
| `sw.js` | `no-cache` (+ `Service-Worker-Allowed: /`) | browsers re-fetch the SW to detect app updates; a cached SW strands installed users on an old shell |
| `manifest.webmanifest` | `public, max-age=300` (+ correct `application/manifest+json` type) | rebrands reach installed users quickly |
| `robots.txt`, `sitemap.xml` | `public, max-age=3600` | crawlers re-check often |

Also enabled on both vhosts: `encode zstd gzip`, HSTS, `nosniff`,
`strict-origin-when-cross-origin`, and a `frame-ancestors` CSP that permits
**same-site** framing only (this replaces `X-Frame-Options`, which would block
subdomains from framing each other). Embedding `meet.`/`live.` inside the
shell needs nothing here — that permission lives on the *embedded* side and is
already granted in the root `Caddyfile`'s meet/live vhosts. Unrendered
`*.template.*` sources are never served (hidden at the file server).

## Wiring the Caddy snippet (one-time)

1. Mount the snippet into the caddy container — `compose/00-edge.yml`,
   caddy service `volumes`:

   ```yaml
   - ../routing/templates/edge-hub.caddy:/etc/caddy/edge-hub.caddy:ro
   ```

2. In the root `Caddyfile`, **delete or comment out** the existing
   `{$LS_BASE_DOMAIN} { ... }` and `{$LS_APP} { ... }` site blocks (Caddy
   rejects duplicate site addresses; the snippet carries the `/join` and
   `/api/events` proxies over). Then add, at the top level:

   ```
   import /etc/caddy/edge-hub.caddy
   ```

3. Recreate caddy (to pick up the new mount), then validate and reload:

   ```sh
   ./bin/ls up -d caddy
   docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile
   docker compose exec caddy caddy reload   --config /etc/caddy/Caddyfile
   ```

The snippet was validated against `caddy:2-alpine` (the pinned image) and
smoke-tested end-to-end; it needs Caddy ≥ 2.7 (heredoc syntax).

### Template rendering dependency

`www/robots.template.txt`, `www/sitemap.template.xml` (and the shell's
`manifest.template.webmanifest`) follow the brand contract: placeholders baked
by `apply-branding.sh`. If the generic render step isn't in your
`apply-branding.sh` yet, add this after the tokens.css step:

```sh
# N) render *.template.* → live filenames with brand placeholders substituted
find "${LS_WWW_DIR}" -name '*.template.*' | while read -r t; do
  out="$(dirname "$t")/$(basename "$t" | sed 's/\.template//')"
  sed -e "s|__LS_BRAND_NAME__|${LS_BRAND_NAME}|g" \
      -e "s|__LS_BRAND_TAGLINE__|${LS_BRAND_TAGLINE}|g" \
      -e "s|__LS_POWERED_BY__|${LS_POWERED_BY}|g" \
      -e "s|__LS_BASE_DOMAIN__|${LS_BASE_DOMAIN}|g" \
      -e "s|__LS_APP__|${LS_APP}|g"   -e "s|__LS_CHAT__|${LS_CHAT}|g" \
      -e "s|__LS_LEARN__|${LS_LEARN}|g" -e "s|__LS_MEET__|${LS_MEET}|g" \
      -e "s|__LS_LIVE__|${LS_LIVE}|g" -e "s|__LS_PREMIUM__|${LS_PREMIUM}|g" \
      -e "s|__LS_AUTH__|${LS_AUTH}|g" \
      "$t" > "$out"
  say "rendered ${out#${LS_WWW_DIR}/}"
done
```

## Verify after deploy

```sh
D=$(. ./libresynergy.env; echo "$LS_BASE_DOMAIN")
curl -s  https://$D/robots.txt                    # policy + Sitemap: line
curl -s  https://$D/sitemap.xml | head            # rendered, no __LS_*__ left
curl -sI https://$D/ | grep -iE 'cache|encoding|security-policy'
curl -sI https://app.$D/sw.js | grep -iE 'cache|service-worker'
curl -sI https://app.$D/manifest.webmanifest | grep -i content-type
curl -s  https://app.$D/robots.txt                # → Disallow: /
curl -sI https://$D/robots.template.txt           # → 404 (sources hidden)
```

## Manual follow-ups: DNS

DNS is the one thing this repo can't do for you. Every hub/sub-app host needs
an `A` record pointing at the **relay's public IP** (not the node):

`@` (root), `app`, `auth`, `chat`, `matrix`, `learn`, `meet`, `live`,
`premium` — plus any optional profiles you run: `btcpay`, `admin`, `tracker`,
`reels`.

- On Cloudflare, `scripts/cf-dns-sync.sh` creates/updates these from
  `libresynergy.env` idempotently.
- Keep records **DNS-only (grey cloud)**. TLS terminates on *your* node — the
  sovereign-relay pattern. An orange-cloud proxy would re-terminate TLS at
  Cloudflare (breaking the SNI relay, and the point).
- Optional `www`: create the `A` record **and** the relay SNI map entry
  (`bin/ls-route web www <any>` or manually), then uncomment the
  `www.` redirect block at the bottom of `edge-hub.caddy`.
- New web routes always need all three: DNS record + relay SNI entry + Caddy
  vhost (`bin/ls-route web …` prints the record to create).

## Manual follow-ups: search engines & CDN

1. **Google Search Console** — verify a **Domain property** (DNS TXT record,
   covers all subdomains; required for the sitemap's cross-subdomain `live.`/
   `learn.` entries to count), then submit `https://<domain>/sitemap.xml`.
   Note: Google retired the `/ping` endpoint — robots.txt discovery and GSC
   submission are the supported paths.
2. **Bing Webmaster Tools** — "Import from GSC" is the 2-minute path; Bing
   also powers DuckDuckGo/Ecosia results.
3. **IndexNow** (optional) — instant re-crawl pings for Bing-family engines;
   drop a key file in `www/` if you want it later.
4. **Social/OG preview cards** — meta tags in the landing page `<head>` (the
   landing's concern, not the edge's); validate with the usual card debuggers
   after launch.
5. **CDN** — generally unnecessary: assets are aggressively cached and
   compressed at the edge, and fronting the dynamic hosts with a third-party
   CDN surrenders TLS. If you ever need geographic offload, restrict it to a
   cookieless static-asset host and keep the app/auth/chat hosts direct.
6. **PWA install checklist** (already satisfied once the shell ships, listed
   for operators changing things): HTTPS everywhere, `manifest.webmanifest`
   reachable with correct MIME type, `sw.js` served `no-cache` from the origin
   root, 192/512 px icons in `/brand/`.
