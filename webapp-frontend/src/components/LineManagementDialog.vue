<template>
  <v-dialog v-model="dialog" max-width="800" scrollable class="line-management-dialog">
    <v-card>
      <v-card-title class="text-center">
        <v-icon start color="blue-darken-2">mdi-server-network</v-icon>
        线路管理
      </v-card-title>
      
      <v-card-text>
        <div v-if="loading" class="text-center my-4">
          <v-progress-circular indeterminate size="small" color="primary"></v-progress-circular>
          <span class="ml-2">加载线路配置中...</span>
        </div>
        
        <div v-else-if="error" class="mb-4">
          <v-alert type="error" density="compact">{{ error }}</v-alert>
        </div>
        
        <div v-else>
          <!-- 普通线路管理 -->
          <div class="mb-6">
            <div class="section-header mb-3">
              <div class="header-info">
                <v-icon size="small" color="blue-darken-1" class="mr-2">mdi-server</v-icon>
                <span class="font-weight-medium">普通线路</span>
                <v-chip size="x-small" color="blue-lighten-3" class="ml-2">
                  {{ normalLines.length }} 条
                </v-chip>
              </div>
              <v-btn
                color="blue-darken-1"
                variant="outlined"
                size="small"
                class="add-btn"
                @click="openAddLineDialog('normal')"
              >
                <v-icon start size="small">mdi-plus</v-icon>
                <span class="btn-text">添加普通线路</span>
              </v-btn>
            </div>
            
            <v-card variant="outlined" class="pa-3 line-container">
              <div v-if="normalLines.length === 0" class="text-center text-grey py-4">
                暂无普通线路
              </div>
              <div v-else class="line-chips-container">
                <v-chip
                  v-for="line in normalLines"
                  :key="line"
                  size="small"
                  class="line-chip normal-line mr-2 mb-2"
                  closable
                  @click:close="confirmDeleteLine('normal', line)"
                >
                  <span class="line-text" :title="line">{{ line }}</span>
                </v-chip>
              </div>
            </v-card>
          </div>
          
          <!-- 高级线路管理 -->
          <div class="mb-4">
            <div class="section-header mb-3">
              <div class="header-info">
                <v-icon size="small" color="amber-darken-2" class="mr-2">mdi-crown</v-icon>
                <span class="font-weight-medium">高级线路</span>
                <v-chip size="x-small" color="amber-lighten-3" class="ml-2">
                  {{ premiumLines.length }} 条
                </v-chip>
              </div>
              <v-btn
                color="amber-darken-2"
                variant="outlined"
                size="small"
                class="add-btn"
                @click="openAddLineDialog('premium')"
              >
                <v-icon start size="small">mdi-plus</v-icon>
                <span class="btn-text">添加高级线路</span>
              </v-btn>
            </div>
            
            <v-card variant="outlined" class="pa-3 line-container">
              <div v-if="premiumLines.length === 0" class="text-center text-grey py-4">
                暂无高级线路
              </div>
              <div v-else class="line-chips-container">
                <v-chip
                  v-for="line in premiumLines"
                  :key="line"
                  size="small"
                  class="line-chip premium-line mr-2 mb-2"
                  closable
                  @click:close="confirmDeleteLine('premium', line)"
                >
                  <span class="line-text" :title="line">{{ line }}</span>
                </v-chip>
              </div>
            </v-card>
          </div>
        </div>
      </v-card-text>
      
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="grey" variant="text" @click="close">关闭</v-btn>
      </v-card-actions>
    </v-card>
    
    <!-- 添加线路对话框 -->
    <v-dialog v-model="addDialog" max-width="400">
      <v-card>
        <v-card-title class="text-center">
          <v-icon 
            start 
            :color="addLineType === 'premium' ? 'amber-darken-2' : 'blue-darken-1'"
          >
            {{ addLineType === 'premium' ? 'mdi-crown' : 'mdi-server' }}
          </v-icon>
          添加{{ addLineType === 'premium' ? '高级' : '普通' }}线路
        </v-card-title>
        
        <v-card-text>
          <v-text-field
            v-model="newLineName"
            label="线路名称"
            variant="outlined"
            density="compact"
            hide-details="auto"
            :error-messages="lineNameError"
            @keyup.enter="addLine"
            autofocus
          ></v-text-field>
        </v-card-text>
        
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn color="grey" variant="text" @click="closeAddDialog">取消</v-btn>
          <v-btn 
            :color="addLineType === 'premium' ? 'amber-darken-2' : 'blue-darken-1'"
            variant="flat"
            @click="addLine"
            :loading="addingLine"
          >
            添加
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    
    <!-- 删除确认对话框 -->
    <v-dialog v-model="deleteDialog" max-width="400">
      <v-card>
        <v-card-title class="text-center">
          <v-icon start color="red">mdi-delete</v-icon>
          确认删除
        </v-card-title>
        
        <v-card-text class="text-center">
          <p>确定要删除{{ deleteLineType === 'premium' ? '高级' : '普通' }}线路</p>
          <p class="font-weight-bold">「{{ deleteLineName }}」</p>
          <p class="text-caption text-grey">吗？此操作不可撤销。</p>
        </v-card-text>
        
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn color="grey" variant="text" @click="closeDeleteDialog">取消</v-btn>
          <v-btn 
            color="red"
            variant="flat"
            @click="deleteLine"
            :loading="deletingLine"
          >
            删除
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-dialog>
</template>

