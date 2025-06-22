<template>
  <v-dialog v-model="showDialog" max-width="480" persistent>
    <v-card class="premium-dialog" elevation="12">
      <!-- 头部渐变背景 -->
      <div class="premium-header">
        <div class="header-content">
          <div class="crown-container">
            <v-icon size="32" class="crown-icon">mdi-crown</v-icon>
            <div class="crown-glow"></div>
          </div>
          <div class="header-text">
            <div class="header-title">解锁 Premium 会员</div>
            <div class="header-subtitle">享受更多线路</div>
          </div>
        </div>
      </div>
      
      <v-card-text class="pa-4">
        <div v-if="loading" class="text-center py-6">
          <div class="loading-container">
            <v-progress-circular 
              indeterminate 
              color="amber-darken-2" 
              size="50"
              width="5"
            ></v-progress-circular>
            <div class="loading-dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
          <div class="mt-3 text-body-1 text-primary">获取价格信息中...</div>
        </div>
        
        <v-form v-else ref="form" v-model="valid" lazy-validation>
          <!-- 警告提示 -->
          <v-alert
            type="warning"
            variant="tonal"
            rounded="lg"
            class="mb-4 warning-alert"
            density="compact"
          >
            <div class="d-flex align-center">
              <v-icon size="20" class="mr-2">mdi-alert-outline</v-icon>
              <div>
                <div class="text-body-2 font-weight-bold mb-1">重要提醒</div>
                <div class="text-caption">无任何保证，谨慎激活</div>
              </div>
            </div>
          </v-alert>

          <!-- 永久会员提示 -->
          <v-alert
            v-if="isPermanent"
            type="success"
            variant="tonal"
            rounded="lg"
            class="mb-4 permanent-alert"
            density="compact"
          >
            <div class="d-flex align-center">
              <v-icon size="20" class="mr-2">mdi-crown-circle</v-icon>
              <div>
                <div class="text-body-2 font-weight-bold mb-1">永久会员</div>
                <div class="text-caption">您已是永久 Premium 会员，无需续费</div>
              </div>
            </div>
          </v-alert>

          <!-- 当前积分显示 -->
          <v-card
            class="credits-card mb-4"
            elevation="3"
            rounded="lg"
          >
            <div class="credits-background"></div>
            <v-card-text class="text-center pa-4 position-relative d-flex flex-column justify-center align-center">
              <v-icon size="24" color="amber-darken-2" class="mb-1">mdi-coins</v-icon>
              <div class="text-caption text-medium-emphasis mb-1">当前可用积分</div>
              <div class="credits-amount">
                <span class="credits-number">{{ currentCredits.toFixed(2) }}</span>
                <span class="credits-unit">积分</span>
              </div>
            </v-card-text>
          </v-card>

          <!-- 天数选择 -->
          <div class="mb-4" v-if="!isPermanent">
            <div class="section-title mb-3">
              <v-icon color="primary" class="mr-2" size="20">mdi-calendar-range</v-icon>
              <span class="text-body-1 font-weight-bold">选择解锁天数</span>
            </div>
            <div class="days-grid">
              <v-btn 
                v-for="option in dayOptions" 
                :key="option.days"
                :variant="selectedDays === option.days ? 'elevated' : 'outlined'"
                :color="selectedDays === option.days ? 'amber-darken-2' : 'grey-lighten-1'"
                class="days-btn"
                size="default"
                rounded="lg"
                @click="selectedDays = option.days"
              >
                <div class="day-option-content">
                  <div class="day-number">{{ option.days }}</div>
                  <div class="day-unit">天</div>
                </div>
              </v-btn>
            </div>
          </div>

          <!-- 费用计算 -->
          <v-card
            v-if="selectedDays && !isPermanent"
            class="cost-card mb-4"
            elevation="4"
            rounded="lg"
          >
            <div class="cost-header">
              <v-icon color="white" class="mr-2" size="18">mdi-calculator</v-icon>
              <span class="text-white font-weight-bold text-body-2">费用计算</span>
            </div>
            <v-card-text class="pa-3">
              <div class="cost-breakdown">
                <div class="cost-item">
                  <span class="cost-label">解锁天数</span>
                  <span class="cost-value">{{ selectedDays }} 天</span>
                </div>
                <div class="cost-item">
                  <span class="cost-label">单日价格</span>
                  <span class="cost-value">{{ dailyPrice }} 积分</span>
                </div>
                <v-divider class="my-2"></v-divider>
                <div class="total-cost">
                  <span class="total-label">总费用</span>
                  <div class="total-value">
                    <span class="total-number">{{ totalCost }}</span>
                    <span class="total-unit">积分</span>
                  </div>
                </div>
              </div>
            </v-card-text>
          </v-card>

          <!-- 到期时间显示 -->
          <v-card
            v-if="isPermanent"
            class="permanent-card mb-3"
            elevation="2"
            rounded="lg"
          >
            <div class="permanent-header">
              <v-icon color="success" class="mr-2" size="18">mdi-infinity</v-icon>
              <span class="text-success font-weight-bold text-body-2">永久会员状态</span>
            </div>
            <v-card-text class="pa-3">
              <div class="permanent-status">
                <v-icon color="success" class="mr-2" size="16">mdi-check-circle</v-icon>
                <span class="text-body-2">您已拥有永久Premium会员权限</span>
              </div>
            </v-card-text>
          </v-card>
          
          <v-card
            v-else-if="selectedDays && currentPremiumExpiry"
            class="expiry-card mb-3"
            elevation="2"
            rounded="lg"
          >
            <div class="expiry-header">
              <v-icon color="success" class="mr-2" size="18">mdi-calendar-check</v-icon>
              <span class="text-success font-weight-bold text-body-2">会员到期时间</span>
            </div>
            <v-card-text class="pa-3">
              <div class="expiry-time">
                <v-icon color="success" class="mr-2" size="16">mdi-clock-outline</v-icon>
                <span class="text-body-2">{{ formatExpiryTime(getNewExpiryTime()) }}</span>
              </div>
            </v-card-text>
          </v-card>
          
          <!-- 错误和成功消息 -->
          <v-alert
            v-if="errorMessage"
            type="error"
            variant="tonal"
            rounded="lg"
            class="mb-4"
            closable
            @click:close="errorMessage = ''"
          >
            <template #prepend>
              <v-icon>mdi-alert-circle</v-icon>
            </template>
            {{ errorMessage }}
          </v-alert>
          
          <v-alert
            v-if="successMessage"
            type="success"
            variant="tonal"
            rounded="lg"
            class="mb-4"
            closable
            @click:close="successMessage = ''"
          >
            <template #prepend>
              <v-icon>mdi-check-circle</v-icon>
            </template>
            {{ successMessage }}
          </v-alert>
        </v-form>
      </v-card-text>
      
      <v-card-actions class="pa-4 pt-0">
        <v-spacer></v-spacer>
        <v-btn 
          variant="outlined" 
          color="grey-darken-1" 
          size="default"
          rounded="lg"
          class="px-4"
          @click="closeDialog"
          :disabled="processing"
        >
          <v-icon start size="18">mdi-close</v-icon>
          取消
        </v-btn>
        <v-btn 
          color="amber-darken-2" 
          size="default"
          rounded="lg"
          class="px-6 ml-3 unlock-btn"
          elevation="3"
          @click="submitUnlock"
          :loading="processing"
          :disabled="loading || processing || !valid || !canUnlock || isPermanent"
        >
          <v-icon start size="18">mdi-crown</v-icon>
          {{ isPermanent ? '已是永久会员' : '确认解锁' }}
          <template v-slot:loader>
            <v-progress-circular indeterminate size="16"></v-progress-circular>
          </template>
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
/**
 * Premium解锁对话框组件
 * 
 * 永久会员检测逻辑：
 * 1. 通过 isPermanentPremium prop 直接传入
 * 2. 当用户已是Premium会员(isPremium=true)且到期时间为空时，表示永久会员
 * 3. 通过特殊值判断：到期时间包含 '9999' 或 'permanent' 字符串
 * 
 * 使用示例：
 * <premium-unlock-dialog
 *   :current-credits="userCredits"
 *   :current-premium-expiry="premiumExpiry"
 *   :is-premium="isPremium"
 *   :is-permanent-premium="false"
 *   @unlock-completed="handleUnlockCompleted"
 * />
 */
