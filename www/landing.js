/* ============================================================================
   LibreSynergy — landing.js (public landing page)
   Self-contained, no dependencies, no trackers. Brand text/URLs arrive via the
   #ls-config / #ls-i18n JSON blocks baked into index.html by apply-branding,
   so this file stays operator-agnostic (no deploy-time placeholders in here).
   ========================================================================== */
(function () {
  'use strict';
  document.documentElement.classList.add('js');

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  function readJSON(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  var cfg = readJSON('ls-config') || {};
  var dict = readJSON('ls-i18n') || {};
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---- i18n: en / es / fr ------------------------------------------------ */
  var SUPPORTED = ['en', 'es', 'fr'];
  var lang = 'en';

  function pickLang() {
    var saved = null;
    try { saved = localStorage.getItem('ls-lang'); } catch (e) {}
    if (saved && SUPPORTED.indexOf(saved) !== -1) return saved;
    var nav = (navigator.language || 'en').slice(0, 2).toLowerCase();
    return SUPPORTED.indexOf(nav) !== -1 ? nav : 'en';
  }

  function t(key) {
    var d = dict[lang] || {};
    var en = dict.en || {};
    return d[key] != null ? d[key] : en[key];
  }

  function applyLang(next) {
    if (SUPPORTED.indexOf(next) === -1) next = 'en';
    lang = next;
    document.documentElement.lang = lang;
    try { localStorage.setItem('ls-lang', lang); } catch (e) {}

    $$('[data-i18n]').forEach(function (el) {
      var v = t(el.getAttribute('data-i18n'));
      if (v != null) el.textContent = v;
    });
    $$('[data-i18n-ph]').forEach(function (el) {
      var v = t(el.getAttribute('data-i18n-ph'));
      if (v != null) el.setAttribute('placeholder', v);
    });
    $$('[data-lang-field]').forEach(function (el) { el.value = lang; });
    $$('.ls-lang a').forEach(function (a) {
      var active = a.getAttribute('data-lang') === lang;
      if (active) a.setAttribute('aria-current', 'true');
      else a.removeAttribute('aria-current');
    });
    renderLive(lastStatus); // re-render live strings in the new language
  }

  $$('.ls-lang a').forEach(function (a) {
    a.addEventListener('click', function (ev) {
      ev.preventDefault();
      applyLang(a.getAttribute('data-lang'));
    });
  });

  /* ---- scroll reveal ------------------------------------------------------ */
  var revealEls = $$('.reveal');
  if ('IntersectionObserver' in window && !reduceMotion) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add('in'); });
  }

  /* ---- nav scroll state ---------------------------------------------------- */
  var nav = $('#lnNav');
  if (nav) {
    var onScroll = function () { nav.classList.toggle('is-scrolled', window.scrollY > 8); };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* ---- hero aurora: gentle pointer parallax --------------------------------- */
  var aurora = $('#aurora');
  if (aurora && !reduceMotion && window.matchMedia('(pointer: fine)').matches) {
    var raf = null;
    window.addEventListener('pointermove', function (ev) {
      if (raf) return;
      raf = requestAnimationFrame(function () {
        raf = null;
        var x = (ev.clientX / window.innerWidth - 0.5) * 30;
        var y = (ev.clientY / window.innerHeight - 0.5) * 22;
        aurora.style.setProperty('--mx', x.toFixed(1));
        aurora.style.setProperty('--my', y.toFixed(1));
      });
    }, { passive: true });
  }

  /* ---- LIVE status: poll OwnCast /api/status -------------------------------- */
  var lastStatus = null;
  var liveSection = $('#live');
  var liveTimer = null;
  var POLL_MS = 45000;

  function fmt(key, n) {
    var s = t(key) || '';
    return s.replace('{n}', String(n));
  }

  function renderLive(status) {
    if (!liveSection) return;
    var online = !!(status && status.online);
    liveSection.setAttribute('data-state', online ? 'on' : 'off');

    var stateEl = $('[data-live-state]', liveSection);
    var titleEl = $('[data-live-title]', liveSection);
    var subEl = $('[data-live-sub]', liveSection);
    var metaEl = $('[data-live-meta]', liveSection);
    var watchEl = $('[data-live-watch]', liveSection);
    var stage = $('[data-live-stage]', liveSection);

    if (stateEl) stateEl.textContent = t(online ? 'live.badgeOn' : 'live.badgeOff');
    if (titleEl) titleEl.textContent = (online && status.streamTitle) ? status.streamTitle : t(online ? 'live.onTitle' : 'live.offTitle');
    if (subEl) subEl.textContent = t(online ? 'live.onSub' : 'live.offSub');
    if (watchEl) watchEl.hidden = !online;
    if (metaEl) {
      var viewers = online && typeof status.viewerCount === 'number' ? status.viewerCount : 0;
      metaEl.hidden = !online;
      metaEl.textContent = online ? fmt('live.viewers', viewers) : '';
    }

    // hero pill + card flag
    var pill = $('[data-live-pill]');
    var pillText = $('[data-live-pill-text]');
    if (pill) pill.hidden = !online;
    if (pillText && online) {
      var n = typeof status.viewerCount === 'number' ? status.viewerCount : 0;
      pillText.textContent = t('live.badgeOn') + (n > 0 ? ' · ' + fmt('live.viewers', n) : '');
    }
    var flag = $('[data-card-live]');
    if (flag) flag.hidden = !online;

    // embed the player only while live (OwnCast is frame-ancestors friendly)
    if (stage && cfg.live) {
      var frame = $('iframe', stage);
      if (online && !frame) {
        frame = document.createElement('iframe');
        frame.src = cfg.live.replace(/\/$/, '') + '/embed/video';
        frame.title = titleEl ? titleEl.textContent : 'Live stream';
        frame.loading = 'lazy';
        frame.setAttribute('allowfullscreen', '');
        frame.setAttribute('allow', 'autoplay; fullscreen; picture-in-picture');
        stage.appendChild(frame);
      } else if (!online && frame) {
        frame.remove();
      }
    }
  }

  function pollLive() {
    if (!cfg.live || document.hidden) return;
    fetch(cfg.live.replace(/\/$/, '') + '/api/status', { mode: 'cors' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (status) {
        if (status) { lastStatus = status; renderLive(status); }
      })
      .catch(function () { /* stream box offline — keep the calm default */ });
  }

  if (liveSection && cfg.live) {
    pollLive();
    liveTimer = setInterval(pollLive, POLL_MS);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) pollLive();
    });
  }

  /* ---- Install the app (PWA) ------------------------------------------------ */
  var deferredPrompt = null;
  window.addEventListener('beforeinstallprompt', function (ev) {
    ev.preventDefault();
    deferredPrompt = ev;
  });

  function isIOS() {
    return /iphone|ipad|ipod/i.test(navigator.userAgent) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  }

  function showIOSTip() {
    var tip = $('#installTip');
    if (!tip) return;
    tip.hidden = false;
    setTimeout(function () { tip.hidden = true; }, 7000);
  }

  $$('[data-install]').forEach(function (btn) {
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(function () { deferredPrompt = null; });
      } else if (isIOS()) {
        showIOSTip();
      } else if (cfg.app) {
        window.location.href = cfg.app; // the installable app shell
      }
    });
  });

  /* ---- housekeeping ----------------------------------------------------------- */
  // theme-color follows the live token value, so a rebrand recolours the chrome UI
  function syncThemeColor() {
    var ink = getComputedStyle(document.documentElement).getPropertyValue('--ls-ink').trim();
    if (!ink) return;
    $$('meta[name="theme-color"]').forEach(function (m) { m.setAttribute('content', ink); });
  }
  syncThemeColor();
  var scheme = window.matchMedia('(prefers-color-scheme: light)');
  if (scheme.addEventListener) scheme.addEventListener('change', syncThemeColor);

  // hide the powered-by line when the operator blanked LS_POWERED_BY
  var powered = $('[data-poweredby]');
  if (powered) {
    var name = $('b', powered);
    if (!name || !name.textContent.trim()) powered.style.display = 'none';
  }

  // current year in the footer
  $$('[data-year]').forEach(function (el) { el.textContent = String(new Date().getFullYear()); });

  // go
  applyLang(pickLang());
})();
