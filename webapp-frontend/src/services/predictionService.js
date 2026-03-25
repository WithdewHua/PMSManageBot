import { apiClient } from '../main'

export const listPredictionMarkets = (params = { include_closed: true, limit: 50 }) => {
  return apiClient.get('/api/prediction/list', { params })
}

export const getPredictionMarketDetail = (marketId) => {
  return apiClient.get(`/api/prediction/${marketId}`)
}

export const listPredictionBets = (marketId, limit = 100) => {
  return apiClient.get(`/api/prediction/${marketId}/bets`, { params: { limit } })
}

export const placePredictionBet = (marketId, option, amount) => {
  return apiClient.post(`/api/prediction/${marketId}/bet`, { option, amount })
}

export const createPredictionMarket = (payload) => {
  return apiClient.post('/api/prediction/create', payload)
}

export const closePredictionMarket = (marketId) => {
  return apiClient.post(`/api/prediction/${marketId}/close`)
}

export const resolvePredictionMarket = (marketId, payload) => {
  return apiClient.post(`/api/prediction/${marketId}/resolve`, payload)
}

export const getUserPredictionStats = () => {
  return apiClient.get('/api/prediction/user-stats')
}

export const submitPredictionMarket = (payload) => {
  return apiClient.post('/api/prediction/submit', payload)
}

export const listPredictionSubmissions = (params = { limit: 50 }) => {
  return apiClient.get('/api/prediction/submissions', { params })
}

export const reviewPredictionSubmission = (submissionId, payload) => {
  return apiClient.post(`/api/prediction/submissions/${submissionId}/review`, payload)
}
