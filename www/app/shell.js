/* ============================================================================
   LibreSynergy app shell — shell.js
   Brand-agnostic: reads all operator values from window.LS (baked into
   index.html by apply-branding.sh), so this file ships identically for every
   operator and caches hard. No frameworks, no network deps beyond the
   OwnCast status poll. ~ vanilla ES2020.
   ============================================================================ */
(() => {
  "use strict";

  const LS = window.LS || { brand: "", tagline: "", poweredBy: "", urls: {} };
  const $  = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  /* =========================================================================
     i18n — en / es / fr picked from navigator.language, default en.
     ========================================================================= */
  const STRINGS = {
    en: {
      "a11y.skip": "Skip to content",
      "nav.home": "Home", "nav.chat": "Chat", "nav.learn": "Learn",
      "nav.meet": "Meet", "nav.live": "Live", "nav.premium": "Premium",
      "topbar.search": "Search", "topbar.notifications": "Notifications", "topbar.account": "Account",
      "common.new_tab": "Open in a new tab", "common.close": "Close",
      "common.got_it": "Got it", "common.powered_by": "Powered by",
      "greet.morning": "Good morning", "greet.afternoon": "Good afternoon",
      "greet.evening": "Good evening", "greet.night": "Up late?",
      "home.kicker": "Welcome back",
      "home.hero_line": "Chat, classes, rooms and live — your whole community, one app.",
      "home.quick_title": "Jump in",
      "home.activity_title": "What’s happening",
      "live.now": "Live now",
      "live.offline_title": "The stage is quiet",
      "live.offline_body": "Nobody is streaming right now. This lights up the second a stream starts.",
      "live.watch": "Watch", "live.viewers": "watching",
      "qa.chat_t": "Talk to everyone", "qa.chat_b": "Rooms, DMs and threads — encrypted, yours.",
      "qa.learn_t": "Keep learning", "qa.learn_b": "Courses and lessons from your community.",
      "qa.meet_t": "Meet face to face", "qa.meet_b": "Instant video rooms — no account juggling.",
      "qa.live_t": "Watch the stream", "qa.live_b": "Live shows, events and drop-ins.",
      "qa.premium_t": "Go Premium", "qa.premium_b": "Unlock member rooms, courses and events.",
      "panel.opens": "Opens in a new tab — your sign-in carries over.",
      "panel.chat_title": "Your community chat",
      "panel.chat_body": "Every room, DM and thread lives on your own Matrix server — end-to-end encrypted. Nobody reads it but you.",
      "panel.chat_f1": "Encrypted rooms & DMs", "panel.chat_f2": "Threads, reactions, media",
      "panel.chat_f3": "Your data, on your server", "panel.chat_cta": "Open Chat",
      "panel.learn_title": "The classroom",
      "panel.learn_body": "Structured courses from your community — video lessons, quizzes, and progress that follows you across devices.",
      "panel.learn_f1": "Courses & cohorts", "panel.learn_f2": "Progress tracking",
      "panel.learn_f3": "Certificates", "panel.learn_cta": "Open Learn",
      "panel.premium_title": "Premium membership",
      "panel.premium_body": "Back the community you love — and unlock everything it makes.",
      "panel.premium_f1": "Members-only rooms", "panel.premium_f2": "All premium courses",
      "panel.premium_f3": "Live member events", "panel.premium_f4": "Cancel anytime",
      "panel.premium_cta": "Upgrade now",
      "install.button": "Install", "install.done": "Installed — see you on your home screen!",
      "ios.title": "Add to your Home Screen",
      "ios.s1": "Tap the Share button", "ios.s2": "Choose “Add to Home Screen”",
      "ios.s3": "Open it from your home screen",
      "search.placeholder": "Search apps, actions…",
      "search.hint": "↑↓ to navigate · ↵ to open · esc to close",
      "search.empty": "No matches — try another word.",
      "search.account": "Account & profile", "search.install": "Install the app",
      "search.hint_view": "View", "search.hint_link": "New tab",
      "bell.empty": "You’re all caught up.",
      "net.offline": "You’re offline — some things may be unavailable.",
      "net.online": "Back online.",
      "act.1": "A new member just joined the community", "act.t1": "just now",
      "act.2": "New lesson published in the classroom", "act.t2": "today",
      "act.3": "The next live session is being scheduled", "act.t3": "this week",
      "act.4": "Fresh rooms are open in chat", "act.t4": "this week"
    },
    es: {
      "a11y.skip": "Saltar al contenido",
      "nav.home": "Inicio", "nav.chat": "Chat", "nav.learn": "Aprender",
      "nav.meet": "Reunión", "nav.live": "En vivo", "nav.premium": "Premium",
      "topbar.search": "Buscar", "topbar.notifications": "Notificaciones", "topbar.account": "Cuenta",
      "common.new_tab": "Abrir en una pestaña nueva", "common.close": "Cerrar",
      "common.got_it": "Entendido", "common.powered_by": "Con tecnología de",
      "greet.morning": "Buenos días", "greet.afternoon": "Buenas tardes",
      "greet.evening": "Buenas noches", "greet.night": "¿Trasnochando?",
      "home.kicker": "Qué bueno verte",
      "home.hero_line": "Chat, clases, salas y directos — toda tu comunidad en una sola app.",
      "home.quick_title": "Entra ya",
      "home.activity_title": "Qué está pasando",
      "live.now": "En vivo",
      "live.offline_title": "El escenario está en calma",
      "live.offline_body": "Nadie está transmitiendo ahora. Esto se enciende en cuanto empiece un directo.",
      "live.watch": "Ver", "live.viewers": "viendo",
      "qa.chat_t": "Habla con todos", "qa.chat_b": "Salas, mensajes e hilos — cifrados y tuyos.",
      "qa.learn_t": "Sigue aprendiendo", "qa.learn_b": "Cursos y lecciones de tu comunidad.",
      "qa.meet_t": "Cara a cara", "qa.meet_b": "Salas de video al instante, sin líos de cuentas.",
      "qa.live_t": "Mira el directo", "qa.live_b": "Shows en vivo, eventos y visitas.",
      "qa.premium_t": "Hazte Premium", "qa.premium_b": "Desbloquea salas, cursos y eventos de miembros.",
      "panel.opens": "Se abre en una pestaña nueva — tu sesión te acompaña.",
      "panel.chat_title": "El chat de tu comunidad",
      "panel.chat_body": "Cada sala, mensaje e hilo vive en tu propio servidor Matrix — cifrado de extremo a extremo. Nadie más lo lee.",
      "panel.chat_f1": "Salas y mensajes cifrados", "panel.chat_f2": "Hilos, reacciones, multimedia",
      "panel.chat_f3": "Tus datos, en tu servidor", "panel.chat_cta": "Abrir el chat",
      "panel.learn_title": "El aula",
      "panel.learn_body": "Cursos estructurados de tu comunidad — lecciones en video, cuestionarios y progreso que te sigue en todos tus dispositivos.",
      "panel.learn_f1": "Cursos y cohortes", "panel.learn_f2": "Seguimiento de progreso",
      "panel.learn_f3": "Certificados", "panel.learn_cta": "Abrir el aula",
      "panel.premium_title": "Membresía Premium",
      "panel.premium_body": "Apoya a la comunidad que amas — y desbloquea todo lo que crea.",
      "panel.premium_f1": "Salas solo para miembros", "panel.premium_f2": "Todos los cursos premium",
      "panel.premium_f3": "Eventos en vivo para miembros", "panel.premium_f4": "Cancela cuando quieras",
      "panel.premium_cta": "Mejorar ahora",
      "install.button": "Instalar", "install.done": "¡Instalada! Nos vemos en tu pantalla de inicio.",
      "ios.title": "Añádela a tu pantalla de inicio",
      "ios.s1": "Toca el botón Compartir", "ios.s2": "Elige “Añadir a pantalla de inicio”",
      "ios.s3": "Ábrela desde tu pantalla de inicio",
      "search.placeholder": "Buscar aplicaciones, acciones…",
      "search.hint": "↑↓ para navegar · ↵ para abrir · esc para cerrar",
      "search.empty": "Sin resultados — prueba otra palabra.",
      "search.account": "Cuenta y perfil", "search.install": "Instalar la app",
      "search.hint_view": "Ver", "search.hint_link": "Pestaña nueva",
      "bell.empty": "Estás al día.",
      "net.offline": "Sin conexión — puede que algo no esté disponible.",
      "net.online": "De vuelta en línea.",
      "act.1": "Un nuevo miembro se unió a la comunidad", "act.t1": "ahora mismo",
      "act.2": "Nueva lección publicada en el aula", "act.t2": "hoy",
      "act.3": "Se está programando la próxima sesión en vivo", "act.t3": "esta semana",
      "act.4": "Hay salas nuevas abiertas en el chat", "act.t4": "esta semana"
    },
    fr: {
      "a11y.skip": "Aller au contenu",
      "nav.home": "Accueil", "nav.chat": "Chat", "nav.learn": "Apprendre",
      "nav.meet": "Réunion", "nav.live": "Direct", "nav.premium": "Premium",
      "topbar.search": "Rechercher", "topbar.notifications": "Notifications", "topbar.account": "Compte",
      "common.new_tab": "Ouvrir dans un nouvel onglet", "common.close": "Fermer",
      "common.got_it": "Compris", "common.powered_by": "Propulsé par",
      "greet.morning": "Bonjour", "greet.afternoon": "Bon après-midi",
      "greet.evening": "Bonsoir", "greet.night": "Encore debout ?",
      "home.kicker": "Ravi de vous revoir",
      "home.hero_line": "Chat, cours, salles et direct — toute votre communauté, une seule app.",
      "home.quick_title": "Plongez",
      "home.activity_title": "Quoi de neuf",
      "live.now": "En direct",
      "live.offline_title": "La scène est calme",
      "live.offline_body": "Personne ne diffuse pour l’instant. Tout s’allume dès qu’un direct démarre.",
      "live.watch": "Regarder", "live.viewers": "spectateurs",
      "qa.chat_t": "Parlez à tout le monde", "qa.chat_b": "Salons, messages et fils — chiffrés, à vous.",
      "qa.learn_t": "Continuez d’apprendre", "qa.learn_b": "Cours et leçons de votre communauté.",
      "qa.meet_t": "En face à face", "qa.meet_b": "Salles vidéo instantanées, sans jongler de comptes.",
      "qa.live_t": "Regardez le direct", "qa.live_b": "Émissions, événements et passages en direct.",
      "qa.premium_t": "Passez Premium", "qa.premium_b": "Débloquez salons, cours et événements membres.",
      "panel.opens": "S’ouvre dans un nouvel onglet — votre session vous suit.",
      "panel.chat_title": "Le chat de votre communauté",
      "panel.chat_body": "Chaque salon, message et fil vit sur votre propre serveur Matrix — chiffré de bout en bout. Personne d’autre ne le lit.",
      "panel.chat_f1": "Salons et messages chiffrés", "panel.chat_f2": "Fils, réactions, médias",
      "panel.chat_f3": "Vos données, sur votre serveur", "panel.chat_cta": "Ouvrir le chat",
      "panel.learn_title": "La salle de classe",
      "panel.learn_body": "Des cours structurés de votre communauté — leçons vidéo, quiz et progression qui vous suit sur tous vos appareils.",
      "panel.learn_f1": "Cours et cohortes", "panel.learn_f2": "Suivi de progression",
      "panel.learn_f3": "Certificats", "panel.learn_cta": "Ouvrir les cours",
      "panel.premium_title": "Adhésion Premium",
      "panel.premium_body": "Soutenez la communauté que vous aimez — et débloquez tout ce qu’elle crée.",
      "panel.premium_f1": "Salons réservés aux membres", "panel.premium_f2": "Tous les cours premium",
      "panel.premium_f3": "Événements membres en direct", "panel.premium_f4": "Annulez à tout moment",
      "panel.premium_cta": "Passer Premium",
      "install.button": "Installer", "install.done": "Installée — rendez-vous sur votre écran d’accueil !",
      "ios.title": "Ajoutez-la à votre écran d’accueil",
      "ios.s1": "Touchez le bouton Partager", "ios.s2": "Choisissez « Sur l’écran d’accueil »",
      "ios.s3": "Ouvrez-la depuis votre écran d’accueil",
      "search.placeholder": "Rechercher applis, actions…",
      "search.hint": "↑↓ pour naviguer · ↵ pour ouvrir · échap pour fermer",
      "search.empty": "Aucun résultat — essayez un autre mot.",
      "search.account": "Compte et profil", "search.install": "Installer l’app",
      "search.hint_view": "Voir", "search.hint_link": "Nouvel onglet",
      "bell.empty": "Vous êtes à jour.",
      "net.offline": "Hors ligne — certaines choses peuvent être indisponibles.",
      "net.online": "De retour en ligne.",
      "act.1": "Un nouveau membre vient de rejoindre la communauté", "act.t1": "à l’instant",
      "act.2": "Nouvelle leçon publiée dans la salle de classe", "act.t2": "aujourd’hui",
      "act.3": "La prochaine session en direct se prépare", "act.t3": "cette semaine",
      "act.4": "De nouveaux salons sont ouverts dans le chat", "act.t4": "cette semaine"
    }
  };

  const lang = (() => {
    const l = (navigator.language || "en").slice(0, 2).toLowerCase();
    return STRINGS[l] ? l : "en";
  })();
  const t = (key) => STRINGS[lang][key] ?? STRINGS.en[key] ?? key;

  function applyI18n() {
    document.documentElement.lang = lang;
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
    $$("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
  }

  /* =========================================================================
     Greeting (time-of-day, refreshed each minute)
     ========================================================================= */
  function greetKey() {
    const h = new Date().getHours();
    if (h >= 5 && h < 12) return "greet.morning";
    if (h >= 12 && h < 18) return "greet.afternoon";
    if (h >= 18 && h < 24) return "greet.evening";
    return "greet.night";
  }
  function updateGreeting() {
    const el = $("[data-greeting]");
    if (el) el.textContent = t(greetKey());
  }

  /* =========================================================================
     Router — hash-based (#/home … #/premium); keeps views mounted so embedded
     calls / streams survive navigation.
     ========================================================================= */
  const VIEWS = ["home", "chat", "learn", "meet", "live", "premium"];
  let currentView = "";

  function mountEmbed(section) {
    const url = section.dataset.embed;
    if (!url || section.dataset.mounted) return;
    section.dataset.mounted = "1";
    const wrap = $(".embed-wrap", section);
    const loading = $(".embed-loading", section);
    const frame = document.createElement("iframe");
    frame.src = url;
    frame.title = t("nav." + section.dataset.view);
    if (section.dataset.allow) frame.allow = section.dataset.allow;
    frame.setAttribute("allowfullscreen", "");
    frame.referrerPolicy = "origin";
    frame.addEventListener("load", () => { if (loading) loading.classList.add("is-done"); });
    wrap.appendChild(frame);
  }

  function show(name) {
    if (!VIEWS.includes(name)) name = "home";
    if (name === currentView) return;
    currentView = name;

    $$(".view").forEach((sec) => {
      sec.classList.toggle("is-active", sec.dataset.view === name);
    });
    $$("[data-nav]").forEach((a) => {
      if (a.dataset.nav === name) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });

    const active = $(`.view[data-view="${name}"]`);
    if (active) mountEmbed(active);

    document.title = name === "home" ? LS.brand : `${t("nav." + name)} · ${LS.brand}`;
    const content = $("#content");
    if (content) content.scrollTop = 0;
    window.scrollTo({ top: 0 });
  }

  function route() {
    const name = location.hash.replace(/^#\/?/, "").split("?")[0] || "home";
    show(name);
  }
  window.addEventListener("hashchange", route);

  /* =========================================================================
     LIVE status — polls OwnCast /api/status; drives the home hero, the rail
     dots and the Live view badge. Backs off politely when the tab is hidden
     or the endpoint is unreachable (CORS / offline).
     ========================================================================= */
  const POLL_MS = 30_000;
  const POLL_MS_ERR = 90_000;
  let liveOnline = null; // null = unknown yet
  let liveTimer = 0;

  function setLiveUI(online, status) {
    const card = $("#liveCard");
    const pill = $("#livePill");
    const viewers = $("#liveViewers");
    const title = $("#liveTitle");
    const watch = $("#liveWatchBtn");
    const offline = $("#liveOffline");
    const stage = $("#liveStage");

    $$("[data-live-dot]").forEach((d) => { d.hidden = !online; });
    $$("[data-live-pill]").forEach((p) => { p.hidden = !online; });

    if (!card) return;
    card.classList.toggle("is-live", !!online);
    if (pill) pill.hidden = !online;
    if (watch) watch.hidden = !online;
    if (offline) offline.style.display = online ? "none" : "";

    if (online) {
      if (title) title.textContent = (status && status.streamTitle) ? status.streamTitle : t("live.now");
      if (viewers) {
        const n = status && typeof status.viewerCount === "number" ? status.viewerCount : null;
        viewers.hidden = n === null;
        if (n !== null) viewers.textContent = `${n} ${t("live.viewers")}`;
      }
      // Mount the OwnCast embedded player in the hero (only while live).
      if (stage && !$("iframe", stage)) {
        const f = document.createElement("iframe");
        f.src = LS.urls.live.replace(/\/$/, "") + "/embed/video";
        f.title = t("live.now");
        f.allow = "autoplay; fullscreen; picture-in-picture";
        f.setAttribute("allowfullscreen", "");
        stage.appendChild(f);
      }
    } else {
      if (title) title.textContent = "";
      if (viewers) viewers.hidden = true;
      const f = stage && $("iframe", stage);
      if (f) f.remove();
    }
  }

  async function pollLive() {
    clearTimeout(liveTimer);
    let delay = POLL_MS;
    if (document.hidden) {
      liveTimer = setTimeout(pollLive, POLL_MS);
      return;
    }
    try {
      const base = (LS.urls.live || "").replace(/\/$/, "");
      const res = await fetch(base + "/api/status", { mode: "cors", cache: "no-store" });
      if (!res.ok) throw new Error("status " + res.status);
      const status = await res.json();
      const online = !!status.online;
      if (online !== liveOnline) { liveOnline = online; setLiveUI(online, status); }
      else if (online) setLiveUI(online, status); // refresh title/viewers
    } catch {
      if (liveOnline !== false) { liveOnline = false; setLiveUI(false, null); }
      delay = POLL_MS_ERR;
    }
    liveTimer = setTimeout(pollLive, delay);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) pollLive(); });

  /* =========================================================================
     Activity feed — skeletons melt into placeholder items (until a real
     activity API lands).
     ========================================================================= */
  const ACT_ICONS = ["i-user", "i-learn", "i-live", "i-chat"];
  function hydrateActivity() {
    const box = $("#activity");
    if (!box) return;
    setTimeout(() => {
      box.innerHTML = "";
      for (let i = 1; i <= 4; i++) {
        const row = document.createElement("div");
        row.className = "activity-item is-in";
        row.style.animationDelay = `${(i - 1) * 70}ms`;
        row.innerHTML =
          `<span class="activity-dot"><svg class="ico" aria-hidden="true"><use href="#${ACT_ICONS[i - 1]}"/></svg></span>` +
          `<span class="activity-text"></span><span class="activity-time"></span>`;
        $(".activity-text", row).textContent = t("act." + i);
        $(".activity-time", row).textContent = t("act.t" + i);
        box.appendChild(row);
      }
    }, 900);
  }

  /* =========================================================================
     Install — beforeinstallprompt on Chromium; Add-to-Home-Screen sheet on iOS.
     ========================================================================= */
  const installBtn = $("#installBtn");
  const iosSheet = $("#iosSheet");
  const iosBackdrop = $("#iosBackdrop");
  let deferredPrompt = null;

  const isStandalone = () =>
    window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const isIOS = () =>
    /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (installBtn && !isStandalone()) installBtn.hidden = false;
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    if (installBtn) installBtn.hidden = true;
    toast(t("install.done"));
  });

  function openIosSheet(open) {
    if (!iosSheet) return;
    iosSheet.hidden = !open;
    iosBackdrop.hidden = !open;
    if (open) $("#iosSheetClose").focus();
    else installBtn && installBtn.focus();
  }

  if (installBtn) {
    installBtn.addEventListener("click", async () => {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        try { await deferredPrompt.userChoice; } catch { /* dismissed */ }
        deferredPrompt = null;
        installBtn.hidden = true;
      } else if (isIOS()) {
        openIosSheet(true);
      }
    });
    // iOS never fires beforeinstallprompt — surface the hint button ourselves.
    if (isIOS() && !isStandalone()) installBtn.hidden = false;
  }
  $("#iosSheetClose") && $("#iosSheetClose").addEventListener("click", () => openIosSheet(false));
  iosBackdrop && iosBackdrop.addEventListener("click", () => openIosSheet(false));

  /* =========================================================================
     Search palette — fuzzy-ish filter over destinations + actions.
     ========================================================================= */
  const palette = $("#palette");
  const paletteBackdrop = $("#paletteBackdrop");
  const paletteInput = $("#paletteInput");
  const paletteResults = $("#paletteResults");
  let hlIndex = 0;
  let lastFocus = null;

  function searchIndex() {
    const items = VIEWS.map((v) => ({
      label: t("nav." + v), icon: "i-" + (v === "home" ? "home" : v),
      hint: t("search.hint_view"), go: () => { location.hash = "#/" + v; }
    }));
    items.push({
      label: t("search.account"), icon: "i-user", hint: t("search.hint_link"),
      go: () => window.open(LS.urls.auth, "_blank", "noopener")
    });
    if (!installBtn.hidden) {
      items.push({ label: t("search.install"), icon: "i-install", hint: "", go: () => installBtn.click() });
    }
    return items;
  }

  function renderResults(q) {
    const norm = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    const query = norm(q.trim());
    const hits = searchIndex().filter((it) => !query || norm(it.label).includes(query));
    paletteResults.innerHTML = "";
    hlIndex = 0;
    if (!hits.length) {
      const li = document.createElement("li");
      li.className = "palette-empty";
      li.textContent = t("search.empty");
      paletteResults.appendChild(li);
      return;
    }
    hits.forEach((it, i) => {
      const li = document.createElement("li");
      li.className = "palette-item" + (i === 0 ? " is-hl" : "");
      li.setAttribute("role", "option");
      li.innerHTML =
        `<svg class="ico" aria-hidden="true"><use href="#${it.icon}"/></svg>` +
        `<span class="palette-item-label"></span><span class="palette-item-hint"></span>`;
      $(".palette-item-label", li).textContent = it.label;
      $(".palette-item-hint", li).textContent = it.hint;
      li.addEventListener("click", () => { closePalette(); it.go(); });
      li.addEventListener("mousemove", () => setHighlight(i));
      paletteResults.appendChild(li);
    });
  }

  function setHighlight(i) {
    const items = $$(".palette-item", paletteResults);
    if (!items.length) return;
    hlIndex = Math.max(0, Math.min(i, items.length - 1));
    items.forEach((el, j) => el.classList.toggle("is-hl", j === hlIndex));
    items[hlIndex].scrollIntoView({ block: "nearest" });
  }

  function openPalette() {
    lastFocus = document.activeElement;
    palette.hidden = false;
    paletteBackdrop.hidden = false;
    paletteInput.value = "";
    renderResults("");
    paletteInput.focus();
  }
  function closePalette() {
    palette.hidden = true;
    paletteBackdrop.hidden = true;
    if (lastFocus) lastFocus.focus();
  }

  $("#searchOpen").addEventListener("click", openPalette);
  $("#paletteClose").addEventListener("click", closePalette);
  paletteBackdrop.addEventListener("click", closePalette);
  paletteInput.addEventListener("input", () => renderResults(paletteInput.value));
  paletteInput.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setHighlight(hlIndex + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHighlight(hlIndex - 1); }
    else if (e.key === "Enter") {
      const items = $$(".palette-item", paletteResults);
      if (items[hlIndex]) items[hlIndex].click();
    }
  });

  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette.hidden ? openPalette() : closePalette(); }
    else if (e.key === "/" && palette.hidden && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); openPalette(); }
    else if (e.key === "Escape") {
      if (!palette.hidden) closePalette();
      if (iosSheet && !iosSheet.hidden) openIosSheet(false);
    }
  });

  /* =========================================================================
     Toast + bell + connectivity
     ========================================================================= */
  const toastEl = $("#toast");
  let toastTimer = 0;
  function toast(msg, ms = 3200) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, ms);
  }
  $("#bellBtn").addEventListener("click", () => toast(t("bell.empty")));
  window.addEventListener("offline", () => toast(t("net.offline"), 5000));
  window.addEventListener("online", () => toast(t("net.online")));

  /* =========================================================================
     Service worker (PWA offline shell — /app/sw.js from the PWA build)
     ========================================================================= */
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/app/sw.js").catch(() => { /* sw optional */ });
    });
  }

  /* =========================================================================
     Boot
     ========================================================================= */
  applyI18n();
  // Platform-correct shortcut hint in the search box
  const kbd = $(".searchbox-kbd");
  if (kbd && !/mac|iphone|ipad|ipod/i.test(navigator.platform || "")) kbd.textContent = "Ctrl K";
  updateGreeting();
  setInterval(updateGreeting, 60_000);
  if (!LS.poweredBy) {
    const pb = $("#poweredBy");
    if (pb) pb.hidden = true;
  }
  // PWA shortcut deep links (/app/?go=chat …): normally the service worker
  // redirects these to the sibling subdomain; on a first run (no SW yet)
  // fall back to the matching in-shell view so the shortcut still lands.
  const go = new URLSearchParams(location.search).get("go");
  if (go && VIEWS.includes(go) && !location.hash) location.hash = "#/" + go;
  route();
  hydrateActivity();
  pollLive();
})();
