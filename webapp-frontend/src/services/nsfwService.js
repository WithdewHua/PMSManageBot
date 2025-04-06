/**
 * NSFW内容管理服务 - 处理NSFW内容的解锁与锁定操作
 */
import { apiClient } from '@/main';

/**
 * 获取NSFW操作相关的积分信息
 * @param {string} service - 服务类型 ('plex' 或 'emby')
 * @param {string} operation - 操作类型 ('unlock' 或 'lock')
 * @returns {Promise<Object>} 包含积分消耗或返还信息的Promise
 */
export async function getNsfwOperationInfo(service, operation) {
  try {
    const response = await apiClient.get('/api/user/nsfw-info', {
      params: { service, operation }
    });
    return response.data;
  } catch (error) {
    console.error('获取NSFW操作积分信息失败:', error);
    throw error;
  }
}

/**
 * 执行NSFW操作（解锁或锁定）
 * @param {string} operation - 操作类型 ('unlock' 或 'lock')
 * @param {string} service - 服务类型 ('plex' 或 'emby')
 * @returns {Promise<Object>} 操作结果的Promise
 */
export async function executeNsfwOperation(operation, service) {
  try {
    const response = await apiClient.post(`/api/user/nsfw/${operation}`, { service });
    return response.data;
  } catch (error) {
    console.error(`NSFW ${operation} 操作失败:`, error);
    throw error;
  }
}
