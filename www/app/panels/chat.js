/* ============================================================================
   LibreSynergy hub panel — chat.js
   Native Matrix community-room panel for the app shell.

   Contract:
     mount(root, ctx)   — render into root
     unmount(root)      — cleanup on view switch
     expand(ctx)        — open the full chat app (Element / __LS_CHAT__)

   ctx = { lang, t(key), user, matrix, endpoints, onExpand, connectMatrix }
   ctx.matrix = { baseUrl, token, userId, room } | null

   Brand-agnostic: styles come from /app/panels/chat.css (auto-injected) and
   use only --ls-* tokens. URLs resolve at runtime from ctx.endpoints /
   window.LS.urls — no build-time placeholders needed in this file.
   All message bodies are rendered via textContent (XSS-safe).
   ============================================================================ */

"use strict";

/* ---------------------------------------------------------------------------
   i18n — local strings (the shell's t() falls back to the raw key for keys it
   does not know, so the panel carries its own table). en / es / fr.
--------------------------------------------------------------------------- */
const STRINGS = {
  en: {
    "room.fallback": "Community",
    "expand": "Open full chat",
    "connect.title": "Connect community chat",
    "connect.body": "One tap links your community account — your sign-in carries over instantly.",
    "connect.btn": "Connect",
    "connect.busy": "Connecting…",
    "connect.err": "Couldn’t connect. Try again.",
    "expired": "Your session expired — reconnect to keep chatting.",
    "empty.title": "No messages yet",
    "empty.body": "Say hello — the room is listening.",
    "err.load": "Couldn’t load messages.",
    "retry": "Retry",
    "composer.ph": "Message the community…",
    "composer.send": "Send",
    "status.live": "Connected",
    "status.re": "Reconnecting…",
    "status.sync": "Syncing…",
    "jump.new": "New messages",
    "msg.failed": "Not sent — tap to retry",
    "edited": "edited",
    "time.now": "now"
  },
  es: {
    "room.fallback": "Comunidad",
    "expand": "Abrir el chat completo",
    "connect.title": "Conecta el chat de la comunidad",
    "connect.body": "Un toque vincula tu cuenta de la comunidad — tu sesión te acompaña al instante.",
    "connect.btn": "Conectar",
    "connect.busy": "Conectando…",
    "connect.err": "No se pudo conectar. Inténtalo de nuevo.",
    "expired": "Tu sesión caducó — reconéctate para seguir chateando.",
    "empty.title": "Aún no hay mensajes",
    "empty.body": "Saluda — la sala te escucha.",
    "err.load": "No se pudieron cargar los mensajes.",
    "retry": "Reintentar",
    "composer.ph": "Escribe a la comunidad…",
    "composer.send": "Enviar",
    "status.live": "Conectado",
    "status.re": "Reconectando…",
    "status.sync": "Sincronizando…",
    "jump.new": "Mensajes nuevos",
    "msg.failed": "No enviado — toca para reintentar",
    "edited": "editado",
    "time.now": "ahora"
  },
  fr: {
    "room.fallback": "Communauté",
    "expand": "Ouvrir le chat complet",
    "connect.title": "Connecter le chat communautaire",
    "connect.body": "Un geste relie votre compte communautaire — votre session vous suit instantanément.",
    "connect.btn": "Connecter",
    "connect.busy": "Connexion…",
    "connect.err": "Connexion impossible. Réessayez.",
    "expired": "Session expirée — reconnectez-vous pour continuer.",
    "empty.title": "Pas encore de messages",
    "empty.body": "Dites bonjour — le salon vous écoute.",
    "err.load": "Impossible de charger les messages.",
    "retry": "Réessayer",
    "composer.ph": "Écrivez à la communauté…",
    "composer.send": "Envoyer",
    "status.live": "Connecté",
    "status.re": "Reconnexion…",
    "status.sync": "Synchronisation…",
    "jump.new": "Nouveaux messages",
    "msg.failed": "Non envoyé — touchez pour réessayer",
    "edited": "modifié",
    "time.now": "à l’instant"
  }
};

