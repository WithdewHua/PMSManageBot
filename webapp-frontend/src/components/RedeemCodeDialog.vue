<template>
  <v-dialog v-model="showDialog" max-width="500">
    <v-card>
      <v-card-title class="headline">兑换邀请码</v-card-title>
      <v-card-text>
        <v-form ref="form" v-model="valid" lazy-validation>
          <!-- 服务类型选择 - 改为横向排列并使用紫色 -->
          <div class="service-selection mb-4">
            <span class="service-label mr-4">选择服务:</span>
            <v-btn-toggle
              v-model="serviceType"
              mandatory
              rounded
              dense
              class="service-toggle"
            >
              <v-btn value="plex" small>
                <v-icon left>mdi-plex</v-icon>
                Plex
              </v-btn>
              <v-btn value="emby" small>
                <v-icon left>mdi-filmstrip</v-icon>
                Emby
              </v-btn>
            </v-btn-toggle>
          </div>

          <!-- 邀请码输入框 -->
          <v-text-field
            v-model="inviteCode"
            label="邀请码"
            :rules="inviteCodeRules"
            required
            outlined
            dense
            hide-details="auto"
            class="mb-3"
          ></v-text-field>
          
          <!-- 特权邀请码提示 -->
          <div v-if="isPrivilegedCode" class="privilege-message mb-3">
            <v-icon color="gold" small>mdi-crown</v-icon>
            <span class="ml-2">特权邀请码，可无视注册限制</span>
          </div>
          
          <!-- 根据所选服务显示对应输入框 -->
          <v-text-field
            v-if="serviceType === 'plex'"
            v-model="email"
            label="Plex 邮箱"
            :rules="emailRules"
            type="email"
            required
            outlined
            dense
            hide-details="auto"
            class="mb-3"
          ></v-text-field>
          
          <v-text-field
            v-if="serviceType === 'emby'"
            v-model="username"
            label="Emby 用户名"
            :rules="usernameRules"
            required
            outlined
            dense
            hide-details="auto"
            class="mb-3"
          ></v-text-field>

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
          text 
          color="grey" 
          @click="closeDialog"
          :disabled="loading"
        >
          取消
        </v-btn>
        <v-btn 
          color="purple" 
          @click="redeemCode"
          :loading="loading"
          :disabled="loading || !valid"
        >
          确认兑换
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { redeemMediaServiceInviteCode, getMediaServiceRegisterStatus, checkPrivilegedInviteCode } from '../services/mediaServiceApi';

