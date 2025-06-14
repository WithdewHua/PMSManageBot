<template>
  <div class="activities-container">
    <div class="content-wrapper">
      <!-- 加载状态 -->
      <div v-if="loading" class="loading-container">
        <div class="loading-content">
          <v-progress-circular indeterminate color="primary" size="50" width="4"></v-progress-circular>
          <div class="loading-text">加载中...</div>
        </div>
      </div>

      <!-- 错误状态 -->
      <div v-else-if="error" class="error-container">
        <v-alert type="error" class="error-alert" rounded="lg" elevation="4">{{ error }}</v-alert>
        <v-btn color="primary" @click="fetchUserInfoAndCheckStatus" class="mt-3">
          重试
        </v-btn>
      </div>

      <!-- 活动列表 -->
      <div v-else class="activities-list">
        <!-- 活动卡片列表 -->
        <v-card 
          v-for="activity in activities" 
          :key="activity.id"
          class="activity-card mb-4" 
          elevation="8"
          :class="{ 
            'coming-soon': !activity.enabled,
            'insufficient-credits': activity.enabled && !canParticipateActivity(activity)
          }"
          @click="activity.enabled && openActivityDialog(activity)"
        >
          <div class="activity-header">
            <v-icon class="activity-icon" size="40" :color="activity.iconColor">
              {{ activity.icon }}
            </v-icon>
            <div class="activity-info">
              <h3 class="activity-title">{{ activity.title }}</h3>
              <p class="activity-subtitle">{{ activity.description }}</p>
              
              <!-- 积分要求信息 -->
              <div v-if="activity.enabled" class="credits-requirement mt-2">
                <v-chip
                  size="small"
                  variant="outlined"
                  :color="canParticipateActivity(activity) ? 'success' : 'warning'"
                  class="mr-2"
                >
                  <v-icon size="small" class="mr-1">mdi-star</v-icon>
                  最低积分要求： {{ activity.requireCredits }}
                </v-chip>
                
                <v-chip
                  v-if="activity.costCredits"
                  size="small"
                  variant="outlined"
                  color="info"
                >
                  <v-icon size="small" class="mr-1">mdi-minus</v-icon>
                  参与消耗积分：{{ activity.costCredits }}
                </v-chip>
              </div>
            </div>
            <v-chip 
              class="activity-status" 
              :color="getActivityStatusColor(activity)"
              variant="elevated"
            >
              {{ getActivityStatusText(activity) }}
            </v-chip>
          </div>
          
          <v-card-actions class="justify-center">
            <div class="text-caption" :class="getActivityActionTextClass(activity)">
              {{ getActivityActionText(activity) }}
            </div>
          </v-card-actions>
        </v-card>
      </div>

      <!-- 幸运大转盘弹窗 -->
      <v-dialog v-model="showLuckyWheelDialog" max-width="800" persistent>
        <v-card class="activity-dialog">
          <v-card-title class="d-flex align-center justify-space-between">
            <div class="d-flex align-center">
              <v-icon class="mr-2" color="warning">mdi-ferris-wheel</v-icon>
              幸运大转盘
            </div>
            <v-btn icon @click="closeLuckyWheelDialog">
              <v-icon>mdi-close</v-icon>
            </v-btn>
          </v-card-title>
          
          <v-divider></v-divider>
          
          <v-card-text class="pa-6">
            <div class="activity-content">
              <LuckyWheel 
                @spin-complete="onSpinComplete" 
                @result-closed="onResultClosed"
              />
            </div>
          </v-card-text>
          
          <v-card-actions class="justify-center pb-4">
            <div class="text-caption text-info">
              当前积分：{{ userCredits.toFixed(2) }}
            </div>
          </v-card-actions>
        </v-card>
      </v-dialog>

      <!-- 通用活动弹窗 -->
      <v-dialog v-model="showActivityDialog" max-width="600">
        <v-card v-if="selectedActivity" class="activity-dialog">
          <v-card-title class="d-flex align-center justify-space-between">
            <div class="d-flex align-center">
              <v-icon class="mr-2" :color="selectedActivity.iconColor">{{ selectedActivity.icon }}</v-icon>
              {{ selectedActivity.title }}
            </div>
            <v-btn icon @click="closeActivityDialog">
              <v-icon>mdi-close</v-icon>
            </v-btn>
          </v-card-title>
          
          <v-divider></v-divider>
          
          <v-card-text class="pa-6">
            <div class="text-center">
              <v-icon size="80" :color="selectedActivity.iconColor" class="mb-4">
                {{ selectedActivity.icon }}
              </v-icon>
              <h3 class="mb-3">{{ selectedActivity.title }}</h3>
              <p class="text-body-1 mb-4">{{ selectedActivity.description }}</p>
              
              <!-- 积分要求信息 -->
              <div v-if="selectedActivity.enabled" class="credits-info mb-4">
                <v-alert
                  :type="canParticipateActivity(selectedActivity) ? 'success' : 'warning'"
                  variant="tonal"
                  density="compact"
                  class="mb-3"
                >
                  <div class="d-flex align-center justify-space-between">
                    <span>
                      <v-icon size="small" class="mr-1">mdi-star</v-icon>
                      最低积分要求：{{ selectedActivity.requireCredits }}
                    </span>
                    <span class="font-weight-bold">
                      当前积分：{{ userCredits.toFixed(2) }}
                    </span>
                  </div>
                </v-alert>
                
                <v-alert
                  v-if="selectedActivity.costCredits"
                  type="info"
                  variant="tonal"
                  density="compact"
                  class="mb-3"
                >
                  <v-icon size="small" class="mr-1">mdi-minus</v-icon>
                  每次参与消耗：{{ selectedActivity.costCredits }} 积分
                </v-alert>
                
                <v-alert
                  v-if="!canParticipateActivity(selectedActivity)"
                  type="error"
                  variant="tonal"
                  density="compact"
                >
                  <v-icon size="small" class="mr-1">mdi-alert</v-icon>
                  积分不足，还需 {{ (selectedActivity.requireCredits - userCredits).toFixed(2) }} 积分
                </v-alert>
              </div>
              
              <v-chip 
                :color="selectedActivity.enabled ? (canParticipateActivity(selectedActivity) ? 'success' : 'warning') : 'grey'"
                variant="elevated"
                class="mb-4"
              >
                {{ getActivityStatusText(selectedActivity) }}
              </v-chip>
            </div>
          </v-card-text>
        </v-card>
      </v-dialog>
    </div>
  </div>