function makeTr(ctx) {
  const lang = (ctx && ctx.lang && STRINGS[ctx.lang]) ? ctx.lang
    : ((navigator.language || "en").slice(0, 2).toLowerCase());
  const table = STRINGS[lang] || STRINGS.en;
  return (key) => table[key] ?? STRINGS.en[key] ?? key;
}

/* ---------------------------------------------------------------------------
   Style injection — one <link> to the sibling stylesheet, cached hard.
--------------------------------------------------------------------------- */
function injectCSS() {
  if (document.getElementById("lsc-style")) return;
  const link = document.createElement("link");
  link.id = "lsc-style";
  link.rel = "stylesheet";
  link.href = new URL("./chat.css", import.meta.url).href;
  document.head.appendChild(link);
}

/* ---------------------------------------------------------------------------
   Small utilities
--------------------------------------------------------------------------- */
const enc = encodeURIComponent;

function el(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text != null) n.textContent = text; // textContent only — XSS-safe
  return n;
}

function svgIcon(path, cls) {
  const NS = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("fill", "none");
  s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "2");
  s.setAttribute("stroke-linecap", "round");
  s.setAttribute("stroke-linejoin", "round");
  s.setAttribute("aria-hidden", "true");
  if (cls) s.setAttribute("class", cls);
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", path);
  s.appendChild(p);
  return s;
}
const ICONS = {
  expand: "M15 3h6v6M9 21H3v-15M21 3l-7 7M3 21l7-7",
  send: "M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z",
  chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
  down: "M12 5v14M19 12l-7 7-7-7",
  spark: "M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"
};

function relTime(ts, tr, lang) {
  const d = Date.now() - ts;
  if (d < 60_000) return tr("time.now");
  if (d < 3_600_000) return Math.floor(d / 60_000) + "m";
  if (d < 86_400_000) return Math.floor(d / 3_600_000) + "h";
  if (d < 7 * 86_400_000) return Math.floor(d / 86_400_000) + "d";
  try { return new Date(ts).toLocaleDateString(lang, { month: "short", day: "numeric" }); }
  catch { return new Date(ts).toLocaleDateString(); }
}

function hueFor(userId) {
  let h = 0;
  for (let i = 0; i < userId.length; i++) h = (h * 31 + userId.charCodeAt(i)) >>> 0;
  return h % 360;
}

function localpart(userId) {
  return String(userId || "").replace(/^@/, "").split(":")[0] || "?";
}

const MEDIA_GLYPH = { "m.image": "🖼", "m.file": "📎", "m.audio": "🎙", "m.video": "🎬" };