import { getPremiumPriceInfo, unlockPremium } from '@/services/premiumService'

export default {
  name: 'PremiumUnlockDialog',
  props: {
    currentCredits: {
      type: Number,
      default: 0
    },
    currentPremiumExpiry: {
      type: String,
      default: null
    },
    isPermanentPremium: {
      type: Boolean,
      default: false
    },
    isPremium: {
      type: Boolean,
      default: false
    }
  },
  data() {
    return {
      showDialog: false,
      valid: true,
      loading: false,
      processing: false,
      serviceType: '',
      selectedDays: 1,
      dailyPrice: 15,
      errorMessage: '',
      successMessage: '',
      dayOptions: [
        { days: 1, label: '1天' },
        { days: 3, label: '3天' },
        { days: 5, label: '5天' },
        { days: 10, label: '10天' },
        { days: 15, label: '15天' },
        { days: 30, label: '30天' },
        { days: 90, label: '90天'},
        { days: 180, label: '180天'},
        { days: 360, label: '360天'}
      ]
    }
  },
  computed: {
    totalCost() {
      return this.selectedDays * this.dailyPrice
    },
    canUnlock() {
      return this.selectedDays && 
             this.totalCost <= this.currentCredits &&
             !this.isPermanentPremium
    },
    isPermanent() {
      // 检查是否为永久会员的逻辑：
      // 1. 通过 isPermanentPremium prop 直接传入
      // 2. 当用户是Premium会员(isPremium=true)但到期时间为空时，表示永久会员
      // 3. 通过特殊值判断：包含 '9999' 或 'permanent' 的字符串
      // 
      // 注意：只有当用户已经是Premium会员时，到期时间为空才表示永久会员
      // 如果用户不是Premium会员，到期时间为空是正常的（表示还未购买）
      return this.isPermanentPremium || 
             (this.isPremium && 
              (this.currentPremiumExpiry === null || 
               this.currentPremiumExpiry === '' ||
               this.currentPremiumExpiry === undefined)) ||
             (this.currentPremiumExpiry && 
              (this.currentPremiumExpiry.includes('9999') || 
               this.currentPremiumExpiry.toLowerCase().includes('permanent')))
    }
  },
  methods: {
    async open(serviceType) {
      this.resetForm()
      this.serviceType = serviceType
      this.showDialog = true
      
      // 如果是永久会员，显示提示并禁用功能
      if (this.isPermanent) {
        this.errorMessage = ''
        this.successMessage = ''
        return
      }
      
      await this.loadPriceInfo()
    },
    
    closeDialog() {
      this.showDialog = false
    },
    
    resetForm() {
      this.selectedDays = 1
      this.errorMessage = ''
      this.successMessage = ''
      this.dailyPrice = 15
      this.valid = true
      if (this.$refs.form) {
        this.$refs.form.resetValidation()
      }
    },

    async loadPriceInfo() {
      this.loading = true
      try {
        const priceInfo = await getPremiumPriceInfo()
        this.dailyPrice = priceInfo.daily_price || 15
      } catch (error) {
        this.errorMessage = '获取价格信息失败'
        console.error('获取Premium价格信息失败:', error)
      } finally {
        this.loading = false
      }
    },
    
    async submitUnlock() {
      this.processing = true
      this.errorMessage = ''
      this.successMessage = ''
      
      try {
        const unlockData = {
          service: this.serviceType,
          days: this.selectedDays,
          total_cost: this.totalCost
        }
        
        const result = await unlockPremium(unlockData)
        
        if (result.success) {
          this.successMessage = result.message || 'Premium会员解锁成功'
          
          // 显示成功提示
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showPopup({
              title: '解锁成功',
              message: `成功解锁 ${this.selectedDays} 天Premium会员，消耗 ${this.totalCost} 积分`
            })
          }
          
          // 通知父组件刷新数据
          this.$emit('unlock-completed', {
            service: this.serviceType,
            days: this.selectedDays,
            cost: this.totalCost,
            current_credits: result.current_credits,
            premium_expiry: result.premium_expiry
          })
          
          // 延迟关闭对话框
          setTimeout(() => {
            this.closeDialog()
          }, 1500)
        } else {
          this.errorMessage = result.message || '解锁失败'
        }
      } catch (error) {
        this.errorMessage = error.response?.data?.message || '解锁失败，请稍后再试'
        console.error('Premium解锁失败:', error)
      } finally {
        this.processing = false
      }
    },

    getNewExpiryTime() {
      if (!this.currentPremiumExpiry) {
        // 如果当前没有Premium，从现在开始计算
        const now = new Date()
        return new Date(now.getTime() + this.selectedDays * 24 * 60 * 60 * 1000)
      } else {
        // 如果已有Premium，从到期时间开始计算
        const expiryDate = new Date(this.currentPremiumExpiry)
        const now = new Date()
        const startDate = expiryDate > now ? expiryDate : now
        return new Date(startDate.getTime() + this.selectedDays * 24 * 60 * 60 * 1000)
      }
    },

    formatExpiryTime(date) {
      return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      })
    }
  }
}
</script>

