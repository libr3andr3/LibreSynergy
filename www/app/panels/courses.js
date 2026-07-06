/* ============================================================================
   LibreSynergy hub panel — panels/courses.js
   Compact native course catalog for the Learn view: browse the Frappe LMS
   catalog right in the hub; enrolling + lessons happen in the full LMS
   (each card opens out). Panel module contract:
       export mount(root, ctx)   — render into root
       export unmount(root)      — cleanup on view switch
       export expand(ctx)        — open the full classroom
   Self-contained: injects its own stylesheet (courses.css next to this file),
   all chrome colour flows from the --ls-* brand tokens, no frameworks.

   Endpoints (verified on node):
     GET  <learn>/api/method/lms.lms.utils.get_courses
          -> {"message":[{name,title,short_introduction,image,tags,
                          card_gradient,paid_course,price,lessons,…}]}
     Course page: <learn>/lms/courses/<name>       (/courses/<name> 404s)
     Same-origin fallback (edge proxy, for when the LMS answers without CORS
     headers): GET /hub-api/lms/get_courses

   The learn base URL is resolved at runtime (ctx.endpoints → window.LS.urls
   baked by apply-branding → a templated __LS_LEARN__ literal, ignored while
   unrendered) so this file ships identically for every operator.
   ============================================================================ */

const CSS_ID = "ls-panel-courses-css";
const CACHE_KEY = "ls_courses_cache_v1";
const CACHE_TTL = 5 * 60 * 1000; // cached catalog is served instantly, then revalidated
const SKELETONS = 6;

/* =========================================================================
   i18n — en / es / fr, same convention as the shell. ctx.t() wins whenever
   the shell already knows a key (it returns the key itself when it doesn't).
   ========================================================================= */
const STRINGS = {
  en: {
    "courses.kicker": "Classroom",
    "courses.title": "Keep learning",
    "courses.count_one": "course", "courses.count_many": "courses",
    "courses.expand": "Browse all in the classroom",
    "courses.open": "Open course",
    "courses.featured": "Featured",
    "courses.upcoming": "Coming soon",
    "courses.lesson_one": "lesson", "courses.lessons": "lessons",
    "courses.enrolled": "enrolled",
    "courses.by": "By",
    "courses.empty_title": "The classroom is quiet",
    "courses.empty_body": "No courses have been published yet. Check back soon — new classes land here first.",
    "courses.error_title": "Couldn’t reach the classroom",
    "courses.error_body": "The course catalog didn’t answer. Check your connection and try again.",
    "courses.retry": "Try again"
  },
  es: {
    "courses.kicker": "Aula",
    "courses.title": "Sigue aprendiendo",
    "courses.count_one": "curso", "courses.count_many": "cursos",
    "courses.expand": "Ver todo en el aula",
    "courses.open": "Abrir curso",
    "courses.featured": "Destacado",
    "courses.upcoming": "Próximamente",
    "courses.lesson_one": "lección", "courses.lessons": "lecciones",
    "courses.enrolled": "inscritos",
    "courses.by": "Por",
    "courses.empty_title": "El aula está en calma",
    "courses.empty_body": "Aún no hay cursos publicados. Vuelve pronto — las clases nuevas llegan aquí primero.",
    "courses.error_title": "No pudimos conectar con el aula",
    "courses.error_body": "El catálogo de cursos no respondió. Revisa tu conexión e inténtalo de nuevo.",
    "courses.retry": "Reintentar"
  },
  fr: {
    "courses.kicker": "Salle de classe",
    "courses.title": "Continuez d’apprendre",
    "courses.count_one": "cours", "courses.count_many": "cours",
    "courses.expand": "Tout voir dans la salle de classe",
    "courses.open": "Ouvrir le cours",
    "courses.featured": "À la une",
    "courses.upcoming": "Bientôt",
    "courses.lesson_one": "leçon", "courses.lessons": "leçons",
    "courses.enrolled": "inscrits",
    "courses.by": "Par",
    "courses.empty_title": "La salle de classe est calme",
    "courses.empty_body": "Aucun cours publié pour l’instant. Revenez bientôt — les nouvelles classes arrivent ici en premier.",
    "courses.error_title": "Impossible de joindre la salle de classe",
    "courses.error_body": "Le catalogue de cours n’a pas répondu. Vérifiez votre connexion et réessayez.",
    "courses.retry": "Réessayer"
  }
};