function reducedMotion() {
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function chatUrl(ctx) {
  return (ctx && ctx.endpoints && (ctx.endpoints.chat || ctx.endpoints.element))
    || (window.LS && window.LS.urls && window.LS.urls.chat)
    || "https://__LS_CHAT__"; /* last resort if this file is ever template-rendered */
}

/* ---------------------------------------------------------------------------
   Matrix REST — thin fetch wrapper. 401 => auth error (token dead).
--------------------------------------------------------------------------- */
async function api(st, path, opts = {}) {
  const m = st.ctx.matrix;
  if (!m) { const e = new Error("no session"); e.auth = true; throw e; }
  const headers = { "Authorization": "Bearer " + m.token, ...(opts.headers || {}) };
  if (opts.body) headers["Content-Type"] = "application/json";
  const res = await fetch(m.baseUrl.replace(/\/$/, "") + path, { ...opts, headers });
  if (res.status === 401) { const e = new Error("auth"); e.auth = true; throw e; }
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

function tightFilter(room, limit) {
  return enc(JSON.stringify({
    presence: { types: [] },
    account_data: { types: [] },
    room: {
      rooms: [room],
      timeline: { limit },
      state: { types: [], lazy_load_members: true },
      ephemeral: { types: [] },
      account_data: { types: [] }
    }
  }));
}

/* ---------------------------------------------------------------------------
   Per-mount state
--------------------------------------------------------------------------- */
const STATES = new WeakMap();

function newState(root, ctx) {
  return {
    root, ctx, tr: makeTr(ctx),
    lang: (ctx && ctx.lang) || (navigator.language || "en").slice(0, 2),
    alive: true,
    abort: null,            // AbortController of the in-flight /sync
    timers: new Map(),      // timeout id -> resolve (so unmount can wake sleepers)
    intervals: new Set(),
    visWaiters: [],
    visHandler: null,
    seen: new Set(),        // rendered event_ids
    byId: new Map(),        // event_id -> { bodyEl, row } (for m.replace edits)
    txnNodes: new Map(),    // txn id -> pending row
    pendingTxns: new Set(),
    profiles: new Map(),    // userId -> display name
    nameNodes: new Map(),   // userId -> Set of nodes to update on profile load
    last: null,             // { sender, ts } of last rendered row (grouping)
    scrolledUp: false,
    unseen: 0,
    ui: {}                  // dom refs
  };
}

function sleep(st, ms) {
  return new Promise((res) => {
    const id = setTimeout(() => { st.timers.delete(id); res(); }, ms);
    st.timers.set(id, res);
  });
}
function waitVisible(st) {
  if (!document.hidden) return Promise.resolve();
  return new Promise((res) => st.visWaiters.push(res));
}

/* ===========================================================================
   PUBLIC — mount / unmount / expand
=========================================================================== */
export function mount(root, ctx) {
  if (STATES.has(root)) unmount(root);
  injectCSS();
  const st = newState(root, ctx);
  STATES.set(root, st);
  root.classList.add("lsc-host");
  if (ctx && ctx.matrix) renderChat(st);
  else renderConnect(st);
}

export function unmount(root) {
  const st = STATES.get(root);
  if (!st) return;
  st.alive = false;
  try { if (st.abort) st.abort.abort(); } catch { /* noop */ }
  st.timers.forEach((res, id) => { clearTimeout(id); try { res(); } catch { /* noop */ } });
  st.timers.clear();
  st.intervals.forEach((id) => clearInterval(id));
  st.intervals.clear();
  st.visWaiters.splice(0).forEach((res) => { try { res(); } catch { /* noop */ } });
  if (st.visHandler) document.removeEventListener("visibilitychange", st.visHandler);
  root.classList.remove("lsc-host");
  root.replaceChildren();
  STATES.delete(root);
}

export function expand(ctx) {
  if (ctx && typeof ctx.onExpand === "function") ctx.onExpand(chatUrl(ctx));
  else window.open(chatUrl(ctx), "_blank", "noopener");
}

/* ===========================================================================
   Connect state — tasteful gate with a one-tap SSO button.
=========================================================================== */
function renderConnect(st, note) {
  const { tr, ctx } = st;
  st.root.replaceChildren();

  const card = el("div", "lsc lsc-gate");
  const orb = el("div", "lsc-gate-orb");
  orb.appendChild(svgIcon(ICONS.chat, "lsc-gate-ico"));
  card.appendChild(orb);
  card.appendChild(el("h3", "lsc-gate-title", tr("connect.title")));
  card.appendChild(el("p", "lsc-gate-body", note || tr("connect.body")));
  if (note) card.querySelector(".lsc-gate-body").classList.add("is-note");

  const btn = el("button", "lsc-btn-primary");
  btn.type = "button";
  btn.appendChild(el("span", "lsc-btn-label", tr("connect.btn")));
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.classList.add("is-busy");
    btn.querySelector(".lsc-btn-label").textContent = tr("connect.busy");
    try {
      await ctx.connectMatrix(); // may navigate away for the SSO bounce
      if (st.alive && ctx.matrix) renderChat(st);
    } catch {
      if (!st.alive) return;
      renderConnect(st, tr("connect.err"));
    }
  });
  card.appendChild(btn);
  st.root.appendChild(card);
}

