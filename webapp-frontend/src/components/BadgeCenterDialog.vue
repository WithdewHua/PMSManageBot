<template>
  <v-dialog v-model="dialog" max-width="800px" persistent scrollable>
    <v-card class="badge-center-dialog">
      <v-card-title class="dialog-title">
        <v-icon start size="28">mdi-medal</v-icon>
        <span class="title-text">勋章中心</span>
        <v-spacer></v-spacer>
        <v-btn 
          icon 
          variant="text" 
          size="small" 
          @click="close"
          class="close-btn"
        >
          <v-icon size="24">mdi-close</v-icon>
        </v-btn>
      </v-card-title>

      <v-divider></v-divider>

      <!-- 用户积分显示 -->
      <v-card-text class="px-6 pt-4 pb-2">
        <v-alert
          type="info"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          <div class="d-flex align-center justify-space-between">
            <span>当前积分</span>
            <span class="text-h6 font-weight-bold">{{ userCredits.toFixed(2) }}</span>
          </div>
        </v-alert>
      </v-card-text>

      <!-- 勋章列表 -->
      <v-card-text class="px-6 py-0" style="max-height: 60vh; overflow-y: auto;">
        <div v-if="loading" class="text-center py-8">
          <v-progress-circular indeterminate color="primary"></v-progress-circular>
          <p class="mt-4 text-grey">加载中...</p>
        </div>

        <div v-else-if="badges.length === 0" class="text-center py-8">
          <v-icon size="64" color="grey-lighten-1">mdi-medal-outline</v-icon>
          <p class="mt-4 text-grey">暂无可兑换的勋章</p>
        </div>

        <v-row v-else>
          <v-col
            v-for="badge in badges"
            :key="badge.id"
            cols="12"
            md="6"
          >
            <v-card
              :class="['badge-card', isOwned(badge.id) ? 'owned' : '']"
              elevation="2"
            >
              <v-card-text class="pa-4">
                <div class="d-flex align-start">
                  <!-- 勋章图标 -->
                  <div class="badge-icon-container mr-4">
                    <img
                      :src="badge.icon_url"
                      :alt="badge.name"
                      class="badge-icon"
                      @error="handleImageError"
                    >
                    <v-chip
                      v-if="isOwned(badge.id)"
                      color="success"
                      size="x-small"
                      class="owned-badge"
                    >
                      已拥有
                    </v-chip>
                  </div>

                  <!-- 勋章信息 -->
                  <div class="flex-grow-1">
                    <h3 class="badge-name mb-2">{{ badge.name }}</h3>
                    <p class="badge-description text-caption mb-3">
                      {{ badge.description }}
                    </p>

                    <div class="badge-details">
                      <v-chip
                        size="small"
                        color="red-darken-2"
                        variant="tonal"
                        class="mr-2 mb-2"
                      >
                        <span class="coin-icon">🪙</span>
                        {{ badge.credits_cost }} 积分
                      </v-chip>

                      <v-chip
                        size="small"
                        color="green-darken-2"
                        variant="tonal"
                        class="mr-2 mb-2"
                      >
                        <span class="chart-icon">📈</span>
                        +{{ (badge.bonus_percentage * 100).toFixed(0) }}% 积分加成
                      </v-chip>

                      <v-chip
                        size="small"
                        color="blue-darken-2"
                        variant="tonal"
                        class="mb-2"
                      >
                        <span class="clock-icon">⏰</span>
                        {{ badge.valid_days }} 天加成有效期
                      </v-chip>
                    </div>

                    <!-- 兑换按钮 -->
                    <div v-if="!isOwned(badge.id)" class="mt-3">
                      <v-btn
                        :disabled="userCredits < badge.credits_cost || redeeming"
                        color="primary"
                        size="small"
                        @click="handleRedeem(badge)"
                      >
                        <v-icon start size="18">mdi-gift</v-icon>
                        {{ userCredits < badge.credits_cost ? '积分不足' : '兑换' }}
                      </v-btn>
                      <div v-if="userCredits < badge.credits_cost" class="text-caption text-error mt-1">
                        还需 {{ (badge.credits_cost - userCredits).toFixed(2) }} 积分
                      </div>
                    </div>
                  </div>
                </div>
              </v-card-text>
            </v-card>
          </v-col>
        </v-row>

        <!-- 公共说明 -->
        <v-alert
          v-if="!loading && badges.length > 0"
          type="info"
          variant="tonal"
          density="compact"
          class="mt-4 mb-4 text-caption"
        >
          <div>
            <strong>勋章说明：</strong>
            <ul class="pl-4 mt-1 mb-0">
              <li>勋章兑换后永久拥有</li>
              <li>勋章积分加成有效期见具体勋章说明</li>
              <li>加成效果可叠加，兑换后立即生效</li>
              <li>每种勋章只能兑换一次</li>
            </ul>
          </div>
        </v-alert>
      </v-card-text>
    </v-card>

    <!-- 确认兑换对话框 -->
    <v-dialog v-model="confirmDialog" max-width="400">
      <v-card>
        <v-card-title class="text-h6">
          确认兑换
        </v-card-title>
        <v-card-text>
          <div class="text-center mb-4">
            <img
              v-if="selectedBadge"
              :src="selectedBadge.icon_url"
              :alt="selectedBadge.name"
              style="width: 80px; height: 80px;"
            >
          </div>
          <p class="mb-2">您确定要兑换 <strong>{{ selectedBadge?.name }}</strong> 吗？</p>
          <p class="text-caption text-grey mb-2">
            • 消耗积分：<strong>{{ selectedBadge?.credits_cost }}</strong><br>
            • 获得加成：<strong>+{{ (selectedBadge?.bonus_percentage * 100).toFixed(0) }}%</strong><br>
            • 加成有效期：<strong>{{ selectedBadge?.valid_days }} 天</strong><br>
            • 勋章状态：<strong class="text-success">永久拥有</strong>
          </p>
          <v-alert type="info" density="compact" class="mt-3">
            兑换后将剩余 <strong>{{ (userCredits - (selectedBadge?.credits_cost || 0)).toFixed(2) }}</strong> 积分
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn
            text="取消"
            @click="confirmDialog = false"
          ></v-btn>
          <v-btn
            color="primary"
            text="确认兑换"
            :loading="redeeming"
            @click="confirmRedeem"
          ></v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-dialog>