export default {
  name: 'RedeemCodeDialog',
  data() {
    return {
      showDialog: false,
      valid: false,
      loading: false,
      serviceType: 'emby', // 默认选择Emby
      inviteCode: '',
      email: '',
      username: '',
      errorMessage: '',
      successMessage: '',
      registerStatus: {
        plex: true,
        emby: true
      },
      isPrivilegedCode: false, // 是否为特权邀请码
      inviteCodeRules: [
        v => !!v || '请输入邀请码',
        v => v.length >= 6 || '邀请码长度不正确'
      ],
      emailRules: [
        v => !!v || '请输入 Plex 邮箱',
        v => /^\w+([.-]?\w+)*@\w+([.-]?\w+)*(\.\w{2,3})+$/.test(v) || '请输入有效的邮箱地址'
      ],
      usernameRules: [
        v => !!v || '请输入 Emby 用户名',
        v => v.length >= 2 || '用户名太短',
      ]
    }
  },
  methods: {
    open(type = null) {
      this.resetForm();
      if (type && (type === 'plex' || type === 'emby')) {
        this.serviceType = type;
      }
      this.showDialog = true;
      this.checkRegisterStatus();
    },
    closeDialog() {
      this.showDialog = false;
    },
    resetForm() {
      this.inviteCode = '';
      this.email = '';
      this.username = '';
      this.errorMessage = '';
      this.successMessage = '';
      this.isPrivilegedCode = false;
      if (this.$refs.form) {
        this.$refs.form.resetValidation();
      }
    },
    // 检查注册状态
    async checkRegisterStatus() {
      try {
        const status = await getMediaServiceRegisterStatus();
        this.registerStatus = status;
        
        // 检查当前服务的注册状态
        await this.updateServiceAvailability();
      } catch (error) {
        console.error('获取注册状态失败:', error);
      }
    },
    
    // 检查邀请码是否为特权码
    async checkInviteCodePrivilege() {
      if (!this.inviteCode) {
        this.isPrivilegedCode = false;
        return;
      }
      
      try {
        const result = await checkPrivilegedInviteCode(this.inviteCode);
        this.isPrivilegedCode = result.privileged;
        // 当邀请码状态改变时，更新服务可用性
        await this.updateServiceAvailability();
      } catch (error) {
        console.error('检查特权邀请码失败:', error);
        this.isPrivilegedCode = false;
      }
    },
    
    // 更新服务可用性提示
    async updateServiceAvailability() {
      this.errorMessage = '';
      
      // 如果是特权邀请码，允许注册任何服务
      if (this.isPrivilegedCode) {
        return;
      }
      
      // 非特权码时检查注册状态
      if (this.serviceType === 'plex' && !this.registerStatus.plex) {
        this.errorMessage = 'Plex 当前不接受新用户注册';
      } else if (this.serviceType === 'emby' && !this.registerStatus.emby) {
        this.errorMessage = 'Emby 当前不接受新用户注册';
      }
    },
    async redeemCode() {
      // 根据当前服务类型验证表单
      if (!this.$refs.form.validate()) {
        return;
      }

      // 检查服务注册状态（特权码跳过检查）
      if (!this.isPrivilegedCode) {
        if (this.serviceType === 'plex' && !this.registerStatus.plex) {
          this.errorMessage = 'Plex 当前不接受新用户注册';
          return;
        } else if (this.serviceType === 'emby' && !this.registerStatus.emby) {
          this.errorMessage = 'Emby 当前不接受新用户注册';
          return;
        }
      }

      // 确保根据服务类型，对应字段有值
      if ((this.serviceType === 'plex' && !this.email) || 
          (this.serviceType === 'emby' && !this.username)) {
        this.errorMessage = `请填写${this.serviceType === 'plex' ? 'Plex 邮箱' : 'Emby 用户名'}`;
        return;
      }

      this.loading = true;
      this.errorMessage = '';
      this.successMessage = '';

      try {
        // 构建请求数据
        const requestData = {
          code: this.inviteCode,
          // 根据服务类型添加对应字段
          ...(this.serviceType === 'plex' ? { email: this.email } : { username: this.username })
        };

        // 使用服务函数发送请求
        const response = await redeemMediaServiceInviteCode(this.serviceType, requestData);

        if (response.success) {
          this.successMessage = response.message || `邀请码兑换成功！已添加到 ${this.serviceType === 'plex' ? 'Plex' : 'Emby'}。`;
          
          // 3秒后自动关闭对话框
          setTimeout(() => {
            this.closeDialog();
          }, 3000);
        } else {
          this.errorMessage = response.message || '兑换失败，请稍后再试。';
        }
      } catch (error) {
        console.error(`兑换 ${this.serviceType} 邀请码失败:`, error);
        this.errorMessage = error.response?.data?.message || error.message || '服务器错误，请稍后再试。';
      } finally {
        this.loading = false;
      }
    }
  },
  watch: {
    // 当服务类型变化时，更新服务可用性
    serviceType() {
      this.errorMessage = '';
      this.successMessage = '';
      this.updateServiceAvailability();
    },
    
    // 当邀请码变化时，检查是否为特权码
    inviteCode() {
      // 防抖处理，避免频繁请求
      clearTimeout(this.checkCodeTimer);
      this.checkCodeTimer = setTimeout(() => {
        this.checkInviteCodePrivilege();
      }, 500);
    }
  },
  
  beforeUnmount() {
    // 清理定时器
    if (this.checkCodeTimer) {
      clearTimeout(this.checkCodeTimer);
    }
  }
}
</script>

<style scoped>
/* 紫色主题色 */
:deep(.v-btn--active) {
  background-color: #9333ea !important;
  color: white !important;
}

.service-selection {
  display: flex;
  align-items: center;
}

.service-label {
  font-weight: 500;
  color: rgba(0, 0, 0, 0.6);
}

:deep(.service-toggle) {
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 4px;
}

/* 修改确认按钮颜色 */
:deep(.v-btn.purple) {
  background-color: #9333ea !important;
}

.error-message {
  color: #ff5252;
  font-size: 14px;
}

.success-message {
  color: #4caf50;
  font-size: 14px;
}

.privilege-message {
  color: #ff9800;
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
}
</style>
