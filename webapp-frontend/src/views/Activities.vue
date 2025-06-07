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
        <!-- 幸运大转盘活动 -->
        <v-card class="activity-card mb-4" elevation="8">
          <div class="activity-header">
            <v-icon class="activity-icon" size="40" color="warning">
              mdi-ferris-wheel
            </v-icon>
            <div class="activity-info">
              <h3 class="activity-title">幸运大转盘</h3>
              <p class="activity-subtitle">
                需要积分大于 30，赢取丰厚奖励
                <span v-if="userCredits < 30" class="text-error">
                  （当前积分：{{ userCredits.toFixed(2) }}）
                </span>
              </p>
            </div>
            <v-chip 
              class="activity-status" 
              :color="statusColor"
              variant="elevated"
            >
              {{ participationStatus }}
            </v-chip>
          </div>
          
          <v-divider></v-divider>
          
          <div class="activity-content">
            <LuckyWheel 
              @spin-complete="onSpinComplete" 
              @result-closed="onResultClosed"
              :disabled="!canParticipate" 
            />
          </div>
          
          <v-card-actions class="justify-center">
            <div v-if="userCredits < 30" class="text-caption text-error">
              积分不足，需要 30 积分才能参与
            </div>
            <div v-else class="text-caption text-success">
              积分充足，可以随时参与
            </div>
          </v-card-actions>
        </v-card>
        
        <!-- 更多活动占位 -->
        <v-card class="activity-card coming-soon" elevation="4">
          <div class="activity-header">
            <v-icon class="activity-icon" size="40" color="grey lighten-1">
              mdi-clock-outline
            </v-icon>
            <div class="activity-info">
              <h3 class="activity-title">更多活动</h3>
              <p class="activity-subtitle">敬请期待更多精彩活动</p>
            </div>
          </div>
        </v-card>
      </div>
    </div>
  </div>
</template>

<script>
import LuckyWheel from '@/components/LuckyWheel.vue'
import { getUserInfo } from '@/api'

export default {
  name: 'Activities',
  components: {
    LuckyWheel
  },
  data() {
    return {
      userCredits: 0, // 用户积分
      loading: true, // 加载状态
      error: null // 错误信息
    }
  },
  mounted() {
    // 获取用户信息
    this.fetchUserInfoAndCheckStatus()
  },
  computed: {
    // 检查是否可以参与转盘
    canParticipate() {
      return this.userCredits >= 30
    },
    
    // 获取参与状态文本
    participationStatus() {
      if (this.userCredits < 30) {
        return '积分不足'
      }
      return '可参与'
    },
    
    // 获取状态颜色
    statusColor() {
      if (this.userCredits < 30) {
        return 'error'
      }
      return 'success'
    }
  },
  methods: {
    async fetchUserInfoAndCheckStatus() {
      try {
        this.loading = true
        this.error = null
        
        // 获取用户信息
        const response = await getUserInfo()
        this.userCredits = response.data.credits
        
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
      
      // 这里可以向后端发送转盘结果并扣除积分
      this.sendSpinResult(result)
    },
    
    onResultClosed(result) {
      // 结果弹窗关闭后更新用户信息
      console.log('结果弹窗已关闭，转盘结果：', result, '更新用户信息')
      this.fetchUserInfoAndCheckStatus()
    },
    
    sendSpinResult(result) {
      // 向后端发送转盘结果的方法
      // TODO: 实现后端API调用，扣除积分并记录奖励
      console.log('发送转盘结果到后端：', result)
      
      // 不在这里立即更新积分信息，等待用户关闭结果弹窗后再更新
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
}

.coming-soon .activity-header {
  opacity: 0.6;
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