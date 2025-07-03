import { apiClient } from '@/main';

/**
 * 通用线路服务（用户端，同时支持Plex和Emby）
 */

/**
 * 获取可用的线路列表（通用）
 * @param {string} service - 服务类型 ('emby' 或 'plex')
 * @returns {Promise<Array>} 线路信息列表，包含名称、标签和是否为高级线路
 */
export async function getAvailableLines(service = 'emby') {
  try {
    // 使用通用API端点
    const response = await apiClient.get(`/api/user/lines/${service}`);
    return response.data.lines || [];
  } catch (error) {
    console.error(`获取${service}线路列表失败:`, error);
    // 降级到旧的API端点以确保向后兼容
    try {
      const endpoint = service === 'plex' ? '/api/user/plex_lines' : '/api/user/emby_lines';
      const fallbackResponse = await apiClient.get(endpoint);
      return fallbackResponse.data.lines || [];
    } catch (fallbackError) {
      console.error(`降级API调用也失败:`, fallbackError);
      return [];
    }
  }
}

/**
 * 绑定线路（通用）
 * @param {string} line - 要绑定的线路名称
 * @param {string} service - 服务类型 ('emby' 或 'plex')
 * @returns {Promise} 绑定结果
 */
export async function bindLine(line, service = 'emby') {
  try {
    // 使用通用API端点
    const response = await apiClient.post(`/api/user/lines/${service}/bind`, { line });
    return response.data;
  } catch (error) {
    console.error(`绑定${service}线路失败:`, error);
    // 降级到旧的API端点以确保向后兼容
    try {
      const endpoint = service === 'plex' ? '/api/user/bind/plex_line' : '/api/user/bind/emby_line';
      const fallbackResponse = await apiClient.post(endpoint, { line });
      return fallbackResponse.data;
    } catch (fallbackError) {
      console.error(`降级API调用也失败:`, fallbackError);
      throw fallbackError;
    }
  }
}

/**
 * 解绑线路（通用）
 * @param {string} service - 服务类型 ('emby' 或 'plex')
 * @returns {Promise} 解绑结果
 */
export async function unbindLine(service = 'emby') {
  try {
    // 使用通用API端点
    const response = await apiClient.post(`/api/user/lines/${service}/unbind`);
    return response.data;
  } catch (error) {
    console.error(`解绑${service}线路失败:`, error);
    // 降级到旧的API端点以确保向后兼容
    try {
      const endpoint = service === 'plex' ? '/api/user/unbind/plex_line' : '/api/user/unbind/emby_line';
      const fallbackResponse = await apiClient.post(endpoint);
      return fallbackResponse.data;
    } catch (fallbackError) {
      console.error(`降级API调用也失败:`, fallbackError);
      throw fallbackError;
    }
  }
}

/**
 * 认证并绑定线路（新的组合API）
 * @param {string} service - 服务类型 ('emby' 或 'plex')
 * @param {Object} credentials - 认证信息
 * @param {string} credentials.username - 用户名（Emby用）
 * @param {string} credentials.email - 邮箱（Plex用）
 * @param {string} credentials.password - 密码
 * @param {string} credentials.line - 要绑定的线路名称
 * @returns {Promise} 认证绑定结果
 */
export async function authBindLine(service, credentials) {
  try {
    const response = await apiClient.post(`/api/user/auth-bind/${service}`, credentials);
    return {
      success: true,
      message: response.data.message || '认证并绑定线路成功',
      data: response.data
    };
  } catch (error) {
    console.error(`认证绑定${service}线路失败:`, error);
    return {
      success: false,
      message: error.response?.data?.detail || error.response?.data?.message || '认证绑定失败，请检查用户名密码',
      error: error
    };
  }
}

/**
 * 基于用户名/邮箱获取可用的线路列表
 * @param {string} service - 服务类型 ('emby' 或 'plex')
 * @param {string} username - 用户名（Emby用）
 * @param {string} email - 邮箱（Plex用）
 * @returns {Promise<Array>} 线路信息列表，包含名称、标签和是否为高级线路
 */
