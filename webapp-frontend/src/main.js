import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import axios from 'axios'
// 引入 Vuetify
import { createVuetify } from 'vuetify'
import 'vuetify/styles'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { aliases, mdi } from 'vuetify/iconsets/mdi'
import '@mdi/font/css/materialdesignicons.css'
// 引入 Service Worker 注册
import registerServiceWorker from './registerServiceWorker'

// 获取正确的环境变量
const apiBaseUrl = process.env.VUE_APP_API_URL || 'http://localhost:6000'

// API 配置
const apiConfig = {
  baseURL: apiBaseUrl,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
  }
}

// 创建 axios 实例
const apiClient = axios.create(apiConfig)

// 添加请求拦截器
apiClient.interceptors.request.use(
  config => {
    // 在发送请求之前做些什么
    config.headers['X-Telegram-Init-Data'] = window.Telegram?.WebApp?.initData;
    // 增加 user id
    config.headers['X-Telegram-User-ID'] = window.Telegram?.WebApp?.initDataUnsafe.user.id;
    return config;
  },
  error => {
    // 对请求错误做些什么
    return Promise.reject(error);
  }
);

// 添加响应拦截器
apiClient.interceptors.response.use(
  response => response,
  error => {
    console.error('API请求错误:', error);
    return Promise.reject(error);
  }
);

// 导出 API 客户端以便在其他文件中使用
export { apiClient };

// 确保 Telegram WebApp 已准备就绪
document.addEventListener('DOMContentLoaded', () => {
  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
    
    // 设置初始路由
    if (window.location.hash === '' || window.location.hash === '#/') {
      router.replace({ name: 'user-info' });
    }
  }
});

// 注册 Service Worker
registerServiceWorker();

const vuetify = createVuetify({
  components,
  directives,
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: {
      mdi,
    },
  },
  theme: {
    defaultTheme: 'light'
  }
})

// 初始化 Telegram WebApp
if (window.Telegram && window.Telegram.WebApp) {
  const tgApp = window.Telegram.WebApp
  tgApp.ready()
  tgApp.expand()
  
  // 设置后退按钮事件处理
  tgApp.BackButton.onClick(() => {
    if (router.currentRoute.value.path !== '/') {
      router.back()
    }
  })
}

const app = createApp(App)
app.use(router)
app.use(vuetify)
app.mount('#app')
