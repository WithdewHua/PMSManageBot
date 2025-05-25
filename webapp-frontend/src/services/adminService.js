import { apiClient } from '../main';

/**
 * 获取管理员设置
 * @returns {Promise} 管理员设置数据
 */
export async function getAdminSettings() {
  try {
    const response = await apiClient.get('/api/admin/settings');
    return response;
  } catch (error) {
    console.error('获取管理员设置失败:', error);
    throw error;
  }
}

/**
 * 设置 Plex 注册状态
 * @param {boolean} enabled - 是否开启注册
 * @returns {Promise} 设置结果
 */
export async function setPlexRegister(enabled) {
  try {
    const response = await apiClient.post('/api/admin/settings/plex-register', {
      enabled: enabled
    });
    return response;
  } catch (error) {
    console.error('设置 Plex 注册状态失败:', error);
    throw error;
  }
}

/**
 * 设置 Emby 注册状态
 * @param {boolean} enabled - 是否开启注册
 * @returns {Promise} 设置结果
 */
export async function setEmbyRegister(enabled) {
  try {
    const response = await apiClient.post('/api/admin/settings/emby-register', {
      enabled: enabled
    });
    return response;
  } catch (error) {
    console.error('设置 Emby 注册状态失败:', error);
    throw error;
  }
}

/**
 * 设置 Emby 高级线路免费使用状态
 * @param {boolean} enabled - 是否开启高级线路免费使用
 * @returns {Promise} 设置结果
 */
export async function setEmbyPremiumFree(enabled) {
  try {
    const response = await apiClient.post('/api/admin/settings/emby-premium-free', {
      enabled: enabled
    });
    return response;
  } catch (error) {
    console.error('设置 Emby 高级线路免费使用状态失败:', error);
    throw error;
  }
}

/**
 * 获取所有用户信息（用于捐赠管理）
 * @returns {Promise} 用户列表
 */
export async function getAllUsers() {
  try {
    const response = await apiClient.get('/api/admin/users');
    return response.data;
  } catch (error) {
    console.error('获取用户列表失败:', error);
    throw error;
  }
}

/**
 * 提交捐赠记录
 * @param {Object} donationData - 捐赠数据
 * @returns {Promise} 提交结果
 */
export async function submitDonationRecord(donationData) {
  try {
    const response = await apiClient.post('/api/admin/donation', donationData);
    return response.data;
  } catch (error) {
    console.error('提交捐赠记录失败:', error);
    throw error;
  }
}
