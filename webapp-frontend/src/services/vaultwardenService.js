/**
 * Vaultwarden 服务 - 处理所有与 Vaultwarden 兑换相关的操作
 */
import { apiClient } from '../main';

/**
 * 获取 Vaultwarden 兑换信息
 * @returns {Promise} 包含兑换信息的Promise对象
 */
export async function getVaultwardenRedeemInfo() {
  try {
    const response = await apiClient.get('/api/vaultwarden/redeem-info');
    return response.data;
  } catch (error) {
    console.error('获取 Vaultwarden 兑换信息失败:', error);
    throw error;
  }
}

/**
 * 兑换 Vaultwarden 账户
 * @param {Object} redeemData - 兑换数据
 * @param {string} redeemData.email - 注册邮箱
 * @returns {Promise} 包含兑换结果的Promise对象
 */
export async function redeemVaultwardenAccount(redeemData) {
  try {
    const response = await apiClient.post('/api/vaultwarden/redeem', redeemData);
    return response.data;
  } catch (error) {
    console.error('兑换 Vaultwarden 账户失败:', error);
    throw error;
  }
}
