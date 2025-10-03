<template>
  <v-dialog 
    v-model="dialog" 
    max-width="600" 
    persistent
    @keydown.esc="close"
  >
    <v-card class="donation-management-dialog">
      <v-card-title class="dialog-title">
        <div class="title-content">
          <v-icon start color="primary">mdi-hand-heart</v-icon>
          捐赠管理
        </div>
        <v-btn 
          icon 
          variant="text" 
          @click="close" 
          class="close-btn"
          size="small"
        >
          <v-icon size="18">mdi-close</v-icon>
        </v-btn>
      </v-card-title>

      <v-card-text class="pa-0">
        <v-tabs 
          v-model="activeTab" 
          class="donation-tabs"
          color="primary"
          slider-color="primary"
          grow
        >
          <v-tab value="self-register" class="tab-item">
            <v-icon start size="small">mdi-clipboard-list</v-icon>
            自助登记
          </v-tab>
          <v-tab value="crypto" class="tab-item">
            <v-icon start size="small">mdi-bitcoin</v-icon>
            Crypto捐赠
          </v-tab>
        </v-tabs>

        <v-window v-model="activeTab" class="tab-content">
          <!-- 自助登记页面 -->
          <v-window-item value="self-register">
            <v-container class="pa-6">
              <div class="self-register-content">
                <div class="section-header">
                  <v-icon color="success" class="mr-2">mdi-clipboard-check</v-icon>
                  <span class="section-title">捐赠自助登记</span>
                </div>
                <p class="section-description">
                  完成捐赠后，请在此处登记您的捐赠信息。管理员确认后将自动更新您的捐赠金额和积分。
                </p>

                <v-form ref="selfRegisterForm" v-model="formValid" class="donation-form">
                  <v-row>
                    <v-col cols="12">
                      <v-select
                        v-model="selfRegisterForm.paymentMethod"
                        :items="paymentMethods"
                        label="支付方式"
                        variant="outlined"
                        :rules="[rules.required]"
                        prepend-inner-icon="mdi-credit-card"
                        class="form-field"
                      ></v-select>
                    </v-col>
                    
                    <v-col cols="12">
                      <v-text-field
                        v-model="selfRegisterForm.amount"
                        label="支付金额"
                        variant="outlined"
                        type="number"
                        step="0.01"
                        min="0.01"
                        suffix="元"
                        :rules="[rules.required, rules.minAmount]"
                        prepend-inner-icon="mdi-currency-cny"
                        class="form-field"
                        @input="validateAmount"
                      ></v-text-field>
                    </v-col>

                    <v-col cols="12">
                      <v-checkbox
                        v-model="selfRegisterForm.isDonationRegistration"
                        label="捐赠开号"
                        color="primary"
                        class="form-field"
                        density="comfortable"
                      >
                        <template #label>
                          <div class="checkbox-label">
                            <v-icon size="small" class="mr-1">mdi-account-plus</v-icon>
                            捐赠开号
                          </div>
                        </template>
                      </v-checkbox>
                      
                      <!-- 捐赠开号说明 -->
                      <v-alert
                        v-if="selfRegisterForm.isDonationRegistration"
                        type="info"
                        variant="tonal"
                        density="compact"
                        class="donation-registration-notice mt-2 mb-2"
                        rounded="lg"
                      >
                        <span class="notice-text">
                          选择捐赠开号将只记录捐赠金额，不增加积分，并会生成一个普通邀请码（仅在开放捐入期间有效）
                        </span>
                      </v-alert>
                    </v-col>

                    <v-col cols="12">
                      <v-textarea
                        v-model="selfRegisterForm.note"
                        label="备注信息（可选）"
                        variant="outlined"
                        rows="3"
                        counter="200"
                        maxlength="200"
                        prepend-inner-icon="mdi-note-text"
                        class="form-field"
                        placeholder="如：交易单号、捐赠时间等补充信息"
                      ></v-textarea>
                    </v-col>
                  </v-row>

                  <div class="form-actions">
                    <v-btn
                      :loading="submitting"
                      :disabled="!formValid || submitting"
                      color="success"
                      size="large"
                      variant="flat"
                      @click="submitSelfRegister"
                      class="submit-btn"
                      block
                    >
                      <v-icon start>mdi-send</v-icon>
                      提交登记
                    </v-btn>
                  </div>
                </v-form>

                <!-- 登记须知 -->
                <v-alert
                  type="info"
                  variant="tonal"
                  class="notice-alert mt-4"
                  rounded="lg"
                >
                  <div class="notice-content">
                    <div class="notice-title">登记须知：</div>
                    <ul class="notice-list">
                      <li>请确保填写的金额与实际捐赠金额一致</li>
                      <li>如选择"捐赠开号"，系统将只记录捐赠金额，不增加积分，并生成普通邀请码</li>
                      <li>管理员将在 24 小时内处理您的登记申请</li>
                      <li>确认后系统将自动增加对应的捐赠金额和积分（捐赠开号除外）</li>
                      <li>如有疑问，请联系管理员</li>
                    </ul>
                  </div>
                </v-alert>
              </div>
            </v-container>
          </v-window-item>

          <!-- Crypto捐赠页面 -->
          <v-window-item value="crypto">
            <v-container class="pa-6">
              <div class="crypto-content">
                <div class="section-header">
                  <v-icon color="orange-darken-2" class="mr-2">mdi-bitcoin</v-icon>
                  <span class="section-title">Crypto 捐赠</span>
                </div>
                <p class="section-description">
                  使用加密货币进行捐赠，支付完成后将自动更新您的捐赠金额和积分。
                </p>

                <!-- 账号绑定检查提示 -->
                <v-alert
                  v-if="!userBindingChecked"
                  type="info"
                  variant="tonal"
                  class="mb-4"
                  rounded="lg"
                >
                  <div class="alert-content">
                    <div class="alert-title">温馨提示</div>
                    <div class="alert-text">
                      <v-icon size="small" class="mr-1">mdi-information</v-icon>
                      只有绑定了 Emby 或 Plex 账号的用户才能进行 Crypto 捐赠
                    </div>
                  </div>
                </v-alert>

                <!-- Crypto 捐赠表单 -->
                <v-form ref="cryptoForm" v-model="cryptoFormValid" class="donation-form">
                  <v-row>
                    <v-col cols="12">
                      <v-select
                        v-model="cryptoForm.cryptoType"
                        :items="cryptoTypes"
                        label="选择加密货币"
                        variant="outlined"
                        :rules="[rules.required]"
                        prepend-inner-icon="mdi-bitcoin"
                        class="form-field"
                      >
                      </v-select>
                    </v-col>
                    
                    <v-col cols="12">
                      <v-text-field
                        v-model="cryptoForm.amount"
                        label="捐赠金额"
                        variant="outlined"
                        type="number"
                        step="0.01"
                        min="0.01"
                        suffix="CNY"
                        :rules="[rules.required, rules.minAmount]"
                        prepend-inner-icon="mdi-currency-cny"
                        class="form-field"
                        hint="最低捐赠金额为 0.01 CNY，系统将自动处理汇率转换"
                        persistent-hint
                      ></v-text-field>
                    </v-col>

                    <v-col cols="12">
                      <v-textarea
                        v-model="cryptoForm.note"
                        label="备注信息（可选）"
                        variant="outlined"
                        rows="3"
                        counter="200"
                        maxlength="200"
                        prepend-inner-icon="mdi-note-text"
                        class="form-field"
                        placeholder="如：特殊说明、感谢留言等"
                      ></v-textarea>
                    </v-col>
                  </v-row>

                  <div class="form-actions">
                    <v-btn
                      :loading="cryptoSubmitting"
                      :disabled="!cryptoFormValid || cryptoSubmitting"
                      color="orange-darken-2"
                      size="large"
                      block
                      @click="createCryptoOrder"
                      class="action-btn"
                    >
                      <v-icon start>mdi-bitcoin</v-icon>
                      创建 Crypto 支付订单
                    </v-btn>
                  </div>
                </v-form>

                <!-- 历史订单 -->
                <div v-if="cryptoOrders.length > 0" class="crypto-orders-section mt-6">
                  <v-divider class="mb-4"></v-divider>
                  <div class="section-header mb-4">
                    <v-icon color="blue-darken-2" class="mr-2">mdi-history</v-icon>
                    <span class="section-title">历史订单</span>
                  </div>
                  
                  <v-card
                    v-for="order in cryptoOrders"
                    :key="order.id"
                    class="crypto-order-card mb-3"
                    variant="outlined"
                  >
                    <v-card-text class="pa-4">
                      <div class="d-flex justify-space-between align-center mb-2">
                        <div class="d-flex align-center">
                          <v-icon :icon="getCryptoIcon(order.crypto_type)" size="small" class="mr-2"></v-icon>
                          <span class="font-weight-medium">{{ getCryptoDisplayName(order.crypto_type) }}</span>
                        </div>
                        <v-chip
                          :color="getOrderStatusColor(order.status)"
                          size="small"
                          variant="flat"
                        >
                          <v-icon start size="x-small" :icon="getOrderStatusIcon(order.status)"></v-icon>
                          {{ getOrderStatusText(order.status) }}
                        </v-chip>
                      </div>
                      
                      <div class="order-details">
                        <div class="order-detail-row">
                          <span class="detail-label">订单金额:</span>
                          <span class="detail-value">¥{{ order.amount }}</span>
                        </div>
                        <div v-if="order.actual_amount" class="order-detail-row">
                          <span class="detail-label">实付金额:</span>
                          <span class="detail-value">{{ order.actual_amount }} {{ getCryptoSymbol(order.crypto_type) }}</span>
                        </div>
                        <div class="order-detail-row">
                          <span class="detail-label">创建时间:</span>
                          <span class="detail-value">{{ formatDateTime(order.created_at) }}</span>
                        </div>
                        <div v-if="order.paid_at" class="order-detail-row">
                          <span class="detail-label">支付时间:</span>
                          <span class="detail-value">{{ formatDateTime(order.paid_at) }}</span>
                        </div>
                        <div v-if="order.note" class="order-detail-row">
                          <span class="detail-label">备注:</span>
                          <span class="detail-value">{{ order.note }}</span>
                        </div>
                      </div>
                      
                      <!-- 支付链接 -->
                      <div v-if="order.status === 1 && order.payment_url" class="mt-3">
                        <v-btn
                          :href="order.payment_url"
                          target="_blank"
                          color="success"
                          size="small"
                          variant="outlined"
                          block
                        >
                          <v-icon start size="small">mdi-open-in-new</v-icon>
                          前往支付
                        </v-btn>
                      </div>
                    </v-card-text>
                  </v-card>
                </div>
              </div>
            </v-container>
          </v-window-item>
        </v-window>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>
