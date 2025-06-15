<template>
  <v-dialog v-model="showDialog" max-width="500">
    <v-card>
      <v-card-title>
        <v-icon start color="amber-darken-2">mdi-bank-transfer</v-icon>
        积分转移
      </v-card-title>
      
      <v-card-text>
        <div v-if="loading" class="text-center py-4">
          <v-progress-circular indeterminate color="primary"></v-progress-circular>
          <div class="mt-2">加载用户列表中...</div>
        </div>
        
        <v-form v-else ref="form" v-model="valid" lazy-validation>
          <!-- 转移提示 -->
          <v-alert
            type="info"
            density="compact"
            class="mb-4"
            rounded="lg"
          >
            每笔转移将收取 5% 手续费，转移对象不可以是自己
          </v-alert>

          <!-- 当前积分显示 -->
          <v-card
            variant="outlined"
            class="mb-4"
            rounded="lg"
          >
            <v-card-text class="text-center">
              <div class="text-caption text-medium-emphasis">当前可用积分</div>
              <div class="text-h5 font-weight-bold text-primary">
                {{ currentCredits.toFixed(2) }}
              </div>
            </v-card-text>
          </v-card>

          <!-- 用户选择 -->
          <v-autocomplete
            v-model="selectedUser"
            :items="userOptions"
            :loading="loading"
            label="选择转移对象"
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
                  <span v-if="item.raw.current_credits > 0">
                    · 当前积分: {{ item.raw.current_credits.toFixed(2) }}
                  </span>
                </v-list-item-subtitle>
              </v-list-item>
            </template>
          </v-autocomplete>
          
          <!-- 转移积分数量输入 -->
          <v-text-field
            v-model="transferAmount"
            label="转移积分数量"
            type="number"
            min="0"
            step="0.01"
            :rules="amountRules"
            variant="outlined"
            density="compact"
            prefix="⭐"
            class="mb-3"
            @input="calculateFee"
          ></v-text-field>

          <!-- 手续费和总额显示 -->
          <v-card
            v-if="transferAmount && parseFloat(transferAmount) > 0"
            variant="outlined"
            class="mb-3"
            rounded="lg"
          >
            <v-card-text class="py-3">
              <div class="d-flex justify-space-between align-center mb-2">
                <span class="text-body-2">转移积分：</span>
                <span class="font-weight-medium">{{ parseFloat(transferAmount).toFixed(2) }}</span>
              </div>
              <div class="d-flex justify-space-between align-center mb-2">
                <span class="text-body-2">手续费 (5%)：</span>
                <span class="font-weight-medium text-warning">{{ feeAmount.toFixed(2) }}</span>
              </div>
              <v-divider class="my-2"></v-divider>
              <div class="d-flex justify-space-between align-center">
                <span class="text-body-1 font-weight-bold">总扣除：</span>
                <span class="text-h6 font-weight-bold text-error">{{ totalDeduction.toFixed(2) }}</span>
              </div>
            </v-card-text>
          </v-card>
          
          <!-- 备注信息 -->
          <v-textarea
            v-model="note"
            label="转移备注 (可选)"
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
          color="amber-darken-2" 
          @click="submitTransfer"
          :loading="processing"
          :disabled="loading || processing || !valid || !canTransfer"
        >
          确认转移
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { getAllUsers } from '@/services/creditsService'
import { transferCredits } from '@/services/creditsService'

export default {
  name: 'CreditsTransferDialog',
  props: {
    currentCredits: {
      type: Number,
      default: 0
    }
  },
  data() {
    return {
      showDialog: false,
      valid: false,
      loading: false,
      processing: false,
      selectedUser: null,
      transferAmount: '',
      note: '',
      userOptions: [],
      errorMessage: '',
      successMessage: '',
      feeAmount: 0,
      totalDeduction: 0,
      userRules: [
        () => !!this.selectedUser || '请选择转移对象'
      ],
      amountRules: [
        v => !!v || '请输入转移积分数量',
        v => !isNaN(parseFloat(v)) && parseFloat(v) > 0 || '请输入有效的积分数量',
        v => parseFloat(v) <= 10000 || '单次转移积分不能超过10000',
        () => this.totalDeduction <= this.currentCredits || '积分不足（包含手续费）'
      ]
    }
  },
  computed: {
    canTransfer() {
      return this.transferAmount && 
             parseFloat(this.transferAmount) > 0 && 
             this.totalDeduction <= this.currentCredits &&
             this.selectedUser
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
      this.transferAmount = ''
      this.note = ''
      this.errorMessage = ''
      this.successMessage = ''
      this.feeAmount = 0
      this.totalDeduction = 0
      if (this.$refs.form) {
        this.$refs.form.resetValidation()
      }
    },

    calculateFee() {
      const amount = parseFloat(this.transferAmount) || 0
      this.feeAmount = amount * 0.05
      this.totalDeduction = amount + this.feeAmount
    },
    
    async loadUsers() {
      this.loading = true
      try {
        const users = await getAllUsers()
        this.userOptions = users.map(user => ({
          tg_id: user.tg_id,
          display_name: user.display_name,
          photo_url: user.photo_url || null,
          current_credits: user.current_credits || 0
        }))
      } catch (error) {
        this.errorMessage = '加载用户列表失败'
        console.error('加载用户列表失败:', error)
      } finally {
        this.loading = false
      }
    },
    
    async submitTransfer() {
      if (!this.$refs.form.validate()) {
        return
      }
      
      this.processing = true
      this.errorMessage = ''
      this.successMessage = ''
      
      try {
        const transferData = {
          target_tg_id: this.selectedUser,
          amount: parseFloat(this.transferAmount),
          note: this.note || null
        }
        
        const result = await transferCredits(transferData)
        
        if (result.success) {
          this.successMessage = result.message || '积分转移成功'
          
          // 显示成功提示
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showPopup({
              title: '转移成功',
              message: `成功转移 ${result.transferred_amount} 积分，手续费 ${result.fee_amount?.toFixed(2)} 积分`
            })
          }
          
          // 通知父组件刷新数据
          this.$emit('transfer-completed', {
            transferred_amount: result.transferred_amount,
            fee_amount: result.fee_amount,
            current_credits: result.current_credits
          })
          
          // 延迟关闭对话框
          setTimeout(() => {
            this.closeDialog()
          }, 1500)
        } else {
          this.errorMessage = result.message || '转移失败'
        }
      } catch (error) {
        this.errorMessage = error.response?.data?.message || '转移失败，请稍后再试'
        console.error('积分转移失败:', error)
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
