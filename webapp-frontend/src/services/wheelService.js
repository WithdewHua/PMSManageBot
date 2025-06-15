// 转盘相关服务
import { apiClient } from '../main'

// 幸运大转盘 API
export const getLuckyWheelConfig = () => {
  return apiClient.get('/api/luckywheel/config')
}

export const spinLuckyWheel = () => {
  return apiClient.post('/api/luckywheel/spin', {})
}

export const updateLuckyWheelConfig = (config) => {
  return apiClient.put('/api/luckywheel/config', config)
}

export const getLuckyWheelUserStatus = () => {
  return apiClient.get('/api/luckywheel/user-status')
}

// 随机性测试 API
export const getLuckyWheelRandomnessStats = (iterations = 10000) => {
  return apiClient.get(`/api/luckywheel/randomness-stats?iterations=${iterations}`)
}

export const updateLuckyWheelRandomnessConfig = (config) => {
  return apiClient.put('/api/luckywheel/randomness-config', config)
}

export const getLuckyWheelRandomnessConfig = () => {
  return apiClient.get('/api/luckywheel/randomness-config')
}

// 获取转盘统计数据
export const getWheelStats = async () => {
  try {
    const response = await apiClient.get('/api/luckywheel/stats')
    return response
  } catch (error) {
    console.error('获取转盘统计失败:', error)
    // 返回默认数据
    return {
      data: {
        totalSpins: 0,
        activeUsers: 0,
        todaySpins: 0,
        lastWeekSpins: 0,
        totalCreditsChange: 0.0,
        totalCreditsPool: 0.0,
        totalInviteCodes: 0
      }
    }
  }
}

// 获取转盘配置统计
export const getWheelConfigStats = async () => {
  try {
    // 临时使用模拟数据
    return {
      data: {
        totalItems: 6,
        lastConfigUpdate: new Date().toISOString(),
        totalProbability: 100
      }
    }
  } catch (error) {
    console.error('获取转盘配置统计失败:', error)
    return {
      data: {
        totalItems: 0,
        lastConfigUpdate: null,
        totalProbability: 0
      }
    }
  }
}

// 获取用户个人活动统计数据
export const getUserActivityStats = () => {
  return apiClient.get('/api/luckywheel/user-activity-stats')
}
