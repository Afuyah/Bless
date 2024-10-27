const CACHE_NAME = 'my-cache-v1';
const urlsToCache = [
    '/',
    '/static/css/styles.css',
    '/static/js/sales.js',
    '/static/images/icon-192x192.png',  // Ensure this path is correct
    // Add any other resources you need to cache
];

// Install the service worker
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('Caching files:', urlsToCache);  // Log cached files
                return cache.addAll(urlsToCache).catch((error) => {
                    console.error('Failed to cache files:', error);  // Catch errors
                });
            })
    );
});

// Fetch resources from the cache
self.addEventListener('fetch', (event) => {
    event.respondWith(
        caches.match(event.request)
            .then((response) => {
                return response || fetch(event.request);
            })
    );
});

// Activate the service worker and clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});
