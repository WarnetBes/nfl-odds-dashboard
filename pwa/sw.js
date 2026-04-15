// ─────────────────────────────────────────────────────────
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
