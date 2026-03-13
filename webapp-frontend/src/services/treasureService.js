// 夺宝奇兵相关服务
import { apiClient } from '../main'

export const listTreasureIssues = (params = { include_closed: true, limit: 50 }) => {
  return apiClient.get('/api/treasure/list', { params })
}

export const getTreasureIssueDetail = (issueId) => {
  return apiClient.get(`/api/treasure/${issueId}`)
}

export const listTreasureParticipations = (issueId, limit = 100) => {
  return apiClient.get(`/api/treasure/${issueId}/participations`, { params: { limit } })
}

export const joinTreasureIssue = (issueId, quantity = 1) => {
  return apiClient.post(`/api/treasure/${issueId}/join`, {
    quantity
  })
}

export const createTreasureIssue = (payload) => {
  return apiClient.post('/api/treasure/create', payload)
}

export const cancelTreasureIssue = (issueId) => {
  return apiClient.post(`/api/treasure/${issueId}/cancel`)
}
