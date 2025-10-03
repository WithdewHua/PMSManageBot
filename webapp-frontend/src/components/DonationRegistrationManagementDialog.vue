<template>
  <v-dialog v-model="showDialog" max-width="1200px" persistent>
    <v-card>
      <v-card-title class="d-flex align-center">
        <v-icon start color="orange-darken-2">mdi-hand-heart</v-icon>
        自助捐助登记管理
        <v-spacer></v-spacer>
        <v-btn icon @click="closeDialog" :disabled="processing">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </v-card-title>
      
      <v-card-text class="pa-0">
        <!-- 加载状态 -->
        <div v-if="loading" class="text-center py-8">
          <v-progress-circular indeterminate color="orange-darken-2"></v-progress-circular>
          <div class="mt-3">加载登记列表中...</div>
        </div>
        
        <!-- 错误状态 -->
        <div v-else-if="error" class="pa-6">
          <v-alert type="error" class="mb-4">{{ error }}</v-alert>
          <div class="text-center">
            <v-btn @click="loadPendingRegistrations" color="orange-darken-2" variant="outlined">
              重新加载
            </v-btn>
          </div>
        </div>
        
        <!-- 无数据状态 -->
        <div v-else-if="registrations.length === 0" class="text-center py-8">
          <v-icon size="64" color="grey-lighten-1">mdi-clipboard-off-outline</v-icon>
          <div class="mt-3 text-h6 text-grey-darken-1">暂无待处理的捐助登记</div>
          <div class="text-body-2 text-grey-darken-1 mt-2">所有登记都已处理完成</div>
        </div>
        
        <!-- 登记列表 -->
        <div v-else>
          <!-- 统计信息 -->
          <div class="pa-4 bg-orange-lighten-5">
            <v-row dense>
              <v-col cols="12" md="4">
                <div class="text-center">
                  <div class="text-h6 text-orange-darken-2">{{ registrations.length }}</div>
                  <div class="text-caption text-grey-darken-1">待处理登记</div>
                </div>
              </v-col>
              <v-col cols="12" md="4">
                <div class="text-center">
                  <div class="text-h6 text-success">{{ totalAmount.toFixed(2) }}元</div>
                  <div class="text-caption text-grey-darken-1">累计金额</div>
                </div>
              </v-col>
              <v-col cols="12" md="4">
                <div class="text-center">
                  <div class="text-h6 text-info">{{ uniqueUsers }}</div>
                  <div class="text-caption text-grey-darken-1">涉及用户</div>
                </div>
              </v-col>
            </v-row>
          </div>
          
          <!-- 登记卡片列表 -->
          <div class="pa-4">
            <v-row>
              <v-col 
                v-for="registration in registrations" 
                :key="registration.id"
                cols="12" 
                md="6" 
                lg="4"
              >
                <v-card 
                  class="registration-card" 
                  variant="outlined"
                  :class="{ 'processing': processingIds.includes(registration.id) }"
                >
                  <!-- 卡片头部 -->
                  <v-card-title class="pb-2">
                    <div class="d-flex align-center justify-space-between w-100">
                      <div class="d-flex align-center">
                        <v-avatar size="32" class="mr-3">
                          <v-icon>mdi-account</v-icon>
                        </v-avatar>
                        <div>
                          <div class="text-body-1 font-weight-bold">
                            {{ registration.username || `用户 ${registration.user_id}` }}
                          </div>
                          <div class="text-caption text-grey-darken-1">
                            ID: {{ registration.id }}
                          </div>
                        </div>
                      </div>
                      <v-chip 
                        :color="getPaymentMethodColor(registration.payment_method)"
                        size="small"
                        variant="tonal"
                      >
                        {{ getPaymentMethodText(registration.payment_method) }}
                      </v-chip>
                    </div>
                  </v-card-title>
                  
                  <!-- 卡片内容 -->
                  <v-card-text class="pt-0">
                    <!-- 金额信息 -->
                    <div class="mb-3">
                      <div class="d-flex align-center justify-space-between">
                        <span class="text-body-2 text-grey-darken-1">捐助金额</span>
                        <span class="text-h6 text-success font-weight-bold">
                          ¥{{ registration.amount.toFixed(2) }}
                        </span>
                      </div>
                    </div>
                    
                    <!-- 时间信息 -->
                    <div class="mb-3">
                      <div class="d-flex align-center">
                        <v-icon size="16" class="mr-1" color="grey-darken-1">mdi-clock-outline</v-icon>
                        <span class="text-caption text-grey-darken-1">
                          {{ formatDateTime(registration.created_at) }}
                        </span>
                      </div>
                    </div>
                    
                    <!-- 备注信息 -->
                    <div v-if="registration.note" class="mb-3">
                      <div class="text-caption text-grey-darken-1 mb-1">用户备注</div>
                      <div class="text-body-2 pa-2 bg-grey-lighten-4 rounded">
                        {{ registration.note }}
                      </div>
                    </div>
                    
                    <!-- 管理员备注输入 -->
                    <div class="mb-3">
                      <v-textarea
                        v-model="adminNotes[registration.id]"
                        label="管理员备注"
                        rows="2"
                        variant="outlined"
                        density="compact"
                        counter="200"
                        maxlength="200"
                        placeholder="可选择添加备注信息..."
                        :disabled="processingIds.includes(registration.id)"
                      ></v-textarea>
                    </div>
                  </v-card-text>
                  
                  <!-- 操作按钮 -->
                  <v-card-actions class="pt-0 px-3 pb-3">
                    <v-row dense>
                      <v-col cols="6">
                        <v-btn
                          @click="handleRegistration(registration, true)"
                          color="success"
                          variant="flat"
                          size="small"
                          :loading="processingIds.includes(registration.id)"
                          :disabled="processingIds.includes(registration.id)"
                          block
                        >
                          <v-icon start>mdi-check</v-icon>
                          批准
                        </v-btn>
                      </v-col>
                      <v-col cols="6">
                        <v-btn
                          @click="handleRegistration(registration, false)"
                          color="error"
                          variant="outlined"
                          size="small"
                          :loading="processingIds.includes(registration.id)"
                          :disabled="processingIds.includes(registration.id)"
                          block
                        >
                          <v-icon start>mdi-close</v-icon>
                          拒绝
                        </v-btn>
                      </v-col>
                    </v-row>
                  </v-card-actions>
                </v-card>
              </v-col>
            </v-row>
          </div>
        </div>
      </v-card-text>
      
      <v-card-actions v-if="!loading && !error">
        <v-btn @click="loadPendingRegistrations" :loading="loading" variant="text">
          <v-icon start>mdi-refresh</v-icon>
          刷新
        </v-btn>
        <v-spacer></v-spacer>
        <v-btn @click="closeDialog" :disabled="processing" variant="outlined">
          关闭
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { getPendingDonationRegistrations, confirmDonationRegistration } from '@/services/donationService'

