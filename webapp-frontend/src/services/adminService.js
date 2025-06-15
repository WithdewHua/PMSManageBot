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
 * 设置高级线路免费使用状态（通用，同时支持Plex和Emby）
 * @param {boolean} enabled - 是否开启高级线路免费使用
 * @returns {Promise} 设置结果
 */
export async function setPremiumFree(enabled) {
  try {
    const response = await apiClient.post('/api/admin/settings/premium-free', {
      enabled: enabled
    });
    return response;
  } catch (error) {
    console.error('设置高级线路免费使用状态失败:', error);
    throw error;
  }
}

/**
 * 设置免费的高级线路列表（通用，同时支持Plex和Emby）
 * @param {Array} freeLines - 免费高级线路列表
 * @returns {Promise} 设置结果
 */
export async function setFreePremiumLines(freeLines) {
  try {
    const response = await apiClient.post('/api/admin/settings/free-premium-lines', {
      free_lines: freeLines
    });
    return response;
  } catch (error) {
    console.error('设置免费高级线路列表失败:', error);
    throw error;
  }
}

/**
 * 设置 Emby 高级线路免费使用状态（兼容性接口，推荐使用 setPremiumFree）
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
 * 设置免费的 Emby 高级线路列表（兼容性接口，推荐使用 setFreePremiumLines）
 * @param {Array} freeLines - 免费高级线路列表
 * @returns {Promise} 设置结果
 */
export async function setEmbyFreePremiumLines(freeLines) {
  try {
    const response = await apiClient.post('/api/admin/settings/emby-free-premium-lines', {
      free_lines: freeLines
    });
    return response;
  } catch (error) {
    console.error('设置免费高级线路列表失败:', error);
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

/**
 * 设置邀请码生成所需积分
 * @param {number} credits - 积分数量
 * @returns {Promise} 设置结果
 */
export async function setInvitationCredits(credits) {
  try {
    const response = await apiClient.post('/api/admin/settings/invitation-credits', {
      credits: credits
    });
    return response;
  } catch (error) {
    console.error('设置邀请码积分失败:', error);
    throw error;
  }
}

/**
 * 设置解锁NSFW所需积分
 * @param {number} credits - 积分数量
 * @returns {Promise} 设置结果
 */
export async function setUnlockCredits(credits) {
  try {
    const response = await apiClient.post('/api/admin/settings/unlock-credits', {
      credits: credits
    });
    return response;
  } catch (error) {
    console.error('设置解锁积分失败:', error);
    throw error;
  }
}
