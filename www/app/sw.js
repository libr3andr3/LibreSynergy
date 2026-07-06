/* ============================================================================
   LibreSynergy — app shell service worker  (/app/sw.js)

   Strategy
   --------
   • install   : precache the app shell (resilient — one missing asset will
                 not brick the install; only offline.html is load-bearing).
   • navigate  : network-first, falling back to the cached shell, then to
                 /app/offline.html.
   • /brand/*  : cache-first, silently revalidated in the background so a
                 rebrand (new tokens.css / logo) propagates on the next load.
   • other GET : network, falling back to a runtime cache (bounded).
   • deep links: PWA shortcut URLs like /app/?go=chat are 302-redirected to
                 the sibling subdomain (chat.<base>), derived at runtime from
                 this origin — no build-time placeholders needed here.

   Shipping an update
   ------------------
   Bump SW_VERSION below. The new worker precaches into fresh `ls-*-<version>`
   caches, activates immediately (skipWaiting + clients.claim), and purges
   every older `ls-*` cache on activate. Nothing else to do.
   ============================================================================ */

'use strict';

const SW_VERSION = '1.0.0'; /* ← bump this string to invalidate all caches */

const PRECACHE = `ls-precache-${SW_VERSION}`;
const RUNTIME = `ls-runtime-${SW_VERSION}`;
const RUNTIME_MAX_ENTRIES = 80;

const OFFLINE_URL = '/app/offline.html';

/* The app shell — everything needed to boot the installed app with no
   network at all. Keep this list small and fast. */
const SHELL_ASSETS = [
  '/app/',
  '/app/shell.css',
  '/app/shell.js',
  OFFLINE_URL,
  '/brand/system.css',
  '/brand/tokens.css',
  '/brand/logo.svg',
];

/* ---- shortcut deep-links ---------------------------------------------------
   Manifest shortcuts must stay same-origin (out-of-scope shortcut URLs are
   dropped by the browser), so they point at /app/?go=<dest>. We resolve the
   real destination here. Sub-app hosts derive from this origin: the shell is
   served at app.<base-domain>, so chat lives at chat.<base-domain>, etc.
   If the SW is somehow not controlling, the URL gracefully opens the shell. */
const GO_TARGETS = ['chat', 'learn', 'live', 'meet', 'premium'];

function goUrl(dest) {
  const host = self.location.hostname;
  const base = host.startsWith('app.') ? host.slice('app.'.length) : host;
  return `https://${dest}.${base}/`;
}

/* ---- install ------------------------------------------------------------- */
self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(PRECACHE);
      /* offline.html is load-bearing: fail the install if it cannot cache. */
      await cache.add(new Request(OFFLINE_URL, { cache: 'reload' }));
      /* Everything else is best-effort so one 404 never bricks the install. */
      await Promise.allSettled(
        SHELL_ASSETS.filter((u) => u !== OFFLINE_URL).map((u) =>
          cache.add(new Request(u, { cache: 'reload' }))
        )
      );
      await self.skipWaiting();
    })()
  );
});

/* ---- activate: purge every ls-* cache from older versions ----------------- */
self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([PRECACHE, RUNTIME]);
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((n) => n.startsWith('ls-') && !keep.has(n))
          .map((n) => caches.delete(n))
      );
      if (self.registration.navigationPreload) {
        try {
          await self.registration.navigationPreload.enable();
        } catch (_) {
          /* not supported — fine */
        }
      }
      await self.clients.claim();
    })()
  );
});

/* ---- fetch ----------------------------------------------------------------- */
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; /* never touch cross-origin */

  /* 1) Navigations */
  if (req.mode === 'navigate') {
    const go = url.searchParams.get('go');
    if (go && GO_TARGETS.includes(go)) {
      event.respondWith(Response.redirect(goUrl(go), 302));
      return;
    }
    event.respondWith(handleNavigation(event));
    return;
  }

  /* 2) Brand assets + precached shell files: cache-first (revalidated) */
  if (url.pathname.startsWith('/brand/') || SHELL_ASSETS.includes(url.pathname)) {
    event.respondWith(cacheFirst(event));
    return;
  }

  /* 3) Everything else same-origin: network, cache fallback */
  event.respondWith(networkWithCacheFallback(req));
});

