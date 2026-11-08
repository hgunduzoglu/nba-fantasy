/* Trade Lab service worker: ana ekrana eklenen uygulama için.
   Veri (/api) hiç önbelleğe alınmaz; derlenmiş dosyalar (/assets, adları içerik özetli) önbellekten,
   sayfa önce ağdan (yeni sürüm hemen gelir), ağ yoksa son kopyadan. */
const CACHE = "tl-shell-v1";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE);
      const hit = await cache.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) cache.put(req, res.clone());
      return res;
    })());
    return;
  }

  if (req.mode === "navigate") {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE);
      try {
        const res = await fetch(req);
        if (res.ok) cache.put("/", res.clone());
        return res;
      } catch (err) {
        const hit = await cache.match("/");
        if (hit) return hit;
        throw err;
      }
    })());
  }
});
