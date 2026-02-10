/**
 * 自定义线路服务
 * 管理用户提交的自定义线路相关API
 */
import { apiClient } from '../main'

/**
 * 获取当前用户的自定义线路列表
 * @returns {Promise} 返回用户提交的线路列表
 */
export async function getMyCustomLines() {
  try {
    const response = await apiClient.get('/api/user/custom-lines/my-lines')
    return response.data
  } catch (error) {
    console.error('获取我的自定义线路失败:', error)
    throw error
  }
}

/**
 * 获取已批准的自定义线路
 * @returns {Promise<Array>} 返回已批准的线路数组
 */
export async function getApprovedCustomLines() {
  try {
    const response = await apiClient.get('/api/user/custom-lines/approved')
    if (response.data.success && response.data.lines) {
      return response.data.lines
    }
    return []
  } catch (error) {
    console.error('获取已批准的自定义线路失败:', error)
    return []
  }
}

/**
 * 提交新的自定义线路
 * @param {Object} lineData 线路数据
 * @returns {Promise} 返回提交结果
 */
export async function submitCustomLine(lineData) {
  try {
    const response = await apiClient.post('/api/user/custom-lines/submit', lineData)
    return response.data
  } catch (error) {
    console.error('提交自定义线路失败:', error)
    throw error
  }
}

/**
 * 获取自定义线路详情
 * @param {number} lineId 线路ID
 * @returns {Promise} 返回线路详情
 */
export async function getCustomLineDetail(lineId) {
  try {
    const response = await apiClient.get(`/api/user/custom-lines/${lineId}`)
    return response.data
  } catch (error) {
    console.error('获取自定义线路详情失败:', error)
    throw error
  }
}

/**
 * 更新自定义线路
 * @param {number} lineId 线路ID
 * @param {Object} updateData 更新数据
 * @returns {Promise} 返回更新结果
 */
export async function updateCustomLine(lineId, updateData) {
  try {
    const response = await apiClient.put(`/api/user/custom-lines/${lineId}`, updateData)
    return response.data
  } catch (error) {
    console.error('更新自定义线路失败:', error)
    throw error
  }
}

/**
 * 删除自定义线路
 * @param {number} lineId 线路ID
 * @returns {Promise} 返回删除结果
 */
export async function deleteCustomLine(lineId) {
  try {
    const response = await apiClient.delete(`/api/user/custom-lines/${lineId}`)
    return response.data
  } catch (error) {
    console.error('删除自定义线路失败:', error)
    throw error
  }
}

/**
 * 续期自定义线路
 * @param {number} lineId 线路ID
 * @param {number} validDays 续期天数
 * @returns {Promise} 返回续期结果
 */
export async function renewCustomLine(lineId, validDays) {
  try {
    const response = await apiClient.post(`/api/user/custom-lines/${lineId}/renew`, {
      valid_days: validDays
    })
    return response.data
  } catch (error) {
    console.error('续期自定义线路失败:', error)
    throw error
  }
}

/**
 * 管理员获取所有自定义线路
 * @param {string} status 状态筛选（可选）
 * @returns {Promise} 返回线路列表
 */
export async function adminGetAllCustomLines(status = null) {
  try {
    const params = status ? { status } : {}
    const response = await apiClient.get('/api/admin/custom-lines', { params })
    return response.data
  } catch (error) {
    console.error('获取所有自定义线路失败:', error)
    throw error
  }
}

/**
 * 管理员审批自定义线路
 * @param {number} lineId 线路ID
 * @param {Object} approvalData 审批数据
 * @returns {Promise} 返回审批结果
 */
export async function adminApproveCustomLine(lineId, approvalData) {
  try {
    const response = await apiClient.post(`/api/admin/custom-lines/${lineId}/approve`, approvalData)
    return response.data
  } catch (error) {
    console.error('审批自定义线路失败:', error)
    throw error
  }
}

/**
 * 管理员更新自定义线路
 * @param {number} lineId 线路ID
 * @param {Object} updateData 更新数据
 * @returns {Promise} 返回更新结果
 */
export async function adminUpdateCustomLine(lineId, updateData) {
  try {
    const response = await apiClient.put(`/api/admin/custom-lines/${lineId}`, updateData)
    return response.data
  } catch (error) {
    console.error('管理员更新自定义线路失败:', error)
    throw error
  }
}

/**
 * 管理员删除自定义线路
 * @param {number} lineId 线路ID
 * @returns {Promise} 返回删除结果
 */
export async function adminDeleteCustomLine(lineId) {
  try {
    const response = await apiClient.delete(`/api/admin/custom-lines/${lineId}`)
    return response.data
  } catch (error) {
    console.error('管理员删除自定义线路失败:', error)
    throw error
  }
}

/**
 * 管理员设置自定义线路标签
 * @param {number} lineId 线路ID
 * @param {Array<string>} tags 标签列表
 * @returns {Promise} 返回设置结果
 */
export async function adminSetCustomLineTags(lineId, tags) {
  try {
    const response = await apiClient.post(`/api/admin/custom-lines/${lineId}/tags`, tags)
    return response.data
  } catch (error) {
    console.error('管理员设置自定义线路标签失败:', error)
    throw error
  }
}
