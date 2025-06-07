<template>
  <div class="activities-container">
    <div class="content-wrapper">
      <!-- 活动列表 -->
      <div class="activities-list">
        <!-- 幸运大转盘活动 -->
        <v-card class="activity-card mb-4" elevation="8">
          <div class="activity-header">
            <v-icon class="activity-icon" size="40" color="warning">
              mdi-ferris-wheel
            </v-icon>
            <div class="activity-info">
              <h3 class="activity-title">幸运大转盘</h3>
              <p class="activity-subtitle">每日免费转一次，赢取VIP奖励</p>
            </div>
            <v-chip 
              class="activity-status" 
              :color="dailySpinUsed ? 'grey' : 'success'"
              variant="elevated"
            >
              {{ dailySpinUsed ? '已参与' : '可参与' }}
            </v-chip>
          </div>
          
          <v-divider></v-divider>
          
          <div class="activity-content">
            <LuckyWheel @spin-complete="onSpinComplete" :disabled="dailySpinUsed" />
          </div>
          
          <v-card-actions class="justify-center">
            <v-btn 
              color="primary" 
              variant="elevated"
              :disabled="dailySpinUsed"
              @click="resetDaily"
              v-if="dailySpinUsed"
            >
              明日再来
            </v-btn>
            <div v-else class="text-caption text-grey">
              今日还有 {{ remainingSpins }} 次机会
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

export default {
  name: 'Activities',
  components: {
    LuckyWheel
  },
  data() {
    return {
      dailySpinUsed: false, // 今日是否已使用转盘
      remainingSpins: 1 // 剩余转盘次数
    }
  },
  mounted() {
    // 检查今日转盘使用情况
    this.checkDailySpinStatus()
  },
  methods: {
    checkDailySpinStatus() {
      // 从localStorage检查今日是否已使用
      const today = new Date().toDateString()
      const lastSpinDate = localStorage.getItem('lastSpinDate')
      
      if (lastSpinDate === today) {
        this.dailySpinUsed = true
        this.remainingSpins = 0
      } else {
        this.dailySpinUsed = false
        this.remainingSpins = 1
      }
    },
    
    onSpinComplete(result) {
      // 转盘完成回调
      console.log('转盘结果：', result)
      
      // 标记今日已使用
      const today = new Date().toDateString()
      localStorage.setItem('lastSpinDate', today)
      
      this.dailySpinUsed = true
      this.remainingSpins = 0
      
      // 这里可以向后端发送转盘结果
      // this.sendSpinResult(result)
    },
    
    resetDaily() {
      // 仅用于测试，实际应用中不需要此功能
      localStorage.removeItem('lastSpinDate')
      this.checkDailySpinStatus()
    },
    
    sendSpinResult(result) {
      // 向后端发送转盘结果的方法
      // TODO: 实现后端API调用
      console.log('发送转盘结果到后端：', result)
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