<style scoped>
/* 主要对话框样式 */
.premium-dialog {
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  overflow: hidden;
}

/* 头部样式 */
.premium-header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  position: relative;
  overflow: hidden;
  padding: 24px 20px;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  position: relative;
  z-index: 2;
}

.header-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.header-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: white;
  text-shadow: 0 2px 4px rgba(0,0,0,0.2);
}

.header-subtitle {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.9);
  font-weight: 500;
}

.premium-header::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 20"><defs><radialGradient id="a" cx="50%" cy="0%" r="100%"><stop offset="0%" stop-color="%23fff" stop-opacity=".1"/><stop offset="100%" stop-color="%23fff" stop-opacity="0"/></radialGradient></defs><rect width="100" height="20" fill="url(%23a)"/></svg>');
  pointer-events: none;
}

.crown-container {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 50px;
  min-height: 50px;
}

.crown-icon {
  position: relative;
  z-index: 3;
  color: #FFC107 !important;
  filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));
  animation: float 3s ease-in-out infinite;
}

.crown-glow {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 50px;
  height: 50px;
  background: radial-gradient(circle, rgba(255, 193, 7, 0.4) 0%, rgba(255, 193, 7, 0.1) 50%, transparent 70%);
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
  z-index: 1;
}

@keyframes float {
  0%, 100% { transform: translateY(0px); }
  50% { transform: translateY(-10px); }
}

