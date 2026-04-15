// ═══════════════════════════════════════════════════════════
//  Sports Odds Dashboard — Cloudflare Worker
//  Хостит PWA статику + проксирует Streamlit Cloud
// ═══════════════════════════════════════════════════════════

const STREAMLIT_URL = "https://nfl-odds-dashboard-cwetbvdeqon6p5ujc7hz6u.streamlit.app";

// ── Встроенные статические ресурсы ──────────────────────────
const MANIFEST_JSON = `{
  "name": "Sports Odds Dashboard",
  "short_name": "OddsDash",
  "description": "NFL · Football · NBA — Live Odds, Value Bets, Arbitrage, Live Scores",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "orientation": "portrait-primary",
  "background_color": "#0d1b2a",
  "theme_color": "#0d1b2a",
  "lang": "ru",
  "dir": "ltr",
  "categories": ["sports", "finance", "utilities"],
  "icons": [
    { "src": "/icons/icon-72x72.png",   "sizes": "72x72",   "type": "image/png", "purpose": "any maskable" },
    { "src": "/icons/icon-96x96.png",   "sizes": "96x96",   "type": "image/png", "purpose": "any maskable" },
    { "src": "/icons/icon-128x128.png", "sizes": "128x128", "type": "image/png", "purpose": "any maskable" },
    { "src": "/icons/icon-144x144.png", "sizes": "144x144", "type": "image/png", "purpose": "any maskable" },
    { "src": "/icons/icon-152x152.png", "sizes": "152x152", "type": "image/png", "purpose": "any maskable" },
    { "src": "/icons/icon-192x192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable" },
    { "src": "/icons/icon-384x384.png", "sizes": "384x384", "type": "image/png", "purpose": "any maskable" },
    { "src": "/icons/icon-512x512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" }
  ],
  "shortcuts": [
    {
      "name": "Сигналы",
      "short_name": "Сигналы",
      "description": "Открыть вкладку Сигналы",
      "url": "/?tab=signals",
      "icons": [{ "src": "/icons/icon-96x96.png", "sizes": "96x96" }]
    },
    {
      "name": "Арбитраж",
      "short_name": "Арбитраж",
      "description": "Открыть вкладку Арбитраж",
      "url": "/?tab=arb",
      "icons": [{ "src": "/icons/icon-96x96.png", "sizes": "96x96" }]
    },
    {
      "name": "Live Scores",
      "short_name": "Live",
      "description": "Открыть Live Scores",
      "url": "/?tab=live",
      "icons": [{ "src": "/icons/icon-96x96.png", "sizes": "96x96" }]
    }
  ],
  "screenshots": [
    {
      "src": "/icons/screenshot-mobile.png",
      "sizes": "390x844",
      "type": "image/png",
      "form_factor": "narrow",
      "label": "Sports Odds Dashboard — мобильный вид"
    }
  ]
}
`;