function pickLang(ctx) {
  const l = (ctx && ctx.lang) || (navigator.language || "en").slice(0, 2).toLowerCase();
  return STRINGS[l] ? l : "en";
}

function makeT(ctx) {
  const table = STRINGS[pickLang(ctx)];
  return (key) => {
    if (ctx && typeof ctx.t === "function") {
      const v = ctx.t(key);
      if (v != null && v !== key) return v; // shell knows this key
    }
    return table[key] ?? STRINGS.en[key] ?? key;
  };
}

/* =========================================================================
   Endpoint resolution — runtime, brand-agnostic.
   ========================================================================= */
function learnBase(ctx) {
  const ep = (ctx && ctx.endpoints) || {};
  const ls = (typeof window !== "undefined" && window.LS && window.LS.urls) || {};
  const candidates = [
    ep.learn, ep.lms, ep.courses,
    ls.learn,
    "https://__LS_LEARN__" // substituted only if this file is ever template-rendered
  ];
  for (let c of candidates) {
    if (typeof c !== "string" || !c.trim()) continue;
    c = c.trim();
    if (c.includes("__LS_")) continue; // unrendered placeholder — skip
    if (!/^https?:\/\//i.test(c)) c = "https://" + c;
    return c.replace(/\/+$/, "");
  }
  return "";
}

const courseUrl = (base, name) =>
  (base || "") + "/lms/courses/" + encodeURIComponent(name);

function assetUrl(base, src) {
  if (typeof src !== "string" || !src.trim()) return "";
  const s = src.trim();
  if (/^https?:\/\//i.test(s)) return s;
  if (!base) return "";
  return base + (s.startsWith("/") ? s : "/" + s);
}

/* =========================================================================
   Data — direct LMS API first; if that fails (no CORS headers from the LMS,
   offline, …) fall back to the same-origin edge proxy /hub-api/lms/get_courses.
   A content-type guard rejects the SPA HTML fallback that unknown hub paths
   currently return, so a missing proxy degrades to the error state.
   ========================================================================= */
async function fetchCourses(base, signal) {
  const urls = [];
  if (base) urls.push(base + "/api/method/lms.lms.utils.get_courses");
  urls.push("/hub-api/lms/get_courses");

  let lastErr = null;
  for (const url of urls) {
    try {
      const res = await fetch(url, {
        signal,
        cache: "no-store",
        headers: { Accept: "application/json" }
      });
      if (!res.ok) throw new Error("HTTP " + res.status + " from " + url);
      const ct = res.headers.get("content-type") || "";
      if (!ct.includes("json")) throw new Error("non-JSON response from " + url);
      const data = await res.json();
      const list = Array.isArray(data) ? data
        : (data && Array.isArray(data.message)) ? data.message
        : null;
      if (!list) throw new Error("unexpected payload shape from " + url);
      return list.filter((c) => c && c.name && (c.published === undefined || c.published));
    } catch (e) {
      if (e && e.name === "AbortError") throw e;
      lastErr = e;
    }
  }
  throw lastErr || new Error("courses unavailable");
}

function readCache() {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const { at, list } = JSON.parse(raw);
    if (!Array.isArray(list) || Date.now() - at > CACHE_TTL) return null;
    return list;
  } catch { return null; }
}
function writeCache(list) {
  try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), list })); }
  catch { /* storage full / private mode — fine */ }
}

/* =========================================================================
   Gradients — keyed off the LMS card_gradient value (course content chosen by
   the operator, not brand chrome). Unknown values hash into a stable hue pair.
   ========================================================================= */
