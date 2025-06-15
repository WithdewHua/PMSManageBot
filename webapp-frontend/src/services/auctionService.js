// 竞拍活动相关服务
import { apiClient } from '../main'

// 获取活跃的竞拍活动列表
export const getActiveAuctions = () => {
  return apiClient.get('/api/auction/list')
}

// 获取特定竞拍活动详情
export const getAuctionDetails = (auctionId) => {
  return apiClient.get(`/api/auction/${auctionId}`)
}

// 参与竞拍（出价）
export const placeBid = (auctionId, bidAmount) => {
  return apiClient.post('/api/auction/bid', {
    auction_id: auctionId,
    bid_amount: bidAmount
  })
}

// 获取竞拍统计信息（管理员）
export const getAuctionStats = () => {
  return apiClient.get('/api/auction/stats')
}

// 创建新的竞拍活动（管理员）
export const createAuction = (auctionData) => {
  return apiClient.post('/api/auction/create', auctionData)
}

// 结束过期的竞拍活动（管理员）
export const finishExpiredAuctions = () => {
  return apiClient.post('/api/auction/finish-expired')
}

// 获取所有竞拍活动列表（管理员）
export const getAllAuctions = (status = null, page = 1, limit = 10) => {
  const params = { page, limit }
  if (status) params.status = status
  return apiClient.get('/api/auction/admin/list', { params })
}

// 更新竞拍活动（管理员）
export const updateAuction = (auctionId, updateData) => {
  return apiClient.put(`/api/auction/admin/${auctionId}`, updateData)
}

// 删除竞拍活动（管理员）
export const deleteAuction = (auctionId) => {
  return apiClient.delete(`/api/auction/admin/${auctionId}`)
}

// 手动结束竞拍活动（管理员）
export const finishAuction = (auctionId) => {
  return apiClient.post(`/api/auction/admin/${auctionId}/finish`)
}

// 获取竞拍出价历史（管理员）
export const getAuctionBids = (auctionId) => {
  return apiClient.get(`/api/auction/admin/${auctionId}/bids`)
}

// 获取用户竞拍历史（管理员）
export const getUserAuctionHistory = (userId) => {
  return apiClient.get(`/api/auction/admin/user/${userId}/history`)
}

// 获取竞拍详细统计（管理员）
export const getDetailedAuctionStats = (startDate = null, endDate = null) => {
  const params = {}
  if (startDate) params.start_date = startDate
  if (endDate) params.end_date = endDate
  return apiClient.get('/api/auction/admin/detailed-stats', { params })
}