/* ===========================================================================
   Chat state — header / message scroll / composer, plus the sync loop.
=========================================================================== */
function renderChat(st) {
  const { tr, ctx } = st;
  st.root.replaceChildren();

  const panel = el("section", "lsc");
  panel.setAttribute("aria-label", tr("room.fallback"));

  /* -- header ------------------------------------------------------------ */
  const head = el("header", "lsc-head");
  const ident = el("div", "lsc-room");
  const glyph = el("span", "lsc-room-glyph");
  glyph.appendChild(svgIcon(ICONS.chat));
  ident.appendChild(glyph);
  const names = el("div", "lsc-room-names");
  const title = el("div", "lsc-room-title", tr("room.fallback"));
  const sub = el("div", "lsc-room-sub");
  const dot = el("span", "lsc-status-dot is-sync");
  const statusTxt = el("span", "lsc-status-txt", tr("status.sync"));
  sub.append(dot, statusTxt);
  names.append(title, sub);
  ident.appendChild(names);
  head.appendChild(ident);

  const expandBtn = el("button", "lsc-iconbtn");
  expandBtn.type = "button";
  expandBtn.title = tr("expand");
  expandBtn.setAttribute("aria-label", tr("expand"));
  expandBtn.appendChild(svgIcon(ICONS.expand));
  expandBtn.addEventListener("click", () => expand(ctx));
  head.appendChild(expandBtn);
  panel.appendChild(head);

  /* -- scrollable timeline ------------------------------------------------ */
  const scroll = el("div", "lsc-scroll");
  scroll.setAttribute("role", "log");
  scroll.setAttribute("aria-live", "polite");
  const list = el("div", "lsc-list");
  scroll.appendChild(list);
  panel.appendChild(scroll);

  /* -- new-messages jump chip --------------------------------------------- */
  const jump = el("button", "lsc-jump");
  jump.type = "button";
  jump.hidden = true;
  jump.appendChild(svgIcon(ICONS.down));
  const jumpTxt = el("span", null, tr("jump.new"));
  jump.appendChild(jumpTxt);
  jump.addEventListener("click", () => { scrollToBottom(st, true); hideJump(st); });
  panel.appendChild(jump);

  /* -- composer ------------------------------------------------------------ */
  const compose = el("form", "lsc-compose");
  const inputWrap = el("div", "lsc-input-wrap");
  const input = el("textarea", "lsc-input");
  input.rows = 1;
  input.placeholder = tr("composer.ph");
  input.setAttribute("aria-label", tr("composer.ph"));
  input.maxLength = 4000;
  inputWrap.appendChild(input);
  compose.appendChild(inputWrap);
  const sendBtn = el("button", "lsc-send");
  sendBtn.type = "submit";
  sendBtn.title = tr("composer.send");
  sendBtn.setAttribute("aria-label", tr("composer.send"));
  sendBtn.appendChild(svgIcon(ICONS.send));
  compose.appendChild(sendBtn);
  panel.appendChild(compose);

  st.root.appendChild(panel);
  st.ui = { panel, title, dot, statusTxt, scroll, list, jump, jumpTxt, input, sendBtn };

  /* -- composer behaviour --------------------------------------------------- */
  const autosize = () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  };
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      compose.requestSubmit();
    }
  });
  compose.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    autosize();
    sendMessage(st, text);
    input.focus();
  });

  /* -- scroll tracking -------------------------------------------------------- */
  scroll.addEventListener("scroll", () => {
    const fromBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight;
    st.scrolledUp = fromBottom > 80;
    if (!st.scrolledUp) hideJump(st);
  }, { passive: true });

  /* -- visibility: cut the long-poll when hidden, resume when visible -------- */
  st.visHandler = () => {
    if (document.hidden) { try { if (st.abort) st.abort.abort(); } catch { /* noop */ } }
    else st.visWaiters.splice(0).forEach((res) => { try { res(); } catch { /* noop */ } });
  };
  document.addEventListener("visibilitychange", st.visHandler);

  /* -- keep relative timestamps fresh ---------------------------------------- */
  const tick = setInterval(() => {
    st.root.querySelectorAll("[data-lsc-ts]").forEach((n) => {
      n.textContent = relTime(+n.dataset.lscTs, tr, st.lang);
    });
  }, 60_000);
  st.intervals.add(tick);

  renderSkeleton(st);
  boot(st);
}

function renderSkeleton(st) {
  const { list } = st.ui;
  list.replaceChildren();
  const widths = [64, 44, 78, 52];
  for (let i = 0; i < 4; i++) {
    const row = el("div", "lsc-skel" + (i % 2 ? " is-own" : ""));
    row.appendChild(el("span", "lsc-skel-ava"));
    const b = el("span", "lsc-skel-bubble");
    b.style.width = widths[i] + "%";
    row.appendChild(b);
    list.appendChild(row);
  }
}