@keyframes pulse {
  0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 0.7; }
  50% { transform: translate(-50%, -50%) scale(1.2); opacity: 0.3; }
}

/* 加载动画 */
.loading-container {
  position: relative;
  display: inline-block;
}

.loading-dots {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  gap: 4px;
}

.loading-dots span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #FFC107;
  animation: bounce 1.4s ease-in-out infinite both;
}

.loading-dots span:nth-child(1) { animation-delay: -0.32s; }
.loading-dots span:nth-child(2) { animation-delay: -0.16s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

/* 服务标签 */
.service-badge {
  display: flex;
  justify-content: center;
}

/* 积分卡片 */
.credits-card {
  position: relative;
  overflow: hidden;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.credits-background {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><pattern id="grain" width="100" height="100" patternUnits="userSpaceOnUse"><circle cx="25" cy="25" r="1" fill="%23fff" opacity="0.1"/><circle cx="75" cy="75" r="1" fill="%23fff" opacity="0.1"/><circle cx="50" cy="10" r="1" fill="%23fff" opacity="0.05"/></pattern></defs><rect width="100" height="100" fill="url(%23grain)"/></svg>');
  opacity: 0.3;
}

.credits-amount {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
}

.credits-number {
  font-size: 2.2rem;
  font-weight: 900;
  color: #FFC107;
  text-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.credits-unit {
  font-size: 1rem;
  font-weight: 600;
  color: rgba(255,255,255,0.9);
}

/* 价格卡片 */
.price-card {
  background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%);
}

.price-display {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
}

.price-label {
  font-size: 1rem;
  font-weight: 600;
  color: #5d4037;
}

.price-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.price-number {
  font-size: 1.5rem;
  font-weight: 800;
  color: #FF6F00;
}

.price-unit {
  font-size: 0.8rem;
  color: #5d4037;
  font-weight: 500;
}

/* 章节标题 */
.section-title {
  display: flex;
  align-items: center;
}

/* 天数选择网格 */
.days-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.days-btn {
  height: 60px !important;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.days-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 12px rgba(0,0,0,0.1) !important;
}

.day-option-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.day-number {
  font-size: 1.2rem;
  font-weight: 800;
  line-height: 1;
}

.day-unit {
  font-size: 0.75rem;
  font-weight: 500;
  opacity: 0.8;
}

/* 费用计算卡片 */
.cost-card {
  background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
  overflow: hidden;
}

.cost-header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 8px 16px;
  display: flex;
  align-items: center;
}

/* 费用明细项间距 */
.cost-breakdown > * + * {
  margin-top: 8px;
}

.cost-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}

.cost-label {
  font-size: 0.9rem;
  color: #546e7a;
  font-weight: 500;
}

.cost-value {
  font-size: 1rem;
  font-weight: 600;
  color: #2e7d32;
}

.total-cost {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
}

.total-label {
  font-size: 1.1rem;
  font-weight: 700;
  color: #1565c0;
}

