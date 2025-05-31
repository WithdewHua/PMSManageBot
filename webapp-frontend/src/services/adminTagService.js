import { apiClient } from '@/main';

/**
 * 管理员标签管理服务
 */

/**
 * 设置线路标签
 * @param {string} lineName - 线路名称
 * @param {Array<string>} tags - 标签数组
 * @returns {Promise} 设置结果
 */
export async function setLineTags(lineName, tags) {
  try {
    const response = await apiClient.post('/api/admin/line_tags', {
      line_name: lineName,
      tags: tags
    });
    return response.data;
  } catch (error) {
    console.error('设置线路标签失败:', error);
    throw error;
  }
}

/**
 * 获取指定线路的标签
 * @param {string} lineName - 线路名称
 * @returns {Promise<Object>} 线路标签信息
 */
export async function getLineTags(lineName) {
  try {
    const response = await apiClient.get(`/api/admin/line_tags/${lineName}`);
    return response.data;
  } catch (error) {
    console.error('获取线路标签失败:', error);
    throw error;
  }
}

/**
 * 获取所有线路的标签信息
 * @returns {Promise<Object>} 所有线路标签信息
 */
export async function getAllLineTags() {
  try {
    const response = await apiClient.get('/api/admin/all_line_tags');
    return response.data;
  } catch (error) {
    console.error('获取所有线路标签失败:', error);
    throw error;
  }
}

/**
 * 删除指定线路的所有标签
 * @param {string} lineName - 线路名称
 * @returns {Promise} 删除结果
 */
export async function deleteLineTags(lineName) {
  try {
    const response = await apiClient.delete(`/api/admin/line_tags/${lineName}`);
    return response.data;
  } catch (error) {
    console.error('删除线路标签失败:', error);
    throw error;
  }
}