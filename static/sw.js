// ── SIAP RSSR Service Worker ──────────────────────────────────────────────
var CACHE_NAME = 'siap-rssr-v1';

// Aset statis yang di-cache saat install
var PRECACHE = [
  '/',
  '/static/manifest.json',
];

// ── Install: pre-cache aset utama ─────────────────────────────────────────
self.addEventListener('install', function(e) {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(PRECACHE);
    }).catch(function() {}) // jangan gagal install karena cache error
  );
});

// ── Activate: hapus cache lama ────────────────────────────────────────────
self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== CACHE_NAME; })
            .map(function(k) { return caches.delete(k); })
      );
    }).then(function() { return self.clients.claim(); })
  );
});

// ── Fetch: Network-first, fallback ke cache ───────────────────────────────
self.addEventListener('fetch', function(e) {
  var req = e.request;

  // Hanya handle GET
  if (req.method !== 'GET') return;

  // Jangan intercept request API / form POST
  var url = new URL(req.url);
  var isAPI = url.pathname.startsWith('/webauthn') ||
              url.pathname.startsWith('/api') ||
              url.pathname.startsWith('/absen') ||
              url.pathname.startsWith('/admin');

  if (isAPI) return; // biarkan browser handle langsung

  e.respondWith(
    fetch(req)
      .then(function(res) {
        // Simpan salinan ke cache jika sukses
        if (res && res.status === 200 && res.type !== 'opaque') {
          var clone = res.clone();
          caches.open(CACHE_NAME).then(function(c) { c.put(req, clone); });
        }
        return res;
      })
      .catch(function() {
        // Offline → coba dari cache
        return caches.match(req).then(function(cached) {
          if (cached) return cached;
          // Fallback halaman offline sederhana untuk navigasi
          if (req.mode === 'navigate') {
            return new Response(
              '<!DOCTYPE html><html lang="id"><head><meta charset="UTF-8">' +
              '<meta name="viewport" content="width=device-width,initial-scale=1">' +
              '<title>Offline – SIAP RSSR</title>' +
              '<style>*{font-family:sans-serif;margin:0;padding:0;box-sizing:border-box}' +
              'body{min-height:100dvh;display:flex;flex-direction:column;align-items:center;' +
              'justify-content:center;background:#0f172a;color:#fff;padding:24px;text-align:center}' +
              'h1{font-size:48px;margin-bottom:16px}p{color:#94a3b8;margin-bottom:24px;font-size:15px}' +
              'button{background:#2563eb;color:#fff;border:none;padding:12px 24px;border-radius:12px;' +
              'font-size:15px;font-weight:700;cursor:pointer}</style></head>' +
              '<body><h1>📡</h1><h2 style="font-size:22px;font-weight:700;margin-bottom:8px">Tidak Ada Koneksi</h2>' +
              '<p>Periksa koneksi internet Anda<br>lalu coba lagi.</p>' +
              '<button onclick="location.reload()">Coba Lagi</button></body></html>',
              { headers: { 'Content-Type': 'text/html' } }
            );
          }
        });
      })
  );
});