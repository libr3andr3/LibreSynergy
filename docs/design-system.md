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

## Third-party apps

Authentik, the Frappe classroom and Jitsi are separate applications; they can't
share `system.css` directly but inherit the **palette and logo** through their
own theming (driven by the same `libresynergy.env` values via
`apply-branding.sh`), so the family resemblance carries across the whole stack.

## Reference

A living style guide + the platform's five core user-flow diagrams is published
as a shareable page (design tokens, type scale, interactive components, and the
join / upgrade / stream / course-seed / self-host journeys).
