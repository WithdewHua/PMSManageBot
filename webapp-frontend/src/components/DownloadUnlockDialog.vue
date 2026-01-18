<template>
  <v-dialog v-model="showDialog" max-width="400">
    <v-card>
      <v-card-title class="d-flex align-center">
        <v-icon start color="primary">mdi-download-lock</v-icon>
        解锁下载权限
      </v-card-title>
      <v-card-text>
        <div v-if="loading" class="text-center py-4">
          <v-progress-circular indeterminate color="primary" size="32"></v-progress-circular>
          <div class="mt-2">加载中...</div>
        </div>
        <div v-else>
          <!-- 已解锁状态 -->
          <div v-if="isUnlocked" class="text-center py-4">
            <v-icon size="64" color="success">mdi-check-circle</v-icon>
            <div class="mt-3 text-h6">下载权限已解锁</div>
            <div class="mt-2 text-body-2 text-grey">
              <template v-if="isPremium">
                您是 Premium 会员，自动拥有下载权限
              </template>
              <template v-else>
                解锁时间: {{ formatUnlockTime(unlockTime) }}
              </template>
            </div>
          </div>
          
          <!-- 未解锁状态 -->
          <div v-else>
            <v-alert type="info" variant="tonal" density="compact" class="mb-4">
              <div class="text-body-2">
                解锁下载权限后，您可以在 {{ serviceName }} 客户端中下载内容到本地观看。
              </div>
            </v-alert>
            
            <div class="d-flex justify-space-between align-center mb-3">
              <span>服务类型：</span>
              <v-chip :color="service === 'plex' ? 'orange' : 'green'" size="small">
                <v-icon start size="small">{{ service === 'plex' ? 'mdi-plex' : 'mdi-emby' }}</v-icon>
                {{ serviceName }}
              </v-chip>
            </div>
            
            <div class="d-flex justify-space-between align-center mb-3">
              <span>解锁费用：</span>
              <span class="text-h6 text-primary">{{ unlockCost }} 积分</span>
            </div>
            
            <div class="d-flex justify-space-between align-center mb-3">
              <span>当前积分：</span>
              <span :class="currentCredits >= unlockCost ? 'text-success' : 'text-error'">
                {{ currentCredits.toFixed(2) }}
              </span>
            </div>
            
            <v-divider class="my-3"></v-divider>
            
            <div class="text-body-2 text-grey mb-2">
              <v-icon size="small" class="mr-1">mdi-information-outline</v-icon>
              提示：
            </div>
            <ul class="text-body-2 text-grey ml-4">
              <li>解锁后永久有效，无需续费</li>
              <li>Premium 会员自动拥有下载权限</li>
            </ul>
            
            <div v-if="error" class="mt-3">
              <v-alert type="error" variant="tonal" density="compact">
                {{ error }}
              </v-alert>
            </div>
          </div>
        </div>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn text @click="closeDialog">
          {{ isUnlocked ? '关闭' : '取消' }}
        </v-btn>
        <v-btn 
          v-if="!isUnlocked && !loading"
          color="primary" 
          @click="confirmUnlock"
          :loading="processing"
          :disabled="processing || currentCredits < unlockCost"
        >
          <v-icon start>mdi-lock-open</v-icon>
          确认解锁
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { getDownloadPermissionStatus, unlockDownloadPermission } from '@/services/downloadService'

export default {
  name: 'DownloadUnlockDialog',
  props: {
    currentCredits: {
      type: Number,
      required: true
    }
  },
  data() {
    return {
      showDialog: false,
      service: '',
      loading: false,
      processing: false,
      error: '',
      isUnlocked: false,
      isPremium: false,
      unlockTime: null,
      unlockCost: 200 // 默认值，会从后端获取
    }
  },
  computed: {
    serviceName() {
      return this.service === 'plex' ? 'Plex' : 'Emby'
    }
  },
  methods: {
    // 打开对话框
    async open(service) {
      this.service = service
      this.showDialog = true
      this.loading = true
      this.error = ''
      
      try {
        const status = await getDownloadPermissionStatus(service)
        this.isUnlocked = status.is_unlocked
        this.isPremium = status.is_premium
        this.unlockTime = status.unlock_time
        this.unlockCost = status.unlock_cost || 200
      } catch (error) {
        this.error = '获取状态失败，请稍后重试'
        console.error('获取下载权限状态失败:', error)
      } finally {
        this.loading = false
      }
    },
    
    // 关闭对话框
    closeDialog() {
      this.showDialog = false
    },
    
    // 确认解锁
    async confirmUnlock() {
      this.processing = true
      this.error = ''
      
      try {
        const result = await unlockDownloadPermission(this.service)
        
        if (result.success) {
          this.isUnlocked = true
          this.unlockTime = Math.floor(Date.now() / 1000)
          
          // 显示成功提示
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showPopup({
              title: '解锁成功',
              message: result.message || '下载权限已解锁'
            })
          }
          
          // 通知父组件更新
          this.$emit('unlocked', {
            service: this.service,
            cost: this.unlockCost
          })
        } else {
          this.error = result.message || '解锁失败'
        }
      } catch (error) {
        this.error = error.response?.data?.detail || '请求失败，请稍后再试'
        console.error('解锁下载权限失败:', error)
      } finally {
        this.processing = false
      }
    },
    
    // 格式化解锁时间
    formatUnlockTime(timestamp) {
      if (!timestamp) return '未知'
      const date = new Date(timestamp * 1000)
      return date.toLocaleString()
    }
  }
}
</script>

<style scoped>
.text-grey {
  color: #9e9e9e;
}
</style>