const GRADIENT_NAMES = {
  red:    ["#f2555f", "#8f1d3c"],
  orange: ["#ff9d4d", "#c2410c"],
  amber:  ["#fbbf24", "#92400e"],
  yellow: ["#fbc94b", "#a16207"],
  green:  ["#4ade80", "#166534"],
  teal:   ["#2dd4bf", "#0f5c5a"],
  cyan:   ["#22d3ee", "#155e75"],
  blue:   ["#60a5fa", "#1e3a8a"],
  indigo: ["#818cf8", "#312e81"],
  violet: ["#a78bfa", "#4c1d95"],
  purple: ["#c084fc", "#581c87"],
  pink:   ["#f472b6", "#831843"],
  gray:   ["#9ca3af", "#374151"],
  grey:   ["#9ca3af", "#374151"],
  black:  ["#52525b", "#18181b"]
};

function gradientFor(key) {
  const k = String(key || "").trim().toLowerCase();
  const named = GRADIENT_NAMES[k];
  if (named) return `linear-gradient(135deg, ${named[0]}, ${named[1]})`;
  const s = k || "course";
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  const h1 = h % 360, h2 = (h1 + 46) % 360;
  return `linear-gradient(135deg, hsl(${h1} 60% 48%), hsl(${h2} 68% 30%))`;
}

/* =========================================================================
   Tiny DOM helpers — all API text goes through textContent (never innerHTML),
   so course data can't inject markup.
   ========================================================================= */
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function svgIcon(paths, cls) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", cls || "crs-ico");
  svg.setAttribute("aria-hidden", "true");
  for (const d of paths) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    svg.appendChild(p);
  }
  return svg;
}
const icoExternal = () => svgIcon([
  "M14 5h5v5", "M19 5l-8 8", "M19 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4"
]);
const icoLearn = () => svgIcon([
  "M12 4 2 9l10 5 10-5-10-5Z", "M6 11.5V16c0 1.66 2.69 3 6 3s6-1.34 6-3v-4.5M22 9v6"
], "crs-ico crs-ico-sm");

function parseTags(tags) {
  if (!tags) return [];
  if (Array.isArray(tags)) return tags.map((s) => String(s).trim()).filter(Boolean);
  return String(tags).split(",").map((s) => s.trim()).filter(Boolean);
}

function priceLabel(c, lang) {
  if (!c.paid_course) return "";
  if (typeof c.price === "string" && c.price.trim()) return c.price.trim();
  const amount = Number(c.course_price);
  if (!isFinite(amount) || amount <= 0) return "";
  try {
    return new Intl.NumberFormat(lang, {
      style: "currency", currency: c.currency || "USD", maximumFractionDigits: 0
    }).format(amount);
  } catch { return `${amount} ${c.currency || "USD"}`; }
}

function metaText(c, t) {
  const parts = [];
  const lessons = Number(c.lessons);
  if (isFinite(lessons) && lessons > 0) {
    parts.push(`${lessons} ${t(lessons === 1 ? "courses.lesson_one" : "courses.lessons")}`);
  }
  const enrolled = Number(c.enrollments);
  if (isFinite(enrolled) && enrolled > 0) parts.push(`${enrolled} ${t("courses.enrolled")}`);
  const rating = parseFloat(c.rating);
  if (isFinite(rating) && rating > 0) parts.push(`★ ${rating.toFixed(1)}`);
  if (!parts.length && Array.isArray(c.instructors) && c.instructors.length) {
    const first = c.instructors.find((i) => i && (i.full_name || i.first_name));
    if (first) parts.push(`${t("courses.by")} ${first.full_name || first.first_name}`);
  }
  return parts.join(" · ");
}

/* =========================================================================
   Rendering
   ========================================================================= */
function badge(text, variant) {
  return el("span", "crs-badge" + (variant ? " crs-badge--" + variant : ""), text);
}

