import { apiClient } from '../main'

/**
 * 勋章服务
 * 提供勋章相关的 API 调用
 */

/**
 * 获取勋章中心配置
 * @returns {Promise} 勋章中心配置信息
 */
export const getBadgeCenterConfig = () => {
  return apiClient.get('/api/badges/config')
}

/**
 * 获取勋章列表（包含用户已拥有的勋章）
 * @returns {Promise} 勋章列表和用户信息
 */
export const getBadgesList = () => {
  return apiClient.get('/api/badges/list')
}

/**
 * 兑换勋章
 * @param {number} badgeId - 要兑换的勋章ID
 * @returns {Promise} 兑换结果
 */
export const redeemBadge = (badgeId) => {
  return apiClient.post('/api/badges/redeem', { badge_id: badgeId })
}

/**
 * 获取当前用户的勋章
 * @returns {Promise} 用户勋章列表
 */
export const getMyBadges = () => {
  return apiClient.get('/api/badges/my-badges')
}

/**
 * 获取指定用户的勋章（用于展示在排行榜等地方）
 * @param {number} tgId - 用户Telegram ID
 * @returns {Promise} 用户勋章列表
 */
export const getUserBadges = (tgId) => {
  return apiClient.get(`/api/badges/user/${tgId}/badges`)
}

// ==================== 管理员接口 ====================

/**
 * 管理员：创建勋章
 * @param {Object} badgeData - 勋章数据
 * @returns {Promise} 创建的勋章信息
 */
export const adminCreateBadge = (badgeData) => {
  return apiClient.post('/api/badges/create', badgeData)
}

/**
 * 管理员：更新勋章
 * @param {number} badgeId - 勋章ID
 * @param {Object} badgeData - 要更新的勋章数据
 * @returns {Promise} 更新后的勋章信息
 */
export const adminUpdateBadge = (badgeId, badgeData) => {
  return apiClient.put(`/api/badges/${badgeId}`, badgeData)
}

/**
 * 管理员：获取所有勋章（包括禁用的）
 * @returns {Promise} 所有勋章列表
 */
export const adminGetAllBadges = () => {
  return apiClient.get('/api/badges/all')
}

/**
 * 管理员：删除勋章
 * @param {number} badgeId - 勋章ID
 * @returns {Promise} 删除结果
 */
export const adminDeleteBadge = (badgeId) => {
  return apiClient.delete(`/api/badges/${badgeId}`)
}

/**
 * 管理员：更新勋章中心配置
 * @param {Object} config - 配置数据 {enabled: boolean, message: string}
 * @returns {Promise} 更新结果
 */
export const updateBadgeConfig = (config) => {
  return apiClient.post('/api/badges/config', config)
}

export default {
  getBadgeCenterConfig,
  getBadgesList,
  redeemBadge,
  getMyBadges,
  getUserBadges,
  adminCreateBadge,
  adminUpdateBadge,
  adminGetAllBadges,
  adminDeleteBadge,
  updateBadgeConfig
}
