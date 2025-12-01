<template>
  <v-dialog v-model="showDialog" max-width="500" persistent>
    <v-card>
      <v-card-title class="dialog-header">
        <v-icon start size="28">mdi-shield-key</v-icon>
        <span class="title-text">兑换 Vaultwarden 账户</span>
        <v-spacer></v-spacer>
        <v-btn 
          icon 
          variant="text" 
          size="small" 
          @click="closeDialog" 
          :disabled="processing"
          class="close-btn"
        >
          <v-icon size="24">mdi-close</v-icon>
        </v-btn>
      </v-card-title>

      <v-divider></v-divider>

      <v-card-text class="pt-4">
        <div v-if="loading" class="text-center py-4">
          <v-progress-circular indeterminate color="primary"></v-progress-circular>
          <div class="mt-2">加载兑换信息中...</div>
        </div>

        <div v-else-if="!redeemInfo.enabled" class="text-center py-4">
          <v-icon size="64" color="grey">mdi-alert-circle-outline</v-icon>
          <div class="mt-3 text-h6">功能未启用</div>
          <div class="text-body-2 text-medium-emphasis mt-2">
            Vaultwarden 兑换功能暂未开放
          </div>
        </div>

        <v-form v-else ref="form" v-model="valid" lazy-validation>
          <!-- 兑换信息卡片 -->
          <v-alert
            type="info"
            density="compact"
            class="mb-4"
            rounded="lg"
          >
            Vaultwarden 是一个开源密码管理器，兑换后您将收到邀请邮件
          </v-alert>

          <!-- 积分信息 -->
          <v-card variant="outlined" class="mb-4" rounded="lg">
            <v-card-text>
              <div class="d-flex justify-space-between align-center mb-2">
                <span class="text-body-2">当前积分：</span>
                <span class="font-weight-bold text-h6">{{ redeemInfo.current_credits?.toFixed(2) || 0 }}</span>
              </div>
              <div class="d-flex justify-space-between align-center">
                <span class="text-body-2">所需积分：</span>
                <span class="font-weight-bold text-h6 text-primary">{{ redeemInfo.required_credits || 0 }}</span>
              </div>
              <v-divider class="my-2"></v-divider>
              <div class="d-flex justify-space-between align-center">
                <span class="text-body-2">兑换后剩余：</span>
                <span class="font-weight-bold" :class="canRedeem ? 'text-success' : 'text-error'">
                  {{ ((redeemInfo.current_credits || 0) - (redeemInfo.required_credits || 0)).toFixed(2) }}
                </span>
              </div>
            </v-card-text>
          </v-card>

          <!-- 积分不足提示 -->
          <v-alert
            v-if="!canRedeem"
            type="error"
            density="compact"
            class="mb-4"
            rounded="lg"
          >
            {{ redeemInfo.error_message || '积分不足，无法兑换' }}
          </v-alert>

          <!-- 邮箱输入 -->
          <v-text-field
            v-model="email"
            label="注册邮箱"
            type="email"
            :rules="emailRules"
            variant="outlined"
            density="compact"
            prepend-inner-icon="mdi-email"
            hint="请输入接收 Vaultwarden 邀请的邮箱地址"
            persistent-hint
            :disabled="!canRedeem"
            class="mb-3"
          ></v-text-field>

          <!-- 使用提示 -->
          <v-expansion-panels variant="accordion" class="mb-3">
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon start>mdi-information-outline</v-icon>
                使用说明
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <ol class="pl-4">
                  <li>输入您的邮箱地址并确认兑换</li>
                  <li>系统将发送邀请邮件到您的邮箱</li>
                  <li>查收邮件并点击邀请链接</li>
                  <li>设置密码完成注册</li>
                  <li>下载客户端/浏览器插件使用</li>
                </ol>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>

          <!-- 错误消息 -->
          <v-alert
            v-if="errorMessage"
            type="error"
            density="compact"
            class="mb-3"
            closable
            @click:close="errorMessage = ''"
          >
            {{ errorMessage }}
          </v-alert>

          <!-- 成功消息 -->
          <v-alert
            v-if="successMessage"
            type="success"
            density="compact"
            class="mb-3"
          >
            {{ successMessage }}
          </v-alert>
        </v-form>
      </v-card-text>

      <v-divider></v-divider>

      <v-card-actions class="pa-4">
        <v-spacer></v-spacer>
        <v-btn
          variant="text"
          color="grey"
          @click="closeDialog"
          :disabled="processing"
        >
          取消
        </v-btn>
        <v-btn
          v-if="redeemInfo.enabled"
          color="blue-darken-2"
          @click="submitRedeem"
          :loading="processing"
          :disabled="!valid || !canRedeem || processing"
        >
          确认兑换
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { getVaultwardenRedeemInfo, redeemVaultwardenAccount } from '@/services/vaultwardenService'

