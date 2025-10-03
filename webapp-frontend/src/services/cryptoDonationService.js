/**
 * Crypto 捐赠相关的 API 服务
 */
import { apiClient } from '@/main'

/**
 * 获取支持的加密货币类型
 * @returns {Promise} API 响应
 */
export const getCryptoTypes = async () => {
  try {
    const response = await apiClient.get('/api/crypto-donations/crypto-types')
    return response.data
  } catch (error) {
    console.error('获取加密货币类型失败:', error)
    throw error
  }
}

/**
 * 创建 Crypto 捐赠订单
 * @param {Object} orderData 订单数据
 * @param {string} orderData.crypto_type 加密货币类型
 * @param {number} orderData.amount 捐赠金额 (CNY)
 * @param {string} [orderData.note] 备注信息
 * @returns {Promise} API 响应
 */
export const createCryptoDonationOrder = async (orderData) => {
  try {
    const response = await apiClient.post('/api/crypto-donations/create', orderData)
    return response.data
  } catch (error) {
    console.error('创建 Crypto 捐赠订单失败:', error)
    throw error
  }
}

/**
 * 获取用户的 Crypto 捐赠订单列表
 * @returns {Promise} API 响应
 */
export const getUserCryptoDonationOrders = async () => {
  try {
    const response = await apiClient.get('/api/crypto-donations/orders')
    return response.data
  } catch (error) {
    console.error('获取 Crypto 捐赠订单列表失败:', error)
    throw error
  }
}

/**
 * 获取特定的 Crypto 捐赠订单详情
 * @param {string} orderId 订单ID
 * @returns {Promise} API 响应
 */
export const getCryptoDonationOrder = async (orderId) => {
  try {
    const response = await apiClient.get(`/api/crypto-donations/orders/${orderId}`)
    return response.data
  } catch (error) {
    console.error('获取 Crypto 捐赠订单详情失败:', error)
    throw error
  }
}

/**
 * 支持的加密货币类型（备用，兼容性）
 */
export const CRYPTO_TYPES = [
  'USDC-Polygon',
  'USDC-ArbitrumOne', 
  'USDC-BSC',
  'USDT-Polygon',
  'USDT-ArbitrumOne',
  'USDT-BSC'
]

/**
 * 获取加密货币类型（优先从后端获取，失败时使用备用）
 * @returns {Promise<Array>} 加密货币类型列表
 */
export const getCryptoTypesWithFallback = async () => {
  try {
    const response = await getCryptoTypes()
    if (response.success && response.data && Array.isArray(response.data)) {
      return response.data
    }
    throw new Error('后端返回数据格式错误')
  } catch (error) {
    console.warn('从后端获取加密货币类型失败，使用备用配置:', error)
    return CRYPTO_TYPES
  }
}

/**
 * 订单状态映射
 */
export const ORDER_STATUS = {
  1: { text: '等待支付', color: 'warning', icon: 'mdi-clock-outline' },
  2: { text: '支付成功', color: 'success', icon: 'mdi-check-circle' },
  3: { text: '已过期', color: 'error', icon: 'mdi-close-circle' }
}