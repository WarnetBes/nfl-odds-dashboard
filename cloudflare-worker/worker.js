// ═══════════════════════════════════════════════════════════
//  Sports Odds Dashboard — Cloudflare Worker v4
//  Исправления относительно v3:
//  BUG-1: setTimeout/clearTimeout → AbortSignal.timeout() (CF Workers совместимость)
//  BUG-2: catch { } → catch (_e) { } (optional catch binding, совместимость)
//  BUG-3: CORS заголовки добавляются ко ВСЕМ ответам (не только PWA-статике)
//  BUG-4: убрали headers.set('host') — CF Workers игнорирует его, ставит сам
//  BUG-5: <\/script> → </script> в PWA_SNIPPET (неверное экранирование)
//  BUG-6: WebSocket proxy через WebSocketPair (Streamlit интерактивность)
//  BUG-7: /favicon.ico → редирект на /icons/icon-192x192.png
//  BUG-8: placeholder {{ERROR_MESSAGE}} в OFFLINE_HTML вместо хрупкого .replace()
// ═══════════════════════════════════════════════════════════

const STREAMLIT_URL = "https://nfl-odds-dashboard-cwetbvdeqon6p5ujc7hz6u.streamlit.app";
const PROXY_TIMEOUT_MS = 25_000;

// ── Manifest ──────────────────────────────────────────────────────────────────
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
    { src: "/icons/icon-512x512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
  ],
  shortcuts: [
    { name: "Сигналы",    url: "/?tab=signals" },
    { name: "Арбитраж",   url: "/?tab=arb"     },
    { name: "Live Scores", url: "/?tab=live"   },
  ],
});

// ── Service Worker ────────────────────────────────────────────────────────────
const SW_JS = `
const CACHE = 'odds-v4';
const STATIC = 'odds-static-v4';

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(STATIC).then(c => c.addAll([
      '/', '/manifest.json', '/offline.html',
      '/icons/icon-192x192.png', '/icons/icon-512x512.png',
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

  if (url.pathname.startsWith('/icons/') ||
      url.pathname === '/manifest.json' ||
      url.pathname === '/offline.html') {
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request).then(r => {
        if (r.ok) { const c = r.clone(); caches.open(STATIC).then(cache => cache.put(e.request, c)); }
        return r;
      }))
    );
    return;
  }

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
  // BUG-2 FIX: catch (_e) для совместимости
  let d;
  try { d = e.data.json(); } catch (_e) { d = { title: '🎯 Value Bet Alert', body: e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || '🎯 Value Bet Alert', {
    body: d.body || 'Новая ставка с положительным EV!',
    icon: '/icons/icon-192x192.png',
    badge: '/icons/icon-72x72.png',
    tag: 'odds-alert',
    renotify: true,
    data: { url: d.url || '/' },
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data.url || '/'));
});
`;

// ── Offline page — BUG-8 FIX: placeholder {{ERROR_MESSAGE}} ──────────────────
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
  <p>{{ERROR_MESSAGE}}</p>
  <div class="status"><span class="dot"></span>Ожидание подключения…</div>
  <button onclick="window.location.reload()">🔄 Повторить</button>
  <script>window.addEventListener('online', () => window.location.reload());</script>
</body>
</html>`;

// ── Hop-by-hop заголовки — фильтруем при проксировании ────────────────────────
// BUG-4 FIX: убрали попытку headers.set('host') — CF Workers игнорирует его
const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailers', 'transfer-encoding', 'upgrade', 'host',
]);

const CORS_HEADERS = {
  "Access-Control-Allow-Origin":  "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function proxyRequestHeaders(original) {
  const headers = new Headers();
  for (const [k, v] of original.entries()) {
    if (!HOP_BY_HOP.has(k.toLowerCase())) headers.set(k, v);
  }
  // BUG-4 FIX: НЕ устанавливаем 'host' — CF Workers делает это сам из URL
  return headers;
}

// BUG-5 FIX: </script> без экранирования — строка вставляется в HTML через .replace(), не в JS
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
  </script>`;

// ── Вспомогательная функция для offline/error страниц ────────────────────────
function offlinePage(message, status) {
  return new Response(
    OFFLINE_HTML.replace("{{ERROR_MESSAGE}}", message),
    { status, headers: { "Content-Type": "text/html; charset=utf-8" } }
  );
}

