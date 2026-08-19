import { apiClient } from '../main'

/**
 * 礼包服务
 * 提供礼包中心、开屏提醒与管理端的 API 调用
 */

// ==================== 用户端 ====================

/**
 * 开屏提醒判定：返回待提醒的礼包列表，并在返回的同时记账
 *
 * 用 POST 而非 GET，因为它确实有副作用（提醒次数 +1）。
 * 返回 packs 为空表示不弹窗。
 * @returns {Promise} { packs: [...] }
 */
export const promptCheckGiftPacks = () => {
  return apiClient.post('/api/gift-packs/prompt-check')
}

/**
 * 获取礼包中心列表（含每个礼包对当前用户的状态与余量）
 * @returns {Promise} { packs: [...], total: number }
 */
export const getGiftPacks = () => {
  return apiClient.get('/api/gift-packs')
}

/**
 * 领取礼包
 * @param {number} packId - 礼包 ID
 * @returns {Promise} 逐项发放结果
 */
export const claimGiftPack = (packId) => {
  return apiClient.post(`/api/gift-packs/${packId}/claim`)
}

// ==================== 管理端 ====================

/**
 * 管理员：礼包列表
 * @param {Object} params - { page, page_size }
 * @returns {Promise} { packs: [...], total: number }
 */
export const adminListGiftPacks = (params = { page: 1, page_size: 50 }) => {
  return apiClient.get('/api/gift-packs/admin/list', { params })
}

/**
 * 管理员：创建礼包
 * @param {Object} payload - 礼包配置
 * @returns {Promise} 创建的礼包
 */
export const adminCreateGiftPack = (payload) => {
  return apiClient.post('/api/gift-packs/admin', payload)
}

/**
 * 管理员：编辑礼包
 * @param {number} packId - 礼包 ID
 * @param {Object} payload - 要更新的字段
 * @returns {Promise} 更新后的礼包
 */
export const adminUpdateGiftPack = (packId, payload) => {
  return apiClient.put(`/api/gift-packs/admin/${packId}`, payload)
}

/**
 * 管理员：启用 / 停用礼包
 * @param {number} packId - 礼包 ID
 * @param {boolean} isEnabled - 是否启用
 * @returns {Promise} 更新后的礼包
 */
export const adminSetGiftPackEnabled = (packId, isEnabled) => {
  return apiClient.post(`/api/gift-packs/admin/${packId}/enabled`, { is_enabled: isEnabled })
}

/**
 * 管理员：删除礼包（已有领取记录时后端会拒绝，只能停用）
 * @param {number} packId - 礼包 ID
 * @returns {Promise} 删除结果
 */
export const adminDeleteGiftPack = (packId) => {
  return apiClient.delete(`/api/gift-packs/admin/${packId}`)
}

/**
 * 管理员：礼包领取统计
 * @param {number} packId - 礼包 ID
 * @returns {Promise} 统计信息
 */
export const adminGetGiftPackStats = (packId) => {
  return apiClient.get(`/api/gift-packs/admin/${packId}/stats`)
}

/**
 * 管理员：礼包领取记录（分页）
 * @param {number} packId - 礼包 ID
 * @param {Object} params - { page, page_size }
 * @returns {Promise} { records: [...], total: number }
 */
export const adminGetGiftPackRecords = (packId, params = { page: 1, page_size: 20 }) => {
  return apiClient.get(`/api/gift-packs/admin/${packId}/records`, { params })
}

export default {
  promptCheckGiftPacks,
  getGiftPacks,
  claimGiftPack,
  adminListGiftPacks,
  adminCreateGiftPack,
  adminUpdateGiftPack,
  adminSetGiftPackEnabled,
  adminDeleteGiftPack,
  adminGetGiftPackStats,
  adminGetGiftPackRecords
}
