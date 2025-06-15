/**
 * 积分服务 - 处理所有与积分相关的操作
 */
import { apiClient } from '../main';

/**
 * 转移积分给其他用户
 * @param {Object} transferData - 转移数据
 * @returns {Promise} 包含转移结果的Promise对象
 */
export async function transferCredits(transferData) {
  try {
    const response = await apiClient.post('/api/user/transfer-credits', transferData);
    return response.data;
  } catch (error) {
    console.error('积分转移失败:', error);
    throw error;
  }
}

/**
 * 获取所有用户信息（用于积分转移和捐赠）
 * @returns {Promise} 用户列表
 */
export async function getAllUsers() {
  try {
    const response = await apiClient.get('/api/user/users');
    return response.data;
  } catch (error) {
    console.error('获取用户列表失败:', error);
    throw error;
  }
}