/* Network-first for pages, with shell → offline.html fallback. */
async function handleNavigation(event) {
  const req = event.request;
  try {
    const preloaded = 'preloadResponse' in event ? await event.preloadResponse : null;
    const res = preloaded || (await fetch(req));
    if (res && res.ok) {
      const cache = await caches.open(RUNTIME);
      cache.put(req, res.clone());
    }
    return res;
  } catch (_) {
    const cached = await caches.match(req);
    if (cached) return cached;
    /* An /app/* page while offline → serve the cached shell so the installed
       app still boots; anything else → the branded offline page. */
    if (new URL(req.url).pathname.startsWith('/app')) {
      const shell = await caches.match('/app/');
      if (shell) return shell;
    }
    const offline = await caches.match(OFFLINE_URL);
    return (
      offline ||
      new Response('You are offline.', {
        status: 503,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      })
    );
  }
}

/* Cache-first, revalidating in the background (kept alive via waitUntil). */
async function cacheFirst(event) {
  const req = event.request;
  const cached = await caches.match(req);
  const revalidate = fetch(req)
    .then(async (res) => {
      if (res && res.ok) {
        const cache = await caches.open(PRECACHE);
        await cache.put(req, res.clone());
      }
      return res;
    })
    .catch(() => undefined);

  if (cached) {
    event.waitUntil(revalidate);
    return cached;
  }
  const fresh = await revalidate;
  return (
    fresh ||
    new Response('', { status: 504, statusText: 'Offline and not cached' })
  );
}

/* Network with runtime-cache fallback for API-ish / misc same-origin GETs. */
async function networkWithCacheFallback(req) {
  try {
    const res = await fetch(req);
    if (res && res.ok && res.type === 'basic') {
      const cache = await caches.open(RUNTIME);
      await cache.put(req, res.clone());
      trimCache(RUNTIME, RUNTIME_MAX_ENTRIES); /* fire-and-forget */
    }
    return res;
  } catch (_) {
    const cached = await caches.match(req);
    return (
      cached ||
      new Response('', { status: 504, statusText: 'Offline and not cached' })
    );
  }
}

/* Keep the runtime cache bounded (drop oldest entries first). */
async function trimCache(name, maxEntries) {
  try {
    const cache = await caches.open(name);
    const keys = await cache.keys();
    if (keys.length <= maxEntries) return;
    await Promise.all(keys.slice(0, keys.length - maxEntries).map((k) => cache.delete(k)));
  } catch (_) {
    /* best-effort */
  }
}

/* ---- messages (update flow) ------------------------------------------------ */
self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  } else if (data.type === 'GET_VERSION' && event.source) {
    event.source.postMessage({ type: 'VERSION', version: SW_VERSION });
  }
});

/* ============================================================================
   FUTURE: Web Push (retention loop) — VAPID-ready skeleton. NOT enabled.
   ----------------------------------------------------------------------------
   To turn on later:
     1. Generate a VAPID key pair (e.g. `npx web-push generate-vapid-keys`).
     2. In shell.js, after SW registration:
          const sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: <VAPID public key as Uint8Array>,
          });
          // POST `sub` to the notifications backend, keyed by the SSO user.
     3. Uncomment the two listeners below and bump SW_VERSION.

self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) {}
  const title = payload.title || 'New activity';
  const options = {
    body: payload.body || '',
    icon: '/brand/icon-512.png',
    badge: '/brand/icon-512.png',
    tag: payload.tag || 'ls-general',
    renotify: Boolean(payload.renotify),
    data: { url: payload.url || '/app/' },  // deep link to open on tap
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/app/';
  event.waitUntil((async () => {
    const clientList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of clientList) {
      if (new URL(client.url).pathname.startsWith('/app') && 'focus' in client) {
        await client.focus();
        if ('navigate' in client) await client.navigate(target);
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});
   ============================================================================ */
