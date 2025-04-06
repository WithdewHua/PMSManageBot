// 缓存版本，需要更新缓存时更改此版本号
const CACHE_VERSION = 'v1';
const CACHE_NAME = `funmedia-assistant-${CACHE_VERSION}`;

// 需要缓存的资源
const urlsToCache = [
  '/',
  '/index.html',
  '/favicon.ico',
  '/css/app.css',
  '/js/app.js',
  '/js/chunk-vendors.js',
  '/img/icons/android-chrome-192x192.png',
  '/img/icons/android-chrome-512x512.png'
];

// 安装 Service Worker
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Service Worker: 缓存资源中');
        return cache.addAll(urlsToCache);
      })
      .then(() => self.skipWaiting())
  );
});

// 激活 Service Worker
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cache => {
          if (cache !== CACHE_NAME) {
            console.log('Service Worker: 清除旧缓存 ' + cache);
            return caches.delete(cache);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 拦截网络请求
self.addEventListener('fetch', event => {
  // 对 API 请求使用网络优先策略
  if (event.request.url.includes('/api/')) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          return response;
        })
        .catch(() => {
          // 如果网络请求失败，尝试从缓存获取
          return caches.match(event.request);
        })
    );
  } else {
    // 对其他资源使用缓存优先策略
    event.respondWith(
      caches.match(event.request)
        .then(response => {
          // 如果在缓存中找到响应，则返回缓存的响应
          if (response) {
            return response;
          }
          
          // 克隆请求，因为请求是一个流，只能使用一次
          const fetchRequest = event.request.clone();
          
          return fetch(fetchRequest)
            .then(response => {
              // 检查是否收到有效响应
              if (!response || response.status !== 200 || response.type !== 'basic') {
                return response;
              }
              
              // 克隆响应，因为响应是一个流，只能使用一次
              const responseToCache = response.clone();
              
              // 打开缓存并存储响应
              caches.open(CACHE_NAME)
                .then(cache => {
                  cache.put(event.request, responseToCache);
                });
                
              return response;
            });
        })
    );
  }
});

// 监听推送通知
self.addEventListener('push', event => {
  if (event.data) {
    const data = event.data.json();
    const options = {
      body: data.body || '有新消息',
      icon: '/img/icons/android-chrome-192x192.png',
      badge: '/img/icons/badge-72x72.png'
    };
    
    event.waitUntil(
      self.registration.showNotification('FunMedia 助手', options)
    );
  }
});

// 处理通知点击
self.addEventListener('notificationclick', event => {
  event.notification.close();
  
  event.waitUntil(
    clients.openWindow('/')
  );
});
