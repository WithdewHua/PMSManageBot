<template>
  <v-dialog v-model="dialog" max-width="800" scrollable>
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
            <div class="d-flex justify-space-between align-center mb-3">
              <div class="d-flex align-center">
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
                @click="openAddLineDialog('normal')"
              >
                <v-icon start size="small">mdi-plus</v-icon>
                添加普通线路
              </v-btn>
            </div>
            
            <v-card variant="outlined" class="pa-3">
              <div v-if="normalLines.length === 0" class="text-center text-grey py-4">
                暂无普通线路
              </div>
              <div v-else>
                <v-chip
                  v-for="line in normalLines"
                  :key="line"
                  size="small"
                  color="blue-lighten-3"
                  class="mr-2 mb-2"
                  closable
                  @click:close="confirmDeleteLine('normal', line)"
                >
                  {{ line }}
                </v-chip>
              </div>
            </v-card>
          </div>
          
          <!-- 高级线路管理 -->
          <div class="mb-4">
            <div class="d-flex justify-space-between align-center mb-3">
              <div class="d-flex align-center">
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
                @click="openAddLineDialog('premium')"
              >
                <v-icon start size="small">mdi-plus</v-icon>
                添加高级线路
              </v-btn>
            </div>
            
            <v-card variant="outlined" class="pa-3">
              <div v-if="premiumLines.length === 0" class="text-center text-grey py-4">
                暂无高级线路
              </div>
              <div v-else>
                <v-chip
                  v-for="line in premiumLines"
                  :key="line"
                  size="small"
                  color="amber-lighten-3"
                  class="mr-2 mb-2"
                  closable
                  @click:close="confirmDeleteLine('premium', line)"
                >
                  {{ line }}
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
  getEmbyLinesConfig, 
  addNormalLine, 
  addPremiumLine, 
  deleteNormalLine, 
  deletePremiumLine 
} from '@/services/adminLineService';

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
        const response = await getEmbyLinesConfig();
        if (response.success) {
          this.normalLines = response.data.normal_lines || [];
          this.premiumLines = response.data.premium_lines || [];
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
.v-chip {
  cursor: pointer;
  transition: transform 0.2s;
}

.v-chip:hover {
  transform: translateY(-1px);
}
</style>