const SW_JS = `// ─────────────────────────────────────────────────────────
//  Sports Odds Dashboard — Service Worker
//  Strategy: Network-first для API, Cache-first для статики
// ─────────────────────────────────────────────────────────

const CACHE_NAME     = "odds-dash-v2";
const STATIC_CACHE   = "odds-dash-static-v2";
const OFFLINE_URL    = "/offline.html";

// Ресурсы которые кэшируем при установке (App Shell)
const APP_SHELL = [
  "/",
  "/manifest.json",
  "/offline.html",
  "/icons/icon-192x192.png",
  "/icons/icon-512x512.png",
  "/icons/apple-touch-icon.png",
];

// ── Install: предзагружаем App Shell ──────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      console.log("[SW] Pre-caching app shell");
      return cache.addAll(APP_SHELL);
    })
  );
  // Активируем немедленно, не ждём закрытия старых вкладок
  self.skipWaiting();
});

// ── Activate: чистим старые кэши ─────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME && k !== STATIC_CACHE)
          .map((k) => {
            console.log("[SW] Deleting old cache:", k);
            return caches.delete(k);
          })
      )
    )
  );
  self.clients.claim();
});

// ── Fetch: стратегия по типу запроса ─────────────────────
self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Пропускаем не-GET и cross-origin без кэша
  if (request.method !== "GET") return;

  // Streamlit websocket — не трогаем
  if (url.protocol === "wss:" || url.protocol === "ws:") return;

  // The Odds API / ESPN API — NETWORK ONLY (актуальные данные)
  if (
    url.hostname.includes("api.the-odds-api.com") ||
    url.hostname.includes("site.api.espn.com") ||
    url.hostname.includes("googleapis.com")
  ) {
    event.respondWith(fetch(request));
    return;
  }

  // Иконки / статика PWA — CACHE FIRST
  if (
    url.pathname.startsWith("/icons/") ||
    url.pathname === "/manifest.json" ||
    url.pathname === "/sw.js" ||
    url.pathname.endsWith(".png") ||
    url.pathname.endsWith(".ico")
  ) {
    event.respondWith(
      caches.match(request).then((cached) => {
        return (
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const clone = response.clone();
              caches.open(STATIC_CACHE).then((cache) => cache.put(request, clone));
            }
            return response;
          })
        );
      })
    );
    return;
  }

  // Streamlit App — NETWORK FIRST с fallback на offline
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => {
        return caches.match(request).then(
          (cached) => cached || caches.match(OFFLINE_URL)
        );
      })
  );
});

// ── Push-уведомления (для будущего использования) ────────
self.addEventListener("push", (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || "🎯 Value Bet Alert", {
      body: data.body || "Новая ставка с положительным EV!",
      icon: "/icons/icon-192x192.png",
      badge: "/icons/icon-72x72.png",
      tag: "odds-alert",
      renotify: true,
      data: { url: data.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url || "/"));
});
`;

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Sports Odds Dashboard — Offline</title>
  <link rel="manifest" href="/manifest.json" />
  <meta name="theme-color" content="#0d1b2a" />
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: #0d1b2a;
      color: #e2e8f0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 2rem;
      text-align: center;
    }
    .logo { font-size: 4rem; margin-bottom: 1rem; }
    h1 {
      font-size: 1.6rem;
      font-weight: 800;
      background: linear-gradient(135deg, #a78bfa, #38bdf8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: .5rem;
    }
    p { color: #64748b; font-size: .95rem; line-height: 1.6; max-width: 300px; }
    .status {
      margin-top: 2rem;
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 14px;
      padding: 1rem 1.5rem;
      font-size: .85rem;
      color: #94a3b8;
    }
    .dot {
      display: inline-block; width: 8px; height: 8px;
      border-radius: 50%; background: #f59e0b;
      animation: blink 1.5s infinite;
      margin-right: 6px;
    }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.3} }
    button {
      margin-top: 1.5rem;
      background: linear-gradient(135deg, #7c3aed, #2563eb);
      border: none; color: #fff;
      padding: .75rem 2rem;
      border-radius: 12px;
      font-size: 1rem; font-weight: 600;
      cursor: pointer;
      min-height: 48px;
    }
    button:hover { opacity: .9; }
  </style>
</head>
<body>
  <div class="logo">🏆</div>
  <h1>Sports Odds Dashboard</h1>
  <p>Нет подключения к интернету.<br>Последние данные могут быть устаревшими.</p>
  <div class="status">
    <span class="dot"></span>
    Ожидание подключения…
  </div>
  <button onclick="window.location.reload()">🔄 Повторить</button>
  <script>
    window.addEventListener('online', () => window.location.reload());
  </script>
</body>
</html>
`;

// ── PNG иконки (base64) ─────────────────────────────────────
const PNG_ASSETS = {
  "/icons/icon-72x72.png": "iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAABV7bNHAAACV0lEQVR4nO2crU4EMRDH5wg5DTwBJARHgkcgeIqzCAzmzD0FBn2eYEgICUHzAIgzvAEaCBIDqpel1/Y/nXY/up2fvu3HLzOz2b2dEilKCpM+J7+7/vnl/na2mPay1k4njRGC6EpY65PklOKjTVmtDMyVcnlzwh5zOV+xfpdbVnZBITkxQhAhYTklZRvIJyanFB8+WTlEZRHkktOFGBuXqFRJSRcPRYxNTlFb0kUMVQ6Rex3Su6nIqj3ZUMS4sKMpNpKiI6gkOUSb64uNpChBpckxpEhiCypVjkEqiSWodDkGiaToGlSqHEPs+qGgpuXS5Ria+0BRFBTUxZP4EAjtk51iY4keA3c/XkFjTC0bTqo5BdWSWjaufcMUG2v0GND+xA+rtbAhqIbaYxOqRRpBABUE+PdupM30Ojo8oNeXpyxjXVwt6P7xOctYTZrvjsx7I40gwHbXE358ftH+8ano2ofbJZ2fya6VohEEWAuq8fZu47rdawQBVBBABQFUEEAFAVQQQAUBVBBABQFUEGAtqPlZCPeDybGhrzsEqCCACgL8E1RzHXLVHyKNIIgKAmwIqjHNfOlFpBEEgYLGHkVof05BfXX39Y1r394IqqEWhWqPgV2DxiaJu5+goFpSLbRPGEFjTDVOahmib/OlS4pdP+vjhdliOmn+Nb2cr8R/T+/t7tD3+5vo2lQkrVHsCLIHKy2SpH1j0UW4xMaWlKa66BpUWiSldhyKb+ND7lklytfYK35YdU02lGjK2fWsffMAPXkBoGd3APT0F4CeHwTQE6gAeoaZksYfRCkmuotrLugAAAAASUVORK5CYII=",
  "/icons/icon-96x96.png": "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAYAAADimHc4AAADJElEQVR4nO2dO24UQRCGywj5FFyABIHkwAE5B3DkgAgJicyJJVKHFgmxL+CIyJETRz6AhYTEOXBGAgGMPNvTj6ruqq2e6f/Ld6bn/7pq9qHZIgIAADcOvBfA5frL7z/S15yeH3Z/fV0usCZsLr1J6WYxlqGn6EGG6wI8Qk/hJcPlpDXBf/z6Wnyeq7MH8Wv2LWKvJ+MGXxM2F66UfYnYy0k4wVuGnoIjw1qEuYBS+B7Bh5REWEowO/Aagg/xEGEiIBd+j8GH5ERoS1AXkAp/DcGHpERoSlA70Np3fQrralARsKVdn8KqGp61vJhojPCJ0tfT+mm+ScAo4U9YSKgWMFr4E9oSmlvQnK2HP6F5nVUCYrZHCX8idr01VSAWgPCf0JAgEoDwl7RKaLoHjB7+REsObAE9/Xq1Brh5sQSg9ZSpbUVVLQjhx6nJpSgAraeNUn7iCsDuzyPNJysAu1+HXI6iCsDu5yHJKSkAu1+XVJ7sCsDul8HNS/XbUCAnKiAsF+z+OsLcYm0IFeDMc+8FzLm8+EyfPrw3O/6vx0d68fLY7Pg1LCoA7UeXUhtCC3KmqxY05+27E/r+46fKse5urunozSuVY2mDCnAGApzZEYAbsA25GzEqwBkIcAYCnIEAZyDAGQhwBgKcgQBnIMAZCHAGApyBAGd2BITPvNb83w5YEuY4zxkV4AwEOAMBzkCAMwsBuBHrkrsBE6EC3IEAZ6IC0IZ0KLUfIlSAO2wBqAIZ3LySAnr4Y+stkcpT1IJQBTwkOWUFoAp0yOUovgmjCvJI8ykKQBW0Ucqv6m0oqiBOTS4sATGLkLBLLA9O92BXAFqRDG5eTZ+EUQX/aMlBJACtaElt65kQP6R3en54ED5Jc3X2oP40zf3tN9XjWdAaPlFlC0Il6IRPpPxt6CgSNK+z6Z3NiH/grT1HoKkCUifdaiVYDHFobkGjSLCaoIEZMgVWMUNmzpbuC6uaojRn7dWw6jliE5ikxwOzJGmjsyTnYJpqGswTTrCpecIhmKj9BGbK/2eomfIxPGT08Cuf+wJiWMroIfQ5XS0mR42U3sIGAIT8BYsOe89ps42tAAAAAElFTkSuQmCC",
  "/icons/icon-128x128.png": "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAAEgUlEQVR4nO2dP24VQQyHHYRScgJuQJOegoIbIJpISHShTZMDUKeJRJceUXIBCoocIA034ASUNFCteFp2dmY8tsde/74+eX7z+8azf98QAQAAAACAdJzNLsCCL7e//3D/9vLm/NBjdKgvNxJ0L0cRI/yXsAy9RGQZwhXuIfAakYQIU2iE4NdEEMF9gRGDX+NZBLeFSQZ/dXfB/tv760epMlyK4K6g0eBHwm5lVApPIrgphBu8ReA1uEJ4EGF6AZzgPYRegiPDTBGmCtAbvufg1/SKMEuCaQL0hB8p+DU9IsyQwPwDswS/xqsIpgK0hn+k4Ne0imAlgZkALeEfOfg1LSJYSPBE+wOIEP4WLd/X4iqougAIv4wHCVRbTK34rMFvUVsStJYDtQ6A8PuojYdWJ1ARAOHzmCGBuAAIfwxrCUQFQPgyWEogJgDCl8VKAhEBEL4OFhKoXwdA+GNoj9+wAHsWInwZ9sZxtAsMCYDw7dCSgC3AEZ7WPRLcPFSOATD7ddAYV5YAaP3zkF4KRDsAwrdBcpy7BcDa75vefMQ6AGa/LVLj3SUAZn8MenIS6QCY/XOQGPdmATD7Y9Ga13AHwOyfy+j4NwmA2R+TltyGOgBmvw9GcqgKgNkfm1p+7A6A2e8Lbh4mbwYBv0CA5Oy+bVJaP7y0/6+f7+n1q5dTa3jz7gN9+/4wtYZTSm8Yld4sQgdIDgRITlEAnP4di1KeT3v/kZf1f4tnz1+of8b7y7f06faj+udwubq76Po5GiwByYEAyYEAyYEAydkUwPsFILBPKaetXNEBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkrMpQOkZcsmNlIEePe8GoAMkBwIkBwIkBwIkp1sAHAj6pjefogAz97QH8uDtYLAJBEjOrgC4IBSL3h+HIEIHSA8ESA5bACwDvuDmURUAp4OxqeU3tASgC/hgJIcmAdAFYtKS2/BBILrAXEbHv1kAdIFYtOYlchqILjAHiXHvEgBdIAY9OYldCEIXsEVqvLsFQBfwTW8+opeC0QVskBxnlgB7lkECXfbGl9OdVW4GQQIdNMaVLQCOBXzBzWOoA2ApsEO69S8MLwGQQB+t8IkMHgiBBGNoj5+IADULIQGP2rhJHId17xhS4vLm/Gxvm5n760f1H5v+9fOH6v+3xCJ8IuElAJ1ABqvwiRSOASDBGJbhEykdBEICHtbhE1V2Dh2ltvUcNqD4x4zwiZQFIGrbfzCzCC3dUPOqq/p1gJbisy4Js8MnMnozCBL8j4fwiQyWgFNat6M98pLQKrrVzTbzO3o9exIfSYSeDmd5p3XaLd0sIngNfmHqPf3eHcojidB7TDPr+YrpD3Vwtqn3LALnYHbmwzXTBVjgiEDkQwbuGYyHp6qmF7CGK8KChRCjp6wegl9wU8iaURFOGZFC8vqEp+AX3BW0RlKEWXgMfsFtYWsiiuA5+AX3Ba6JIEKE4BfCFFrCgxCRAl8TtvAtLGWIHPoph/gSNUbEOErQAAAAAACn/AXzE+u34aBtCgAAAABJRU5ErkJggg==",
  "/icons/icon-144x144.png": "iVBORw0KGgoAAAANSUhEUgAAAJAAAACQCAYAAADnRuK4AAAFH0lEQVR4nO3dMW4VMRCA4QmKcg+E6JE4AAUNRS6QhgZEgYSUJqKlREqDKCNqOAEFDWegoUKIhhNQpgnVimX1Nmt7xvaM9/9aBNm3/hl7XwJPBAAAAECWo94X0Nuny+sb7Z9xdnGy2/u4mxduEUquPYQ17AvsEcyWEYMa6gV5jGbNKDGFfxGRolkTOaawFz5COEsRQwp3wSOGsxQppDAXWjOcF+8eFP/eq/NvZtexFCEk9xdoGY4mlFyWYXkOye2FWYTTMpgtFkF5DMndBWnD8RTNGm1MnkJycyEiungihLOkCclLRC4uQqQsnojRrCmJyUNE3S9g7+EsRQupa0C58YwczlJuSL0i6hZQTjx7CmcpJ6QeETX/gkydfJ6nUdOAmDo6HqfRnRZfRIR4LOTcl1bfM2wSEPHY8RZR9TGX+iIIJ1/qllZzO6s6gYinrtT7VnMSVQuIeNroHVGVgIinrZ4RNXsKWyIeW73up3lAKZUTTx0p99V6CpkGRDz9tY7ILCDi8aNlRM3OQMTTVqv7bRLQVs3E08fWfbeYQuqA9vDvtEamXT9VQJx7/Kt9Hqp6BiIeH2quQ3FAnHtiqXUe6vZONMZQFBDTJ6YaU8h8AhGPb9brkx0Qj+1jy11f0wnE9InBcp2yAmL67EPOOptNIKZPLFbrlRwQ02dfUtfbZAIxfWKyWLekgJg++5Sy7rwTDRV1QGxfsWnXbzMgtq9921p/1QRi+oxBs46cgaByfNsvRt2+Tp88lo8f3ve+jP98/vJVzp696n0ZRT5dXt+s/QcNxROI7WsspevJFgYVAoLK6hko6vnnkB8/f8nDR6dNv+bL50/l7ZvXTb9mTWvnoKIJxPlnTCXryhYGFQKCCgFBhYCgcjCgkZ7AYOdQF9kTiCewseWuL1sYVAgIKgQEFQKCCgFBhYCgQkBQISCoEBBUCAgqBAQVAoIKAUGFgKCSHVDqR00jptz1PRhQzc8ZR1xm/6wHmBAQVAgIKgQElaKAeBIbU8m6rgbEkxjmzP+DKUCEgKBUHBDnoLGUruetAXEOgsjtHbCFQUUVENvYGDTruBkQ29i+ba2/egtjCsWmXT/OQFBJCohtbJ9S1t1kArGNxWSxbskBMYX2JXW9zc5ATKFYrNYrKyCm0D7krLPpUxhTKAbLdcoOiCk0ttz1NX8fiCnkm/X6FAW0VSkR+bS1LiW7C+9EQ6U4IKZQLDWmj0jlCUREPtRcB1VAKdUSUV8p91/zZK2eQDzWx6ZdP5MtjPOQT7XOPXPNnsKIqK1W99ssIM5DftQ+98yZTiAi6q9lPCIix1Z/0OTs4uRo6yMzr86/Nf3kw/v37sqf39+bfb1eWscj0vGdaCaRrV73s0pAqZUTkY3U+1jjLZdqE4iI2ugZj4hI9TcBUz9CnE+Dztc7HpEGAYnkfQ49IW3Lmdq1v1PQ5BCd8yLY0m7nKR6Rhk9hRKTnLR6RRlvYXM52JsKWJpL/F6rlN7i7fSedc1Eaj1NnruuPYjCN1nmeOnPdf5YnNyKRsUMqOf/1/Jms7gFN9h5StHAm3S9griSiScSYNE+bHuIRcRaQiC4ikRghad+m8BKPiMOAJtqQRHzFZPHelqdwJu4uaMkipEnLoCzfDPUYzsTthS1ZhrSkCavmu+aew5m4v8ClmiF5ESGcSZgLXRoxpEjhTMJd8NIIIUUMZxL2wg+JFFPkaOaGeBGHeIxplGjmhntBa3oENWIwS8O/wC0WYe0hFAAAAPzzF1cQKL6kBlm+AAAAAElFTkSuQmCC",
  "/icons/icon-152x152.png": "iVBORw0KGgoAAAANSUhEUgAAAJgAAACYCAYAAAAYwiAhAAAFPUlEQVR4nO3dv2oVQRSA8aNIrExexdfxBQJ2IggBG1uxsUohVoIIVj6GnVYpbVL6BjbauLAsd+/On3Nmzpn5fr3e2Ttf5uzdhEQEAAAAAIBUD3ovwJsv7/78rf0/nr264H39b9o3QiOkXDOGN80F9wjqyAzBDX2BHqPaM2psw11UpKj2jBTbEBcyQlR7oscWevEjh7UVNbSQi7YO6/r90+J/++HFT7V1nBIttFCL1Q6rJqRc2uFFCS3EIrXCahnUEa3gvIfmenEi9XF5impPbWyeI3O7sJqwIkS1pyY2j6G5W5BIeVyRw9oqDc1bZK4WUxLWSFHtKYnNS2guFiGSH9cMYW3lhuYhsoe9FyBCXKlyr9vDg+iuhRNWuSinWbfAcuIirH05ofWIrMuIJC49Oe9Pj5HZPDDi0uc5sqZHZurFEVa51JHZalw2O8GIq43U96/VSdYkMOJqy1Nk5oERVx9eIjMNjLj68hCZ2Y1eyqIJq52Um3+LG38X3yrCuEwC4/TyJ+X9thiV6oERl189IlMNjLj8ax1Z03sw4vKh5T6oBXZUPXH5crQfWqeYSmAefrAN+jT2tcmI5PTyqcW+VAfGaIzNelRWBUZcY7CMjCf5MFUcGKfXWKxOMU4wmCoKjNNrTBanmPoJRlyxae9fdmA8VJ1b7v6rnmCcXmPQ3MeswDi9IJLXAZ8iYUotMMbjWLT2MzkwxiPWUntQOcE4vcaksa/cg8FUUmCMR5yS0sWj2hfxPB6vLp/I/d333svYdfPmrdx+/NR7GWddv39a9avVGZEwdRgY4xHnHPVRdYJ5Ho/QU7PP1fdg0Tx/+Vo+f/3W5bV///ohjy8uurx2L9yDwdTZwLj/QopznRSfYNx/zaV0vxmRMEVgMEVgMEVgMLUbGJ8gkWOvl6ITjE+QcyrZd0YkTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBUFVvO7ChBXyb7vBmbxF+gxrr1eGJEwRWAwRWAwRWAwVRwYnyTnUrrfZwPjkyRSnOuEEQlTBAZTVYFxHzYH098yzX0YzjnqgxEJU9WBMSbHVru/SYExJnFKSheMSJhSCYwxOSaNfU0OjDGJtdQe1EYkp9hYtPaTezCYygqMMQmRvA5UTzDG5Bg09zE7ME6xueXuv/o9GKdYbNr7VxTYUcVEFtPRvpVMLz5FwlRxYJxiY7E4vUQ4wWCsKjBOsTFYnV4iCicYkcVmGZdIoxFJZD612BeVwHj4OiaNfVU7wRiVsViPxkXTT5FE5kPLfVANLKV6Iusr5f3XvOVRP8GIzK/WcYkYjUgi86dHXCI8yYcx08cLe3+Jfsvqj8xfXT6R+7vvJv+3hps3b+X24yfT10idFFaPmkxPsNRFMy5t9I5LpMGIJLI+PMQl0ugejMja8hKXiPE92Fbve7IZeIpLpHFgIumRiRBajpzTv+X3jps/psi5OEZmGq9xiXR6DkZkejzHJdJhRK7ljEsRRuZa7hderx+pcvFzXISWLkpYCxffKsp9E2Ydm9HiEnFygi1yTzKROU6zki8oD3GJOAtsURKayFixlZ7SXsJauFrMWmlkIrFDqxn/3uIScRzYoiY0kRix1d5Tegxr4XZha7WRLTzFpvVBxXNcIkECW2iFtmgZnPYnX+9hLUIscks7tK2a8KwfoUQJaxFqsVvWoXkSLaxFyEVvjRxa1LAWoRd/ygixRY9qbZgLOSVSbCNFtTbkRZ3iMbZRo1ob/gL39AhuhqC2prvgIxrhzRgSAAAAgEn8AxKVPZPXZ5QCAAAAAElFTkSuQmCC",
  "/icons/icon-192x192.png": "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",
  "/icons/icon-384x384.png": "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",
  "/icons/icon-512x512.png": "iVBORw0KGgoAAAANSUhEUgAAAgAAAAIACAYAAAD0eNT6AAAVAUlEQVR4nO3dvYptV3YG0CXT6Hk6MTjo3IFD40CBocHQ0JkSgVOHRknHipwpsVOD4zY4cCIMDX4WJXKgLpfq3vo55+y91/wb4wF0i7vXmt935j51tRYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD09EX0DwAc8/23P/4U9Wd/9c2XZggU5fJCQpGhfhVlAXJxISFAx4A/SkGAvVw4uJCgP04xgGu4WHASYb+PUgDHuUTwAGGfj1IA93Fh4APCvi6lAN7mcsAnBH5fCgE8cxlgCf2JlAGmcwEYSeDzKYWAaRx4xhD63EoZYAKHnNaEPkcpA3TlYNOO0OcqygCdOMy0IPTZTRmgOgeYsoQ+WSgDVOTQUorQJztlgCocVEoQ/FSjCJCdA0paQp8ulAEycihJR/DTlSJAJg4jaQh+plAEyMAhJJTQZzplgCgOHiEEP7ykCLCbA8dWgh/epwiwi4PGFoIf7qMIcDUHjEsJfjhGEeAqDhaXEPx7/e4Pv97+Z3739Q/b/8zJFAHO5kBxKsF/nohQv4qycB5FgLM4SJxC8D+mU8g/Sjl4jCLAUQ4Qhwj+2wj6+ykGt1EEeJSDw0ME/9uE/XWUgrcpAtzLgeEugv9zAj+OQvA5RYBbOSjcTPgL+wqUAiWA2zgkfGh68Av9uqaXAUWA9zgcvGlq8Av8vqYWAkWA1zgUvGpa+Av9eaaVASWATzkQvDAp+IU+TyaVAUWAJw4Ca605wS/0+ciUMqAI4ADQPvyFPo/qXgaUgNk8/ME6B7/Q52ydy4AiMJOHPlTH8Bf67NKxDCgB83jgwwh+OI8iQGUe9CDdwl/wk0W3IqAEzOAhD9Ap+IU+2XUqA4pAbx5uc13CX/BTTZcioAT05cE21iH8BT/VdSgCSkBPHmpDgh/yUQTIxsNspnL4C32mqFwGlIA+PMhGqoa/4GeqqkVACejBQ2xA8ENtigAR/iL6B+AY4Q/1Vb0PVecPP9PeCqt4+aoOOtil4jbAJqAmD60gwQ/9KQJczcMqplr4C344ploRUALq8KAKqRT+gh/OVakIKAE1+BJgEcIfZqt0ryrNq8m0tOQqXaRKAwoqsw3gDB5MYlXCX/BDjCpFQAnIySuApIQ/8JEq96/KPJtGK0uowmWpMnhgigrbAJuAXGwAkhH+wCMq3MsK820SbSyR7JejwoAB8m8DbAJysAFIQvgDZ8l+X7PPuym0sAQyX4bsgwR4X+ZtgE1ALH/5gTIH/1rCH7rIXALWUgSi+EsPkjn8BT/0lLkIKAH7+Q5AAOEPRMh8vzPPxa4UgM0yH/LMwwE4R+Z7nnk+dmTlslHWw515IADXyfpKwOuAPWwANhH+QDZZ73/WedmNArBB1sOc9fID+2SdA1nnZifWLBfLeIizXnggVsZXAl4HXMcG4ELCH6gk43zIOEe7UAAukvHQZrzcQC4Z50TGedqBAnCBjIc146UGcso4LzLO1eq8WzlZtkOa8SIDdWT7XoDvBJzHBuBEwh/oJtscyTZnK1MAmsp2aYG6zJOeFICTZGqlLitwtkxzJdO8rUwBOEGmw5jpkgK9ZJovmeZuVQrAQZkOYabLCfSUac5kmr8V+TblAVkOX6YLCcyR5TcE/GbAY2wAHiT8gemyzJ8s87gaBeABWQ5blssHzJVlDmWZy5UoAHfKcsiyXDqALPMoy3yuQgG4Q5bDleWyATzJMpeyzOkKFIBislwygE+ZT7UoADfK0CpdLiC7DHMqw7yuQAG4QYbDlOFSAdwiw7zKMLezUwA+kOEQZbhMAPfIMLcyzO/MFIB3ZDg8GS4RwCMyzK8MczwrBSCxDJcH4AhzLC8F4A3RrdGlAbqInmfR8zwrBeAV0Ycl+rIAnC16rkXP9YwUgE9EH5LoSwJwlej5Fj3fs1EAAGAgBeAXotthdDsGuFr0nIue85koAH8WfSiiLwXALtHzLnreZ6EArPjDEH0ZAHaLnnvRcz8DBSBY9CUAiGL+xRpfACJboMMPTBc5B6dvAUYXAOEPEE8JiDG2AEx+6AA8m5oHYwtAJJ/+AV4yF/cbWQCs/gHy8Spgr3EFQPgD5KUE7DOuAEQR/gC3MS/3GFUAprU7AO4zKSfGFACrf4A6vAq43pgCEEX4AzzG/LzWiAIQ1eYcXoBjoubohC1A+wIw4SECcL7u+dG+AETx6R/gHObpNVoXAKt/gB68Cjhf6wIQQfgDXMN8PVfbAtC5tQGwT9c8aVkArP4BevIq4DwtC0AE4Q+wh3l7jnYFoGNLAyBet3xpVwAiaKMAe5m7x7UqABHtzCEEiBExfzttAdoUgE4PBYC8uuRNmwIQwad/gFjm8ONaFACrf4C5vAp4TIsCAADcp3wB8OkfAFuA+5UvALsJf4CczOf7lC4A1dsXALVVzqHSBWA37RIgN3P6dmULQOXWBUAfVfOobAHYTasEqMG8vk3JArC7bTlMALXsntsVtwAlCwAAcEy5AuDTPwC3sAV4X7kCAAAcV6oA+PQPwD1sAd5WqgAAAOcoUwB8+gfgEbYArytTAACA85QoAD79A3CELcDnShSAnYQ/QE/m+0vpC0CFFgUAn8qeX+kLwE7aIUBv5vwzBQAABkpdAHauT7RCgBl2zvvMrwFSFwAA4BppC0Dm1gQAt8qaZ2kLwE7W/wCzmPtJC0DWtgQAj8iYaykLwE5aIMBM0+f/+AIAABOlKwB+9Q+AXSb/SmC6AgAAXC9VAfDpH4Ddpm4BUhUAAGAPBQAABkpTAKz/AYgy8TVAmgIAAOwzrgD49A/Aa6blQ4oCkGUdAgA7ZMi9FAVgl2ntDoD7TMqJUQUAAPhZeAHIsAYBgN2i8y+8AOwyaa0DwOOm5MWYAgAAPAstANHrDwCIFJmDIzYAU9Y5AJxjQm6MKAAAwEu/ivqDrf+J8u//+i/rN3/1l9E/Bon8zd/9dv3xv/47+sdgqO+//fGnr7758ovdf277DcCENQ4A5+ueH+0LAADwuZACYP0PAM8icrH1BqD7+gaAa3XOkdYFAAB4nQIAAANtLwC73nN0XtsAsM+uPNn9PQAbAAAYSAEAgIG2FgDrfwAq6vgawAYAAAZSAABgIAUAAAbaVgC8/wegsm7fAwj73wFDRb/5679d//On/43+MXjFP//TP67f/8PfR/8YUIZXAAAwUKsCYP0PwJU65UyrAgAA3GZLAYj4/xwDQFU7ctMGAAAGUgAAYKA2BaDTFzMAyKtL3rQpAADA7S4vAL4ACAD3uzo/bQAAYKAWBaDL+xgAauiQOy0KAABwHwUAAAa6tAD4AiAAPO7KHLUBAICByheADl/EAKCe6vlTvgAAAPdTAABgIAUAAAa6rAD4DQAAOO6qPLUBAICBSheA6t/ABKC2yjlUugAAAI9RAABgIAUAAAZSAABgIAUAAAa6pAD4NwAA4DxX5GrZDUDlX70AoI+qeVS2AAAAj1MAAGAgBQAABlIAAGAgBQAABlIAAGAgBQAABlIAAGAgBQAABjq9APhngAHgfGfna8kNQNV/dhGAnirmUskCAAAcowAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAlC8B3X/8Q/SMAwP+rmEunF4Cvvvnyi7P/mwAw3dn5WnIDAAAcowAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMpAAAwEAKAAAMVLYAVPxnFwHop2oeXVIA/HPAAHCeK3K17AYAAHicAgAAAykAADCQAgAAAykAADBQ6QJQ9VcvAOihcg6VLgAAwGMuKwD+LQAAOO6qPLUBAICBFAAAGEgBAICByheAyt/ABKCu6vlTvgAAAPe7tAD4TQAAeNyVOWoDAAADKQAAMFCLAlD9ixgA1NIhd1oUAADgPpcXAF8EBID7XZ2fNgAAMFCbAtDhfQwA+XXJmzYFAAC4nQIAAANtKQC+CAgAt9uRmzYAADBQqwLQ5YsZAOTUKWdaFQAA4DYKAAAMtK0A7PoiYKf1DAB57MqXXXlpAwAAAykAADCQAgAAA20tAL4HAEBF3d7/r2UDAAAjKQAAMND2AuA1AACVdFz/r2UDAAAjKQAAMFDrAuA1AABHdM6RkAKw+z0HAGQWkYutNwAAwOvaF4DO6xsArtM9P8IKgNcAABCXh+03AADA50YUgO5rHADONSE3QguA1wAATBaZgyM2AADAS2MKwIR1DgDHTcmL8ALgNQAAE0XnX3gBAAD2G1UApqx1AHjMpJxIUQCi1yAAsFOG3EtRAHaa1O4AuN20fBhXAACARAVg5zpkWssD4H07cyHD+n+tRAUAANhHAQCAgVIVAK8BANht4vp/rWQFAADYI10BsAUAYJepn/7XSlgAAIDrjS8AtgAAM02f/ykLQLY1CQAckTHXUhaA3aa3QIBpzP3EBSBjWwKAe2XNs7QFAAC4TuoC4FcCATjb5F/9+6XUBQAAuIYC8Au2AAC9mfPP0heAzOsTAHhL9vxKXwB20w4BejLfXypRAHa3KIcEoJfdcz37p/+1ihQAAOBcZQqALQAAj/Dp/3VlCgAAcJ5SBcAWAIB7+PT/tlIFAAA4R7kCYAsAwC18+n9fuQIAABxXsgDYAgDwHp/+P1ayAERQAgBqMK9vU7YAVGxbAPRTNY/KFoAIWiVAbub07UoXgKqtC4AeKudQ6QIQQbsEyMl8vk/5AhDRvhwygFwi5nLlT/9rNSgAAMD9WhQAWwCAuXz6f0yLAhBFCQCIZQ4/rk0B6NDGAMivS960KQBreRUAMInV/zGtCkAUJQBgL3P3uHYFoFM7AyCPbvnSrgBE0UYB9jBvz9GyAES1NIcS4FpRc7bbp/+1mhaAtXo+LAD265onbQtAFFsAgGuYr+dqXQC8CgDower/fK0LQCQlAOAc5uk12heAzu0NgOt0z4/2BWAtrwIAqrL6v86IAhBJCQB4jPl5rTEFILLNOcQA94mcmxM+/a81qACsNeehAvCYSTkxqgBEsgUAuI15uce4AuBVAEBeVv/7jCsAaykBABkJ/71GFoBoSgDAS+bifmMLwMS2B8DnpubB2AKwllcBABlY/ccYXQDWUgIAIgn/OOMLQDQlAJjK/IulAKz4FugSANNEz73ouZ+BAvBn0Ych+jIA7BI976LnfRYKwC9EH4roSwFwteg5Fz3nM1EAAGAgBeAT0e0wuh0DXCV6vkXP92wUgFdEH5LoSwJwtui5Fj3XM1IA3hB9WKIvC8BZoudZ9DzPSgFILPrSABxljuWlALwjQ2t0eYCqMsyvDHM8KwXgAxkOT4ZLBHCPDHMrw/zOTAG4QYZDlOEyAdwiw7zKMLez+1X0D1DFV998+cX33/74U+TP8N3XP6zf/eHXkT/CeP/5H/8W/SNAasK/DhuAYjJcLoDXmE+1KAB3yNIqXTIgmyxzKcucrkABuFOWw5XlsgFkmUdZ5nMVCsADshyyLJcOmCvLHMoylytRAB6U5bBluXzAPFnmT5Z5XI3fAjggw28GrPV8Cf2GALBDluBfS/gfYQNwUKbDl+lSAj1lmjOZ5m9FCsAJMh3CTJcT6CXTfMk0d6tSAE6S6TBmuqRAD5nmSqZ5W5kC0FSmywrUZp70pACcKFsrdWmBo7LNkWxztjK/BXCyLL8Z8MRvCACPyBb8awn/s9kAXCDjIc14mYGcMs6LjHO1OgXgIhkPa8ZLDeSScU5knKcd+Eu9WKbXAU+8DgBeI/xn8Re7QcYSsJYiAPwsY/CvJfyv5hXABlkPcdZLD+yTdQ5knZudKACbZD3MWS8/cL2s9z/rvOzGX/JmWV8HrOWVAEyRNfjXEv472QBslvlwZx4KwDky3/PM87EjBSBA5kOeeTgAx2S+35nnYlf+wgNlfh2wllcC0EXm4F9L+Efxl55A5iKgBEBtmcNf8Mfyl59E5hKwliIA1WQO/rWEfwa+A5BE9suQfZgAz7Lf1+zzbgoPIZnsm4C1bAMgq+zBv5bwz8QGIJkKl6PCkIFpKtzLCvNtEg8jqQqbgLVsAyBaheBfS/hnZAOQVJXLUmX4QEdV7l+VeTaNh5JclU3AWrYBsEuV4F9L+GfmwRShCACCnzN5BVBEpctUaUhBFZXuVaV5NZmHVEylTcBatgFwVKXgX0v4V+JBFVStBKylCMC9qgX/WsK/Gg+rMEUA+hH87OKhFVexBKylCMCnKgb/WsK/Ml8CLK7q5as67OAKVe9D1fnDzzy8RmwDoBbBTyQPsZmqJWAtRYA5qgb/WsK/Ew+yocol4IkyQDeVQ/+J8O/Fw2xMEYB4gp+sPNTmOpSAtRQB6ukQ/GsJ/8482AG6lIC1FAHy6xL8awn/7jzcQToVgbWUAfLoFPprCf4pPORhupWAtRQB4nQL/rWE/yQe9FCKADxO8NOBBz5YxxLwRBngbB1D/4nwn8lDp3URWEsZ4HGdQ38twT+dh89aq38JeKIM8JHuof9E+OMA8MKUIrCWMsCzKaG/luDnmYPAqyYVgbWUgYkmhf5agp/PORC8aVoJeKIM9DUt9J8If17jUPChqUXgiUJQ19TAfyL4eY/Dwc2mF4G1lIEKpof+WoKf2zgk3EUJ+JxSEEfYf074cysHhYcoAm9TCK4j8N8m+LmXA8MhisBtlIL7CfvbCH4e5eBwCkXgMYqBoH+U4OcoB4hTKQLn6VQOhPx5BD9ncZC4hCKwV0RZEOp7CX7O5kBxKUUAjhH8XMXBYgtFAO4j+LmaA8ZWigC8T/Czi4NGCEUAXhL87ObAEUoRYDrBTxQHjzSUAaYQ+mTgEJKOIkBXgp9MHEbSUgToQvCTkUNJCcoA1Qh9snNAKUURIDvBTxUOKmUpA2Qh9KnIoaUFZYDdhD7VOcC0owxwFaFPJw4zrSkDHCX06crBZgxlgFsJfSZwyBlJGeBTQp9pHHhYCsFEAp/pXAD4hDLQl9CHZy4DfEAhqEvgw9tcDniAUpCPsIf7uDBwEqVgH2EPx7lEcCGl4DhhD9dwsSCAYvA5QQ97uXCQUMeCIOAhFxcSiossC0IdAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIDk/g/Uplb45t768AAAAABJRU5ErkJggg==",
  "/icons/apple-touch-icon.png": "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",
  "/favicon-16x16.png": "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAADVElEQVR4nE2TXUybdRTGn/N/37a00GG/xkc/2GzH1jJEhMKUyJDJ8MLFzYWqM0uM8wI1fiWTC2+6xotNE+NHlnhhJGaLcZaFTHdDvGmWxRkdY8IYCGpgbApjLEBA+7Z9///jxezCc3UunnPyJOf5Ef4XJ1lQihQA8DiHfryMzrnFfIvQmNxO22/NUWTc7TQGAOk0a4kESQAgAEgmWaRSpHiYvWcy5vFLE4MHp25dcS0s3wSzhNtZiXBl1NgVO5DpbKzoi+yj8XQPa4kBkkgmWQDA9DmOfdA3NtsQP8TCE2Dh8UuLr8a0+LaYmicg4a7mULST3+0dyl7s52eLSXTgGPgGu06cHB36dPDV4OLyjcKmUq8OQDAU7sUkAITbd2fMTwZ7S6Q6mZ48x7ui+2kYAHDqxD9fPNzyIgt3dd4VbGCnP8Y23za2eMJs8YTZ5ouw0x/j8kA92ysjBe/WOH/YNz7CzHadRznw+kffHhr78wJvKvPqpiwAAGpCftjtJQADRi6H+YVFKJawWUv1pZU59dPk+cbL39R1iczP6P5j/lcHoJgAyuXyCAX9eOe1I2hqqEdTYz3e6n0Z4QdrYBg5gBWsFgdP3RrmidnVA/r8SrZ5YXkWmrCwYoZSCqUOO4ZHrqH/836AgPyRwyh12KGUAoNh0ay0tPoX3Vm5+YguFevMqvhRAIBSDJvNCovrAYCAEpsNSjE2illCKqXrHqdj0u2sglIFIqINBoaUEqB7c1EEQKoCl5dtZleZb1o8Xo+hrRU7TcmKBNF9JxFBCAEhBDYeJtJgFLIUrnqIaoNV3wtXh2Uivr07E6qI0b/GuiShAQCyhgFzbR3m2jqyWaO4DcWmslvL0FLbPd/RhvNCKpOe2R18I9F+NM9QWqGQlYI01O2oRbytFfG2VuyMbYcQGgBWq2u35XNP9Imu5t1v0g5a0tM9LAJ7aOriV/y8VJ+dPf3DMW10ckQFQz7eFtlCRMDVsVFcvTYCXSdxeM9xcfCxV1LtL9HZZDKjo9hpALjyNT/68Xu//7L/6fc5ENnLJb46tnqjvLmmnbuePMqpty/NZL7kF4oA3qdxI6LMbL0+iKeuz+X2/X1nJk7EcDurp2v95UOtTfiOYnS3pyetDQwkJAD8B7V6gDkR4hKNAAAAAElFTkSuQmCC",
  "/favicon-32x32.png": "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAHqElEQVR4nK1XaWxU1xX+zn3L2DNjzxiMjcEQ2w0QVqmFNim4BCKW0hTSUNtqVaGkIXLUhFCBRVqg1fOkcWlBMgGiiiUNIBoEdhERgRax2WnaItqwCUxLTG1cMJsdb+PxzLx33z39YQwm3kjJJ50fb+7cc77z3XPuQhgADKZiC1ooRLL77z8rPBoIDkoXsajL6UM1enXlpObu42VlrFVVgUMhUv35p/4Gy/JZKygnFwDG5VtmybeKn/QnYAEIWdEophHBUADrAgTGBdJwPWbjYO3VqmNF6yc0dREpKOj08YUIVFiszwyRLCw84J07dv7LvkS8Fonx6Lo7l9HQegNnq4/DlnEIISCljfFZ0zBscDayhk5C0Gs2MWH3tRsNG3/yVlo1M1NxMag3NXohwGRZnX/eURKemZrif8dVGHfkkzIcOrWN6xurXUfGSQhdAHzPDbNSRMQp/nSaNuF5bWHuEqQHgh2RuPPLvGVmKQCwxYI+R+IBAsxMAEBEvLc0ssyf4C3968XD2Hm0RN5sqhEePVGYRiKI+l45KW1E7Xb2epLcOZMX6YvnrQIz9lysu77i52tHXLcsFt2V6OaJybKgXbpUzt9/asH2tKBn0Zrdb7hHz75PiaZXeAwvFCsw91tTIBCE0CBdB5FYK48cMla+9VK5keJPqf302n9nLVszsrb7coiuidbdSn9uyrNL04KeRW/uWh4/emaXFvANFoaeAFfJAYMDAIPhKglBAgH/EKpvqjZWbPmu3RJpzs7JGLmDiERn3LtqA/cr9d1ftU3PTE06UbpvpTpyerse9KeTq2S/AQeCJnR0xNswOCnTefu1Y4ZGnvV5y2i5ZbEeCpEUzExVVWCr8IA3LZC07aMLx7UjZ3ZogS8hOAC4SsKXEMCt5v/omz9cKb0eLP3Dmo7poZCQZWWsicpiaKEQqfFj5r8IgdE7j1gywfQL9CE3EfVrvUG6DpJ9qVR5fg9duHpRS/IlvgmwQDkgZhTDfeGF7QkeAyuOfPJHvtlUc6/gPg9mhuM4sO3ezXH6V0zXTK2scp2r63h6569bnywoJ1cnIn5/rf1VlzHy0KktyjS8Wm/FxszQdR0pwQA0Tes1gONIhNvbwcw9xpRykehJwrmaCq6ur8GojJyFAE7qABD0Gfn/rq8W1xurZaInqUe1CyHQ3h5B7je/jn27NqM90vGA3MwMQQTbcTB9XgGaW1th6HoPIkQEpVzxt6oPkJO+fIFVeMDSGUx/AnIaW67BcePwUjJ6SQCu6yIYSMblKzVY+KNC+HxeKMUgIjhSIpicjD3b34HHY4BV3+0qhKBbTTVgIC0lIStJL/5pZeBr7oxvnLlyHIL60LYbOjqiuH3rDrx+3wME4jEbtm33O5eVgml4qbr+tBuJ28nZOROn6wm2TgSYjowPFLsrA+imCdM07hEgQTBNo98tugsEgiNtABBMMHUAYEAJMWDy9zNhvmfdvx8WQnRuwEpBCdPWiADjYRV4VBAI0nW6PkzR1na9XQicG581Dfwwm/2jBCeCLaOckzFJeAwzHImE/ylC5QW2EKgdnjoKIDy8jv8fA7hKIi3lMTIEIuf+9UGdAADHxp+z0sfzIH86HGmD+r+pPRIUK3fy43NZ01Dp/8qiqACAK3UnjyclGOHcCQu1qB1m+gIF+bAgErCdGEakjsLk0bkUiWNfKERKVFisF62f2uQo7H4+dwn5PMmuq5wvXQUhBKLxNvXc1Nc1U0NdVe2pI8xMYgagAODmndrfpAWC0TmTf0yRaAsLTe8jE4KuaT2sr/MBAARpiMUjyEqf6M6ZkkfhDndtaNNTbZXF0ASFSFkW60tKcupaIu7qxd95QxsxZLxsjzZDEz1JRGMxxBsb8FlDI5obGtHU0IhwQyMaGj/r9TQkElDswpYxuXThJgPAxyeqf7+trIy1mSGSOgCEQnAti/X9/yjY+MNpZVNLXtqbt2LLArupvd70JQSg2O1sIcfBrKdzcbTiIHRdA3PnlcpVCh7TxJhR2ZDSBe7uiII0KHbREQvLorytYszwJ27X3bn94tathTIjA/evZABgWSyKi8EbVtWkPZ6Zc7Il0py9YssC51ZzjRHwpcKREoNSApg9Mxd+n7dnvzKjsakZh49+BOm60ISGmBOB7cRlUd5m/dtTnkXt7XDey79I3td1Heshl2WxAIB1q29mf/g7PrG3NMwzZrzu0uBh0kzLYl/GWEbSYwxvJiNx2IPmHc4IZHEgcyInDh3FSBnqZj0xyy5ddZ4Pb+Zr75a0/OBujAfWtUepd7+379/ApbqOZZfqzqKsslSdr/2LImIhSCPTSCQiQuc6EBwnxlJJONJWmalj8L2pr2qzpxTA1FBRfb1u8dKSrNreMu+117qUCIVIvbcm/ExG0L9aMZ75tP4y/l51ELearqK6/rRypM1CCLiug+yMSVpaMBOTR8/F5FHT4fXgSls7NuUX0cauzHuTvd9mt6wKPRSaKQFgz7qO6YMDifNdF/McF0PbOuKDu45fBsPUPNEEA62ahoqYjf3vHdt66ODBVzr6excOSADofDPk50MREQPAuHH5ZtErGwIpnDFD12BICfZ6Qc3N8bPnaj6+8duts1u75nY9cPvz/z+rHciWnreMiQAAAABJRU5ErkJggg==",
};

// ── b64 → ArrayBuffer ───────────────────────────────────────
function b64toAB(b64) {
  const bin = atob(b64);
  const ab  = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) ab[i] = bin.charCodeAt(i);
  return ab.buffer;
}

// ── CORS headers ────────────────────────────────────────────
const CORS = {
  "Access-Control-Allow-Origin":  "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

// ── Main handler ────────────────────────────────────────────
export default {
  async fetch(request, env, ctx) {
    const url    = new URL(request.url);
    const path   = url.pathname;

    // OPTIONS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    // ── /manifest.json ──────────────────────────────────────
    if (path === "/manifest.json") {
      return new Response(MANIFEST_JSON, {
        headers: {
          "Content-Type":  "application/manifest+json; charset=utf-8",
          "Cache-Control": "public, max-age=86400",
          ...CORS,
        },
      });
    }

    // ── /sw.js ──────────────────────────────────────────────
    if (path === "/sw.js") {
      return new Response(SW_JS, {
        headers: {
          "Content-Type":  "application/javascript; charset=utf-8",
          "Cache-Control": "public, max-age=3600, must-revalidate",
          "Service-Worker-Allowed": "/",
          ...CORS,
        },
      });
    }

    // ── /offline.html ───────────────────────────────────────
    if (path === "/offline.html") {
      return new Response(OFFLINE_HTML, {
        headers: {
          "Content-Type":  "text/html; charset=utf-8",
          "Cache-Control": "public, max-age=86400",
          ...CORS,
        },
      });
    }

    // ── PNG иконки и фавиконы ───────────────────────────────
    if (PNG_ASSETS[path]) {
      return new Response(b64toAB(PNG_ASSETS[path]), {
        headers: {
          "Content-Type":  "image/png",
          "Cache-Control": "public, max-age=604800, immutable",
          ...CORS,
        },
      });
    }

    // ── Всё остальное — проксируем на Streamlit ─────────────
    const targetUrl = new URL(path + url.search, STREAMLIT_URL);
    const proxyReq  = new Request(targetUrl.toString(), {
      method:  request.method,
      headers: request.headers,
      body:    request.method !== "GET" && request.method !== "HEAD"
               ? request.body : undefined,
    });

    try {
      const resp = await fetch(proxyReq);

      // Для HTML-ответов Streamlit — инжектируем PWA meta-теги
      if (resp.headers.get("Content-Type")?.includes("text/html")) {
        const html = await resp.text();
        const pwaHead = `
  <!-- PWA Meta Tags injected by Cloudflare Worker -->
  <link rel="manifest" href="/manifest.json" />
  <meta name="mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <meta name="apple-mobile-web-app-title" content="OddsDash" />
  <meta name="application-name" content="OddsDash" />
  <meta name="msapplication-TileColor" content="#0d1b2a" />
  <meta name="theme-color" content="#0d1b2a" id="theme-color-meta" />
  <link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png" />
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png" />
  <script>
    // Register Service Worker
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js', {scope: '/'})
          .then(reg => console.log('[PWA] SW registered:', reg.scope))
          .catch(err => console.warn('[PWA] SW failed:', err));
      });
    }
    // PWA Install prompt
    let deferredPrompt;
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      const btn = document.getElementById('pwa-install-btn');
      if (btn) btn.style.display = 'flex';
    });
    window.addEventListener('appinstalled', () => {
      deferredPrompt = null;
      const btn = document.getElementById('pwa-install-btn');
      if (btn) btn.style.display = 'none';
    });
    function installPWA() {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(() => { deferredPrompt = null; });
      }
    }
  </script>
`;
        const patched = html.replace("</head>", pwaHead + "
</head>");
        const newHeaders = new Headers(resp.headers);
        newHeaders.delete("Content-Security-Policy"); // allow SW
        return new Response(patched, {
          status:  resp.status,
          headers: newHeaders,
        });
      }

      return resp;
    } catch (err) {
      return new Response(OFFLINE_HTML, {
        status:  503,
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }
  },
};
