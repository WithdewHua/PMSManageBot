<template>
  <v-dialog v-model="showDialog" max-width="500">
    <v-card>
      <v-card-title class="headline">绑定线路</v-card-title>
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

          <!-- 密码输入框 -->
          <v-text-field
            v-model="password"
            label="密码"
            :rules="passwordRules"
            type="password"
            required
            outlined
            dense
            hide-details="auto"
            class="mb-3"
          ></v-text-field>

          <!-- 线路选择下拉框 -->
          <v-select
            v-model="selectedLine"
            label="选择线路"
            :items="availableLines"
            :loading="loadingLines"
            :rules="lineRules"
            required
            outlined
            dense
            hide-details="auto"
            class="mb-3"
            @focus="loadAvailableLines"
          >
            <template v-slot:no-data>
              <v-list-item>
                <v-list-item-title>
                  {{ loadingLines ? '加载中...' : '暂无可用线路' }}
                </v-list-item-title>
              </v-list-item>
            </template>
          </v-select>

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
          @click="bindLine"
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
import { authBindLine, bindLine as bindLineService } from '../services/userLineService';
import { getAvailableEmbyLines } from '../services/embyService';
import { getAvailablePlexLines } from '../services/plexService';

export default {
  name: 'BindLineDialog',
  data() {
    return {
      showDialog: false,
      valid: false,
      loading: false,
      loadingLines: false,
      serviceType: 'plex', // 默认选择Plex
      email: '',
      username: '',
      password: '',
      selectedLine: '',
      availableLines: [],
      errorMessage: '',
      successMessage: '',
      emailRules: [
        v => !!v || '请输入 Plex 邮箱',
        v => /^\w+([.-]?\w+)*@\w+([.-]?\w+)*(\.\w{2,3})+$/.test(v) || '请输入有效的邮箱地址'
      ],
      usernameRules: [
        v => !!v || '请输入 Emby 用户名',
        v => v && v.length >= 2 || '用户名至少2个字符'
      ],
      passwordRules: [
        v => !!v || '请输入密码',
        v => v && v.length >= 1 || '密码不能为空'
      ],
      lineRules: [
        v => !!v || '请选择线路'
      ]
    }
  },
  watch: {
    serviceType() {
      // 服务类型改变时重置表单和线路列表
      this.resetForm();
      this.availableLines = [];
      this.selectedLine = '';
    }
  },
  methods: {
    // 打开对话框
    open(type = null) {
      if (type) {
        this.serviceType = type;
      }
      this.showDialog = true;
      this.resetForm();
      this.loadAvailableLines();
    },
    
    // 关闭对话框
    closeDialog() {
      this.showDialog = false;
      this.resetForm();
    },
    
    // 重置表单
    resetForm() {
      this.email = '';
      this.username = '';
      this.password = '';
      this.selectedLine = '';
      this.errorMessage = '';
      this.successMessage = '';
      if (this.$refs.form) {
        this.$refs.form.resetValidation();
      }
    },
    
    // 加载可用线路
    async loadAvailableLines() {
      if (this.loadingLines) return;
      
      this.loadingLines = true;
      try {
        let lines = [];
        if (this.serviceType === 'emby') {
          lines = await getAvailableEmbyLines();
        } else {
          lines = await getAvailablePlexLines();
        }
        
        // 转换为下拉框所需的格式
        this.availableLines = lines.map(line => ({
          title: line.name,
          value: line.name
        }));
      } catch (error) {
        console.error('获取线路列表失败:', error);
        this.errorMessage = '获取线路列表失败，请稍后再试';
        this.availableLines = [];
      } finally {
        this.loadingLines = false;
      }
    },
    
    // 绑定线路
    async bindLine() {
      // 验证表单
      if (!this.$refs.form.validate()) {
        return;
      }
      
      this.loading = true;
      this.errorMessage = '';
      this.successMessage = '';
      
      try {
        // 构建认证请求参数
        const credentials = {
          line: this.selectedLine,
          password: this.password
        };
        
        if (this.serviceType === 'plex') {
          credentials.username = this.email; // Plex使用邮箱作为用户名
        } else {
          credentials.username = this.username; // Emby使用用户名
        }
        
        // 调用新的认证绑定API
        const result = await authBindLine(this.serviceType, credentials);
        
        if (result.success) {
          this.successMessage = result.message || '认证并绑定线路成功';
          
          // 延迟关闭对话框
          setTimeout(() => {
            this.closeDialog();
            // 通知父组件刷新数据
            this.$emit('line-bound', {
              service: this.serviceType,
              line: this.selectedLine
            });
          }, 1500);
        } else {
          this.errorMessage = result.message || '认证绑定失败，请检查用户名密码是否正确';
        }
      } catch (error) {
        console.error('认证绑定线路失败:', error);
        this.errorMessage = error.response?.data?.detail || error.response?.data?.message || '认证绑定失败，请稍后再试';
      } finally {
        this.loading = false;
      }
    }
  }
}
</script>

<style scoped>
/* 服务选择样式 */
.service-selection {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.service-label {
  font-weight: 500;
  color: #424242;
  white-space: nowrap;
}

.service-toggle {
  border-radius: 20px !important;
}

.service-toggle .v-btn {
  min-width: 80px !important;
  color: #9c27b0 !important;
  border: 1px solid #9c27b0 !important;
}

.service-toggle .v-btn--active {
  background-color: #9c27b0 !important;
  color: white !important;
}

/* 错误和成功消息样式 */
.error-message {
  color: #f44336;
  font-size: 14px;
  margin-top: 8px;
}

.success-message {
  color: #4caf50;
  font-size: 14px;
  margin-top: 8px;
}

/* 小屏幕适配 */
@media (max-width: 480px) {
  .service-selection {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  
  .service-label {
    margin-bottom: 8px;
  }
  
  .service-toggle {
    width: 100%;
  }
}
</style>