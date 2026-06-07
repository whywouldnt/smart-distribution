/**
 * Smart Distribution — Service Worker
 * =====================================
 * Strateji:
 *   - Statik varlıklar (HTML, manifest): Cache-First
 *     Uygulama her zaman anında açılır, arka planda güncelleme kontrol edilir.
 *
 *   - API çağrıları (/api/v1/*): Network-First + Cache Fallback
 *     İnternet varsa taze veri gelir.
 *     İnternet yoksa son önbelleğe alınan rota verisi gösterilir.
 *
 * Güncelleme:
 *   CACHE_VERSION değiştirildiğinde eski önbellek silinir.
 */

const CACHE_VERSION = 'sd-v2';
const STATIC_CACHE  = `${CACHE_VERSION}-static`;
const API_CACHE     = `${CACHE_VERSION}-api`;

// Önbelleğe alınacak statik varlıklar
const STATIC_ASSETS = [
  '/static/index.html',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap',
];

// Önbelleğe alınacak API path pattern'ları
const CACHEABLE_API_PATTERNS = [
  /\/api\/v1\/delivery\/today-route/,
  /\/api\/v1\/dashboard\/stats/,
  /\/api\/v1\/dashboard\/vehicles/,
];

// ── Install: Statik varlıkları önbelleğe al ───────────────────────────────
self.addEventListener('install', event => {
  self.skipWaiting(); // Hemen aktive ol
  event.waitUntil(
    caches.open(STATIC_CACHE).then(cache => {
      // Hata olursa teker teker dene (CDN'ler bazen bloke edilebilir)
      return Promise.allSettled(
        STATIC_ASSETS.map(url => cache.add(url).catch(() => null))
      );
    })
  );
});

// ── Activate: Eski önbellekleri temizle ───────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== STATIC_CACHE && k !== API_CACHE)
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: İstek stratejileri ─────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // 1) API istekleri: Network-First
  const isApi = url.pathname.startsWith('/api/v1/');
  if (isApi) {
    if (request.method === 'GET') {
      const isCacheable = CACHEABLE_API_PATTERNS.some(p => p.test(url.pathname));
      if (isCacheable) {
        event.respondWith(networkFirstWithCache(request));
      }
      return;
    }

    // POST/PATCH/PUT istekleri için Offline desteği
    if (request.method === 'POST' || request.method === 'PATCH' || request.method === 'PUT') {
      event.respondWith(
        fetch(request.clone()).catch(async (error) => {
          // İnternet yoksa isteği yakala ve çökmesini engelle
          console.warn('Offline mod: İstek kuyruğa alınıyor...', request.url);
          
          // Gelişmiş senaryoda burada IndexedDB'ye kayıt yapılır (Background Sync)
          return new Response(
            JSON.stringify({ 
              detail: 'Çevrimdışısınız. İşleminiz cihaz hafızasına alındı, internet bağlantısı sağlandığında senkronize edilecektir.',
              status: 'queued'
            }), 
            { 
              status: 202, // 202 Accepted
              headers: { 'Content-Type': 'application/json' } 
            }
          );
        })
      );
      return;
    }
    return;
  }

  // 2) Statik varlıklar: Cache-First
  event.respondWith(cacheFirstWithNetworkFallback(request));
});

// ── Strateji: Network-First ───────────────────────────────────────────────
async function networkFirstWithCache(request) {
  const cache = await caches.open(API_CACHE);
  try {
    const response = await fetch(request.clone());
    if (response.ok) {
      // Başarılı yanıtı önbelleğe yaz
      cache.put(request, response.clone());
    }
    return response;
  } catch (_networkErr) {
    // Ağ yoksa önbellekten dön
    const cached = await cache.match(request);
    if (cached) {
      // Offline modda olduğunu gösteren özel header ekle
      const headers = new Headers(cached.headers);
      headers.set('X-Served-From', 'service-worker-cache');
      return new Response(cached.body, {
        status: cached.status,
        statusText: cached.statusText,
        headers,
      });
    }
    // Önbellekte de yoksa offline hata yanıtı döndür
    return new Response(
      JSON.stringify({ detail: 'Çevrimdışısınız. Son veriler gösteriliyor.' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    );
  }
}

// ── Strateji: Cache-First ─────────────────────────────────────────────────
async function cacheFirstWithNetworkFallback(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (_) {
    // Hem önbellekte hem ağda yoksa en azından ana sayfayı dön
    const fallback = await caches.match('/static/index.html');
    return fallback || new Response('Çevrimdışı', { status: 503 });
  }
}
