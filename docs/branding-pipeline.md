# The branding pipeline

Everything an operator sees — name, tagline, colors, icons, URLs — flows from
**one file** (`libresynergy.env`) through **one script**
(`scripts/apply-branding.sh`). Nothing customer-facing is hand-edited on the
node. That is the reproducibility guarantee: a new operator sets five variables
and gets the exact same premium product under their own brand.

```
libresynergy.env
      │
      ▼
scripts/apply-branding.sh          scripts/deploy-node.sh
  1 tokens.css   (palette)           rsync www/ + renderer + env → node
  2 templates    (__LS_*__ → real)   run apply-branding on node
  3 icons        (logo.svg → PNGs)   force-recreate caddy
  4 Authentik    (blueprint)
  5 Frappe LMS   (app_name/footer)
  6 Jitsi        (APP_NAME)
```

## The brand contract (what every page must follow)

Every HTML document under `www/` links, **in this order**:

```html
<link rel="stylesheet" href="/brand/system.css">   <!-- the design system -->
<link rel="stylesheet" href="/brand/tokens.css">   <!-- per-operator palette -->
```

and styles exclusively with the CSS variables (`--ls-ink`, `--ls-surface`,
`--ls-text`, `--ls-muted`, `--ls-brand`, `--ls-gold`, `--ls-ok`, `--ls-danger`,
`--ls-gradient`, …). **Never hardcode brand hex** — `tokens.css` is generated
and overrides the defaults in `system.css`.

Text and URLs are never baked into committed files either. Source files use
double-underscore placeholders and are named `*.template.<ext>`:

| Placeholder            | Comes from                                | Example              |
|------------------------|-------------------------------------------|-----------------------------|
| `__LS_BRAND_NAME__`    | `LS_BRAND_NAME`                            | `Acme Studio`                      |
| `__LS_BRAND_TAGLINE__` | `LS_BRAND_TAGLINE`                         | `A self-hosted community`   |
| `__LS_POWERED_BY__`    | `LS_POWERED_BY`                            | `LibreSynergy`              |
| `__LS_BASE_DOMAIN__`   | `LS_BASE_DOMAIN`                           | `acme.studio`                   |
| `__LS_APP__`           | `LS_APP` (default `app.<base>`)            | `app.acme.studio`               |
| `__LS_CHAT__`          | `LS_CHAT` (default `chat.<base>`)          | `chat.acme.studio`              |
| `__LS_LEARN__`         | `LS_LEARN` (default `learn.<base>`)        | `learn.acme.studio`             |
| `__LS_MEET__`          | `LS_MEET` (default `meet.<base>`)          | `meet.acme.studio`              |
| `__LS_LIVE__`          | `LS_LIVE` (default `live.<base>`)          | `live.acme.studio`              |
| `__LS_PREMIUM__`       | `LS_PREMIUM` (default `premium.<base>`)    | `premium.acme.studio`           |
| `__LS_AUTH__`          | `LS_AUTH` (default `auth.<base>`)          | `auth.acme.studio`              |
| `__LS_COLOR_BRAND__`   | `LS_COLOR_BRAND`                           | `#7c6cff`                   |
| `__LS_COLOR_ACCENT__`  | `LS_COLOR_ACCENT`                          | `#ffc15e`                   |
| `__LS_COLOR_INK__`     | `LS_COLOR_INK`                             | `#0b0b12`                   |

Subdomain variables **derive automatically** from `LS_BASE_DOMAIN` when unset —
a new operator usually only sets `LS_BRAND_NAME`, `LS_BRAND_TAGLINE`,
`LS_BASE_DOMAIN` and the three colors.

