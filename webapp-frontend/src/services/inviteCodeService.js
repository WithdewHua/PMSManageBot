/**
 * 邀请码服务 - 处理所有与邀请码相关的操作
 */
import { apiClient } from '../main';

/**
 * 获取生成邀请码所需的积分信息
 * @returns {Promise} 包含所需积分和当前积分的Promise对象
 */
export function getInvitePointsInfo() {
  return new Promise((resolve, reject) => {
    // 生产环境：使用apiClient发送请求
    if (process.env.NODE_ENV === 'production') {
      apiClient.get('/api/invite/points-info')
        .then(response => {
          resolve({
            required_points: response.data.required_points,
            current_points: response.data.current_points,
            can_generate: response.data.can_generate,
            error_message: response.data.error_message || ''
          });
        })
        .catch(error => {
          console.error('获取邀请码积分信息失败:', error);
          reject(error);
        });
    } else {
      // 开发环境模拟
      setTimeout(() => {
        resolve({
          required_points: 1000,
          current_points: 1500,
          can_generate: true
        });
      }, 500);
    }
  });
}

/**
 * 生成邀请码
 * @returns {Promise} 包含生成结果的Promise对象
 */
export function generateInviteCode() {
  return new Promise((resolve, reject) => {
    // 生产环境：使用apiClient发送请求
    if (process.env.NODE_ENV === 'production') {
      apiClient.post('/api/invite/generate')
        .then(response => {
          resolve({
            success: response.data.success,
            message: response.data.message,
            code: response.data.code // 如果API直接返回邀请码
          });
        })
        .catch(error => {
          console.error('生成邀请码失败:', error);
          reject(error);
        });
    } else {
      // 开发环境模拟
      setTimeout(() => {
        resolve({
          success: true,
          message: '邀请码生成成功！已发送到您的消息中'
        });
      }, 1000);
    }
  });
}

/**
 * 将邀请码兑换为积分
 * @param {string} code - 邀请码
 * @returns {Promise} 包含兑换结果的Promise对象
 */
export function redeemInviteCodeForCredits(code) {
  return new Promise((resolve, reject) => {
    // 验证邀请码
    if (!code || code.trim().length === 0) {
      return reject(new Error('邀请码不能为空'));
    }

    // 生产环境：使用apiClient发送请求
    if (process.env.NODE_ENV === 'production') {
      apiClient.post('/api/invite/redeem-for-credits', { code: code.trim() })
        .then(response => {
          resolve({
            success: response.data.success,
            message: response.data.message,
            credits_earned: response.data.credits_earned,
            current_credits: response.data.current_credits
          });
        })
        .catch(error => {
          console.error('邀请码兑换积分失败:', error);
          reject(error);
        });
    } else {
      // 开发环境模拟
      setTimeout(() => {
        // 模拟成功响应
        resolve({
          success: true,
          message: '邀请码兑换成功！获得 288 积分',
          credits_earned: 288,
          current_credits: 1788
        });
      }, 800);
    }
  });
}
