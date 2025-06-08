/**
 * 媒体服务 API - 处理与媒体服务(Plex/Emby)相关的 API 请求
 */
import { apiClient } from '../main';

/**
 * 兑换媒体服务邀请码
 * @param {string} serviceType - 服务类型 ('plex' 或 'emby')
 * @param {Object} data - 请求数据对象，包含 code 和 email 或 username
 * @returns {Promise} 包含兑换结果的Promise对象
 */
export function redeemMediaServiceInviteCode(serviceType, data) {
  return new Promise((resolve, reject) => {
    // 验证服务类型
    if (serviceType !== 'plex' && serviceType !== 'emby') {
      return reject(new Error('不支持的媒体服务类型'));
    }
    
    // 验证必要参数
    if (!data.code) {
      return reject(new Error('缺少邀请码'));
    }
    
    if (serviceType === 'plex' && !data.email) {
      return reject(new Error('缺少 Plex 邮箱'));
    }
    
    if (serviceType === 'emby' && !data.username) {
      return reject(new Error('缺少 Emby 用户名'));
    }

    // 生产环境：使用apiClient发送请求
    if (process.env.NODE_ENV === 'production') {
      apiClient.post(`/api/invite/redeem/${serviceType}`, data)
        .then(response => {
          resolve({
            success: response.data.success,
            message: response.data.message
          });
        })
        .catch(error => {
          console.error(`兑换 ${serviceType} 邀请码失败:`, error);
          reject(error);
        });
    } else {
      // 开发环境模拟
      setTimeout(() => {
        // 模拟成功响应
        resolve({
          success: true,
          message: `邀请码兑换成功！已添加到 ${serviceType === 'plex' ? 'Plex' : 'Emby'}。`
        });
      }, 800);
    }
  });
}

/**
 * 获取媒体服务的注册状态
 * @returns {Promise} 包含注册状态的Promise对象
 */
export function getMediaServiceRegisterStatus() {
  return new Promise((resolve, reject) => {
    if (process.env.NODE_ENV === 'production') {
      apiClient.get('/api/invite/register-status')
        .then(response => {
          resolve({
            plex: response.data.plex,
            emby: response.data.emby
          });
        })
        .catch(error => {
          console.error('获取媒体服务注册状态失败:', error);
          reject(error);
        });
    } else {
      // 开发环境模拟
      setTimeout(() => {
        resolve({
          plex: true,
          emby: true
        });
      }, 300);
    }
  });
}

/**
 * 检查邀请码是否为特权邀请码
 * @param {string} code - 邀请码
 * @returns {Promise} 包含特权状态的Promise对象
 */
export function checkPrivilegedInviteCode(code) {
  return new Promise((resolve) => {
    if (!code) {
      return resolve({ privileged: false });
    }

    if (process.env.NODE_ENV === 'production') {
      apiClient.post('/api/invite/check-privileged', { code })
        .then(response => {
          resolve({
            privileged: response.data.privileged
          });
        })
        .catch(error => {
          console.error('检查特权邀请码失败:', error);
          // 出错时默认为非特权码
          resolve({ privileged: false });
        });
    } else {
      // 开发环境模拟 - 模拟一些特权码
      setTimeout(() => {
        const privilegedCodes = ['ADMIN123', 'VIP999', 'SUPER888'];
        resolve({
          privileged: privilegedCodes.includes(code.toUpperCase())
        });
      }, 200);
    }
  });
}

/**
 * 绑定媒体服务账户
 * @param {string} serviceType - 服务类型 ('plex' 或 'emby')
 * @param {Object} data - 请求数据对象
 * @returns {Promise} 包含绑定结果的Promise对象
 */
export function bindMediaServiceAccount(serviceType, data) {
  return new Promise((resolve, reject) => {
    if (process.env.NODE_ENV === 'production') {
      apiClient.post(`/api/user/bind/${serviceType}`, data)
        .then(response => {
          resolve({
            success: response.data.success,
            message: response.data.message
          });
        })
        .catch(error => {
          console.error(`绑定 ${serviceType} 账户失败:`, error);
          reject(error);
        });
    } else {
      // 开发环境模拟
      setTimeout(() => {
        resolve({
          success: true,
          message: `${serviceType} 账户绑定成功！`
        });
      }, 800);
    }
  });
}
