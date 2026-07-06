/* ============================================================================
   LibreSynergy hub panel — LIVE (OwnCast)  ·  www/app/panels/live.js
   Compact native panel: polls /api/status; offline → quiet-stage state,
   online → embedded player (hero) + stream chat, side-by-side on wide
   containers, stacked on mobile. Self-contained ES module (injects live.css).

   Contract:
     mount(root, ctx)  — render into root
     unmount(root)     — stop polling, drop iframes, clean listeners
     expand(ctx)       — open the full stream page via ctx.onExpand(url)

   ctx = { lang, t(key), user, matrix, endpoints, onExpand(url_or_view) }

   Endpoint resolution (first hit wins):
     ctx.endpoints.live  →  window.LS.urls.live  →  "https://__LS_LIVE__"
   (the placeholder is only a template-render fallback; at runtime the shell
   bakes the real URL into window.LS via apply-branding).

   Verified endpoint shapes (curl on node):
     GET  {live}/api/status            → {online, streamTitle, viewerCount?,
                                          lastConnectTime, lastDisconnectTime}
     GET  {live}/embed/video/          → player page (bare path 301s here)
     GET  {live}/embed/chat/readwrite/ → interactive chat embed
   ============================================================================ */

const CSS_ID = "ls-panel-live-css";

const POLL_MS = 30_000;     // healthy poll cadence
const POLL_ERR_MS = 90_000; // back off when unreachable
const FETCH_TIMEOUT_MS = 10_000;

const LAST_KEY = "ls_live_last";     // {"title":string,"at":epoch_ms}
const NOTIFY_KEY = "ls_live_notify"; // "1" = user opted in (placeholder)

/* ---------------------------------------------------------------------------
   i18n — shared keys (live.now, live.viewers, live.offline_*, nav.live) defer
   to ctx.t() when the shell translates them; the rest live here.
   --------------------------------------------------------------------------- */
const STRINGS = {
  en: {
    "nav.live": "Live",
    "live.now": "Live now",
    "live.viewers": "watching",
    "live.offline_title": "The stage is quiet",
    "live.offline_body": "Nobody is streaming right now. This lights up the second a stream starts.",
    "live.tuning": "Tuning in…",
    "live.last_stream": "Last stream",
    "live.notify": "Notify me when it starts",
    "live.notify_on": "You’re on the list",
    "live.expand": "Expand",
    "live.expand_hint": "Open the full stream page",
    "live.chat": "Stream chat",
    "live.fullscreen": "Fullscreen",
    "live.player": "Live stream player"
  },
  es: {
    "nav.live": "En vivo",
    "live.now": "En vivo",
    "live.viewers": "viendo",
    "live.offline_title": "El escenario está en calma",
    "live.offline_body": "Nadie está transmitiendo ahora. Esto se enciende en cuanto empiece un directo.",
    "live.tuning": "Sintonizando…",
    "live.last_stream": "Último directo",
    "live.notify": "Avísame cuando empiece",
    "live.notify_on": "Estás en la lista",
    "live.expand": "Ampliar",
    "live.expand_hint": "Abrir la página completa del directo",
    "live.chat": "Chat del directo",
    "live.fullscreen": "Pantalla completa",
    "live.player": "Reproductor en vivo"
  },
  fr: {
    "nav.live": "Direct",
    "live.now": "En direct",
    "live.viewers": "spectateurs",
    "live.offline_title": "La scène est calme",
    "live.offline_body": "Personne ne diffuse pour l’instant. Tout s’allume dès qu’un direct démarre.",
    "live.tuning": "Connexion…",
    "live.last_stream": "Dernier direct",
    "live.notify": "Prévenez-moi au démarrage",
    "live.notify_on": "Vous êtes sur la liste",
    "live.expand": "Agrandir",
    "live.expand_hint": "Ouvrir la page complète du direct",
    "live.chat": "Chat du direct",
    "live.fullscreen": "Plein écran",
    "live.player": "Lecteur du direct"
  }
};

/* --------------------------------------------------------------------------- */

const states = new WeakMap(); // root → panel state

function ensureCss() {
  if (document.getElementById(CSS_ID)) return;
  const link = document.createElement("link");
  link.id = CSS_ID;
  link.rel = "stylesheet";
  link.href = new URL("./live.css", import.meta.url).href;
  document.head.appendChild(link);
}

function pickLang(ctx) {
  const l = String((ctx && ctx.lang) || navigator.language || "en").slice(0, 2).toLowerCase();
  return STRINGS[l] ? l : "en";
}