function buildCard(c, base, t, lang, index) {
  const a = el("a", "crs-card");
  a.href = courseUrl(base, c.name);
  a.target = "_blank";
  a.rel = "noopener";
  a.setAttribute("role", "listitem");
  a.setAttribute("aria-label", `${c.title || c.name} — ${t("courses.open")}`);
  a.style.animationDelay = `${Math.min(index, 8) * 45}ms`;

  /* media: image when the LMS has one, else a gradient keyed off card_gradient */
  const media = el("div", "crs-media");
  media.style.background = gradientFor(c.card_gradient || c.title || c.name);
  const mono = el("span", "crs-mono", (c.title || c.name || "•").trim().charAt(0).toUpperCase());
  mono.setAttribute("aria-hidden", "true");
  media.appendChild(mono);
  const imgSrc = assetUrl(base, c.image);
  if (imgSrc) {
    const img = el("img", "crs-img");
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    img.referrerPolicy = "no-referrer";
    img.addEventListener("error", () => img.remove()); // gradient shows through
    img.src = imgSrc;
    media.appendChild(img);
  }
  const badges = el("div", "crs-badges");
  if (c.upcoming) badges.appendChild(badge(t("courses.upcoming"), "soon"));
  if (c.featured) badges.appendChild(badge("★ " + t("courses.featured"), "gold"));
  const price = priceLabel(c, lang);
  if (price) badges.appendChild(badge(price, "price"));
  if (badges.childElementCount) media.appendChild(badges);
  a.appendChild(media);

  /* body */
  const body = el("div", "crs-body");
  body.appendChild(el("h3", "crs-name", c.title || c.name));
  const intro = String(c.short_introduction || "").trim();
  if (intro) body.appendChild(el("p", "crs-intro", intro));
  const tags = parseTags(c.tags).slice(0, 3);
  if (tags.length) {
    const row = el("div", "crs-tags");
    for (const tag of tags) row.appendChild(el("span", "crs-tag", tag));
    body.appendChild(row);
  }
  a.appendChild(body);

  /* foot: meta + the "Open course ↗" affordance (enroll lives in the full LMS) */
  const foot = el("div", "crs-foot");
  foot.appendChild(el("span", "crs-meta", metaText(c, t)));
  const open = el("span", "crs-open", t("courses.open"));
  open.appendChild(icoExternal());
  foot.appendChild(open);
  a.appendChild(foot);

  return a;
}

function renderSkeleton(grid) {
  grid.setAttribute("aria-busy", "true");
  grid.innerHTML = "";
  for (let i = 0; i < SKELETONS; i++) {
    const card = el("div", "crs-card is-skel");
    card.setAttribute("aria-hidden", "true");
    card.appendChild(el("div", "crs-media"));
    const body = el("div", "crs-body");
    for (const w of ["72%", "94%", "58%"]) {
      const line = el("span", "crs-skel");
      line.style.width = w;
      body.appendChild(line);
    }
    card.appendChild(body);
    const foot = el("div", "crs-foot");
    const line = el("span", "crs-skel");
    line.style.width = "38%";
    foot.appendChild(line);
    card.appendChild(foot);
    grid.appendChild(card);
  }
}

function renderState(grid, kind, t, action) {
  grid.removeAttribute("aria-busy");
  grid.innerHTML = "";
  const box = el("div", "crs-state crs-state--" + kind);
  const orb = el("div", "crs-state-orb");
  orb.setAttribute("aria-hidden", "true");
  orb.appendChild(icoLearn());
  box.appendChild(orb);
  box.appendChild(el("h3", "crs-state-title", t(`courses.${kind}_title`)));
  box.appendChild(el("p", "crs-state-body", t(`courses.${kind}_body`)));
  if (action) {
    const btn = el("button", "crs-btn crs-btn--brand", action.label);
    btn.type = "button";
    btn.addEventListener("click", action.run);
    box.appendChild(btn);
  }
  grid.appendChild(box);
}

