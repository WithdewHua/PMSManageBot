<template>
  <v-dialog v-model="showDialog" max-width="500">
    <v-card>
      <v-card-title>
        <v-icon start color="red-darken-2">mdi-gift</v-icon>
        填写捐赠信息
      </v-card-title>
      
      <v-card-text>
        <div v-if="loading" class="text-center py-4">
          <v-progress-circular indeterminate color="primary"></v-progress-circular>
          <div class="mt-2">加载用户列表中...</div>
        </div>
        
        <v-form v-else ref="form" v-model="valid" lazy-validation>
          <!-- 用户选择 -->
          <v-autocomplete
            v-model="selectedUser"
            :items="userOptions"
            :loading="loading"
            label="选择捐赠用户"
            hint="搜索用户名或选择用户"
            persistent-hint
            clearable
            item-title="display_name"
            item-value="tg_id"
            :rules="userRules"
            variant="outlined"
            density="compact"
            class="mb-3"
          >
            <template v-slot:item="{ props, item }">
              <v-list-item v-bind="props">
                <template v-slot:prepend>
                  <v-avatar size="32">
                    <v-img 
                      v-if="item.raw.photo_url" 
                      :src="item.raw.photo_url"
                      :alt="item.raw.display_name"
                    />
                    <v-icon v-else>mdi-account-circle</v-icon>
                  </v-avatar>
                </template>
                <v-list-item-subtitle>
                  ID: {{ item.raw.tg_id }}
                  <span v-if="item.raw.current_donation > 0">
                    · 当前捐赠: {{ item.raw.current_donation.toFixed(2) }}元
                  </span>
                </v-list-item-subtitle>
              </v-list-item>
            </template>
          </v-autocomplete>
          
          <!-- 捐赠金额输入 -->
          <v-text-field
            v-model="donationAmount"
            label="捐赠金额 (元)"
            type="number"
            min="0"
            step="0.01"
            :rules="amountRules"
            variant="outlined"
            density="compact"
            prefix="¥"
            class="mb-3"
          ></v-text-field>
          
          <!-- 备注信息 -->
          <v-textarea
            v-model="note"
            label="备注信息 (可选)"
            rows="2"
            variant="outlined"
            density="compact"
            counter="200"
            maxlength="200"
            class="mb-3"
          ></v-textarea>
          
          <div v-if="errorMessage" class="error-message mt-3">
            {{ errorMessage }}
          </div>
          
          <div v-if="successMessage" class="success-message mt-3">
            {{ successMessage }}
          </div>
        </v-form>
      </v-card-text>
      
      <v-card-actions>
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
          color="red-darken-2" 
          @click="submitDonation"
          :loading="processing"
          :disabled="loading || processing || !valid"
        >
          确认提交
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { getAllUsers } from '@/services/creditsService'
import { submitDonationRecord } from '@/services/adminService'

export default {
  name: 'DonationDialog',
  data() {
    return {
      showDialog: false,
      valid: false,
      loading: false,
      processing: false,
      selectedUser: null,
      donationAmount: '',
      note: '',
      userOptions: [],
      errorMessage: '',
      successMessage: '',
      userRules: [
        v => !!v || '请选择捐赠用户'
      ],
      amountRules: [
        v => !!v || '请输入捐赠金额',
        v => !isNaN(parseFloat(v)) && parseFloat(v) > 0 || '请输入有效的金额',
        v => parseFloat(v) <= 10000 || '单次捐赠金额不能超过10000元'
      ]
    }
  },
  methods: {
    async open() {
      this.resetForm()
      this.showDialog = true
      await this.loadUsers()
    },
    
    closeDialog() {
      this.showDialog = false
    },
    
    resetForm() {
      this.selectedUser = null
      this.donationAmount = ''
      this.note = ''
      this.errorMessage = ''
      this.successMessage = ''
      if (this.$refs.form) {
        this.$refs.form.resetValidation()
      }
    },
    
    async loadUsers() {
      this.loading = true
      try {
        const users = await getAllUsers()
        this.userOptions = users.map(user => ({
          tg_id: user.tg_id,
          display_name: user.display_name,
          photo_url: user.photo_url || null,
          current_donation: user.current_donation || 0
        }))
      } catch (error) {
        this.errorMessage = '加载用户列表失败'
        console.error('加载用户列表失败:', error)
      } finally {
        this.loading = false
      }
    },
    
    async submitDonation() {
      if (!this.$refs.form.validate()) {
        return
      }
      
      this.processing = true
      this.errorMessage = ''
      this.successMessage = ''
      
      try {
        const donationData = {
          tg_id: this.selectedUser,
          amount: parseFloat(this.donationAmount),
          note: this.note || null
        }
        
        const result = await submitDonationRecord(donationData)
        
        if (result.success) {
          this.successMessage = result.message || '捐赠记录提交成功'
          
          // 显示成功提示
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showPopup({
              title: '提交成功',
              message: '捐赠记录已成功提交'
            })
          }
          
          // 通知父组件刷新数据
          this.$emit('donation-submitted', donationData)
          
          // 延迟关闭对话框
          setTimeout(() => {
            this.closeDialog()
          }, 1500)
        } else {
          this.errorMessage = result.message || '提交失败'
        }
      } catch (error) {
        this.errorMessage = error.response?.data?.message || '提交失败，请稍后再试'
        console.error('提交捐赠记录失败:', error)
      } finally {
        this.processing = false
      }
    }
  }
}
</script>

<style scoped>
.error-message {
  color: #ff5252;
  font-size: 14px;
}

.success-message {
  color: #4caf50;
  font-size: 14px;
}

/* 用户选择项样式 */
:deep(.v-list-item) {
  padding: 8px 16px;
}

:deep(.v-list-item-title) {
  font-weight: 500;
}

:deep(.v-list-item-subtitle) {
  color: rgba(0, 0, 0, 0.6);
  font-size: 12px;
}
</style>
