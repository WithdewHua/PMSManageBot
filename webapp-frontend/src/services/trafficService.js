import { apiClient } from '@/main';

/**
 * Premium 线路流量统计服务
 */

/**
 * 获取Premium线路流量统计数据
 * @returns {Promise<Object>} 流量统计数据
 */
export async function getPremiumLineTrafficStats() {
  try {
    const response = await apiClient.get('/api/premium/line-traffic-stats');
    return response.data;
  } catch (error) {
    console.error('获取 Premium 线路流量统计失败:', error);
    throw error;
  }
}

/**
 * 获取全平台流量统计概览
 * @returns {Promise<Object>} 流量概览数据
 */
export async function getTrafficOverview() {
  try {
    const response = await apiClient.get('/api/system/traffic-overview');
    return response.data;
  } catch (error) {
    console.error('获取流量统计概览失败:', error);
    throw error;
  }
}

/**
 * 格式化流量大小显示
 * @param {number} bytes - 字节数
 * @returns {string} 格式化后的流量大小
 */
export function formatTrafficSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const k = 1024;
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + units[i];
}

/**
 * 格式化用户名显示
 * @param {string} username - 用户名
 * @param {number} maxLength - 最大显示长度
 * @returns {string} 格式化后的用户名
 */
export function formatUsername(username, maxLength = 15) {
  if (!username) return '未知用户';
  
  if (username.length > maxLength) {
    return username.substring(0, maxLength) + '...';
  }
  
  return username;
}
