import { apiClient } from '@/main';

/**
 * 管理员标签管理服务
 */

/**
 * 设置线路标签
 * @param {string} lineName - 线路名称
 * @param {Array<string>} tags - 标签数组
 * @returns {Promise} 设置结果
 */
export async function setLineTags(lineName, tags) {
  try {
    const response = await apiClient.post('/api/admin/line_tags', {
      line_name: lineName,
      tags: tags
    });
    return response.data;
  } catch (error) {
    console.error('设置线路标签失败:', error);
    throw error;
  }
}

/**
 * 获取指定线路的标签
 * @param {string} lineName - 线路名称
 * @returns {Promise<Object>} 线路标签信息
 */
export async function getLineTags(lineName) {
  try {
    const response = await apiClient.get(`/api/admin/line_tags/${lineName}`);
    return response.data;
  } catch (error) {
    console.error('获取线路标签失败:', error);
    throw error;
  }
}

/**
 * 获取所有线路的标签信息
 * @returns {Promise<Object>} 所有线路标签信息
 */
export async function getAllLineTags() {
  try {
    console.log('发送请求到 /api/admin/all_line_tags')
    const response = await apiClient.get('/api/admin/all_line_tags');
    console.log('收到响应:', {
      status: response.status,
      headers: response.headers,
      data: response.data
    })
    
    // 检查响应状态
    if (response.status !== 200) {
      throw new Error(`HTTP错误: ${response.status}`)
    }
    
    return response.data;
  } catch (error) {
    console.error('获取所有线路标签失败:', error);
    
    // 增强错误信息
    if (error.response) {
      console.error('错误响应:', {
        status: error.response.status,
        data: error.response.data,
        headers: error.response.headers
      })
      
      if (error.response.status === 401) {
        throw new Error('未授权访问，请检查登录状态')
      } else if (error.response.status === 403) {
        throw new Error('权限不足，需要管理员权限')
      } else if (error.response.status >= 500) {
        throw new Error(`服务器错误: ${error.response.data?.detail || error.response.statusText}`)
      } else {
        throw new Error(`请求失败: ${error.response.data?.detail || error.response.statusText}`)
      }
    } else if (error.request) {
      console.error('网络错误:', error.request)
      throw new Error('网络连接失败，请检查网络状态')
    } else {
      throw new Error(`请求配置错误: ${error.message}`)
    }
  }
}

/**
 * 删除指定线路的所有标签
 * @param {string} lineName - 线路名称
 * @returns {Promise} 删除结果
 */
export async function deleteLineTags(lineName) {
  try {
    const response = await apiClient.delete(`/api/admin/line_tags/${lineName}`);
    return response.data;
  } catch (error) {
    console.error('删除线路标签失败:', error);
    throw error;
  }
}