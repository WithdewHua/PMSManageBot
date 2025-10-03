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
                        <v-icon start size="small">mdi-information</v-icon>
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
                  使用加密货币进行捐赠，支持多种主流数字货币。
                </p>

                <!-- 占位内容 -->
                <v-alert
                  type="warning"
                  variant="tonal"
                  class="coming-soon-alert"
                  rounded="lg"
                >
                  <v-icon start>mdi-construction</v-icon>
                  <div class="alert-content">
                    <div class="alert-title">功能开发中</div>
                    <div class="alert-text">Crypto 捐赠功能正在开发中，敬请期待！</div>
                  </div>
                </v-alert>
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
      
      // 支付方式选项
      paymentMethods: [
        { title: '微信赞赏码', value: 'wechat' },
        { title: '支付宝口令', value: 'alipay' },
        { title: '其他', value: 'other' }
      ],
      
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
  text-align: center;
  padding: 40px 20px;
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