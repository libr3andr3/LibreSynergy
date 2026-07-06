# Design system

One visual language across every first-party surface — landing, app shell,
checkout, admin, emails. Dark-first, offline-first (no webfont/CDN), driven
entirely by brand tokens so re-branding one file reskins the whole platform.

## Files

- **`www/brand/tokens.css`** — the brandable palette, *generated* from
  `libresynergy.env` by `apply-branding.sh` (violet `--ls-brand` → gold
  `--ls-gold` "sovereignty palette").
- **`www/brand/system.css`** — the design system: full token set (color, type
  scale, spacing, radius, shadow, motion) + components (`.ls-btn`, `.ls-card`,
  `.ls-badge`, `.ls-input`, `.ls-nav`, `.ls-lang`, …). Served at
  `/brand/system.css`.

## Adopt in any page

```html
<link rel="stylesheet" href="/brand/system.css">
<!-- for a custom brand, link the generated tokens AFTER so they override: -->
<link rel="stylesheet" href="/brand/tokens.css">

<button class="ls-btn ls-btn--brand">Join free</button>
<span class="ls-badge ls-badge--ok">Synced</span>
<div class="ls-card ls-card--hover">…</div>
```

Existing pages that predate the system keep their own layout CSS but map their
local palette variables onto the shared `--ls-*` tokens (e.g.
`--accent: var(--ls-brand)`), so colours, type and controls stay consistent
without a full rewrite. This is how the landing, app shell, checkout and admin
were unified.

## Themes

Dark by default. Light mode ships via `:root[data-theme="light"]` plus a
`prefers-color-scheme` fallback — style through the tokens, never hardcode a
colour in a component, and both themes stay correct.

## Third-party apps — per-app theming

Each bundled app is a separate application with its own theming hook, so they
can't share `system.css` directly. What they *can* share is the palette and
brand, pushed in per app. Depth varies by what each app exposes:

| App | Hook | Depth |
|-----|------|-------|
| **Authentik** (SSO login/signup) | `custom.css` mounted at `/web/dist/custom.css` — sets `--ak-accent`, PatternFly primary/link colors, dark ground. Ships as `compose/authentik-theme.css`. | **Full** — violet accent + dark surfaces |
| **OwnCast** (livestream) | Admin API `POST /api/admin/config/appearance` with a map of `--theme-color-*` variables. | **Full** — palette applied to watch page + chat |
| **Jitsi** (webinars) | Logo/watermark/favicon mounted over the image assets (see `compose/40-meet.yml`). | **Brand** — logo + favicon; colours stay Jitsi default |
| **Cinny** (chat) | Folds design system; colours are computed, not exposed as simple tokens. | **Brand** — logo/favicon; ships a usable dark theme |
| **Frappe LMS** (classroom) | App name + footer via Website Settings; the lesson UI is a built SPA. | **Brand** — name/logo; SPA colours default |
| **BTCPay** (crypto checkout) | Server Settings → Theme (custom theme CSS URI). | **Operator** — set in the BTCPay admin UI (needs the store admin login) |

The two highest-visibility surfaces — the **login** everyone passes through and
the **public livestream** page — are themed in full. The rest carry the logo and
favicon so the family resemblance holds; deep colour theming there is fragile or
gated behind an app's own admin, so it's left as an operator choice rather than
forced.

`compose/authentik-theme.css` mirrors the default palette; for a custom brand,
regenerate it from your `libresynergy.env` colours (or edit the six hex values).

## Reference

A living style guide + the platform's five core user-flow diagrams is published
as a shareable page (design tokens, type scale, interactive components, and the
join / upgrade / stream / course-seed / self-host journeys).