import { submitDonationRegistration } from '@/services/donationService'
import { 
  createCryptoDonationOrder, 
  getUserCryptoDonationOrders,
  getCryptoTypesWithFallback,
  CRYPTO_TYPES, 
  ORDER_STATUS 
} from '@/services/cryptoDonationService'

export default {
  name: 'DonationManagementDialog',
  data() {
    return {
      dialog: false,
      activeTab: 'self-register',
      formValid: false,
      submitting: false,
      
      // 自助登记表单
      selfRegisterForm: {
        paymentMethod: '',
        amount: '',
        note: '',
        isDonationRegistration: false
      },
      
      // Crypto 捐赠相关
      cryptoFormValid: false,
      cryptoSubmitting: false,
      cryptoOrders: [],
      userBindingChecked: true, // 默认为 true，实际检查在组件挂载时进行
      cryptoForm: {
        cryptoType: '',
        amount: '',
        note: ''
      },
      
      // 支付方式选项
      paymentMethods: [
        { title: '微信赞赏码', value: 'wechat' },
        { title: '支付宝口令', value: 'alipay' },
        { title: '其他', value: 'other' }
      ],
      
      // 加密货币类型选项（动态获取）
      cryptoTypes: [],
      
      // 表单验证规则
      rules: {
        required: v => !!v || '此字段为必填项',
        minAmount: v => {
          const num = parseFloat(v)
          return (num && num > 0) || '金额必须大于0'
        }
      }
    }
  },
  
  methods: {
    // 打开对话框
    open() {
      this.dialog = true
      this.activeTab = 'self-register'
      this.resetForm()
    },
    
    // 关闭对话框
    close() {
      this.dialog = false
      this.resetForm()
    },
    
    // 重置表单
    resetForm() {
      this.selfRegisterForm = {
        paymentMethod: '',
        amount: '',
        note: '',
        isDonationRegistration: false
      }
      this.formValid = false
      this.submitting = false
      
      // 重置 Crypto 表单
      this.resetCryptoForm()
      
      // 重置表单验证状态
      if (this.$refs.selfRegisterForm) {
        this.$refs.selfRegisterForm.resetValidation()
      }
    },
    
    // 验证金额
    validateAmount() {
      const amount = parseFloat(this.selfRegisterForm.amount)
      if (isNaN(amount) || amount <= 0) {
        return false
      }
      return true
    },
    
    // 提交自助登记
    async submitSelfRegister() {
      // 验证表单
      const { valid } = await this.$refs.selfRegisterForm.validate()
      if (!valid) {
        return
      }
      
      try {
        this.submitting = true
        
        const formData = {
          payment_method: this.selfRegisterForm.paymentMethod,
          amount: parseFloat(this.selfRegisterForm.amount),
          note: this.selfRegisterForm.note || '',
          is_donation_registration: this.selfRegisterForm.isDonationRegistration
        }
        
        const response = await submitDonationRegistration(formData)
        
        if (response.success) {
          this.showMessage('捐赠登记提交成功！管理员将在24小时内处理。', 'success')
          this.$emit('registration-submitted', response.data)
          this.close()
        } else {
          this.showMessage(response.message || '提交失败，请稍后重试', 'error')
        }
      } catch (error) {
        console.error('提交捐赠登记失败:', error)
        this.showMessage('提交失败，请稍后重试', 'error')
      } finally {
        this.submitting = false
      }
    },

    // 创建 Crypto 支付订单
    async createCryptoOrder() {
      // 验证表单
      const { valid } = await this.$refs.cryptoForm.validate()
      if (!valid) {
        return
      }
      
      try {
        this.cryptoSubmitting = true
        
        const orderData = {
          crypto_type: this.cryptoForm.cryptoType,
          amount: parseFloat(this.cryptoForm.amount),
          note: this.cryptoForm.note || ''
        }
        
        const response = await createCryptoDonationOrder(orderData)
        
        if (response.success) {
          this.showMessage('Crypto 支付订单创建成功！', 'success')
          
          // 重置表单
          this.resetCryptoForm()
          
          // 刷新订单列表
          await this.loadCryptoOrders()
          
          // 如果有支付链接，打开支付页面
          if (response.data.payment_url) {
            window.open(response.data.payment_url, '_blank')
          }
          
          this.$emit('crypto-order-created', response.data)
        } else {
          this.showMessage(response.message || '创建订单失败，请稍后重试', 'error')
        }
      } catch (error) {
        console.error('创建 Crypto 支付订单失败:', error)
        if (error.response?.status === 403) {
          this.showMessage('请先绑定 Emby 或 Plex 账号后再进行捐赠', 'warning')
          this.userBindingChecked = false
        } else {
          this.showMessage('创建订单失败，请稍后重试', 'error')
        }
      } finally {
        this.cryptoSubmitting = false
      }
    },

    // 重置 Crypto 表单
    resetCryptoForm() {
      this.cryptoForm = {
        cryptoType: '',
        amount: '',
        note: ''
      }
      this.cryptoFormValid = false
      
      if (this.$refs.cryptoForm) {
        this.$refs.cryptoForm.resetValidation()
      }
    },

    // 加载加密货币类型
    async loadCryptoTypes() {
      try {
        const cryptoTypesData = await getCryptoTypesWithFallback()
        this.cryptoTypes = cryptoTypesData.map(crypto => ({
          title: crypto,
          value: crypto
        }))
      } catch (error) {
        console.error('加载加密货币类型失败:', error)
        // 使用备用配置
        this.cryptoTypes = CRYPTO_TYPES.map(crypto => ({
          title: crypto,
          value: crypto
        }))
      }
    },

    // 加载 Crypto 订单历史
    async loadCryptoOrders() {
      try {
        const response = await getUserCryptoDonationOrders()
        if (response.success) {
          this.cryptoOrders = response.data || []
        }
      } catch (error) {
        console.error('加载 Crypto 订单历史失败:', error)
      }
    },

    // 获取加密货币图标（统一显示为 bitcoin）
    // eslint-disable-next-line no-unused-vars
    getCryptoIcon(cryptoType) {
      return 'mdi-bitcoin'
    },

    // 获取加密货币显示名称（简化版）
    getCryptoDisplayName(cryptoType) {
      return cryptoType
    },

    // 获取订单状态颜色
    getOrderStatusColor(status) {
      return ORDER_STATUS[status]?.color || 'grey'
    },

    // 获取订单状态图标
    getOrderStatusIcon(status) {
      return ORDER_STATUS[status]?.icon || 'mdi-help-circle'
    },

    // 获取订单状态文本
    getOrderStatusText(status) {
      return ORDER_STATUS[status]?.text || '未知状态'
    },

    // 获取加密货币符号
    getCryptoSymbol(cryptoType) {
      if (cryptoType.includes('USDC')) return 'USDC'
      if (cryptoType.includes('USDT')) return 'USDT'
      return cryptoType.split('-')[0]
    },

    // 格式化日期时间
    formatDateTime(dateString) {
      if (!dateString) return '-'
      try {
        return new Date(dateString).toLocaleString('zh-CN', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        })
      } catch (error) {
        return dateString
      }
    },
    
    // 显示消息
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
  },

  // 组件生命周期
  async mounted() {
    // 加载加密货币类型
    await this.loadCryptoTypes()
    
    // 当组件挂载且对话框打开时，加载 Crypto 订单历史
    this.$watch('dialog', async (newVal) => {
      if (newVal) {
        await this.loadCryptoOrders()
      }
    })
  }
}
</script>