<script>
import { 
  getLinesConfig, 
  addNormalLine, 
  addPremiumLine, 
  deleteNormalLine, 
  deletePremiumLine 
} from '@/services/lineService';

export default {
  name: 'LineManagementDialog',
  data() {
    return {
      dialog: false,
      loading: false,
      error: null,
      normalLines: [],
      premiumLines: [],
      
      // 添加线路相关
      addDialog: false,
      addLineType: 'normal', // 'normal' | 'premium'
      newLineName: '',
      lineNameError: '',
      addingLine: false,
      
      // 删除线路相关
      deleteDialog: false,
      deleteLineType: 'normal',
      deleteLineName: '',
      deletingLine: false,
    }
  },
  methods: {
    async open() {
      this.dialog = true;
      await this.fetchLinesConfig();
    },
    
    close() {
      this.dialog = false;
      this.error = null;
    },
    
    async fetchLinesConfig() {
      this.loading = true;
      this.error = null;
      
      try {
        const response = await getLinesConfig();
        if (response) {
          this.normalLines = response.normal_lines || [];
          this.premiumLines = response.premium_lines || [];
        } else {
          this.error = response.message || '获取线路配置失败';
        }
      } catch (error) {
        this.error = error.response?.data?.message || '获取线路配置失败，请稍后再试';
        console.error('获取线路配置失败:', error);
      } finally {
        this.loading = false;
      }
    },
    
    openAddLineDialog(type) {
      this.addLineType = type;
      this.newLineName = '';
      this.lineNameError = '';
      this.addDialog = true;
    },
    
    closeAddDialog() {
      this.addDialog = false;
      this.newLineName = '';
      this.lineNameError = '';
    },
    
    validateLineName() {
      this.lineNameError = '';
      
      if (!this.newLineName.trim()) {
        this.lineNameError = '线路名称不能为空';
        return false;
      }
      
      // 检查是否与现有线路重复
      const allLines = [...this.normalLines, ...this.premiumLines];
      if (allLines.includes(this.newLineName.trim())) {
        this.lineNameError = '该线路名称已存在';
        return false;
      }
      
      return true;
    },
    
    async addLine() {
      if (!this.validateLineName()) {
        return;
      }
      
      this.addingLine = true;
      
      try {
        let response;
        const lineName = this.newLineName.trim();
        
        if (this.addLineType === 'premium') {
          response = await addPremiumLine(lineName);
        } else {
          response = await addNormalLine(lineName);
        }
        
        if (response.success) {
          this.showMessage(response.message || '线路添加成功');
          this.closeAddDialog();
          await this.fetchLinesConfig();
          this.$emit('lines-updated');
        } else {
          this.lineNameError = response.message || '添加线路失败';
        }
      } catch (error) {
        this.lineNameError = error.response?.data?.message || '添加线路失败，请稍后再试';
        console.error('添加线路失败:', error);
      } finally {
        this.addingLine = false;
      }
    },
    
    confirmDeleteLine(type, lineName) {
      this.deleteLineType = type;
      this.deleteLineName = lineName;
      this.deleteDialog = true;
    },
    
    closeDeleteDialog() {
      this.deleteDialog = false;
      this.deleteLineName = '';
    },
    
    async deleteLine() {
      this.deletingLine = true;
      
      try {
        let response;
        
        if (this.deleteLineType === 'premium') {
          response = await deletePremiumLine(this.deleteLineName);
        } else {
          response = await deleteNormalLine(this.deleteLineName);
        }
        
        if (response.success) {
          this.showMessage(response.message || '线路删除成功');
          this.closeDeleteDialog();
          await this.fetchLinesConfig();
          this.$emit('lines-updated');
        } else {
          this.showMessage(response.message || '删除线路失败', 'error');
        }
      } catch (error) {
        this.showMessage(error.response?.data?.message || '删除线路失败，请稍后再试', 'error');
        console.error('删除线路失败:', error);
      } finally {
        this.deletingLine = false;
      }
    },
    
    showMessage(message, type = 'success') {
      if (window.Telegram?.WebApp) {
        window.Telegram.WebApp.showPopup({
          title: type === 'error' ? '错误' : '成功',
          message: message
        });
      } else {
        alert(message);
      }
    }
  }
}
</script>

