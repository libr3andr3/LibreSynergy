# Yaya brand assets (powered by LibreSynergy)

Central brand folder, served at **https://yaya.sh/brand/**. Every app references these files,
so swapping the placeholders here updates branding everywhere (some apps need a restart/recreate).

## Files
- `logo.svg` — horizontal wordmark (mark + "Yaya"). Used on landing, emails, login pages, premium, Jitsi.
- `app-icon.svg` — square mark only (favicons, SVG icon links).
- `icon-192.png`, `icon-512.png` — raster app icons (PWA / manifests).
- `apple-touch-icon.png` (180), `favicon-32.png`, `favicon.ico` — favicons.
- `login-bg.jpg` — Authentik login/recovery background (1920×1280).
- `tokens.css` — the palette as CSS variables.

## Palette — "sovereignty": violet (community) → gold (value/independence)
- ink `#0b0b12` · surface `#15151f` · line `#262633`
- text `#eef0ff` · muted `#9aa0b5`
- brand violet `#7c6cff` (strong `#6a4cff`) · gold `#ffc15e`
- ok `#5ad28a` · gradient `linear-gradient(135deg,#7c6cff,#ffc15e)`

## To swap in your real logo
1. Replace `logo.svg`, `app-icon.svg` (keep the same filenames), and regenerate the PNG/ICO with:
   `python3` + Pillow (see scratchpad `mkicon.py`) or any tool, keeping filenames identical.
2. Re-copy into the apps that hold local copies:
   - Authentik: `/home/yaya/docker/data/authentik/media/public/brand/` (sudo) — then it's live.
   - Frappe: `docker cp` into `learn_yaya_sh-app-1:.../sites/learn.yaya.sh/public/files/yaya-*`.
   - Jitsi & Cinny read via mounts/URLs — just recreate those containers.
3. Apps referencing by URL (emails, Jitsi welcome, manifests) update automatically.

## Where each app is branded
- **Authentik** (login + all emails): blueprint `yaya-branding.yaml` + `templates/email/base.html`.
- **Frappe LMS**: Website Settings (app_name/app_logo/favicon/footer_powered) + Navbar Settings.
- **Jitsi**: `data/jitsi/web/custom-interface_config.js` + watermark/favicon mounts in its compose.
- **Cinny**: `apps/chat_cinny/manifest.json` + favicon mount. In-app logo/title is compiled-in
  (fork required for 100%).
- **Custom pages**: landing (`www/index.html`), welcome shim (`www/welcome.html`), premium bridge.