export default {
  name: 'DonationRegistrationManagementDialog',
  data() {
    return {
      showDialog: false,
      loading: false,
      processing: false,
      error: null,
      registrations: [],
      adminNotes: {}, // 管理员备注，以登记ID为键
      processingIds: [] // 正在处理的登记ID列表
    }
  },
  computed: {
    totalAmount() {
      return this.registrations.reduce((sum, reg) => sum + reg.amount, 0)
    },
    uniqueUsers() {
      const userIds = [...new Set(this.registrations.map(reg => reg.user_id))]
      return userIds.length
    }
  },
  methods: {
    async open() {
      this.showDialog = true
      this.resetData()
      await this.loadPendingRegistrations()
    },
    
    closeDialog() {
      this.showDialog = false
      this.resetData()
    },
    
    resetData() {
      this.registrations = []
      this.adminNotes = {}
      this.processingIds = []
      this.error = null
    },
    
    async loadPendingRegistrations() {
      try {
        this.loading = true
        this.error = null
        
        const response = await getPendingDonationRegistrations()
        this.registrations = response.data || []
        
        // 初始化管理员备注
        this.adminNotes = {}
        this.registrations.forEach(reg => {
          this.adminNotes[reg.id] = ''
        })
        
      } catch (error) {
        console.error('加载待处理登记失败:', error)
        this.error = error.response?.data?.detail || '加载失败，请稍后重试'
      } finally {
        this.loading = false
      }
    },
    
    async handleRegistration(registration, approved) {
      const action = approved ? '批准' : '拒绝'
      const userName = registration.username || `用户 ${registration.user_id}`
      
      if (!confirm(`确定要${action}${userName}的捐助登记吗？\n金额：¥${registration.amount.toFixed(2)}`)) {
        return
      }
      
      try {
        // 添加到处理中列表
        this.processingIds.push(registration.id)
        
        const data = {
          approved: approved,
          admin_note: this.adminNotes[registration.id] || null
        }
        
        await confirmDonationRegistration(registration.id, data)
        
        // 显示成功消息
        this.showMessage(`已${action}捐助登记`, 'success')
        
        // 从列表中移除已处理的登记
        this.registrations = this.registrations.filter(reg => reg.id !== registration.id)
        delete this.adminNotes[registration.id]
        
        // 通知父组件
        this.$emit('registration-processed', {
          registration,
          approved,
          admin_note: data.admin_note
        })
        
      } catch (error) {
        console.error(`${action}登记失败:`, error)
        this.showMessage(`${action}失败：${error.response?.data?.detail || error.message}`, 'error')
      } finally {
        // 从处理中列表移除
        this.processingIds = this.processingIds.filter(id => id !== registration.id)
      }
    },
    
    getPaymentMethodText(method) {
      const methodMap = {
        'wechat': '微信',
        'alipay': '支付宝',
        'bank': '银行转账',
        'other': '其他'
      }
      return methodMap[method] || method
    },
    
    getPaymentMethodColor(method) {
      const colorMap = {
        'wechat': 'green',
        'alipay': 'blue',
        'bank': 'orange',
        'other': 'grey'
      }
      return colorMap[method] || 'grey'
    },
    
    formatDateTime(dateTime) {
      if (!dateTime) return '-'
      return new Date(dateTime).toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      })
    },
    
    showMessage(message, type = 'success') {
      if (window.Telegram?.WebApp) {
        window.Telegram.WebApp.showPopup({
          title: type === 'error' ? '错误' : '成功',
          message: message
        })
      } else {
        alert(message)
      }
    }
  }
}
</script>

<style scoped>
.registration-card {
  transition: all 0.3s ease;
  height: 100%;
}

.registration-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  transform: translateY(-2px);
}

.registration-card.processing {
  opacity: 0.7;
  pointer-events: none;
}

.bg-orange-lighten-5 {
  background-color: rgba(255, 152, 0, 0.05) !important;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .registration-card {
    margin-bottom: 16px;
  }
  
  .registration-card .v-card-title {
    padding: 12px;
  }
  
  .registration-card .v-card-text {
    padding: 12px;
  }
  
  .registration-card .v-card-actions {
    padding: 12px;
  }
}
</style>