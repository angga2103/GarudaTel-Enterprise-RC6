
const CACHE_NAME = 'garudatell-v3';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
    // Mode Bypass: Membiarkan request PPOB langsung ke server agar transaksi tidak nyangkut di cache
});
