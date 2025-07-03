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

          <!-- Plex 认证方式选择 -->
          <div v-if="serviceType === 'plex'" class="auth-method-selection mb-4">
            <span class="auth-label mr-4">认证方式:</span>
            <v-btn-toggle
              v-model="plexAuthMethod"
              mandatory
              rounded
              dense
              class="auth-toggle"
            >
              <v-btn value="password" small>
                <v-icon left>mdi-key</v-icon>
                密码
              </v-btn>
              <v-btn value="token" small>
                <v-icon left>mdi-shield-key</v-icon>
                Token
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

          <!-- Plex Token 输入框 -->
          <v-text-field
            v-if="serviceType === 'plex' && plexAuthMethod === 'token'"
            v-model="plexToken"
            label="Plex Token"
            :rules="tokenRules"
            type="password"
            required
            outlined
            dense
            hide-details="auto"
            class="mb-3"
          >
            <template v-slot:append>
              <v-tooltip 
                v-model="showTokenHelp"
                bottom 
                max-width="400" 
                class="token-help-tooltip"
                :open-on-hover="false"
                :open-on-focus="false"
              >
                <template v-slot:activator="{ props }">
                  <v-icon 
                    v-bind="props" 
                    small 
                    color="info" 
                    class="help-icon"
                    @click="toggleTokenHelp"
                  >
                    mdi-help-circle
                  </v-icon>
                </template>
                <div class="token-help-content">
                  <div class="help-title">
                    <v-icon small color="white" class="mr-2">mdi-key-variant</v-icon>
                    获取 Plex Token
                  </div>
                  <div class="help-steps">
                    <div class="step">
                      <span class="step-number">1</span>
                      打开 Plex Web 应用
                    </div>
                    <div class="step">
                      <span class="step-number">2</span>
                      按 F12 打开开发者工具
                    </div>
                    <div class="step">
                      <span class="step-number">3</span>
                      切换到 Network 标签页
                    </div>
                    <div class="step">
                      <span class="step-number">4</span>
                      过滤 "FunMedia" 请求
                    </div>
                    <div class="step">
                      <span class="step-number">5</span>
                      从请求 Header 或 URL 参数中复制 <code>X-Plex-Token</code>
                    </div>
                  </div>
                </div>
              </v-tooltip>
            </template>
          </v-text-field>

          <!-- 密码输入框 -->
          <v-text-field
            v-if="serviceType === 'emby' || (serviceType === 'plex' && plexAuthMethod === 'password')"
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
          <v-menu
            v-model="lineMenu"
            :close-on-content-click="false"
            offset-y
            max-height="400"
            @update:model-value="onLineMenuToggle"
          >
            <template v-slot:activator="{ props }">
              <v-text-field
                v-bind="props"
                v-model="selectedLine"
                label="选择线路"
                :rules="lineRules"
                required
                outlined
                dense
                hide-details="auto"
                class="mb-3"
                readonly
                :loading="loadingLines"
                placeholder="请选择线路"
              ></v-text-field>
            </template>
            
            <v-card min-width="300">
              <v-list class="line-selector-list" max-height="350">
                <v-list-item 
                  v-for="lineInfo in availableLines" 
                  :key="lineInfo.name" 
                  @click="selectLine(lineInfo.name)" 
                  :active="selectedLine === lineInfo.name"
                  :color="selectedLine === lineInfo.name ? '#9333ea' : undefined"
                  class="line-item"
                >
                  <v-list-item-title class="d-flex align-center justify-space-between">
                    <div class="line-name-container">
                      <div class="line-name-wrapper">
                        <span class="line-name">{{ lineInfo.name }}</span>
                        <v-chip
                          v-if="currentBoundLine === lineInfo.name"
                          size="x-small"
                          color="success"
                          variant="flat"
                          class="ml-2 current-line-chip"
                        >
                          <v-icon size="x-small" class="mr-1">mdi-link</v-icon>
                          当前绑定
                        </v-chip>
                      </div>
                      <div v-if="lineInfo.tags && lineInfo.tags.length > 0" class="tags-container mt-1">
                        <v-chip
                          v-for="tag in lineInfo.tags"
                          :key="tag"
                          size="x-small"
                          :color="getTagColor(tag)"
                          variant="flat"
                          class="mr-1 mb-1 tag-chip"
                        >
                          {{ tag }}
                        </v-chip>
                      </div>
                    </div>
                    <v-icon v-if="selectedLine === lineInfo.name" color="success" size="small">mdi-check</v-icon>
                  </v-list-item-title>
                </v-list-item>
                
                <v-list-item v-if="availableLines.length === 0 && !loadingLines && !hasValidCredentials" class="text-center">
                  <v-list-item-title class="text-grey">
                    <v-icon class="mr-2" size="small">mdi-information</v-icon>
                    请先输入{{ serviceType === 'emby' ? '用户名' : '邮箱' }}
                  </v-list-item-title>
                </v-list-item>
                
                <v-list-item v-if="availableLines.length === 0 && !loadingLines && hasValidCredentials" class="text-center">
                  <v-list-item-title class="text-grey">暂无可用线路</v-list-item-title>
                </v-list-item>
                
                <v-list-item v-if="loadingLines" class="text-center">
                  <v-list-item-title class="text-grey">
                    <v-progress-circular indeterminate size="20" class="mr-2"></v-progress-circular>
                    加载中...
                  </v-list-item-title>
                </v-list-item>
                
                <v-divider v-if="!loadingLines"></v-divider>
                
                <v-list-item v-if="!loadingLines">
                  <v-text-field
                    v-model="customLine"
                    label="自定义线路"
                    variant="underlined"
                    density="compact"
                    hide-details
                    class="mx-2"
                    @keyup.enter="selectCustomLine"
                  >
                    <template v-slot:append>
                      <v-icon @click="selectCustomLine" color="primary" size="small">mdi-check</v-icon>
                    </template>
                  </v-text-field>
                </v-list-item>
              </v-list>
            </v-card>
          </v-menu>

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
import { authBindLine, getAvailableEmbyLinesByUser, getAvailablePlexLinesByUser, getCurrentBoundEmbyLine, getCurrentBoundPlexLine } from '../services/userLineService';

