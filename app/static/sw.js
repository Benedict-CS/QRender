const CACHE_NAME = 'qrender-v1';
const ASSETS = [
  '/',
  '/static/logo.png',
  '/static/images/demo_microdot_1.png',
  '/static/images/demo_microdot_2.png',
  '/static/images/demo_microdot_3.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS);
    })
  );
});

self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request);
    })
  );
});
