import { apiClient } from '@/main';

/**
 * 绑定 Emby 线路
 * @param {string} line - 要绑定的线路名称
 * @returns {Promise} 绑定结果
 */
export async function bindEmbyLine(line) {
  try {
    const response = await apiClient.post('/api/user/bind/emby_line', { line });
    return response.data;
  } catch (error) {
    console.error('绑定 Emby 线路失败:', error);
    throw error;
  }
}

/**
 * 解绑 Emby 线路（自动选择）
 * @returns {Promise} 解绑结果
 */
export async function unbindEmbyLine() {
  try {
    const response = await apiClient.post('/api/user/unbind/emby_line');
    return response.data;
  } catch (error) {
    console.error('解绑 Emby 线路失败:', error);
    throw error;
  }
}

/**
 * 获取所有可用的Emby线路列表
 * @returns {Promise<Array>} 线路信息列表，包含名称、标签和是否为高级线路
 */
export async function getAvailableEmbyLines() {
  try {
    const response = await apiClient.get('/api/user/emby_lines');
    return response.data.lines || [];
  } catch (error) {
    console.error('获取Emby线路列表失败:', error);
    return [];
  }
}