function renderEmpty(st) {
  const { tr } = st;
  const { list } = st.ui;
  list.replaceChildren();
  const box = el("div", "lsc-empty");
  const orb = el("div", "lsc-empty-orb");
  orb.appendChild(svgIcon(ICONS.spark));
  box.appendChild(orb);
  box.appendChild(el("div", "lsc-empty-title", tr("empty.title")));
  box.appendChild(el("div", "lsc-empty-body", tr("empty.body")));
  list.appendChild(box);
}

function renderLoadError(st) {
  const { tr } = st;
  const { list } = st.ui;
  list.replaceChildren();
  const box = el("div", "lsc-empty is-error");
  box.appendChild(el("div", "lsc-empty-title", tr("err.load")));
  const retry = el("button", "lsc-btn-ghost", tr("retry"));
  retry.type = "button";
  retry.addEventListener("click", () => { renderSkeleton(st); boot(st); });
  box.appendChild(retry);
  list.appendChild(box);
}

/* ===========================================================================
   Boot: initial sync token -> history -> live loop.
   Order matters: grab next_batch FIRST so nothing lands between the history
   fetch and the first long-poll (overlap is deduped by event_id).
=========================================================================== */
async function boot(st) {
  const room = st.ctx.matrix.room;
  try {
    const first = await api(st, `/_matrix/client/v3/sync?timeout=0&filter=${tightFilter(room, 1)}`);
    if (!st.alive) return;
    const since = first.next_batch;

    const hist = await api(st, `/_matrix/client/v3/rooms/${enc(room)}/messages?dir=b&limit=30`);
    if (!st.alive) return;

    const events = (hist.chunk || []).filter(isMessage).reverse(); // oldest -> newest
    st.ui.list.replaceChildren();
    st.last = null;
    if (!events.length) renderEmpty(st);
    else for (const ev of events) appendEvent(st, ev, false);
    scrollToBottom(st, false);

    fetchRoomName(st, room);
    syncLoop(st, since);
  } catch (e) {
    if (!st.alive) return;
    if (e && e.auth) return sessionExpired(st);
    renderLoadError(st);
    setStatus(st, "re");
  }
}

async function fetchRoomName(st, room) {
  try {
    const r = await api(st, `/_matrix/client/v3/rooms/${enc(room)}/state/m.room.name`);
    if (st.alive && r && r.name) st.ui.title.textContent = r.name;
  } catch { /* unnamed room — keep the fallback label */ }
}

async function syncLoop(st, since) {
  const room = st.ctx.matrix.room;
  const filter = tightFilter(room, 30);
  let backoff = 0;
  setStatus(st, "live");

  while (st.alive) {
    if (document.hidden) { await waitVisible(st); if (!st.alive) return; }
    try {
      st.abort = new AbortController();
      const r = await api(
        st,
        `/_matrix/client/v3/sync?since=${enc(since)}&timeout=30000&filter=${filter}`,
        { signal: st.abort.signal }
      );
      if (!st.alive) return;
      since = r.next_batch;
      const tl = r.rooms && r.rooms.join && r.rooms.join[room] && r.rooms.join[room].timeline;
      if (tl && Array.isArray(tl.events)) {
        for (const ev of tl.events) if (isMessage(ev)) appendEvent(st, ev, true);
      }
      if (backoff) { backoff = 0; setStatus(st, "live"); }
    } catch (e) {
      if (!st.alive) return;
      if (e && e.auth) return sessionExpired(st);
      if (e && e.name === "AbortError") continue; // hidden-tab pause — loop re-checks
      backoff = Math.min(backoff ? backoff * 2 : 2000, 30_000);
      setStatus(st, "re");
      await sleep(st, backoff);
    }
  }
}

function setStatus(st, mode) {
  const { dot, statusTxt } = st.ui;
  if (!dot) return;
  dot.className = "lsc-status-dot " + (mode === "live" ? "is-live" : mode === "re" ? "is-re" : "is-sync");
  statusTxt.textContent = st.tr(mode === "live" ? "status.live" : mode === "re" ? "status.re" : "status.sync");
}

function sessionExpired(st) {
  try { localStorage.removeItem("ls_matrix"); } catch { /* private mode */ }
  if (st.ctx) st.ctx.matrix = null;
  renderConnect(st, st.tr("expired"));
}