export default {
  name: 'BindLineDialog',
  data() {
    return {
      showDialog: false,
      showTokenHelp: false, // 控制 token 帮助提示的显示
      valid: false,
      loading: false,
      loadingLines: false,
      lineMenu: false,
      serviceType: 'plex', // 默认选择Plex
      email: '',
      username: '',
      password: '',
      plexToken: '', // 新增 Plex Token 字段
      selectedLine: '',
      customLine: '',
      availableLines: [],
      currentBoundLine: null, // 存储当前绑定的线路信息
      errorMessage: '',
      successMessage: '',
      plexAuthMethod: 'password', // 默认Plex认证方式为密码
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
      tokenRules: [
        v => !!v || '请输入 Plex Token',
        v => v && v.length >= 1 || 'Token 不能为空'
      ],
      lineRules: [
        v => !!v || '请选择线路'
      ]
    }
  },
  computed: {
    // 检查是否有有效的凭据
    hasValidCredentials() {
      if (this.serviceType === 'emby') {
        return this.username && this.username.trim();
      } else {
        return this.email && this.email.trim();
      }
    }
  },
  watch: {
    serviceType() {
      // 服务类型改变时重置表单和线路列表
      this.resetForm();
      this.availableLines = [];
      this.currentBoundLine = null;
      this.selectedLine = '';
      this.customLine = '';
    },
    plexAuthMethod() {
      // Plex认证方式改变时清空相关字段和线路列表
      this.password = '';
      this.plexToken = '';
      this.availableLines = [];
      this.currentBoundLine = null;
      this.selectedLine = '';
      this.errorMessage = '';
    },
    username: {
      handler() {
        // 用户名变化时清空线路列表和错误信息
        this.availableLines = [];
        this.currentBoundLine = null;
        this.selectedLine = '';
        this.errorMessage = '';
      },
      immediate: false
    },
    email: {
      handler() {
        // 邮箱变化时清空线路列表和错误信息
        this.availableLines = [];
        this.currentBoundLine = null;
        this.selectedLine = '';
        this.errorMessage = '';
      },
      immediate: false
    },
    password() {
      // 密码变化时清空选中的线路
      this.selectedLine = '';
      this.errorMessage = '';
    },
    plexToken() {
      // Token变化时清空选中的线路
      this.selectedLine = '';
      this.errorMessage = '';
    },
    
    // 监听对话框显示状态，关闭时重置帮助提示
    showDialog(newVal) {
      if (!newVal) {
        this.showTokenHelp = false;
      }
    }
  },
  methods: {
    // 切换 Token 帮助提示显示状态
    toggleTokenHelp() {
      this.showTokenHelp = !this.showTokenHelp;
    },
    
    // 打开对话框
    open(type = null) {
      if (type) {
        this.serviceType = type;
      }
      this.showDialog = true;
      this.resetForm();
      // 不再自动加载线路，等用户输入凭据后手动获取
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
      this.plexToken = '';
      this.selectedLine = '';
      this.customLine = '';
      this.currentBoundLine = null; // 重置当前绑定线路信息
      this.errorMessage = '';
      this.successMessage = '';
      this.showTokenHelp = false; // 重置帮助提示状态
      this.plexAuthMethod = 'password'; // 重置Plex认证方式为密码
      if (this.$refs.form) {
        this.$refs.form.resetValidation();
      }
    },
    
    // 加载可用线路
    async loadAvailableLines() {
      if (this.loadingLines) return;
      
      // 检查必要的凭据是否已输入
      if (this.serviceType === 'emby') {
        if (!this.username || !this.username.trim()) {
          this.availableLines = [];
          this.currentBoundLine = null;
          return;
        }
      } else {
        if (!this.email || !this.email.trim()) {
          this.availableLines = [];
          this.currentBoundLine = null;
          return;
        }
      }
      
      this.loadingLines = true;
      this.errorMessage = '';
      try {
        // 并行获取可用线路和当前绑定线路
        const [linesResult, currentLineResult] = await Promise.all([
          this.serviceType === 'emby' 
            ? getAvailableEmbyLinesByUser(this.username)
            : getAvailablePlexLinesByUser(this.email),
          this.serviceType === 'emby'
            ? getCurrentBoundEmbyLine(this.username)
            : getCurrentBoundPlexLine(this.email)
        ]);
        
        // 保留完整的线路信息（包括标签）
        this.availableLines = linesResult;
        
        // 处理当前绑定线路信息
        if (currentLineResult.success && currentLineResult.data?.line) {
          this.currentBoundLine = currentLineResult.data.line;
          // 如果没有手动选择过线路，自动设置为当前绑定的线路
          if (!this.selectedLine) {
            this.selectedLine = this.currentBoundLine;
          }
        } else {
          this.currentBoundLine = null;
        }
        
      } catch (error) {
        console.error('获取线路信息失败:', error);
        if (error.response?.data?.message) {
          this.errorMessage = error.response.data.message;
        } else {
          this.errorMessage = `获取线路信息失败，请检查${this.serviceType === 'emby' ? '用户名' : '邮箱'}是否正确`;
        }
        this.availableLines = [];
        this.currentBoundLine = null;
      } finally {
        this.loadingLines = false;
      }
    },
    
    // 处理线路菜单切换
    async onLineMenuToggle(isOpen) {
      if (isOpen && !this.loadingLines && this.hasValidCredentials && this.availableLines.length === 0) {
        await this.loadAvailableLines();
      }
    },
    
    // 选择线路
    selectLine(lineName) {
      this.selectedLine = lineName;
      this.lineMenu = false;
    },
    
    // 选择自定义线路
    selectCustomLine() {
      if (this.customLine && this.customLine.trim()) {
        this.selectedLine = this.customLine.trim();
        this.customLine = '';
        this.lineMenu = false;
      }
    },
    
    // 获取标签颜色
    getTagColor(tag) {
      // 使用更深色的背景色，确保在白色背景下有良好对比度
      const contrastColors = [
        'red-darken-1',
        'pink-darken-1', 
        'purple-darken-1',
        'deep-purple-darken-1',
        'indigo-darken-1',
        'blue-darken-1',
        'light-blue-darken-1',
        'cyan-darken-1',
        'teal-darken-1',
        'green-darken-1',
        'light-green-darken-1',
        'lime-darken-1',
        'amber-darken-1',
        'orange-darken-1',
        'deep-orange-darken-1',
        'brown-darken-1',
        'blue-grey-darken-1',
        'red-darken-2',
        'pink-darken-2',
        'purple-darken-2',
        'deep-purple-darken-2',
        'indigo-darken-2',
        'blue-darken-2',
        'teal-darken-2',
        'green-darken-2'
      ];
      
      // 使用标签内容作为种子生成稳定的随机索引
      let hash = 0;
      for (let i = 0; i < tag.length; i++) {
        const char = tag.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // 转换为32位整数
      }
      
      const colorIndex = Math.abs(hash) % contrastColors.length;
      return contrastColors[colorIndex];
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
          line: this.selectedLine
        };
        
        if (this.serviceType === 'plex') {
          credentials.username = this.email; // Plex使用邮箱作为用户名
          
          // 根据认证方式添加不同的认证信息
          if (this.plexAuthMethod === 'token') {
            credentials.token = this.plexToken;
            credentials.auth_method = 'token';
          } else {
            credentials.password = this.password;
            credentials.auth_method = 'password';
          }
        } else {
          credentials.username = this.username; // Emby使用用户名
          credentials.password = this.password;
        }
        
        // 调用新的认证绑定API
        const result = await authBindLine(this.serviceType, credentials);
        
        if (result.success) {
          this.successMessage = result.message || '认证并绑定线路成功';
          
          // 更新当前绑定线路
          this.currentBoundLine = this.selectedLine;
          
          // 立即通知父组件刷新数据
          this.$emit('line-bound', {
            service: this.serviceType,
            line: this.selectedLine
          });
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

/* 认证方式选择样式 */
.auth-method-selection {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.auth-label {
  font-weight: 500;
  color: #424242;
  white-space: nowrap;
}

.auth-toggle {
  border-radius: 20px !important;
}

.auth-toggle .v-btn {
  min-width: 80px !important;
  color: #4caf50 !important;
  border: 1px solid #4caf50 !important;
}

.auth-toggle .v-btn--active {
  background-color: #4caf50 !important;
  color: white !important;
}

/* 线路选择器列表样式 */
.line-selector-list {
  max-height: 350px;
  overflow-y: auto;
}

.line-selector-list::-webkit-scrollbar {
  width: 6px;
}

.line-selector-list::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.line-selector-list::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.line-selector-list::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

.line-item {
  min-height: 56px;
}

.line-name-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 0;
}

.line-name-wrapper {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}

.line-name {
  font-weight: 500;
  font-size: 14px;
  word-break: break-all;
  overflow-wrap: break-word;
  line-height: 1.3;
}

.current-line-chip {
  color: white !important;
  font-weight: 500 !important;
  font-size: 10px !important;
  height: 20px !important;
}

.tags-container {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px;
  max-width: 320px;
  line-height: 1.2;
}

.tags-container .v-chip {
  height: 18px !important;
  font-size: 10px !important;
  padding: 0 6px !important;
}

.tag-chip {
  color: white !important;
  font-weight: 500 !important;
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

/* Token 帮助提示样式 */
.help-icon {
  cursor: pointer;
  transition: all 0.2s ease;
  padding: 4px; /* 增加点击区域 */
  border-radius: 50%;
  position: relative;
}

.help-icon:hover {
  color: #1976d2 !important;
  background-color: rgba(25, 118, 210, 0.08);
  transform: scale(1.1);
}

/* 移动设备触摸优化 */
.help-icon:active {
  transform: scale(0.95);
  background-color: rgba(25, 118, 210, 0.12);
}

.token-help-content {
  max-width: 360px;
  padding: 12px;
  background: rgba(55, 71, 79, 0.95);
  border-radius: 8px;
  color: white;
  font-size: 13px;
  line-height: 1.4;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.help-title {
  display: flex;
  align-items: center;
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 12px;
  color: #e3f2fd;
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  padding-bottom: 8px;
}

.help-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 4px 0;
}

.step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  background: #2196f3;
  color: white;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
  margin-top: 1px;
}

.step code {
  background: rgba(255, 255, 255, 0.15);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 12px;
  color: #81d4fa;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

/* 小屏幕适配 */
@media (max-width: 480px) {
  .service-selection,
  .auth-method-selection {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  
  .service-label,
  .auth-label {
    margin-bottom: 8px;
  }
  
  .service-toggle,
  .auth-toggle {
    width: 100%;
  }
  
  /* 移动设备上的帮助提示优化 */
  .token-help-content {
    max-width: 280px;
    font-size: 12px;
    padding: 10px;
  }
  
  .help-title {
    font-size: 13px;
    margin-bottom: 10px;
    padding-bottom: 6px;
  }
  
  .step {
    gap: 6px;
    padding: 3px 0;
  }
  
  .step-number {
    width: 16px;
    height: 16px;
    font-size: 10px;
  }
  
  .help-icon {
    padding: 6px; /* 移动设备上增加更大的点击区域 */
  }
}
</style>