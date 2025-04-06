// 注册 Service Worker
function registerServiceWorker() {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js')
        .then(registration => {
          console.log('Service Worker 注册成功：', registration.scope);
          
          // 检查更新
          registration.addEventListener('updatefound', () => {
            const newWorker = registration.installing;
            console.log('Service Worker 安装中...');
            
            newWorker.addEventListener('statechange', () => {
              if (newWorker.state === 'installed') {
                if (navigator.serviceWorker.controller) {
                  console.log('发现新版本，应用将在刷新后更新');
                  // 可以在这里显示通知，告诉用户有新版本可用
                  if (window.Telegram?.WebApp) {
                    window.Telegram.WebApp.showPopup({
                      title: '应用更新',
                      message: '发现新版本，请刷新应用以应用更新'
                    });
                  }
                } else {
                  console.log('应用已缓存，可离线使用');
                }
              }
            });
          });
        })
        .catch(error => {
          console.error('Service Worker 注册失败：', error);
        });
        
      // 检测是否有控制当前页面的 Service Worker
      if (navigator.serviceWorker.controller) {
        console.log('页面由 Service Worker 控制');
      }
    });
  } else {
    console.log('当前浏览器不支持 Service Worker');
  }
}

export default registerServiceWorker;