</template>

<script>
import { getBadgesList, redeemBadge } from '../services/badgeService'

export default {
  name: 'BadgeCenterDialog',
  data() {
    return {
      dialog: false,
      confirmDialog: false,
      loading: false,
      redeeming: false,
      badges: [],
      userCredits: 0,
      userBadges: [],
      selectedBadge: null,
    }
  },
  methods: {
    async open() {
      this.dialog = true
      await this.loadBadges()
    },
    close() {
      this.dialog = false
      this.confirmDialog = false
      this.selectedBadge = null
    },
    async loadBadges() {
      this.loading = true
      try {
        const response = await getBadgesList()
        if (response.data) {
          this.badges = response.data.badges || []
          this.userCredits = response.data.user_credits || 0
          this.userBadges = response.data.user_badges || []
        }
      } catch (error) {
        console.error('加载勋章列表失败:', error)
        this.$emit('error', error.response?.data?.detail || '加载勋章列表失败')
      } finally {
        this.loading = false
      }
    },
    isOwned(badgeId) {
      const owned = this.userBadges.some(ub => ub.badge_id === badgeId)
      console.log(`检查勋章 ${badgeId} 是否已拥有:`, owned)
      return owned
    },
    handleRedeem(badge) {
      console.log('handleRedeem called')
      console.log('- 勋章信息:', badge)
      console.log('- 用户积分:', this.userCredits)
      console.log('- 需要积分:', badge.credits_cost)
      console.log('- 积分是否足够:', this.userCredits >= badge.credits_cost)
      console.log('- 是否已拥有:', this.isOwned(badge.id))
      
      if (this.isOwned(badge.id)) {
        this.$emit('error', '您已拥有该勋章')
        return
      }
      if (this.userCredits < badge.credits_cost) {
        this.$emit('error', `积分不足，还需要 ${(badge.credits_cost - this.userCredits).toFixed(2)} 积分`)
        return
      }
      this.selectedBadge = badge
      this.confirmDialog = true
    },
    async confirmRedeem() {
      if (!this.selectedBadge) return

      this.redeeming = true
      try {
        const response = await redeemBadge(this.selectedBadge.id)
        if (response.data && response.data.success) {
          this.$emit('success', response.data.message || '兑换成功')
          this.confirmDialog = false
          this.selectedBadge = null
          // 重新加载勋章列表
          await this.loadBadges()
          // 通知父组件更新用户信息
          this.$emit('badge-redeemed')
        } else {
          this.$emit('error', response.data?.message || '兑换失败')
        }
      } catch (error) {
        console.error('兑换勋章失败:', error)
        this.$emit('error', error.response?.data?.detail || '兑换失败，请稍后重试')
      } finally {
        this.redeeming = false
      }
    },
    handleImageError(event) {
      // 如果图标加载失败，使用默认图标
      event.target.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIwIiBoZWlnaHQ9IjEyMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48Y2lyY2xlIGN4PSI2MCIgY3k9IjYwIiByPSI1MCIgZmlsbD0iI0ZGRDcwMCIvPjx0ZXh0IHg9IjYwIiB5PSI3MCIgZm9udC1zaXplPSI0MCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iI0ZGRiI+8J+PhTwvdGV4dD48L3N2Zz4='
    }
  }
}
</script>

<style scoped>
.badge-center-dialog {
  border-radius: 16px;
}

.dialog-title {
  font-size: 1.25rem;
  font-weight: 600;
  padding: 20px 24px;
  background: linear-gradient(135deg, #FFD700 0%, #FFA500 100%);
  color: white;
  display: flex;
  align-items: center;
}

.title-text {
  margin-left: 8px;
}

.close-btn {
  color: white !important;
  opacity: 0.9;
  transition: all 0.2s ease;
}

.close-btn:hover {
  opacity: 1;
  background-color: rgba(255, 255, 255, 0.15) !important;
  transform: rotate(90deg);
}

.close-btn:active {
  transform: rotate(90deg) scale(0.95);
}

.badge-card {
  border-radius: 12px;
  transition: all 0.3s ease;
  border: 2px solid transparent;
}

.badge-card:hover:not(.owned) {
  border-color: #FFD700;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(255, 215, 0, 0.3) !important;
}

.badge-card.owned {
  opacity: 0.7;
  background-color: #f5f5f5;
}

.badge-icon-container {
  position: relative;
  flex-shrink: 0;
}

.badge-icon {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  border: 2px solid #FFD700;
  padding: 4px;
  background: white;
}

.owned-badge {
  position: absolute;
  bottom: -4px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 10px !important;
  height: 18px !important;
}

.badge-name {
  font-size: 1.1rem;
  font-weight: 600;
  color: #333;
}

.badge-description {
  color: #666;
  line-height: 1.4;
}

.badge-details {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.coin-icon,
.chart-icon,
.clock-icon {
  margin-right: 4px;
  font-size: 14px;
}
</style>
