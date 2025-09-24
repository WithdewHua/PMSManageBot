// 自动版本控制 - 构建时会被自动更新
const BUILD_DATE = '20250924';
const MANUAL_VERSION = '0.1.1-1758678351735';
const CACHE_VERSION = `v${BUILD_DATE}`;
const CACHE_NAME = `funmedia-assistant-${CACHE_VERSION}`;
const FULL_CACHE_NAME = `${CACHE_NAME}-${MANUAL_VERSION}`;

// 版本检查和强制更新功能
const checkForUpdates = async () => {
  try {
    const response = await fetch('/version.json', { 
      cache: 'no-cache',
      headers: { 'Cache-Control': 'no-cache' }
    });
    
    if (response.ok) {
      const serverVersion = await response.json();
      const currentVersion = MANUAL_VERSION;
      
      if (serverVersion.version !== currentVersion) {
        console.log('发现新版本，准备更新缓存');
        // 通知客户端有新版本
        self.clients.matchAll().then(clients => {
          clients.forEach(client => {
            client.postMessage({
              type: 'NEW_VERSION_AVAILABLE',
              version: serverVersion.version
            });
          });
        });
      }
    }
  } catch (error) {
    console.log('版本检查失败:', error);
  }
};

// 基础缓存资源（只缓存核心导航资源）
const urlsToCache = [
  '/',
  '/index.html',
  '/favicon.ico',
  '/manifest.json'
];

// 安装 Service Worker
self.addEventListener('install', event => {
  console.log('Service Worker 安装中...', FULL_CACHE_NAME);
  event.waitUntil(
    caches.open(FULL_CACHE_NAME)
      .then(cache => {
        console.log('Service Worker: 缓存基础资源');
        return cache.addAll(urlsToCache);
      })
      .then(() => {
        console.log('Service Worker: 强制激活新版本');
        self.skipWaiting();
      })
  );
});

// 定期检查更新（每小时检查一次）
setInterval(checkForUpdates, 60 * 60 * 1000);

// Service Worker 激活时立即检查更新
self.addEventListener('activate', event => {
  console.log('Service Worker 激活中...', FULL_CACHE_NAME);
  event.waitUntil(
    Promise.all([
      // 清理旧缓存
      caches.keys().then(cacheNames => {
        return Promise.all(
          cacheNames.map(cacheName => {
            // 清除所有不匹配当前版本的缓存
            if (cacheName !== FULL_CACHE_NAME && cacheName.startsWith('funmedia-assistant-')) {
              console.log('Service Worker: 清除旧缓存', cacheName);
              return caches.delete(cacheName);
            }
          })
        );
      }),
      // 检查版本更新
      checkForUpdates()
    ])
    .then(() => {
      console.log('Service Worker: 激活完成，接管所有客户端');
      return self.clients.claim();
    })
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
    // 判断资源类型进行缓存
    const url = new URL(event.request.url);
    const extension = url.pathname.split('.').pop().toLowerCase();
    
    // 判断是否为需要缓存的静态资源
    const shouldCache = ['js', 'css', 'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico', 'woff', 'woff2', 'ttf', 'eot'].includes(extension);
    
    // 对可缓存的静态资源使用缓存优先策略
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
              if (!response || response.status !== 200) {
                return response;
              }
              
              // 如果是可缓存的资源类型，则进行缓存
              if (shouldCache) {
                // 克隆响应，因为响应是一个流，只能使用一次
                const responseToCache = response.clone();
                
                // 打开缓存并存储响应
                caches.open(FULL_CACHE_NAME)
                  .then(cache => {
                    console.log('缓存资源:', url.pathname);
                    cache.put(event.request, responseToCache);
                  });
              }
                
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