export default {
  name: 'VaultwardenRedeemDialog',
  data() {
    return {
      showDialog: false,
      valid: false,
      loading: false,
      processing: false,
      email: '',
      redeemInfo: {
        enabled: false,
        required_credits: 0,
        current_credits: 0,
        can_redeem: false,
        error_message: ''
      },
      errorMessage: '',
      successMessage: '',
      emailRules: [
        v => !!v || '请输入邮箱地址',
        v => /.+@.+\..+/.test(v) || '请输入有效的邮箱地址',
      ]
    }
  },
  computed: {
    canRedeem() {
      return this.redeemInfo.can_redeem && this.redeemInfo.enabled
    }
  },
  methods: {
    async open() {
      this.showDialog = true
      this.resetForm()
      await this.loadRedeemInfo()
    },
    
    closeDialog() {
      if (!this.processing) {
        this.showDialog = false
        this.resetForm()
      }
    },

    resetForm() {
      this.email = ''
      this.errorMessage = ''
      this.successMessage = ''
      this.valid = false
      if (this.$refs.form) {
        this.$refs.form.resetValidation()
      }
    },

    async loadRedeemInfo() {
      this.loading = true
      this.errorMessage = ''

      try {
        this.redeemInfo = await getVaultwardenRedeemInfo()
      } catch (error) {
        console.error('加载兑换信息失败:', error)
        this.errorMessage = error.response?.data?.detail || '加载兑换信息失败，请稍后重试'
      } finally {
        this.loading = false
      }
    },

    async submitRedeem() {
      // 验证表单
      const { valid } = await this.$refs.form.validate()
      if (!valid) {
        return
      }

      this.processing = true
      this.errorMessage = ''
      this.successMessage = ''

      try {
        const result = await redeemVaultwardenAccount({
          email: this.email
        })

        if (result.success) {
          this.successMessage = result.message
          // 触发事件通知父组件刷新积分
          this.$emit('redeem-success', {
            credits_deducted: result.credits_deducted,
            remaining_credits: result.remaining_credits
          })

          // 2秒后关闭对话框
          setTimeout(() => {
            this.closeDialog()
          }, 2000)
        } else {
          this.errorMessage = result.message || '兑换失败，请稍后重试'
        }
      } catch (error) {
        console.error('兑换失败:', error)
        const errorData = error.response?.data
        this.errorMessage = errorData?.detail || errorData?.message || '兑换失败，请稍后重试'
      } finally {
        this.processing = false
      }
    }
  }
}
</script>

<style scoped>
.dialog-header {
  background: linear-gradient(135deg, #1565C0 0%, #0D47A1 100%);
  color: white;
  font-size: 1.25rem;
  font-weight: 600;
  padding: 20px 24px;
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

.close-btn:hover:not([disabled]) {
  opacity: 1;
  background-color: rgba(255, 255, 255, 0.15) !important;
  transform: rotate(90deg);
}

.close-btn:active:not([disabled]) {
  transform: rotate(90deg) scale(0.95);
}

.close-btn[disabled] {
  opacity: 0.5;
}

.error-message {
  color: #d32f2f;
  font-size: 0.875rem;
  margin-top: 8px;
}

.success-message {
  color: #388e3c;
  font-size: 0.875rem;
  margin-top: 8px;
}

ol {
  font-size: 0.875rem;
  line-height: 1.8;
}

ol li {
  margin-bottom: 4px;
}
</style>
