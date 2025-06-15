<template>
  <v-dialog v-model="showDialog" max-width="500">
    <v-card>
      <v-card-title>
        <v-icon start color="blue-darken-2">mdi-ticket-confirmation</v-icon>
        邀请码管理
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
            label="选择用户"
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
                  <span v-if="item.raw.current_credits !== undefined">
                    · 当前积分: {{ item.raw.current_credits.toFixed(2) }}
                  </span>
                </v-list-item-subtitle>
              </v-list-item>
            </template>
          </v-autocomplete>
          
          <!-- 生成数量输入 -->
          <v-text-field
            v-model="generateCount"
            label="生成数量"
            type="number"
            min="1"
            max="100"
            :rules="countRules"
            variant="outlined"
            density="compact"
            suffix="个"
            class="mb-3"
          ></v-text-field>
          
          <!-- 特权邀请码选项 -->
          <v-checkbox
            v-model="isPremium"
            label="生成特权邀请码"
            color="purple-darken-2"
            density="compact"
            class="mb-3"
          >
            <template v-slot:label>
              <div class="d-flex align-center">
                <v-icon size="small" color="purple-darken-2" class="mr-2">mdi-crown</v-icon>
                <span>生成特权邀请码</span>
                <v-tooltip activator="parent" location="top">
                  特权邀请码可以获得更多权限和福利
                </v-tooltip>
              </div>
            </template>
          </v-checkbox>
          
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
          color="blue-darken-2" 
          @click="generateInviteCodes"
          :loading="processing"
          :disabled="loading || processing || !valid"
        >
          生成邀请码
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { getAllUsers } from '@/services/creditsService'
import { generateAdminInviteCodes } from '@/services/adminService'

export default {
  name: 'AdminInviteCodeDialog',
  data() {
    return {
      showDialog: false,
      valid: false,
      loading: false,
      processing: false,
      selectedUser: null,
      generateCount: 1,
      isPremium: false,
      note: '',
      userOptions: [],
      errorMessage: '',
      successMessage: '',
      userRules: [
        v => !!v || '请选择用户'
      ],
      countRules: [
        v => !!v || '请输入生成数量',
        v => !isNaN(parseInt(v)) && parseInt(v) > 0 || '请输入有效的数量',
        v => parseInt(v) <= 100 || '单次生成数量不能超过100个'
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
      this.generateCount = 1
      this.isPremium = false
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
          current_credits: user.current_credits || 0
        }))
      } catch (error) {
        this.errorMessage = '加载用户列表失败'
        console.error('加载用户列表失败:', error)
      } finally {
        this.loading = false
      }
    },
    
    async generateInviteCodes() {
      if (!this.$refs.form.validate()) {
        return
      }
      
      this.processing = true
      this.errorMessage = ''
      this.successMessage = ''
      
      try {
        const requestData = {
          tg_id: this.selectedUser,
          count: parseInt(this.generateCount),
          is_premium: this.isPremium,
          note: this.note || null
        }
        
        const result = await generateAdminInviteCodes(requestData)
        
        if (result.success) {
          this.successMessage = result.message || `成功生成 ${this.generateCount} 个邀请码`
          
          // 显示成功提示
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showPopup({
              title: '生成成功',
              message: `已为用户生成 ${this.generateCount} 个${this.isPremium ? '特权' : '普通'}邀请码`
            })
          }
          
          // 通知父组件刷新数据
          this.$emit('invite-codes-generated', requestData)
          
          // 延迟关闭对话框
          setTimeout(() => {
            this.closeDialog()
          }, 1500)
        } else {
          this.errorMessage = result.message || '生成失败'
        }
      } catch (error) {
        this.errorMessage = error.response?.data?.message || '生成失败，请稍后再试'
        console.error('生成邀请码失败:', error)
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