<style scoped>
.donation-management-dialog {
  border-radius: 16px !important;
  overflow: hidden;
}

.dialog-title {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  font-size: 18px;
  font-weight: 600;
  color: #333;
  padding: 20px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: relative;
}

.title-content {
  display: flex;
  align-items: center;
  flex: 1;
}

.close-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 32px !important;
  height: 32px !important;
  background: rgba(255, 255, 255, 0.8) !important;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 8px !important;
  backdrop-filter: blur(8px);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  color: #666 !important;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.95) !important;
  border-color: rgba(0, 0, 0, 0.12);
  color: #333 !important;
  transform: scale(1.05);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.close-btn:active {
  transform: scale(0.95);
  transition-duration: 0.1s;
}

.donation-tabs {
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  background: rgba(248, 250, 252, 0.5);
}

.tab-item {
  font-weight: 500;
  text-transform: none;
  letter-spacing: 0.5px;
}

.tab-content {
  min-height: 400px;
}

.section-header {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #333;
}

.section-description {
  color: #666;
  font-size: 14px;
  margin-bottom: 24px;
  line-height: 1.5;
}

.donation-form {
  margin-bottom: 24px;
}

.form-field {
  margin-bottom: 8px;
}

.form-actions {
  margin-top: 16px;
}

.submit-btn {
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.5px;
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(76, 175, 80, 0.3);
}