/* ===========================================================================
   Events -> DOM
=========================================================================== */
function isMessage(ev) {
  return ev && ev.type === "m.room.message" && ev.content && typeof ev.content === "object";
}

function bodyOf(content) {
  return typeof content.body === "string" ? content.body : "";
}

function appendEvent(st, ev, live) {
  const { tr } = st;
  if (ev.event_id && st.seen.has(ev.event_id)) return;

  // Local echo of our own send (same device): confirm the optimistic row.
  const txn = ev.unsigned && ev.unsigned.transaction_id;
  if (txn && st.pendingTxns.has(txn)) {
    const row = st.txnNodes.get(txn);
    if (row) {
      row.classList.remove("is-pending");
      const bodyEl = row.querySelector(".lsc-body");
      if (ev.event_id && bodyEl) st.byId.set(ev.event_id, { bodyEl, row });
    }
    st.pendingTxns.delete(txn);
    st.txnNodes.delete(txn);
    if (ev.event_id) st.seen.add(ev.event_id);
    return;
  }

  // Edits (m.replace): update the original bubble in place when we have it.
  const rel = ev.content["m.relates_to"];
  const newContent = ev.content["m.new_content"];
  if (rel && rel.rel_type === "m.replace" && newContent) {
    if (ev.event_id) st.seen.add(ev.event_id);
    const target = st.byId.get(rel.event_id);
    if (target && typeof newContent.body === "string") {
      target.bodyEl.textContent = newContent.body;
      if (!target.row.querySelector(".lsc-edited")) {
        const tag = el("span", "lsc-edited", tr("edited"));
        target.bodyEl.insertAdjacentElement("afterend", tag);
      }
      return;
    }
    // Original is outside our window — render the edited text as a message.
    ev = { ...ev, content: newContent };
  }

  const body = bodyOf(ev.content);
  if (!body) { if (ev.event_id) st.seen.add(ev.event_id); return; } // redacted / empty

  if (ev.event_id) st.seen.add(ev.event_id);
  const emptyBox = st.ui.list.querySelector(".lsc-empty");
  if (emptyBox) emptyBox.remove();

  const row = renderRow(st, {
    sender: ev.sender,
    ts: ev.origin_server_ts || Date.now(),
    body,
    msgtype: ev.content.msgtype || "m.text",
    eventId: ev.event_id || null,
    pending: false
  });
  st.ui.list.appendChild(row);

  if (live) {
    const own = ev.sender === st.ctx.matrix.userId;
    if (own || !st.scrolledUp) scrollToBottom(st, true);
    else showJump(st);
  }
}

function renderRow(st, m) {
  const { tr } = st;
  const own = m.sender === st.ctx.matrix.userId;
  const grouped = !!(st.last && st.last.sender === m.sender &&
    (m.ts - st.last.ts) < 5 * 60_000);
  st.last = { sender: m.sender, ts: m.ts };

  const row = el("div", "lsc-msg" + (own ? " is-own" : "") + (grouped ? " is-grouped" : "") +
    (m.pending ? " is-pending" : ""));

  if (!own) {
    const ava = el("span", "lsc-ava");
    if (!grouped) {
      const name = displayNameFor(st, m.sender);
      ava.style.background = `hsl(${hueFor(m.sender)} 62% 46%)`;
      ava.textContent = (name[0] || "?").toUpperCase();
      trackNameNode(st, m.sender, ava, "initial");
    } else {
      ava.classList.add("is-spacer");
    }
    row.appendChild(ava);
  }

  const stack = el("div", "lsc-stack");
  if (!grouped) {
    const meta = el("div", "lsc-meta");
    if (!own) {
      const nameEl = el("span", "lsc-name", displayNameFor(st, m.sender));
      nameEl.style.color = `hsl(${hueFor(m.sender)} 70% 66%)`;
      trackNameNode(st, m.sender, nameEl, "name");
      meta.appendChild(nameEl);
    }
    const timeEl = el("span", "lsc-time", relTime(m.ts, tr, st.lang));
    timeEl.dataset.lscTs = String(m.ts);
    meta.appendChild(timeEl);
    stack.appendChild(meta);
  }

  const bubble = el("div", "lsc-bubble");
  if (m.msgtype === "m.emote") bubble.classList.add("is-emote");
  if (m.msgtype === "m.notice") bubble.classList.add("is-notice");
  const glyph = MEDIA_GLYPH[m.msgtype];
  if (glyph) {
    const chip = el("span", "lsc-media-glyph", glyph);
    chip.setAttribute("aria-hidden", "true");
    bubble.appendChild(chip);
  }
  const bodyEl = el("span", "lsc-body", m.body); // textContent — escaped by construction
  bubble.appendChild(bodyEl);
  stack.appendChild(bubble);
  row.appendChild(stack);

  if (m.eventId) st.byId.set(m.eventId, { bodyEl, row });
  return row;
}

