import { apiClient } from '@/main';

/**
 * 线路调度服务
 * 提供线路调度功能的 API 调用
 */

/**
 * 检查线路调度解锁状态
 * @param {string} service - 服务类型 ('emby' 或 'plex')
 * @returns {Promise<Object>} 解锁状态信息
 */
export async function checkLineScheduleUnlockStatus(service) {
  try {
    const response = await apiClient.get(`/api/user/line-schedules/unlock-status/${service}`);
    return response.data;
  } catch (error) {
    console.error('检查线路调度解锁状态失败:', error);
    throw error;
  }
}

/**
 * 解锁线路调度功能
 * @param {string} service - 服务类型 ('emby' 或 'plex')
 * @returns {Promise<Object>} 解锁结果
 */
export async function unlockLineSchedule(service) {
  try {
    const response = await apiClient.post('/api/user/line-schedules/unlock', { service });
    return response.data;
  } catch (error) {
    console.error('解锁线路调度功能失败:', error);
    // 如果后端返回了错误响应，将其返回而不是抛出异常
    if (error.response && error.response.data) {
      return error.response.data;
    }
    throw error;
  }
}

/**
 * 获取用户的线路调度列表
 * @param {string} service - 服务类型 ('emby' 或 'plex')
 * @returns {Promise<Array>} 线路调度列表
 */
export async function getLineSchedules(service) {
  try {
    const response = await apiClient.get(`/api/user/line-schedules/${service}`);
    return response.data.schedules || [];
  } catch (error) {
    console.error('获取线路调度列表失败:', error);
    throw error;
  }
}

/**
 * 创建线路调度
 * @param {Object} scheduleData - 调度数据
 * @param {string} scheduleData.service - 服务类型 ('emby' 或 'plex')
 * @param {string} scheduleData.line - 线路名称
 * @param {Array<number>} scheduleData.days_of_week - 星期几列表 [0-6]
 * @param {string} scheduleData.start_time - 开始时间 HH:MM
 * @param {string} scheduleData.end_time - 结束时间 HH:MM
 * @param {number} scheduleData.priority - 优先级
 * @returns {Promise<Object>} 创建结果
 */
export async function createLineSchedule(scheduleData) {
  try {
    const response = await apiClient.post('/api/user/line-schedules', scheduleData);
    return response.data;
  } catch (error) {
    console.error('创建线路调度失败:', error);
    // 如果后端返回了错误响应，将其返回而不是抛出异常
    if (error.response && error.response.data) {
      return error.response.data;
    }
    throw error;
  }
}

/**
 * 更新线路调度
 * @param {number} scheduleId - 调度 ID
 * @param {Object} scheduleData - 要更新的调度数据
 * @returns {Promise<Object>} 更新结果
 */
export async function updateLineSchedule(scheduleId, scheduleData) {
  try {
    const response = await apiClient.put(`/api/user/line-schedules/${scheduleId}`, scheduleData);
    return response.data;
  } catch (error) {
    console.error('更新线路调度失败:', error);
    // 如果后端返回了错误响应，将其返回而不是抛出异常
    if (error.response && error.response.data) {
      return error.response.data;
    }
    throw error;
  }
}

/**
 * 删除线路调度
 * @param {number} scheduleId - 调度 ID
 * @returns {Promise<Object>} 删除结果
 */
export async function deleteLineSchedule(scheduleId) {
  try {
    const response = await apiClient.delete(`/api/user/line-schedules/${scheduleId}`);
    return response.data;
  } catch (error) {
    console.error('删除线路调度失败:', error);
    // 如果后端返回了错误响应，将其返回而不是抛出异常
    if (error.response && error.response.data) {
      return error.response.data;
    }
    throw error;
  }
}

/**
 * 获取当前生效的线路调度状态
 * @param {string} service - 服务类型 ('emby' 或 'plex')
 * @returns {Promise<Object>} 调度状态信息
 */
export async function getLineScheduleStatus(service) {
  try {
    const response = await apiClient.get(`/api/user/line-schedules/status/${service}`);
    return response.data;
  } catch (error) {
    console.error('获取线路调度状态失败:', error);
    throw error;
  }
}
