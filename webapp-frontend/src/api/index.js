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

export const getCreditsRankings = () => {
  return apiClient.get('/api/rankings/credits')
}

export const getDonationRankings = () => {
  return apiClient.get('/api/rankings/donation')
}

export const getPlexWatchedTimeRankings = () => {
  return apiClient.get('/api/rankings/watched-time/plex')
}

export const getEmbyWatchedTimeRankings = () => {
  return apiClient.get('/api/rankings/watched-time/emby')
}

export const getPlexTrafficRankings = (startDate = null, endDate = null) => {
  const params = new URLSearchParams()
  if (startDate) params.append('start_date', startDate)
  if (endDate) params.append('end_date', endDate)
  
  const queryString = params.toString()
  const url = `/api/rankings/traffic/plex${queryString ? `?${queryString}` : ''}`
  
  return apiClient.get(url)
}

export const getEmbyTrafficRankings = (startDate = null, endDate = null) => {
  const params = new URLSearchParams()
  if (startDate) params.append('start_date', startDate)
  if (endDate) params.append('end_date', endDate)
  
  const queryString = params.toString()
  const url = `/api/rankings/traffic/emby${queryString ? `?${queryString}` : ''}`
  
  return apiClient.get(url)
}

export const getSystemStats = () => {
  return apiClient.get('/api/system/stats')
}

export const getPremiumStatistics = () => {
  return apiClient.get('/api/premium/statistics')
}

// 导出解析 initData 方法和获取用户方法
export { parseInitData, getTelegramUser }
