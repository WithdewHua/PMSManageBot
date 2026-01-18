/**
 * 下载权限管理服务 - 处理下载权限的查询与解锁操作
 */
import { apiClient } from '@/main';

/**
 * 获取下载权限状态
 * @param {string} service - 服务类型 ('plex' 或 'emby')
 * @returns {Promise<Object>} 包含下载权限状态信息的Promise
 */
export async function getDownloadPermissionStatus(service) {
  try {
    const response = await apiClient.get(`/api/user/download-permission/status/${service}`);
    return response.data;
  } catch (error) {
    console.error('获取下载权限状态失败:', error);
    throw error;
  }
}

/**
 * 解锁下载权限
 * @param {string} service - 服务类型 ('plex' 或 'emby')
 * @returns {Promise<Object>} 操作结果的Promise
 */
export async function unlockDownloadPermission(service) {
  try {
    const response = await apiClient.post(`/api/user/download-permission/unlock/${service}`);
    return response.data;
  } catch (error) {
    console.error(`解锁 ${service} 下载权限失败:`, error);
    throw error;
  }
}