function resolveBase(ctx) {
  const fromCtx = ctx && ctx.endpoints && (ctx.endpoints.live || ctx.endpoints.owncast);
  const fromLS = typeof window !== "undefined" && window.LS && window.LS.urls && window.LS.urls.live;
  const base = fromCtx || fromLS || "https://__LS_LIVE__";
  return String(base).replace(/\/+$/, "");
}

/* Prefer the shell's translation when it has one; fall back to local dict. */
function makeT(ctx, lang) {
  return (key) => {
    if (ctx && typeof ctx.t === "function") {
      try {
        const v = ctx.t(key);
        if (v && v !== key) return v;
      } catch { /* shell t() optional */ }
    }
    return (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key;
  };
}

function readJSON(key) {
  try { return JSON.parse(localStorage.getItem(key)); } catch { return null; }
}
function writeJSON(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)); } catch { /* private mode */ }
}

function relTime(whenMs, lang) {
  if (!isFinite(whenMs)) return "";
  const s = Math.round((whenMs - Date.now()) / 1000);
  const abs = Math.abs(s);
  try {
    const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
    if (abs < 90) return rtf.format(Math.round(s / 1), "second");
    if (abs < 5400) return rtf.format(Math.round(s / 60), "minute");
    if (abs < 129600) return rtf.format(Math.round(s / 3600), "hour");
    return rtf.format(Math.round(s / 86400), "day");
  } catch { return ""; }
}

/* Tiny stroke icons matching the shell's icon language. */
const ICONS = {
  expand: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7"/></svg>',
  fullscreen: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/></svg>',
  bell: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 15.5V11a6 6 0 1 0-12 0v4.5L4.5 18h15L18 15.5z"/><path d="M10 21a2.2 2.2 0 0 0 4 0"/></svg>',
  check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 12.5l5 5 10-11"/></svg>'
};

/* ---------------------------------------------------------------------------
   DOM scaffold — built once per mount; state flips [data-state] + hidden.
   All dynamic text goes through textContent (stream titles are untrusted).
   --------------------------------------------------------------------------- */