export async function getAvailableLinesByUser(service, username, email) {
  try {
    const payload = {};
    
    if (service === 'emby') {
      payload.username = username;
    } else {
      payload.email = email;
    }
    
    const response = await apiClient.post(`/api/user/lines/${service}/available`, payload);
    return response.data.lines || [];
  } catch (error) {
    console.error(`基于用户凭据获取${service}线路列表失败:`, error);
    throw error;
  }
}

/**
 * 基于用户名获取可用的Emby线路列表
 * @param {string} username - Emby用户名
 * @returns {Promise<Array>} 线路信息列表，包含名称、标签和是否为高级线路
 */
export async function getAvailableEmbyLinesByUser(username) {
  return getAvailableLinesByUser('emby', username, null);
}

/**
 * 基于邮箱获取可用的Plex线路列表
 * @param {string} email - Plex邮箱
 * @returns {Promise<Array>} 线路信息列表，包含名称、标签和是否为高级线路
 */
export async function getAvailablePlexLinesByUser(email) {
  return getAvailableLinesByUser('plex', null, email);
}

/**
 * 基于用户名/邮箱获取当前绑定的线路信息
 * @param {string} service - 服务类型 ('emby' 或 'plex')
 * @param {string} username - 用户名（Emby用）
 * @param {string} email - 邮箱（Plex用）
 * @returns {Promise<Object>} 当前绑定的线路信息
 */
export async function getCurrentBoundLine(service, username, email) {
  try {
    const payload = {};
    
    if (service === 'emby') {
      payload.username = username;
    } else {
      payload.email = email;
    }
    
    const response = await apiClient.post(`/api/user/lines/${service}/current`, payload);
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    console.error(`获取用户当前绑定的${service}线路失败:`, error);
    return {
      success: false,
      error: error,
      message: error.response?.data?.detail || error.response?.data?.message || '获取当前绑定线路失败'
    };
  }
}

/**
 * 基于用户名获取当前绑定的Emby线路信息
 * @param {string} username - Emby用户名
 * @returns {Promise<Object>} 当前绑定的线路信息
 */
export async function getCurrentBoundEmbyLine(username) {
  return getCurrentBoundLine('emby', username, null);
}

/**
 * 基于邮箱获取当前绑定的Plex线路信息
 * @param {string} email - Plex邮箱
 * @returns {Promise<Object>} 当前绑定的线路信息
 */
export async function getCurrentBoundPlexLine(email) {
  return getCurrentBoundLine('plex', null, email);
}

// 为了向后兼容，保留原有的特定服务函数

/**
 * 获取所有可用的Emby线路列表
 * @returns {Promise<Array>} 线路信息列表，包含名称、标签和是否为高级线路
 */
export async function getAvailableEmbyLines() {
  return getAvailableLines('emby');
}

/**
 * 绑定 Emby 线路
 * @param {string} line - 要绑定的线路名称
 * @returns {Promise} 绑定结果
 */
export async function bindEmbyLine(line) {
  return bindLine(line, 'emby');
}

/**
 * 解绑 Emby 线路（自动选择）
 * @returns {Promise} 解绑结果
 */
export async function unbindEmbyLine() {
  return unbindLine('emby');
}

/**
 * 获取所有可用的Plex线路列表
 * @returns {Promise<Array>} 线路信息列表，包含名称、标签和是否为高级线路
 */
export async function getAvailablePlexLines() {
  return getAvailableLines('plex');
}

/**
 * 绑定 Plex 线路
 * @param {string} line - 要绑定的线路名称
 * @returns {Promise} 绑定结果
 */
export async function bindPlexLine(line) {
  return bindLine(line, 'plex');
}

/**
 * 解绑 Plex 线路（自动选择）
 * @returns {Promise} 解绑结果
 */
export async function unbindPlexLine() {
  return unbindLine('plex');
}