.submit-btn:hover {
  box-shadow: 0 6px 16px rgba(76, 175, 80, 0.4);
  transform: translateY(-1px);
}

.notice-alert {
  border: 1px solid rgba(33, 150, 243, 0.2);
  background: linear-gradient(135deg, rgba(33, 150, 243, 0.05) 0%, rgba(33, 150, 243, 0.02) 100%) !important;
}

.notice-content {
  font-size: 13px;
  line-height: 1.5;
}

.notice-title {
  font-weight: 600;
  margin-bottom: 8px;
  color: #1976D2;
}

.notice-list {
  margin: 0;
  padding-left: 16px;
  color: #555;
}

.notice-list li {
  margin-bottom: 4px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  font-size: 14px;
  font-weight: 500;
}

.donation-registration-notice {
  border: 1px solid rgba(33, 150, 243, 0.2);
  background: linear-gradient(135deg, rgba(33, 150, 243, 0.05) 0%, rgba(33, 150, 243, 0.02) 100%) !important;
}

.donation-registration-notice .notice-text {
  font-size: 12px;
  line-height: 1.4;
  color: #1976D2;
}

.coming-soon-alert {
  border: 1px solid rgba(255, 152, 0, 0.2);
  background: linear-gradient(135deg, rgba(255, 152, 0, 0.05) 0%, rgba(255, 152, 0, 0.02) 100%) !important;
}

