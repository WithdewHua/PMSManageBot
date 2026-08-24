// 21 点相关服务
import { apiClient } from '../main'

export const dealBlackjackHand = (betCredits) => {
  return apiClient.post('/api/blackjack/deal', {
    bet_credits: betCredits
  })
}

export const hitBlackjackHand = (handId) => {
  return apiClient.post(`/api/blackjack/${handId}/hit`)
}

export const standBlackjackHand = (handId) => {
  return apiClient.post(`/api/blackjack/${handId}/stand`)
}

export const doubleBlackjackHand = (handId) => {
  return apiClient.post(`/api/blackjack/${handId}/double`)
}

// 投降：返还一半基础注额，手牌立即结算。仅在响应的 can_surrender 为真时可用
export const surrenderBlackjackHand = (handId) => {
  return apiClient.post(`/api/blackjack/${handId}/surrender`)
}

// 取当前进行中的手牌，用于进入活动时恢复牌桌
export const getCurrentBlackjackHand = () => {
  return apiClient.get('/api/blackjack/current')
}

export const getUserBlackjackStats = () => {
  return apiClient.get('/api/blackjack/user-stats')
}

// 对用户公开的参数：注额档位、门槛、赔率、抽水比率。
// 规则说明中的数字一律取自此处，不在前端硬编码，以免与后端配置漂移。
export const getBlackjackConfig = () => {
  return apiClient.get('/api/blackjack/config')
}

// 以下四个仅管理员可用
export const getBlackjackAdminConfig = () => {
  return apiClient.get('/api/blackjack/admin/config')
}

export const updateBlackjackConfig = (payload) => {
  return apiClient.put('/api/blackjack/config', payload)
}

// 向幸运奖池注入种子余额。奖池平时只由抽水供养，这是唯一会增发积分的路径，
// 用途是上线冷启动时让奖池有个初值。
export const seedBlackjackJackpot = (amount) => {
  return apiClient.post('/api/blackjack/admin/jackpot/seed', { amount })
}

// 全站运营聚合统计，供管理页卡片展示。金额项只统计已结束的手牌，
// 故 active_hands 对应的押注尚未反映在 total_wagered 与 net_credits 里。
export const getBlackjackAdminStats = () => {
  return apiClient.get('/api/blackjack/admin/stats')
}
