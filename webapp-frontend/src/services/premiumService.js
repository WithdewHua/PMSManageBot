/**
 * Premium服务 - 处理所有与Premium会员相关的操作
 */
import { apiClient } from '../main';

/**
 * 解锁Premium会员
 * @param {Object} unlockData - 解锁数据
 * @returns {Promise} 解锁结果
 */
export async function unlockPremium(unlockData) {
  try {
    const response = await apiClient.post('/api/premium/unlock', unlockData);
    return response.data;
  } catch (error) {
    console.error('Premium解锁失败:', error);
    throw error;
  }
}