.total-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.total-number {
  font-size: 1.8rem;
  font-weight: 900;
  color: #FF6F00;
  text-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.total-unit {
  font-size: 0.9rem;
  color: #5d4037;
  font-weight: 600;
}

/* 到期时间卡片 */
.expiry-card {
  background: linear-gradient(135deg, #e8f5e8 0%, #f1f8e9 100%);
  border: 1px solid #4caf50;
}

.expiry-header {
  padding: 8px 16px;
  background: rgba(76, 175, 80, 0.1);
  display: flex;
  align-items: center;
}

.expiry-time {
  display: flex;
  align-items: center;
  font-size: 1rem;
  font-weight: 600;
  color: #2e7d32;
  word-break: break-all;
  line-height: 1.3;
}

/* 解锁按钮 */
.unlock-btn {
  background: linear-gradient(135deg, #FFC107 0%, #FF8F00 100%) !important;
  color: white !important;
  font-weight: 700 !important;
  text-transform: none !important;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

.unlock-btn:hover {
  transform: translateY(-2px) !important;
  box-shadow: 0 8px 25px rgba(255, 193, 7, 0.4) !important;
}

.unlock-btn:active {
  transform: translateY(0) !important;
}

/* 警告提示框样式 */
.warning-alert {
  border: 2px solid #ff9800 !important;
  background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%) !important;
  box-shadow: 0 4px 12px rgba(255, 152, 0, 0.2) !important;
  animation: warningPulse 2s ease-in-out infinite;
}

/* 永久会员提示框样式 */
.permanent-alert {
  border: 2px solid #4caf50 !important;
  background: linear-gradient(135deg, #e8f5e8 0%, #c8e6c9 100%) !important;
  box-shadow: 0 4px 12px rgba(76, 175, 80, 0.2) !important;
  animation: permanentGlow 2s ease-in-out infinite;
}

@keyframes permanentGlow {
  0%, 100% { 
    box-shadow: 0 4px 12px rgba(76, 175, 80, 0.2);
  }
  50% { 
    box-shadow: 0 6px 20px rgba(76, 175, 80, 0.4);
  }
}

/* 永久会员卡片 */
.permanent-card {
  background: linear-gradient(135deg, #e8f5e8 0%, #f1f8e9 100%);
  border: 2px solid #4caf50;
}

.permanent-header {
  padding: 8px 16px;
  background: linear-gradient(135deg, #4caf50 0%, #388e3c 100%);
  display: flex;
  align-items: center;
  color: white;
}

.permanent-status {
  display: flex;
  align-items: center;
  font-size: 1rem;
  font-weight: 600;
  color: #2e7d32;
  word-break: break-all;
  line-height: 1.3;
}

@keyframes warningPulse {
  0%, 100% { 
    box-shadow: 0 4px 12px rgba(255, 152, 0, 0.2);
  }
  50% { 
    box-shadow: 0 6px 20px rgba(255, 152, 0, 0.4);
  }
}

/* 响应式设计 */
@media (max-width: 600px) {
  .premium-header {
    padding: 20px 16px;
  }
  
  .header-content {
    gap: 12px;
  }
  
  .header-title {
    font-size: 1.1rem;
  }
  
  .header-subtitle {
    font-size: 0.8rem;
  }
  
  .crown-container {
    min-width: 40px;
    min-height: 40px;
  }
  
  .crown-icon {
    font-size: 28px !important;
  }
  
  .crown-glow {
    width: 40px;
    height: 40px;
  }
  
  .days-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }
  
  .credits-number {
    font-size: 2rem;
  }
  
  .total-number {
    font-size: 1.5rem;
  }
  
  .price-number {
    font-size: 1.3rem;
  }
  
  .days-btn {
    height: 50px !important;
  }
  
  .day-number {
    font-size: 1.1rem;
  }
  
  .day-unit {
    font-size: 0.7rem;
  }
  
  .expiry-time {
    font-size: 0.9rem;
    flex-wrap: wrap;
  }
}

/* 动画效果 */
@keyframes slideInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.v-card {
  animation: slideInUp 0.4s ease-out;
}

/* 深色模式适配 */
@media (prefers-color-scheme: dark) {
  .premium-dialog {
    background: linear-gradient(135deg, #2a2a2a 0%, #1a1a1a 100%);
  }
  
  .cost-label {
    color: #b0bec5;
  }
  
  .expiry-time {
    color: #81c784;
  }
}
</style>