/* -- display names: cached, lazily resolved, DOM patched on arrival --------- */
function displayNameFor(st, userId) {
  if (st.profiles.has(userId)) return st.profiles.get(userId);
  const fallback = localpart(userId);
  st.profiles.set(userId, fallback);
  api(st, `/_matrix/client/v3/profile/${enc(userId)}/displayname`)
    .then((r) => {
      if (!st.alive || !r || !r.displayname) return;
      st.profiles.set(userId, r.displayname);
      const nodes = st.nameNodes.get(userId);
      if (nodes) nodes.forEach(({ node, kind }) => {
        if (!node.isConnected) return;
        node.textContent = kind === "initial"
          ? (r.displayname[0] || "?").toUpperCase()
          : r.displayname;
      });
    })
    .catch(() => { /* keep localpart */ });
  return fallback;
}

function trackNameNode(st, userId, node, kind) {
  let set = st.nameNodes.get(userId);
  if (!set) { set = new Set(); st.nameNodes.set(userId, set); }
  set.add({ node, kind });
}

/* ===========================================================================
   Sending — optimistic row, txn dedupe with the sync echo, tap-to-retry.
=========================================================================== */
function sendMessage(st, text) {
  const room = st.ctx.matrix.room;
  const txn = "lsc" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  st.pendingTxns.add(txn);

  const row = renderRow(st, {
    sender: st.ctx.matrix.userId,
    ts: Date.now(),
    body: text,
    msgtype: "m.text",
    eventId: null,
    pending: true
  });
  st.txnNodes.set(txn, row);
  st.ui.list.appendChild(row);
  scrollToBottom(st, true);

  api(st, `/_matrix/client/v3/rooms/${enc(room)}/send/m.room.message/${enc(txn)}`, {
    method: "PUT",
    body: JSON.stringify({ msgtype: "m.text", body: text })
  }).then((r) => {
    if (!st.alive) return;
    if (st.pendingTxns.has(txn)) { // echo hasn't confirmed it yet
      row.classList.remove("is-pending");
      if (r && r.event_id) {
        st.seen.add(r.event_id);
        const bodyEl = row.querySelector(".lsc-body");
        if (bodyEl) st.byId.set(r.event_id, { bodyEl, row });
      }
      st.pendingTxns.delete(txn);
      st.txnNodes.delete(txn);
    }
  }).catch((e) => {
    if (!st.alive) return;
    st.pendingTxns.delete(txn);
    st.txnNodes.delete(txn);
    if (e && e.auth) return sessionExpired(st);
    row.classList.remove("is-pending");
    row.classList.add("is-failed");
    row.title = st.tr("msg.failed");
    const retry = () => {
      row.removeEventListener("click", retry);
      row.remove();
      st.last = null; // don't group against a removed row
      sendMessage(st, text);
    };
    row.addEventListener("click", retry);
  });
}

/* ===========================================================================
   Scrolling helpers
=========================================================================== */
function scrollToBottom(st, smooth) {
  const { scroll } = st.ui;
  if (!scroll) return;
  scroll.scrollTo({ top: scroll.scrollHeight, behavior: smooth && !reducedMotion() ? "smooth" : "auto" });
}
function showJump(st) {
  st.unseen++;
  st.ui.jumpTxt.textContent = st.tr("jump.new") + (st.unseen > 1 ? ` · ${st.unseen}` : "");
  st.ui.jump.hidden = false;
}
function hideJump(st) {
  st.unseen = 0;
  if (st.ui.jump) st.ui.jump.hidden = true;
}
