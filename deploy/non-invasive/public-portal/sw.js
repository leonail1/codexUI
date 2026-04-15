self.addEventListener('install', (event) => {
  self.skipWaiting()
  event.waitUntil(Promise.resolve())
})

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys()
    await Promise.all(keys.map((key) => caches.delete(key)))
    await self.clients.claim()
  })())
})

self.addEventListener('fetch', () => {
  // Intentionally no-op. The public portal should not cache the upstream app shell.
})
