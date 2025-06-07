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
                append-icon="mdi-chevron-down"
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
                      <span class="line-name">{{ lineInfo.name }}</span>
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
                
                <v-list-item v-if="availableLines.length === 0 && !loadingLines" class="text-center">
                  <v-list-item-title class="text-grey">暂无可用线路</v-list-item-title>
                </v-list-item>
                
                <v-list-item v-if="loadingLines" class="text-center">
                  <v-list-item-title class="text-grey">
                    <v-progress-circular indeterminate size="20" class="mr-2"></v-progress-circular>
                    加载中...
                  </v-list-item-title>
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
import { authBindLine } from '../services/userLineService';
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
      lineMenu: false,
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
        
        // 保留完整的线路信息（包括标签）
        this.availableLines = lines;
      } catch (error) {
        console.error('获取线路列表失败:', error);
        this.errorMessage = '获取线路列表失败，请稍后再试';
        this.availableLines = [];
      } finally {
        this.loadingLines = false;
      }
    },
    
    // 处理线路菜单切换
    async onLineMenuToggle(isOpen) {
      if (isOpen && !this.loadingLines) {
        await this.loadAvailableLines();
      }
    },
    
    // 选择线路
    selectLine(lineName) {
      this.selectedLine = lineName;
      this.lineMenu = false;
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

.line-name {
  font-weight: 500;
  font-size: 14px;
  word-break: break-all;
  overflow-wrap: break-word;
  line-height: 1.3;
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