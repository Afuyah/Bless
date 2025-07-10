const APP_VERSION = 'v3.1.0-nawiri-pos';
const CACHE_PREFIX = 'nawiri-cache';
const CACHE_NAME = `${CACHE_PREFIX}-${APP_VERSION}`;
const API_CACHE_NAME = `${CACHE_PREFIX}-api-${APP_VERSION}`;
const OFFLINE_CACHE_NAME = `${CACHE_PREFIX}-offline-${APP_VERSION}`;

// Precached application shell and critical assets
const PRECACHE_ASSETS = [
  '/',
  '/manifest.json',
  '/static/css/main.css',
  '/static/js/main.js',
  '/static/images/logo.svg',
  '/static/images/icon-192x192.png',
  '/static/images/icon-512x512.png',
  '/static/fonts/Inter.woff2',
  '/offline',
  '/static/offline-data.json' // Pre-cached offline data
];

// Dynamic routes to cache (with offline fallbacks)
const DYNAMIC_CACHE_ROUTES = [
  { route: '/sales', offline: '/static/offline-sales.html' },
  { route: '/products', offline: '/static/offline-products.json' },
  { route: '/customers', offline: '/static/offline-customers.json' }
];

// API endpoints to cache (with appropriate strategies)
const API_CACHE_ENDPOINTS = [
  { pattern: /\/api\/products/, strategy: 'stale-while-revalidate', maxAge: 3600 },
  { pattern: /\/api\/sales/, strategy: 'network-first', maxAge: 1800 },
  { pattern: /\/api\/inventory/, strategy: 'cache-first', maxAge: 86400 }
];

// ========== Service Worker Lifecycle Events ========== //

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      // Create and populate the cache
      const cache = await caches.open(CACHE_NAME);
      await cache.addAll(PRECACHE_ASSETS);
      
      // Cache offline fallbacks for dynamic routes
      const offlineCache = await caches.open(OFFLINE_CACHE_NAME);
      await Promise.all(
        DYNAMIC_CACHE_ROUTES.map(({ offline }) => offlineCache.add(offline))
      );
      
      console.log(`Service Worker ${APP_VERSION} installed`);
      self.skipWaiting(); // Activate immediately
    })()
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Clean up old caches
      const cacheKeys = await caches.keys();
      await Promise.all(
        cacheKeys.map((key) => {
          if (key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME && key !== API_CACHE_NAME && key !== OFFLINE_CACHE_NAME) {
            console.log(`Deleting old cache: ${key}`);
            return caches.delete(key);
          }
        })
      );
      
      // Claim all clients immediately
      await self.clients.claim();
      console.log(`Service Worker ${APP_VERSION} activated`);
      
      // Send notification to all clients
      const clients = await self.clients.matchAll();
      clients.forEach(client => {
        client.postMessage({
          type: 'SW_ACTIVATED',
          version: APP_VERSION
        });
      });
    })()
  );
});

// ========== Advanced Fetch Handling ========== //

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  
  // Skip non-GET requests and chrome-extension
  if (request.method !== 'GET' || url.protocol === 'chrome-extension:') {
    return;
  }
  
  // Handle API requests with specific strategies
  for (const endpoint of API_CACHE_ENDPOINTS) {
    if (endpoint.pattern.test(url.pathname)) {
      event.respondWith(handleApiRequest(event, endpoint));
      return;
    }
  }
  
  // Handle navigation requests (HTML pages)
  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          // Try network first for navigation
          const networkResponse = await fetch(request);
          return networkResponse;
        } catch (error) {
          // Fallback to cached offline page
          const offlineResponse = await caches.match('/offline');
          if (offlineResponse) return offlineResponse;
          
          // Ultimate fallback
          return new Response('<h1>You are offline</h1>', {
            headers: { 'Content-Type': 'text/html' }
          });
        }
      })()
    );
    return;
  }
  
  // Default cache-first strategy for other assets
  event.respondWith(
    (async () => {
      // Try cache first
      const cachedResponse = await caches.match(request);
      if (cachedResponse) return cachedResponse;
      
      // Fallback to network
      try {
        const networkResponse = await fetch(request);
        
        // Cache the response for future use
        if (isCacheable(request)) {
          const cache = await caches.open(CACHE_NAME);
          cache.put(request, networkResponse.clone());
        }
        
        return networkResponse;
      } catch (error) {
        // For CSS/JS, return empty response rather than offline page
        if (request.headers.get('Accept').includes('text/css') || 
            request.headers.get('Accept').includes('application/javascript')) {
          return new Response('', { status: 404, statusText: 'Not Found' });
        }
        
        // For images, return a placeholder
        if (request.headers.get('Accept').includes('image')) {
          return caches.match('/static/images/offline-placeholder.png');
        }
        
        // For other requests, check dynamic routes for offline fallbacks
        for (const route of DYNAMIC_CACHE_ROUTES) {
          if (url.pathname.startsWith(route.route)) {
            const offlineResponse = await caches.match(route.offline);
            if (offlineResponse) return offlineResponse;
          }
        }
        
        return new Response('Offline content not available', {
          status: 503,
          statusText: 'Service Unavailable'
        });
      }
    })()
  );
});

// ========== Custom Fetch Handlers ========== //