</template>

<script>
import LuckyWheel from '@/components/LuckyWheel.vue'
import { getUserInfo } from '@/api'
import { getLuckyWheelUserStatus } from '@/services/wheelService'

export default {
  name: 'Activities',
  components: {
    LuckyWheel
  },
  data() {
    return {
      userCredits: 0, // 用户积分
      loading: true, // 加载状态
      error: null, // 错误信息
      showLuckyWheelDialog: false, // 幸运大转盘弹窗
      showActivityDialog: false, // 通用活动弹窗
      selectedActivity: null, // 选中的活动
      // 活动配置 - 将从后端获取
      activitiesConfig: {
        luckyWheel: {
          costCredits: 10,
          minCreditsRequired: 30
        }
      },
      activities: [
        {
          id: 'lucky-wheel',
          title: '幸运大转盘',
          description: '转一转，赢取丰厚奖励',
          icon: 'mdi-ferris-wheel',
          iconColor: 'warning',
          enabled: true,
          // 这些值将从后端获取
          requireCredits: 30,
          costCredits: 10
        },
        {
          id: 'black-jack',
          title: '21 点',
          description: '🃏沉浸娱乐，抓住财富',
          icon: 'mdi-gift',
          iconColor: 'pink',
          enabled: false,
          requireCredits: 50,
          costCredits: 20
        }
      ]
    }
  },
  mounted() {
    // 获取用户信息和活动配置（优化：一次调用同时获取积分和活动配置）
    this.fetchUserInfoAndCheckStatus()
  },
  computed: {
    // 检查用户是否可以参与各个活动
    canParticipateActivity() {
      return (activity) => {
        return this.userCredits >= activity.requireCredits
      }
    }
  },
  methods: {
    async fetchActivitiesConfig() {
      try {
        // 获取幸运大转盘配置，同时获取用户积分信息
        const response = await getLuckyWheelUserStatus()
        const config = response.data
        
        // 更新用户积分（从 getLuckyWheelUserStatus 获取）
        this.userCredits = config.current_credits
        
        // 更新活动配置
        this.activitiesConfig.luckyWheel = {
          costCredits: config.cost_credits,
          minCreditsRequired: config.min_credits_required
        }
        
        // 更新活动列表中的配置
        const luckyWheelActivity = this.activities.find(a => a.id === 'lucky-wheel')
        if (luckyWheelActivity) {
          luckyWheelActivity.requireCredits = config.min_credits_required
          luckyWheelActivity.costCredits = config.cost_credits
        }
        
        // 21点游戏暂时使用模拟配置
        const blackJackActivity = this.activities.find(a => a.id === 'black-jack')
        if (blackJackActivity) {
          blackJackActivity.requireCredits = 50
          blackJackActivity.costCredits = 20
        }
        
        console.log('活动配置获取成功:', this.activitiesConfig)
      } catch (err) {
        console.error('获取活动配置失败:', err)
        // 使用默认配置，但仍需要获取用户积分
        const luckyWheelActivity = this.activities.find(a => a.id === 'lucky-wheel')
        if (luckyWheelActivity) {
          luckyWheelActivity.requireCredits = 30
          luckyWheelActivity.costCredits = 10
        }
        
        const blackJackActivity = this.activities.find(a => a.id === 'black-jack')
        if (blackJackActivity) {
          blackJackActivity.requireCredits = 50
          blackJackActivity.costCredits = 20
        }
        
        // 如果获取活动配置失败，仍需要获取用户积分
        await this.fetchUserCreditsOnly()
      }
    },

    async fetchUserCreditsOnly() {
      try {
        // 仅获取用户积分信息
        const response = await getUserInfo()
        this.userCredits = response.data.credits
      } catch (err) {
        console.error('获取用户积分失败:', err)
        this.error = err.response?.data?.detail || '获取用户信息失败'
      }
    },

    async fetchUserInfoAndCheckStatus() {
      try {
        this.loading = true
        this.error = null
        
        // 优化：直接调用 fetchActivitiesConfig，它会同时获取积分信息
        await this.fetchActivitiesConfig()
        
        this.loading = false
      } catch (err) {
        this.error = err.response?.data?.detail || '获取用户信息失败'
        this.loading = false
        console.error('获取用户信息失败:', err)
      }
    },
    
    onSpinComplete(result) {
      // 转盘完成回调
      console.log('转盘结果：', result)
      // 转盘已经通过后端处理，这里只需要处理前端逻辑
    },
    
    onResultClosed(result) {
      // 结果弹窗关闭后更新用户积分信息
      console.log('结果弹窗已关闭，转盘结果：', result, '更新用户积分信息')
      // 优化：只更新积分信息，不需要重新获取活动配置
      this.fetchUserCreditsOnly()
    },

    // 打开活动弹窗
    openActivityDialog(activity) {
      // 检查是否满足参与条件
      if (!this.canParticipateActivity(activity)) {
        // 不满足条件时显示提示但仍可以打开弹窗查看详情
        console.log(`积分不足，需要 ${activity.requireCredits} 积分才能参与`)
      }
      
      if (activity.id === 'lucky-wheel') {
        this.showLuckyWheelDialog = true
      } else {
        this.selectedActivity = activity
        this.showActivityDialog = true
      }
    },

    // 关闭幸运大转盘弹窗
    closeLuckyWheelDialog() {
      this.showLuckyWheelDialog = false
    },

    // 关闭通用活动弹窗
    closeActivityDialog() {
      this.showActivityDialog = false
      this.selectedActivity = null
    },

    // 获取活动状态颜色
    getActivityStatusColor(activity) {
      if (!activity.enabled) return 'grey'
      if (!this.canParticipateActivity(activity)) return 'warning'
      return 'success'
    },

    // 获取活动状态文本
    getActivityStatusText(activity) {
      if (!activity.enabled) return '敬请期待'
      if (!this.canParticipateActivity(activity)) return '积分不足'
      return '立即参与'
    },

    // 获取活动操作文本
    getActivityActionText(activity) {
      if (!activity.enabled) return '活动暂未开放'
      if (!this.canParticipateActivity(activity)) {
        const need = activity.requireCredits - this.userCredits
        return `还需 ${need.toFixed(2)} 积分才能参与`
      }
      return '点击进入活动'
    },

    // 获取活动操作文本样式
    getActivityActionTextClass(activity) {
      if (!activity.enabled) return 'text-grey'
      if (!this.canParticipateActivity(activity)) return 'text-warning'
      return 'text-primary'
    }
  }
}
</script>

