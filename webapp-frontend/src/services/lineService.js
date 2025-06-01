import { apiClient } from '@/main';

/**
 * 通用线路管理服务（同时支持Plex和Emby）
 */

/**
 * 获取所有线路配置
 * @returns {Promise<Object>} 线路配置数据
 */
export async function getLinesConfig() {
  try {
    const response = await apiClient.get('/api/admin/lines');
    return response.data;
  } catch (error) {
    console.error('获取线路配置失败:', error);
    throw error;
  }
}

/**
 * 添加普通线路
 * @param {string} lineName - 线路名称
 * @returns {Promise} 添加结果
 */
export async function addNormalLine(lineName) {
  try {
    const response = await apiClient.post('/api/admin/lines/normal', {
      line_name: lineName
    });
    return response.data;
  } catch (error) {
    console.error('添加普通线路失败:', error);
    throw error;
  }
}

/**
 * 添加高级线路
 * @param {string} lineName - 线路名称
 * @returns {Promise} 添加结果
 */
export async function addPremiumLine(lineName) {
  try {
    const response = await apiClient.post('/api/admin/lines/premium', {
      line_name: lineName
    });
    return response.data;
  } catch (error) {
    console.error('添加高级线路失败:', error);
    throw error;
  }
}

/**
 * 删除普通线路
 * @param {string} lineName - 线路名称
 * @returns {Promise} 删除结果
 */
export async function deleteNormalLine(lineName) {
  try {
    const response = await apiClient.delete(`/api/admin/lines/normal/${encodeURIComponent(lineName)}`);
    return response.data;
  } catch (error) {
    console.error('删除普通线路失败:', error);
    throw error;
  }
}

/**
 * 删除高级线路
 * @param {string} lineName - 线路名称
 * @returns {Promise} 删除结果
 */
export async function deletePremiumLine(lineName) {
  try {
    const response = await apiClient.delete(`/api/admin/lines/premium/${encodeURIComponent(lineName)}`);
    return response.data;
  } catch (error) {
    console.error('删除高级线路失败:', error);
    throw error;
  }
}