function buildDom(root, st) {
  const t = st.t;
  root.innerHTML = "";

  const el = document.createElement("section");
  el.className = "lp";
  el.dataset.state = "loading";
  el.innerHTML = `
    <header class="lp-head">
      <span class="lp-pill" hidden><span class="lp-pill-dot" aria-hidden="true"></span><span class="lp-pill-txt"></span></span>
      <div class="lp-meta" aria-live="polite">
        <h2 class="lp-title"></h2>
        <p class="lp-sub"></p>
      </div>
      <button type="button" class="lp-expand ls-btn ls-btn--ghost ls-btn--sm">
        <span class="lp-expand-txt"></span>${ICONS.expand}
      </button>
    </header>

    <div class="lp-stage">
      <div class="lp-skel" aria-hidden="true"><span class="lp-spinner"></span></div>

      <div class="lp-offline" hidden>
        <div class="lp-orb" aria-hidden="true"><span></span></div>
        <h3 class="lp-off-title"></h3>
        <p class="lp-off-body"></p>
        <p class="lp-off-last" hidden>
          <span class="lp-off-last-label"></span>
          <span class="lp-off-last-title"></span>
          <span class="lp-off-last-when"></span>
        </p>
        <button type="button" class="lp-notify">
          <span class="lp-notify-ico lp-notify-ico--bell">${ICONS.bell}</span>
          <span class="lp-notify-ico lp-notify-ico--check">${ICONS.check}</span>
          <span class="lp-notify-txt"></span>
        </button>
      </div>

      <div class="lp-live" hidden>
        <div class="lp-player">
          <div class="lp-load" aria-hidden="true"><span class="lp-spinner"></span></div>
          <button type="button" class="lp-fs" hidden>${ICONS.fullscreen}</button>
        </div>
        <aside class="lp-chatbox">
          <div class="lp-chat-head">
            <span class="lp-chat-dot" aria-hidden="true"></span>
            <span class="lp-chat-title"></span>
          </div>
          <div class="lp-chat-body">
            <div class="lp-load" aria-hidden="true"><span class="lp-spinner"></span></div>
          </div>
        </aside>
      </div>
    </div>`;

  const q = (sel) => el.querySelector(sel);
  st.els = {
    panel: el,
    pill: q(".lp-pill"), pillTxt: q(".lp-pill-txt"),
    title: q(".lp-title"), sub: q(".lp-sub"),
    expandBtn: q(".lp-expand"), expandTxt: q(".lp-expand-txt"),
    skel: q(".lp-skel"),
    offline: q(".lp-offline"),
    offTitle: q(".lp-off-title"), offBody: q(".lp-off-body"),
    offLast: q(".lp-off-last"), offLastLabel: q(".lp-off-last-label"),
    offLastTitle: q(".lp-off-last-title"), offLastWhen: q(".lp-off-last-when"),
    notifyBtn: q(".lp-notify"), notifyTxt: q(".lp-notify-txt"),
    live: q(".lp-live"),
    player: q(".lp-player"), playerLoad: q(".lp-player .lp-load"),
    fsBtn: q(".lp-fs"),
    chatBody: q(".lp-chat-body"), chatLoad: q(".lp-chat-body .lp-load"),
    chatTitle: q(".lp-chat-title")
  };

  // Static copy
  st.els.pillTxt.textContent = t("live.now");
  st.els.expandTxt.textContent = t("live.expand");
  st.els.expandBtn.title = t("live.expand_hint");
  st.els.expandBtn.setAttribute("aria-label", t("live.expand_hint"));
  st.els.offTitle.textContent = t("live.offline_title");
  st.els.offBody.textContent = t("live.offline_body");
  st.els.offLastLabel.textContent = t("live.last_stream");
  st.els.chatTitle.textContent = t("live.chat");
  st.els.fsBtn.title = t("live.fullscreen");
  st.els.fsBtn.setAttribute("aria-label", t("live.fullscreen"));
  st.els.title.textContent = t("nav.live");
  st.els.sub.textContent = t("live.tuning");
  refreshNotify(st);

  // Wire-up
  st.els.expandBtn.addEventListener("click", () => expand(st.ctx));
  st.els.notifyBtn.addEventListener("click", () => {
    const on = localStorage.getItem(NOTIFY_KEY) === "1";
    try { localStorage.setItem(NOTIFY_KEY, on ? "0" : "1"); } catch { /* private mode */ }
    refreshNotify(st);
  });
  st.els.fsBtn.addEventListener("click", () => {
    if (document.fullscreenElement) { document.exitFullscreen().catch(() => {}); return; }
    const req = st.els.player.requestFullscreen || st.els.player.webkitRequestFullscreen;
    if (req) { try { req.call(st.els.player); } catch { /* denied */ } }
  });

  root.appendChild(el);
}

function refreshNotify(st) {
  const on = localStorage.getItem(NOTIFY_KEY) === "1";
  st.els.notifyBtn.classList.toggle("is-on", on);
  st.els.notifyBtn.setAttribute("aria-pressed", on ? "true" : "false");
  st.els.notifyTxt.textContent = st.t(on ? "live.notify_on" : "live.notify");
}

/* ---------------------------------------------------------------------------
   Iframes — lazy: created only while the stream is online, torn down when it
   ends (frees the HLS connection + chat socket).
   --------------------------------------------------------------------------- */
function mountFrames(st) {
  const t = st.t;
  if (!st.els.player.querySelector("iframe")) {
    st.els.playerLoad.classList.remove("is-done");
    const f = document.createElement("iframe");
    f.src = st.base + "/embed/video/"; // canonical: bare /embed/video 301s here
    f.title = t("live.player");
    f.allow = "autoplay; fullscreen; picture-in-picture";
    f.setAttribute("allowfullscreen", "");
    f.referrerPolicy = "origin";
    f.loading = "lazy";
    f.addEventListener("load", () => st.els.playerLoad.classList.add("is-done"));
    st.els.player.appendChild(f);
    st.els.fsBtn.hidden = !(document.fullscreenEnabled || document.webkitFullscreenEnabled);
  }
  if (!st.els.chatBody.querySelector("iframe")) {
    st.els.chatLoad.classList.remove("is-done");
    const f = document.createElement("iframe");
    f.src = st.base + "/embed/chat/readwrite/"; // interactive; bare /embed/chat 307s to readonly
    f.title = t("live.chat");
    f.allow = "clipboard-write";
    f.referrerPolicy = "origin";
    f.loading = "lazy";
    f.addEventListener("load", () => st.els.chatLoad.classList.add("is-done"));
    st.els.chatBody.appendChild(f);
  }
}

function unmountFrames(st) {
  st.els.player.querySelectorAll("iframe").forEach((f) => f.remove());
  st.els.chatBody.querySelectorAll("iframe").forEach((f) => f.remove());
  st.els.fsBtn.hidden = true;
}