<style scoped>
.activities-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
  padding-bottom: 80px; /* 为底部导航栏留出空间 */
}

.content-wrapper {
  max-width: 800px;
  margin: 0 auto;
  padding-top: 20px;
}

.activities-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.activity-card {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  overflow: hidden;
  backdrop-filter: blur(10px);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  cursor: pointer;
}

.activity-card:hover:not(.coming-soon) {
  transform: translateY(-4px);
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.15) !important;
}

.activity-header {
  display: flex;
  align-items: center;
  padding: 24px;
  gap: 16px;
}

.activity-icon {
  background: rgba(255, 152, 0, 0.1);
  border-radius: 12px;
  padding: 8px;
}

.activity-info {
  flex: 1;
}

.activity-title {
  font-size: 20px;
  font-weight: 700;
  color: #333;
  margin: 0 0 4px 0;
}

.activity-subtitle {
  font-size: 14px;
  color: #666;
  margin: 0;
}

.activity-status {
  font-weight: 600;
}

.activity-content {
  padding: 0 24px 24px 24px;
}

.coming-soon {
  opacity: 0.7;
  cursor: default;
}

.coming-soon .activity-header {
  opacity: 0.6;
}

.insufficient-credits {
  border: 2px solid #ff9800;
  background: rgba(255, 152, 0, 0.05);
}

