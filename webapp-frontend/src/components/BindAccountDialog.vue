<template>
  <v-dialog v-model="showDialog" max-width="500">
    <v-card>
      <v-card-title class="headline">绑定媒体服务账户</v-card-title>
      <v-card-text>
        <v-form ref="form" v-model="valid" lazy-validation>
          <!-- 服务类型选择 -->
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

          <!-- Plex 邮箱输入框 -->
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
          
          <!-- Emby 用户名输入框 -->
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
          @click="bindAccount"
          :loading="loading"
          :disabled="loading || !valid"
        >
          确认绑定
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { bindMediaServiceAccount } from '../services/mediaServiceApi';

export default {
  name: 'BindAccountDialog',
  data() {
    return {
      showDialog: false,
      valid: false,
      loading: false,
      serviceType: 'plex', // 默认选择Plex
      email: '',
      username: '',
      errorMessage: '',
      successMessage: '',
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
    },
    closeDialog() {
      this.showDialog = false;
    },
    resetForm() {
      this.email = '';
      this.username = '';
      this.errorMessage = '';
      this.successMessage = '';
      if (this.$refs.form) {
        this.$refs.form.resetValidation();
      }
    },
    async bindAccount() {
      // 根据当前服务类型验证表单
      if (!this.$refs.form.validate()) {
        return;
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
          // 根据服务类型添加对应字段
          ...(this.serviceType === 'plex' ? { email: this.email } : { username: this.username })
        };

        // 使用服务函数发送请求
        const response = await bindMediaServiceAccount(this.serviceType, requestData);

        if (response.success) {
          this.successMessage = response.message || `${this.serviceType === 'plex' ? 'Plex' : 'Emby'} 账户绑定成功！`;
          
          // 3秒后自动关闭对话框
          setTimeout(() => {
            this.closeDialog();
          }, 3000);
        } else {
          this.errorMessage = response.message || '绑定失败，请稍后再试。';
        }
      } catch (error) {
        console.error(`绑定 ${this.serviceType} 账户失败:`, error);
        this.errorMessage = error.response?.data?.message || error.message || '服务器错误，请稍后再试。';
      } finally {
        this.loading = false;
      }
    }
  },
  watch: {
    // 当服务类型变化时，清除对应的错误信息
    serviceType() {
      this.errorMessage = '';
      this.successMessage = '';
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
</style>
