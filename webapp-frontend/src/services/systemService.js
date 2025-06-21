import { apiClient } from '../main';

/**
 * 获取系统状态信息
 * @returns {Promise} 系统状态数据
 */
export async function getSystemStatus() {
  try {
    const response = await apiClient.get('/api/system/status');
    return response.data;
  } catch (error) {
    console.error('获取系统状态失败:', error);
    throw error;
  }
}
