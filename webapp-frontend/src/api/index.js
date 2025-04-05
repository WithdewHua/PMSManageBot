import { apiClient } from '../main'

// 解析 Telegram WebApp initData
function parseInitData(initDataString) {
  const initData = {}
  const pairs = initDataString.split('&')
  
  for (let i = 0; i < pairs.length; i++) {
    const pair = pairs[i].split('=')
    if (pair.length === 2) {
      initData[decodeURIComponent(pair[0])] = decodeURIComponent(pair[1])
    }
  }
  
  return initData
}

// 获取 Telegram WebApp 用户信息
function getTelegramUser() {
  if (window.Telegram?.WebApp?.initDataUnsafe?.user) {
    return window.Telegram.WebApp.initDataUnsafe.user
  }
  return null
}

// API 方法
export const getUserInfo = () => {
  return apiClient.get('/api/user/info')
}

export const getRankings = () => {
  return apiClient.get('/api/rankings')
}

// 导出解析 initData 方法和获取用户方法
export { parseInitData, getTelegramUser }