.insufficient-credits .activity-header {
  opacity: 0.8;
}

.credits-requirement {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.credits-requirement .v-chip {
  font-size: 11px;
  height: 24px;
}

.credits-info .v-alert {
  text-align: left;
}

.credits-info .v-alert .v-alert__content {
  font-size: 14px;
}

.activity-dialog {
  border-radius: 20px;
  overflow: hidden;
}

.activity-dialog .v-card-title {
  background: linear-gradient(45deg, #667eea, #764ba2);
  color: white;
  font-weight: 600;
}

.activity-content {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 200px;
}

/* 原有的空状态样式保留，以防需要 */
.empty-state {
  text-align: center;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  padding: 60px 40px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
}

.empty-icon {
  margin-bottom: 20px;
  opacity: 0.7;
}

.empty-title {
  font-size: 24px;
  font-weight: 600;
  color: #333;
  margin-bottom: 10px;
}

.empty-description {
  font-size: 16px;
  color: #666;
  margin: 0;
}

/* 响应式设计 */
@media (max-width: 480px) {
  .activities-container {
    padding: 10px;
  }
  
  .content-wrapper {
    padding-top: 10px;
  }
  
  .activity-header {
    padding: 16px;
    flex-direction: column;
    text-align: center;
    gap: 12px;
  }
  
  .activity-content {
    padding: 0 16px 16px 16px;
  }
  
  .activity-title {
    font-size: 18px;
  }
  
  .activity-subtitle {
    font-size: 13px;
  }
  
  .empty-state {
    padding: 40px 20px;
  }
  
  .empty-title {
    font-size: 20px;
  }
  
  .empty-description {
    font-size: 14px;
  }
}
</style>