<style scoped>
/* 线路管理对话框响应式设计 */
.line-management-dialog {
  width: 100%;
  max-width: 800px;
}

/* 章节头部样式 */
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.header-info {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.add-btn {
  flex-shrink: 0;
}

/* 线路容器 */
.line-container {
  border-radius: 8px;
  background-color: #fafafa;
}

.line-chips-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-start;
}

/* 线路芯片样式 */
.line-chip {
  cursor: pointer;
  transition: all 0.2s ease;
  max-width: 100%;
  min-width: 120px;
  height: auto !important;
  padding: 4px 8px !important;
  border-radius: 6px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  font-weight: 500 !important;
}

.line-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}

/* 普通线路样式 */
.normal-line {
  background-color: #1565c0 !important;
  color: white !important;
  border: 1px solid #0d47a1 !important;
}

.normal-line:hover {
  background-color: #0d47a1 !important;
}

.normal-line .v-chip__close {
  color: white !important;
  opacity: 0.8;
}

.normal-line .v-chip__close:hover {
  opacity: 1 !important;
}

/* 高级线路样式 */
.premium-line {
  background-color: #ff8f00 !important;
  color: white !important;
  border: 1px solid #e65100 !important;
}

.premium-line:hover {
  background-color: #e65100 !important;
}

.premium-line .v-chip__close {
  color: white !important;
  opacity: 0.8;
}

.premium-line .v-chip__close:hover {
  opacity: 1 !important;
}

/* 线路文本样式 */
.line-text {
  display: block;
  width: 100%;
  word-break: break-all;
  overflow-wrap: break-word;
  line-height: 1.3;
  font-size: 0.875rem;
  font-weight: 500;
  text-align: left;
  max-width: 300px;
}

/* 响应式设计 */
@media (max-width: 600px) {
  .line-management-dialog {
    margin: 16px;
    max-width: calc(100vw - 32px);
  }
  
  .section-header {
    flex-direction: column;
    align-items: stretch;
  }
  
  .header-info {
    justify-content: center;
  }
  
  .add-btn {
    width: 100%;
  }
  
  .line-chip {
    min-width: 100px;
    max-width: calc(50% - 4px);
    font-size: 0.75rem;
  }
  
  .line-text {
    font-size: 0.75rem;
    max-width: 200px;
  }
}

@media (max-width: 400px) {
  .btn-text {
    display: none;
  }
  
  .line-chip {
    min-width: 80px;
    max-width: 100%;
    margin-bottom: 6px;
  }
  
  .line-text {
    font-size: 0.7rem;
    max-width: 150px;
  }
  
  .line-chips-container {
    gap: 6px;
  }
  
  .add-btn {
    min-width: 48px;
    padding: 0 12px;
  }
}

/* 深色主题适配 */
@media (prefers-color-scheme: dark) {
  .line-container {
    background-color: #303030;
  }
}
</style>