Brand image assets are served at `/brand/` and referenced by those paths:
`logo.svg`, `favicon.ico`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`.

## `scripts/apply-branding.sh` — the canonical renderer

Pure bash + coreutils, idempotent (files are only rewritten when content
changes, so mtimes and rsync stay quiet). Also runnable via `./bin/ls brand`
(the old root `apply-branding.sh` is now a shim to it).

What each step does:

1. **tokens.css** — writes `www/brand/tokens.css` from `LS_COLOR_BRAND` /
   `LS_COLOR_ACCENT` / `LS_COLOR_INK` (plus the derived `--ls-gradient`).
2. **Templates** — for every `*.template.*` file under `www/`
   (`index.template.html` → `index.html`,
   `app/manifest.template.webmanifest` → `app/manifest.webmanifest`,
   `sitemap.template.xml` → `sitemap.xml`, …) substitutes the placeholder
   table above and writes the final file next to the template. Substitution is
   literal (safe for `&`, `/`, `\` in values — bash pattern substitution with
   `patsub_replacement` disabled). Any `__LS_*__` token the script doesn't
   know is left in place **and flagged with a warning** so typos can't ship
   silently.
3. **Icons** — if `www/brand/logo.svg` exists and `rsvg-convert` or
   ImageMagick (`magick`/`convert`) is on the host, regenerates
   `icon-192.png`, `icon-512.png` (transparent) and `apple-touch-icon.png`
   (180×180 on the ink color, since iOS fills transparency with black).
   Regenerates only when `logo.svg` is newer (`LS_FORCE_ICONS=1` to force);
   skips gracefully with a note when no converter is installed.
4. **Authentik** — finds the running worker container (name contains
   `worker` + `auth…` name or `authentik` image; override with
   `LS_AUTH_WORKER_CONTAINER`) and runs `ak apply_blueprint` for every
   YAML in `/blueprints/custom/`.
5. **Frappe LMS** — finds the app container (override
   `LS_LEARN_APP_CONTAINER`) and sets Website Settings `app_name` +
   `footer_powered` via `bench console`.
6. **Jitsi** — sets `interfaceConfig.APP_NAME` / `PROVIDER_NAME` in
   `<data>/jitsi/web/custom-interface_config.js` (recreate the meet web
   container afterwards).

Steps 4–6 skip cleanly when docker or the containers aren't present, so the
script is safe to run on a dev laptop (`LS_SKIP_SERVICES=1` skips them
explicitly). Env file discovery supports both layouts: the repo
(`<root>/libresynergy.env` + `<root>/www/`) and the node deploy dir
(`<dir>/libresynergy/libresynergy.env` + `<dir>/www/`); relative `LS_WWW_DIR` /
`LS_DATA_DIR` resolve against the env file's directory, with `./www` and
`../www` fallbacks. `LS_ENV_FILE=/path` overrides discovery.

```bash
# render everything locally (great for previewing www/ before deploy)
bash scripts/apply-branding.sh

# render files only, no docker
LS_SKIP_SERVICES=1 bash scripts/apply-branding.sh
```

## `scripts/deploy-node.sh` — ship it

```bash
NODE_DIR=/opt/libresynergy bash scripts/deploy-node.sh          # NODE_DIR is required
NODE_SSH=mynode NODE_DIR=/opt/ls bash scripts/deploy-node.sh
PUSH_ENV=0  NODE_DIR=/opt/libresynergy bash scripts/deploy-node.sh   # keep the node's own env
SKIP_CADDY=1 NODE_DIR=/opt/libresynergy bash scripts/deploy-node.sh  # don't bounce the edge
```

Steps: (1) rsync `www/` to `$NODE_DIR/www/` — **additive, never `--delete`**,
so node-local content (VODs, uploads) survives; (2) rsync
`scripts/apply-branding.sh` and `libresynergy.env` to
`$NODE_DIR/libresynergy/` (the node's previous env is kept as
`libresynergy.env.bak-<timestamp>` when it differs); (3) run apply-branding on
the node; (4) `docker compose -p $CADDY_PROJECT up -d --force-recreate caddy`
(project default `libresynergy`), with a `docker restart` fallback. Ends with
an HTTPS smoke test against `https://$LS_APP`.

`NODE_DIR` must be the directory whose `www/` is bind-mounted into caddy at
`/srv/www` — verify before the first deploy:
`ssh <node> docker inspect <caddy> --format '{{json .Mounts}}'`.

## Adding a new branded page

1. Create `www/<page>.template.html` using placeholders and the two
   `/brand/*.css` links. Commit **only the template** — rendered files are
   derived artifacts.
2. `bash scripts/apply-branding.sh` to preview locally.
3. `bash scripts/deploy-node.sh` to ship.

## Troubleshooting

- **Placeholder still visible on the site** — the renderer warned about it;
  check the spelling against the table above and re-run.
- **Colors didn't change** — the page must load `/brand/tokens.css` *after*
  `/brand/system.css`; hard-refresh (tokens are generated, check its header
  comment for the brand name).
- **Icons stale** — `LS_FORCE_ICONS=1 bash scripts/apply-branding.sh`.
- **Authentik/Frappe step skipped** — the container match is conservative; set
  `LS_AUTH_WORKER_CONTAINER=` / `LS_LEARN_APP_CONTAINER=` explicitly.
- **Chat (Cinny) branding** — compiled into the client; rebuild
  `apps/chat_cinny` and `up -d --build` (the renderer reminds you).