function renderCourses(grid, list, base, t, lang) {
  grid.removeAttribute("aria-busy");
  grid.innerHTML = "";
  if (!list.length) { renderState(grid, "empty", t); return; }
  // featured first, otherwise keep the LMS ordering (stable sort)
  const ordered = list.slice().sort((a, b) => (b.featured ? 1 : 0) - (a.featured ? 1 : 0));
  ordered.forEach((c, i) => grid.appendChild(buildCard(c, base, t, lang, i)));
}

/* =========================================================================
   Stylesheet injection — once per document, resolved relative to this module
   so /app/panels/courses.css loads wherever the hub is mounted.
   ========================================================================= */
function injectCSS() {
  if (document.getElementById(CSS_ID)) return;
  const link = document.createElement("link");
  link.id = CSS_ID;
  link.rel = "stylesheet";
  link.href = new URL("./courses.css", import.meta.url).href;
  document.head.appendChild(link);
}

/* =========================================================================
   Lifecycle
   ========================================================================= */
const state = new WeakMap();

export function mount(root, ctx) {
  injectCSS();
  const t = makeT(ctx);
  const lang = pickLang(ctx);
  const base = learnBase(ctx);

  root.classList.add("crs");
  root.innerHTML = "";

  /* header — kicker/title/count + "Browse all in the classroom ↗" */
  const head = el("header", "crs-head");
  const copy = el("div", "crs-head-copy");
  const kicker = el("p", "crs-kicker");
  kicker.appendChild(icoLearn());
  kicker.appendChild(el("span", null, t("courses.kicker")));
  copy.appendChild(kicker);
  copy.appendChild(el("h2", "crs-title", t("courses.title")));
  const count = el("p", "crs-count");
  count.hidden = true;
  copy.appendChild(count);
  head.appendChild(copy);

  const expandBtn = el("button", "crs-btn crs-btn--ghost crs-expand", t("courses.expand"));
  expandBtn.type = "button";
  expandBtn.appendChild(icoExternal());
  expandBtn.addEventListener("click", () => expand(ctx));
  head.appendChild(expandBtn);
  root.appendChild(head);

  /* grid */
  const grid = el("div", "crs-grid");
  grid.setAttribute("role", "list");
  root.appendChild(grid);

  const st = { ac: null, dead: false, lastJSON: "" };
  state.set(root, st);

  const paint = (list) => {
    const json = JSON.stringify(list);
    if (json === st.lastJSON) return; // silent revalidate found nothing new
    st.lastJSON = json;
    renderCourses(grid, list, base, t, lang);
    count.hidden = false;
    count.textContent = `${list.length} ${t(list.length === 1 ? "courses.count_one" : "courses.count_many")}`;
  };

  const load = async (opts) => {
    const silent = !!(opts && opts.silent);
    if (st.dead) return;
    if (st.ac) st.ac.abort();
    st.ac = new AbortController();
    if (!silent) { count.hidden = true; renderSkeleton(grid); }
    try {
      const list = await fetchCourses(base, st.ac.signal);
      if (st.dead) return;
      writeCache(list);
      paint(list);
    } catch (e) {
      if (st.dead || (e && e.name === "AbortError")) return;
      if (!silent) renderState(grid, "error", t, { label: t("courses.retry"), run: () => load() });
    }
  };

  const cached = readCache();
  if (cached) { paint(cached); load({ silent: true }); }
  else load();
}

export function unmount(root) {
  const st = state.get(root);
  if (st) {
    st.dead = true;
    if (st.ac) st.ac.abort();
    state.delete(root);
  }
  root.classList.remove("crs");
  root.innerHTML = "";
}

export function expand(ctx) {
  const base = learnBase(ctx);
  if (ctx && typeof ctx.onExpand === "function") {
    ctx.onExpand(base || "learn");
    return;
  }
  if (base) window.open(base, "_blank", "noopener");
}

export default { mount, unmount, expand };
