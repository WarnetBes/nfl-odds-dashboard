// ═══════════════════════════════════════════════════════════
//  Sports Odds Dashboard — Cloudflare Worker v3 (fixed)
//  • Хостит PWA статику (manifest, sw.js, offline, иконки)
//  • Проксирует всё остальное на Streamlit Cloud
//  • Инжектирует PWA meta-теги в HTML-ответы Streamlit
//  Deploy: https://sports-odds-dashboard.warnetbesholin.workers.dev
// ═══════════════════════════════════════════════════════════

const STREAMLIT_URL = "https://nfl-odds-dashboard-cwetbvdeqon6p5ujc7hz6u.streamlit.app";

// ── FIX 1: Таймаут для проксирования — Streamlit может долго отвечать ──
const PROXY_TIMEOUT_MS = 25_000;

const MANIFEST = JSON.stringify({
  name: "Sports Odds Dashboard",
  short_name: "OddsDash",
  description: "NFL · Football · NBA — Live Odds, Value Bets, Arbitrage",
  start_url: "/",
  scope: "/",
  display: "standalone",
  orientation: "portrait-primary",
  background_color: "#0d1b2a",
  theme_color: "#0d1b2a",
  lang: "ru",
  categories: ["sports", "finance", "utilities"],
  icons: [
    { src: "/icons/icon-72x72.png",   sizes: "72x72",   type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-96x96.png",   sizes: "96x96",   type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-128x128.png", sizes: "128x128", type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-144x144.png", sizes: "144x144", type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-152x152.png", sizes: "152x152", type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-192x192.png", sizes: "192x192", type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-384x384.png", sizes: "384x384", type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-512x512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" }
  ],
  shortcuts: [
    { name: "Сигналы",    url: "/?tab=signals" },
    { name: "Арбитраж",   url: "/?tab=arb"     },
    { name: "Live Scores", url: "/?tab=live"   }
  ]
});

// ── FIX 2: try/catch для парсинга push-данных внутри SW ──
const SW_JS = `
const CACHE = 'odds-v3';
const STATIC = 'odds-static-v3';

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(STATIC).then(c => c.addAll([
      '/', '/manifest.json', '/offline.html',
      '/icons/icon-192x192.png', '/icons/icon-512x512.png'
    ]))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE && k !== STATIC).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.protocol === 'wss:' || url.protocol === 'ws:') return;

  // Cache-first for static PWA assets
  if (url.pathname.startsWith('/icons/') || url.pathname === '/manifest.json' || url.pathname === '/offline.html') {
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request).then(r => {
        if (r.ok) { const c = r.clone(); caches.open(STATIC).then(cache => cache.put(e.request, c)); }
        return r;
      }))
    );
    return;
  }

  // Network-first for app pages
  e.respondWith(
    fetch(e.request)
      .then(r => {
        if (r.ok) { const c = r.clone(); caches.open(CACHE).then(cache => cache.put(e.request, c)); }
        return r;
      })
      .catch(() => caches.match(e.request).then(cached => cached || caches.match('/offline.html')))
  );
});

self.addEventListener('push', e => {
  if (!e.data) return;
  let d;
  try { d = e.data.json(); } catch { d = { title: '🎯 Value Bet Alert', body: e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || '🎯 Value Bet Alert', {
    body: d.body || 'Новая ставка с положительным EV!',
    icon: '/icons/icon-192x192.png',
    badge: '/icons/icon-72x72.png',
    tag: 'odds-alert',
    renotify: true,
    data: { url: d.url || '/' }
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data.url || '/'));
});
`;

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sports Odds Dashboard — Offline</title>
  <link rel="manifest" href="/manifest.json">
  <meta name="theme-color" content="#0d1b2a">
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif;background:#0d1b2a;color:#e2e8f0;
         display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;
         padding:2rem;text-align:center}
    .logo{font-size:4rem;margin-bottom:1rem}
    h1{font-size:1.6rem;font-weight:800;background:linear-gradient(135deg,#a78bfa,#38bdf8);
       -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:.5rem}
    p{color:#64748b;font-size:.95rem;line-height:1.6;max-width:300px}
    .status{margin-top:2rem;background:#1e293b;border:1px solid #334155;border-radius:14px;
            padding:1rem 1.5rem;font-size:.85rem;color:#94a3b8}
    .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#f59e0b;
         animation:blink 1.5s infinite;margin-right:6px}
    @keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
    button{margin-top:1.5rem;background:linear-gradient(135deg,#7c3aed,#2563eb);border:none;
           color:#fff;padding:.75rem 2rem;border-radius:12px;font-size:1rem;font-weight:600;
           cursor:pointer;min-height:48px}
    button:active{opacity:.85;transform:scale(.98)}
  </style>
</head>
<body>
  <div class="logo">🏆</div>
  <h1>Sports Odds Dashboard</h1>
  <p>Нет подключения к интернету.<br>Последние данные могут быть устаревшими.</p>
  <div class="status"><span class="dot"></span>Ожидание подключения…</div>
  <button onclick="window.location.reload()">🔄 Повторить</button>
  <script>window.addEventListener('online', () => window.location.reload());</script>
</body>
</html>`;

// ── FIX 3: фильтруем hop-by-hop заголовки при проксировании ────────────────
const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailers', 'transfer-encoding', 'upgrade', 'host',
]);

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function proxyRequestHeaders(original) {
  const headers = new Headers();
  for (const [k, v] of original.entries()) {
    if (!HOP_BY_HOP.has(k.toLowerCase())) headers.set(k, v);
  }
  headers.set('host', new URL(STREAMLIT_URL).host);
  return headers;
}

// ── PWA-сниппет вынесен в константу ─────────────────────────────────────────
const PWA_SNIPPET = `
  <link rel="manifest" href="/manifest.json" />
  <meta name="mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <meta name="apple-mobile-web-app-title" content="OddsDash" />
  <meta name="theme-color" content="#0d1b2a" />
  <link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />
  <script>
    if ('serviceWorker' in navigator)
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(r => console.log('[PWA] SW registered:', r.scope))
        .catch(e => console.warn('[PWA] SW error:', e));
    window.addEventListener('beforeinstallprompt', e => {
      e.preventDefault();
      window._pwaPrompt = e;
    });
  <\/script>`;

export default {
  async fetch(request, env, ctx) {
    const url  = new URL(request.url);
    const path = url.pathname;

    // ── OPTIONS preflight ─────────────────────────────────────────────────────
    if (request.method === "OPTIONS")
      return new Response(null, { status: 204, headers: CORS });

    // ── PWA static assets ─────────────────────────────────────────────────────
    if (path === "/manifest.json")
      return new Response(MANIFEST, {
        headers: {
          "Content-Type": "application/manifest+json; charset=utf-8",
          "Cache-Control": "public, max-age=86400",
          ...CORS
        }
      });

    if (path === "/sw.js")
      return new Response(SW_JS, {
        headers: {
          "Content-Type": "application/javascript; charset=utf-8",
          "Service-Worker-Allowed": "/",
          // FIX 4: sw.js не должен кешироваться — иначе обновления не применяются
          "Cache-Control": "no-cache, no-store, must-revalidate",
          ...CORS
        }
      });

    if (path === "/offline.html")
      return new Response(OFFLINE_HTML, {
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "public, max-age=86400",
          ...CORS
        }
      });

    // ── Proxy to Streamlit ────────────────────────────────────────────────────
    try {
      const target = new URL(path + url.search, STREAMLIT_URL);

      // FIX 5: AbortController + таймаут
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);

      let resp;
      try {
        resp = await fetch(new Request(target.toString(), {
          method:  request.method,
          headers: proxyRequestHeaders(request.headers),
          // FIX 6: пробрасываем body для POST (нужно для Streamlit WebSocket handshake)
          body:    ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
          signal:  controller.signal,
          redirect: "follow",
        }));
      } finally {
        clearTimeout(timer);
      }

      const contentType = resp.headers.get("content-type") ?? "";

      if (contentType.includes("text/html")) {
        const html    = await resp.text();
        // FIX 7: fallback если </head> отсутствует в ответе
        const patched = html.includes("</head>")
          ? html.replace("</head>", PWA_SNIPPET + "\n  </head>")
          : html + PWA_SNIPPET;

        const newHeaders = new Headers(resp.headers);
        newHeaders.set("Content-Type", "text/html; charset=utf-8");
        newHeaders.delete("Content-Security-Policy");

        return new Response(patched, { status: resp.status, headers: newHeaders });
      }

      // FIX 8: все не-HTML ответы пробрасываем напрямую через body stream
      return new Response(resp.body, {
        status:  resp.status,
        headers: resp.headers,
      });

    } catch (err) {
      // FIX 9: различаем таймаут (504) и недоступность сервиса (503)
      const isTimeout = err.name === "AbortError";
      const status    = isTimeout ? 504 : 503;
      const message   = isTimeout
        ? "Streamlit не ответил вовремя. Попробуйте ещё раз."
        : "Сервис временно недоступен.";

      return new Response(
        OFFLINE_HTML.replace("Нет подключения к интернету.", message),
        { status, headers: { "Content-Type": "text/html; charset=utf-8" } }
      );
    }
  }
};
