import { inject } from 'vue'

/**
 * 在组合式 API 组件中使用 API 客户端
 * @returns {import('axios').AxiosInstance} API 客户端实例
 */
export function useApi() {
  return inject('api')
}

/**
 * API 请求通用错误处理
 * @param {Error} error - Axios 错误对象
 * @returns {Object} 格式化的错误信息
 */
export function handleApiError(error) {
  const errorMessage = {
    status: error.response?.status || 500,
    message: '请求失败，请稍后重试',
    details: null
  }
  
  if (error.response) {
    // 服务器返回了错误状态码
    errorMessage.message = error.response.data?.message || `错误 ${error.response.status}`;
    errorMessage.details = error.response.data;
  } else if (error.request) {
    // 请求已发出，但未收到响应
    errorMessage.message = '服务器无响应，请检查网络连接';
  }
  
  return errorMessage;
}