async function handleApiRequest(event, endpoint) {
  const { request } = event;
  
  switch (endpoint.strategy) {
    case 'network-first':
      return networkFirst(request, endpoint.maxAge);
    case 'cache-first':
      return cacheFirst(request, endpoint.maxAge);
    case 'stale-while-revalidate':
      return staleWhileRevalidate(event, endpoint.maxAge);
    default:
      return fetch(request);
  }
}

async function networkFirst(request, maxAge = 60) {
  try {
    // Try to fetch from network
    const networkResponse = await fetch(request);
    
    // Cache the response with timestamp
    const cache = await caches.open(API_CACHE_NAME);
    const responseWithDate = addCacheDate(networkResponse.clone());
    cache.put(request, responseWithDate);
    
    return networkResponse;
  } catch (error) {
    // Network failed - try cache
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      if (isCacheValid(cachedResponse, maxAge)) {
        return cachedResponse;
      }
    }
    throw error; // No valid cache available
  }
}

async function cacheFirst(request, maxAge = 3600) {
  // Check cache first
  const cachedResponse = await caches.match(request);
  if (cachedResponse && isCacheValid(cachedResponse, maxAge)) {
    return cachedResponse;
  }
  
  // Try network
  try {
    const networkResponse = await fetch(request);
    
    // Cache the response with timestamp
    const cache = await caches.open(API_CACHE_NAME);
    const responseWithDate = addCacheDate(networkResponse.clone());
    cache.put(request, responseWithDate);
    
    return networkResponse;
  } catch (error) {
    // If network fails and we have stale cache, return it
    if (cachedResponse) return cachedResponse;
    throw error;
  }
}

async function staleWhileRevalidate(event, maxAge = 300) {
  const { request } = event;
  
  // Immediately return cached response if available
  const cachedResponse = await caches.match(request);
  if (cachedResponse && isCacheValid(cachedResponse, maxAge)) {
    // Update cache in background
    event.waitUntil(
      fetch(request)
        .then((networkResponse) => {
          const cache = caches.open(API_CACHE_NAME);
          const responseWithDate = addCacheDate(networkResponse.clone());
          return cache.then(c => c.put(request, responseWithDate));
        })
        .catch(() => { /* Ignore update errors */ })
    );
    return cachedResponse;
  }
  
  // No valid cache - fetch from network
  try {
    const networkResponse = await fetch(request);
    
    // Cache the response with timestamp
    const cache = await caches.open(API_CACHE_NAME);
    const responseWithDate = addCacheDate(networkResponse.clone());
    cache.put(request, responseWithDate);
    
    return networkResponse;
  } catch (error) {
    // If we have stale cache (even if expired), return it
    if (cachedResponse) return cachedResponse;
    throw error;
  }
}

// ========== Helper Functions ========== //

function isCacheable(request) {
  const url = new URL(request.url);
  return (
    url.protocol === 'https:' &&
    !url.pathname.includes('/auth/') &&
    !url.pathname.includes('/admin/') &&
    !request.headers.get('Cache-Control')?.includes('no-store')
  );
}

function addCacheDate(response) {
  const date = new Date().toISOString();
  const newHeaders = new Headers(response.headers);
  newHeaders.set('X-Cache-Date', date);
  
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: newHeaders
  });
}

function isCacheValid(response, maxAgeSeconds) {
  const cacheDate = response.headers.get('X-Cache-Date');
  if (!cacheDate) return true; // No date - assume valid
  
  const cacheTime = new Date(cacheDate).getTime();
  const currentTime = new Date().getTime();
  const age = (currentTime - cacheTime) / 1000;
  
  return age < maxAgeSeconds;
}

// ========== Background Sync ========== //

self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-pending-orders') {
    event.waitUntil(
      (async () => {
        const cache = await caches.open('pending-orders');
        const requests = await cache.keys();
        
        await Promise.all(
          requests.map(async (request) => {
            try {
              const response = await fetch(request);
              if (response.ok) {
                await cache.delete(request);
              }
            } catch (error) {
              console.error('Failed to sync order:', error);
            }
          })
        );
      })()
    );
  }
});

// ========== Push Notifications ========== //

self.addEventListener('push', (event) => {
  const data = event.data?.json();
  
  const title = data?.title || 'New notification';
  const options = {
    body: data?.body || 'You have a new message',
    icon: '/static/images/icon-192x192.png',
    badge: '/static/images/badge.png',
    data: {
      url: data?.url || '/'
    }
  };
  
  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: 'window' }).then((clientList) => {
      if (clients.openWindow) {
        return clients.openWindow(event.notification.data.url);
      }
    })
  );
});

// ========== Client Communication ========== //

self.addEventListener('message', (event) => {
  switch (event.data.action) {
    case 'SKIP_WAITING':
      self.skipWaiting();
      break;
      
    case 'UPDATE_CACHE':
      event.waitUntil(
        caches.open(CACHE_NAME)
          .then(cache => cache.add(event.data.url))
      );
      break;
      
    case 'CACHE_DATA':
      event.waitUntil(
        caches.open('app-data')
          .then(cache => cache.put('/api/data', new Response(JSON.stringify(event.data.data))))
      );
      break;
      
    case 'GET_CACHED_DATA':
      event.ports[0].postMessage(
        caches.match('/api/data')
          .then(response => response?.json())
      );
      break;
  }
});