/* ---------------------------------------------------------------------------
   Status → UI
   --------------------------------------------------------------------------- */
function setState(st, name) {
  st.els.panel.dataset.state = name;
  st.els.skel.hidden = name !== "loading";
  st.els.offline.hidden = name !== "offline";
  st.els.live.hidden = name !== "online";
}

function applyStatus(st, status) {
  const t = st.t;
  const online = !!(status && status.online);

  if (online) {
    const title = (status.streamTitle || "").trim();
    if (title) writeJSON(LAST_KEY, { title, at: Date.now() });

    setState(st, "online");
    mountFrames(st);
    st.els.pill.hidden = false;
    st.els.title.textContent = title || t("live.now");
    const n = typeof status.viewerCount === "number" ? status.viewerCount : null;
    st.els.sub.textContent = n === null ? "" :
      `${new Intl.NumberFormat(st.lang).format(n)} ${t("live.viewers")}`;
    st.online = true;
    return;
  }

  // Offline (or unreachable — same quiet-stage face).
  if (st.online !== false) {
    unmountFrames(st);
    setState(st, "offline");
  }
  st.els.pill.hidden = true;
  st.els.title.textContent = t("nav.live");

  // Last stream breadcrumb: prefer the server's lingering title, then ours.
  const stored = readJSON(LAST_KEY);
  const lastTitle = ((status && status.streamTitle) || "").trim() ||
                    (stored && stored.title) || "";
  const lastAtMs = status && status.lastDisconnectTime
    ? Date.parse(status.lastDisconnectTime)
    : (stored && stored.at) || NaN;
  const when = relTime(lastAtMs, st.lang);

  st.els.sub.textContent = when ? `${t("live.last_stream")} · ${when}` : "";
  if (lastTitle) {
    st.els.offLast.hidden = false;
    st.els.offLastTitle.textContent = lastTitle;
    st.els.offLastWhen.textContent = when ? ` · ${when}` : "";
  } else {
    st.els.offLast.hidden = true;
  }
  st.online = false;
}

/* ---------------------------------------------------------------------------
   Polling — pauses while the tab is hidden; resumes instantly on return.
   --------------------------------------------------------------------------- */
function schedule(st, ms) {
  if (st.dead) return;
  clearTimeout(st.timer);
  st.timer = setTimeout(() => poll(st), ms);
}

async function poll(st) {
  if (st.dead) return;
  if (document.hidden) { schedule(st, POLL_MS); return; } // paused; visibility handler re-polls
  let delay = POLL_MS;
  try {
    st.aborter = new AbortController();
    const kill = setTimeout(() => st.aborter.abort(), FETCH_TIMEOUT_MS);
    const res = await fetch(st.base + "/api/status", {
      mode: "cors", cache: "no-store", signal: st.aborter.signal
    });
    clearTimeout(kill);
    if (!res.ok) throw new Error("status " + res.status);
    const status = await res.json();
    if (st.dead) return;
    applyStatus(st, status);
  } catch {
    if (st.dead) return;
    applyStatus(st, null);
    delay = POLL_ERR_MS;
  }
  schedule(st, delay);
}

/* ===========================================================================
   Public contract
   =========================================================================== */
export function mount(root, ctx) {
  if (states.has(root)) unmount(root);
  ensureCss();

  const lang = pickLang(ctx);
  const st = {
    ctx: ctx || {},
    lang,
    t: makeT(ctx, lang),
    base: resolveBase(ctx),
    online: null,   // unknown until first poll
    timer: 0,
    aborter: null,
    dead: false,
    els: null,
    onVis: null
  };
  states.set(root, st);

  buildDom(root, st);

  st.onVis = () => { if (!document.hidden && !st.dead) schedule(st, 0); };
  document.addEventListener("visibilitychange", st.onVis);

  schedule(st, 0);
}

export function unmount(root) {
  const st = states.get(root);
  if (!st) return;
  st.dead = true;
  clearTimeout(st.timer);
  try { if (st.aborter) st.aborter.abort(); } catch { /* already done */ }
  if (st.onVis) document.removeEventListener("visibilitychange", st.onVis);
  root.innerHTML = "";
  states.delete(root);
}

export function expand(ctx) {
  const url = resolveBase(ctx);
  if (ctx && typeof ctx.onExpand === "function") ctx.onExpand(url);
  else window.open(url, "_blank", "noopener");
}
