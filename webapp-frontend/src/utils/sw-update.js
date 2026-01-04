// src/utils/sw-update.js
export class ServiceWorkerUpdater {
  constructor() {
    this.newVersionAvailable = false;
    this.registration = null;
    this.callbacks = {
      onUpdateAvailable: null,
      onUpdateApplied: null
    };
  }

  async init() {
    if ('serviceWorker' in navigator) {
      try {
        this.registration = await navigator.serviceWorker.register('/service-worker.js');
        console.log('Service Worker 注册成功');
        
        // 监听 Service Worker 消息
        navigator.serviceWorker.addEventListener('message', this.handleMessage.bind(this));
        
        // 监听更新
        this.registration.addEventListener('updatefound', this.handleUpdateFound.bind(this));
        
        return true;
      } catch (error) {
        console.error('Service Worker 注册失败:', error);
        return false;
      }
    }
    return false;
  }

  handleMessage(event) {
    if (event.data && event.data.type === 'NEW_VERSION_AVAILABLE') {
      this.newVersionAvailable = true;
      console.log('检测到新版本:', event.data.version);
      
      if (this.callbacks.onUpdateAvailable) {
        this.callbacks.onUpdateAvailable(event.data.version);
      }
    }
  }

  handleUpdateFound() {
    const newWorker = this.registration.installing;
    console.log('发现 Service Worker 更新');
    
    newWorker.addEventListener('statechange', () => {
      if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
        // 新的 Service Worker 已安装，但旧的仍在控制页面
        this.newVersionAvailable = true;
        
        if (this.callbacks.onUpdateAvailable) {
          this.callbacks.onUpdateAvailable();
        }
      }
    });
  }

  async applyUpdate() {
    if (this.newVersionAvailable && this.registration) {
      // 跳过等待，立即激活新的 Service Worker
      if (this.registration.waiting) {
        this.registration.waiting.postMessage({ type: 'SKIP_WAITING' });
      }
      
      // 重新加载页面以应用更新
      window.location.reload();
      
      if (this.callbacks.onUpdateApplied) {
        this.callbacks.onUpdateApplied();
      }
    }
  }

  onUpdateAvailable(callback) {
    this.callbacks.onUpdateAvailable = callback;
  }

  onUpdateApplied(callback) {
    this.callbacks.onUpdateApplied = callback;
  }

  async checkForUpdates() {
    if (this.registration) {
      await this.registration.update();
    }
  }
}

// 创建全局实例
export const swUpdater = new ServiceWorkerUpdater();
