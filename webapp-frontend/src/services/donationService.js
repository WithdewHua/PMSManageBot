import { api } from '@/api'

/**
 * 提交捐赠自助登记
 * @param {Object} data - 捐赠登记数据
 * @param {string} data.payment_method - 支付方式 (wechat/alipay/bank/other)
 * @param {number} data.amount - 捐赠金额
 * @param {string} data.note - 备注信息
 * @returns {Promise} API响应
 */
export async function submitDonationRegistration(data) {
  try {
    const response = await api.post('/donations/register', data)
    return response.data
  } catch (error) {
    console.error('提交捐赠登记失败:', error)
    throw error
  }
}

/**
 * 获取用户捐赠登记历史
 * @returns {Promise} API响应
 */
export async function getDonationRegistrations() {
  try {
    const response = await api.get('/donations/registrations')
    return response.data
  } catch (error) {
    console.error('获取捐赠登记历史失败:', error)
    throw error
  }
}

/**
 * 获取捐赠登记详情
 * @param {number} registrationId - 登记ID
 * @returns {Promise} API响应
 */
export async function getDonationRegistrationDetail(registrationId) {
  try {
    const response = await api.get(`/donations/registrations/${registrationId}`)
    return response.data
  } catch (error) {
    console.error('获取捐赠登记详情失败:', error)
    throw error
  }
}

/**
 * 管理员确认捐赠登记
 * @param {number} registrationId - 登记ID
 * @param {Object} data - 确认数据
 * @param {boolean} data.approved - 是否批准
 * @param {string} data.admin_note - 管理员备注
 * @returns {Promise} API响应
 */
export async function confirmDonationRegistration(registrationId, data) {
  try {
    const response = await api.post(`/donations/registrations/${registrationId}/confirm`, data)
    return response.data
  } catch (error) {
    console.error('确认捐赠登记失败:', error)
    throw error
  }
}

/**
 * 获取待处理的捐赠登记列表（管理员用）
 * @returns {Promise} API响应
 */
export async function getPendingDonationRegistrations() {
  try {
    const response = await api.get('/donations/registrations/pending')
    return response.data
  } catch (error) {
    console.error('获取待处理捐赠登记失败:', error)
    throw error
  }
}