.alert-content {
  font-size: 14px;
  line-height: 1.5;
}

.alert-title {
  font-weight: 600;
  margin-bottom: 4px;
  color: #F57C00;
}

.alert-text {
  color: #666;
}

.crypto-content {
  text-align: left;
}

.crypto-orders-section {
  margin-top: 24px;
}

.crypto-order-card {
  border-radius: 12px;
  transition: all 0.2s ease;
}

.crypto-order-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.order-details {
  margin-top: 12px;
}

.order-detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  border-bottom: 1px solid #f5f5f5;
}

.order-detail-row:last-child {
  border-bottom: none;
}

.detail-label {
  font-size: 13px;
  color: #666;
  font-weight: 400;
}

.detail-value {
  font-size: 13px;
  color: #333;
  font-weight: 500;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .donation-management-dialog {
    margin: 8px;
    max-width: calc(100vw - 16px) !important;
  }
  
  .dialog-title {
    padding: 16px 20px;
    font-size: 16px;
  }
  
  .close-btn {
    top: 10px;
    right: 10px;
    width: 28px !important;
    height: 28px !important;
    border-radius: 6px !important;
  }
  
  .section-title {
    font-size: 15px;
  }
  
  .section-description {
    font-size: 13px;
    margin-bottom: 20px;
  }
  
  .submit-btn {
    height: 44px;
    font-size: 15px;
  }
  
  .notice-content {
    font-size: 12px;
  }
  
  .alert-content {
    font-size: 13px;
  }
}

@media (max-width: 480px) {
  .tab-content {
    min-height: 350px;
  }
  
  .dialog-title {
    padding: 12px 16px;
    font-size: 15px;
  }
  
  .close-btn {
    top: 8px;
    right: 8px;
    width: 26px !important;
    height: 26px !important;
    border-radius: 5px !important;
  }
  
  .section-header {
    margin-bottom: 10px;
  }
  
  .section-title {
    font-size: 14px;
  }
  
  .section-description {
    font-size: 12px;
    margin-bottom: 16px;
  }
  
  .submit-btn {
    height: 42px;
    font-size: 14px;
  }
  
  .notice-list {
    padding-left: 12px;
  }
}
</style>