// ── BUG-6 FIX: WebSocket proxy через WebSocketPair ───────────────────────────
async function handleWebSocket(request) {
  const url = new URL(request.url);
  const target = new URL(url.pathname + url.search, STREAMLIT_URL);
  target.protocol = "wss:";

  const [client, server] = Object.values(new WebSocketPair());
  const proto = request.headers.get("sec-websocket-protocol") ?? undefined;
  const upstream = new WebSocket(target.toString(), proto);

  upstream.addEventListener("open", () => {
    server.accept();
  });

  // Клиент → Streamlit
  server.addEventListener("message", e => {
    if (upstream.readyState === WebSocket.OPEN) upstream.send(e.data);
  });
  server.addEventListener("close", e => {
    upstream.close(e.code, e.reason);
  });

  // Streamlit → клиент
  upstream.addEventListener("message", e => {
    server.send(e.data);
  });
  upstream.addEventListener("close", e => {
    try { server.close(e.code, e.reason); } catch (_e) { /* already closed */ }
  });
  upstream.addEventListener("error", () => {
    try { server.close(1011, "upstream error"); } catch (_e) { /* ignore */ }
  });

  return new Response(null, { status: 101, webSocket: client });
}

// ── Main handler ──────────────────────────────────────────────────────────────
export default {
  async fetch(request, env, ctx) {
    const url  = new URL(request.url);
    const path = url.pathname;

    // OPTIONS preflight
    if (request.method === "OPTIONS")
      return new Response(null, { status: 204, headers: CORS_HEADERS });

    // BUG-6 FIX: WebSocket upgrade — Streamlit интерактивность (виджеты, live данные)
    if (request.headers.get("upgrade") === "websocket") {
      return handleWebSocket(request);
    }

    // ── PWA static assets ─────────────────────────────────────────────────────
    if (path === "/manifest.json")
      return new Response(MANIFEST, {
        headers: {
          "Content-Type": "application/manifest+json; charset=utf-8",
          "Cache-Control": "public, max-age=86400",
          ...CORS_HEADERS,
        },
      });

    if (path === "/sw.js")
      return new Response(SW_JS, {
        headers: {
          "Content-Type": "application/javascript; charset=utf-8",
          "Service-Worker-Allowed": "/",
          "Cache-Control": "no-cache, no-store, must-revalidate",
          ...CORS_HEADERS,
        },
      });

    if (path === "/offline.html")
      return new Response(
        OFFLINE_HTML.replace("{{ERROR_MESSAGE}}", "Нет подключения к интернету.<br>Последние данные могут быть устаревшими."),
        {
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "public, max-age=86400",
            ...CORS_HEADERS,
          },
        }
      );

    // BUG-7 FIX: /favicon.ico → редирект на иконку PWA
    if (path === "/favicon.ico")
      return Response.redirect(new URL("/icons/icon-192x192.png", url).toString(), 302);

    // ── Proxy to Streamlit ────────────────────────────────────────────────────
    try {
      const target = new URL(path + url.search, STREAMLIT_URL);

      // BUG-1 FIX: AbortSignal.timeout() вместо setTimeout/clearTimeout
      // CF Workers НЕ поддерживают глобальный setTimeout — это Node.js/browser API
      const resp = await fetch(new Request(target.toString(), {
        method:   request.method,
        headers:  proxyRequestHeaders(request.headers),
        body:     ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        signal:   AbortSignal.timeout(PROXY_TIMEOUT_MS),
        redirect: "follow",
      }));

      const contentType = resp.headers.get("content-type") ?? "";

      // HTML: инжектируем PWA-сниппет
      if (contentType.includes("text/html")) {
        const html    = await resp.text();
        const patched = html.includes("</head>")
          ? html.replace("</head>", PWA_SNIPPET + "\n  </head>")
          : html + PWA_SNIPPET;

        const newHeaders = new Headers(resp.headers);
        newHeaders.set("Content-Type", "text/html; charset=utf-8");
        newHeaders.delete("Content-Security-Policy");
        // BUG-3 FIX: CORS и для HTML-ответов
        for (const [k, v] of Object.entries(CORS_HEADERS)) newHeaders.set(k, v);

        return new Response(patched, { status: resp.status, headers: newHeaders });
      }

      // BUG-3 FIX: CORS ко всем non-HTML проксированным ответам
      const proxyHeaders = new Headers(resp.headers);
      for (const [k, v] of Object.entries(CORS_HEADERS)) proxyHeaders.set(k, v);

      return new Response(resp.body, {
        status:  resp.status,
        headers: proxyHeaders,
      });

    } catch (err) {
      const isTimeout = err.name === "TimeoutError" || err.name === "AbortError";
      const status    = isTimeout ? 504 : 503;
      const message   = isTimeout
        ? "Streamlit не ответил вовремя.<br>Попробуйте обновить страницу."
        : "Сервис временно недоступен.<br>Повторите попытку позже.";
      return offlinePage(message, status);
    }
  },
};
