const CACHE_NAME = 'my-cache-v1';
const urlsToCache = [
    '/',
    '/static/css/styles.css',
    '/static/js/script.js',
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

// Fetch resources with network-first strategy for API calls
self.addEventListener('fetch', (event) => {
    if (event.request.url.includes('/api/')) {
        // Network-first strategy for API requests
        event.respondWith(
            fetch(event.request)
                .then((response) => {
                    // Update cache with the latest response
                    return caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, response.clone());
                        return response;
                    });
                })
                .catch(() => {
                    return caches.match(event.request);
                })
        );
    } else {
        // Cache-first strategy for other requests
        event.respondWith(
            caches.match(event.request)
                .then((response) => {
                    return response || fetch(event.request);
                })
        );
    }
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
    return self.clients.claim(); // Claim clients immediately
});

// Notify clients of new content
self.addEventListener('message', (event) => {
    if (event.data.action === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});
