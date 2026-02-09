<template>
  <v-dialog v-model="dialog" max-width="900" scrollable class="line-management-dialog">
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
          <!-- 说明 -->
          <v-alert type="info" density="compact" class="mb-4">
            点击线路卡片可以编辑标签，点击删除按钮可删除线路
          </v-alert>
          
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
              <div v-else class="line-cards-container">
                <v-card
                  v-for="line in normalLines"
                  :key="line"
                  class="line-card normal-line-card"
                  variant="outlined"
                  @click="openEditTagsDialog(line, 'normal')"
                >
                  <div class="line-card-header">
                    <v-icon size="small" color="blue-darken-1" class="mr-2">mdi-server</v-icon>
                    <span class="line-name" :title="line">{{ line }}</span>
                    <v-btn
                      icon
                      size="x-small"
                      variant="text"
                      color="red"
                      class="delete-btn"
                      @click.stop="confirmDeleteLine('normal', line)"
                    >
                      <v-icon size="small">mdi-close</v-icon>
                    </v-btn>
                  </div>
                  <div class="line-card-tags">
                    <template v-if="lineTags[line] && lineTags[line].length > 0">
                      <v-chip
                        v-for="tag in lineTags[line].slice(0, 3)"
                        :key="tag"
                        size="x-small"
                        color="blue-darken-1"
                        variant="flat"
                        class="mr-1 mb-1 tag-chip"
                      >
                        {{ tag }}
                      </v-chip>
                      <v-chip
                        v-if="lineTags[line].length > 3"
                        size="x-small"
                        color="grey"
                        variant="outlined"
                        class="mr-1 mb-1"
                      >
                        +{{ lineTags[line].length - 3 }}
                      </v-chip>
                    </template>
                    <span v-else class="text-caption text-grey">无标签</span>
                  </div>
                </v-card>
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
              <div v-else class="line-cards-container">
                <v-card
                  v-for="line in premiumLines"
                  :key="line"
                  class="line-card premium-line-card"
                  variant="outlined"
                  @click="openEditTagsDialog(line, 'premium')"
                >
                  <div class="line-card-header">
                    <v-icon size="small" color="amber-darken-2" class="mr-2">mdi-crown</v-icon>
                    <span class="line-name" :title="line">{{ line }}</span>
                    <v-btn
                      icon
                      size="x-small"
                      variant="text"
                      color="red"
                      class="delete-btn"
                      @click.stop="confirmDeleteLine('premium', line)"
                    >
                      <v-icon size="small">mdi-close</v-icon>
                    </v-btn>
                  </div>
                  <div class="line-card-tags">
                    <template v-if="lineTags[line] && lineTags[line].length > 0">
                      <v-chip
                        v-for="tag in lineTags[line].slice(0, 3)"
                        :key="tag"
                        size="x-small"
                        color="amber-darken-2"
                        variant="flat"
                        class="mr-1 mb-1 tag-chip"
                      >
                        {{ tag }}
                      </v-chip>
                      <v-chip
                        v-if="lineTags[line].length > 3"
                        size="x-small"
                        color="grey"
                        variant="outlined"
                        class="mr-1 mb-1"
                      >
                        +{{ lineTags[line].length - 3 }}
                      </v-chip>
                    </template>
                    <span v-else class="text-caption text-grey">无标签</span>
                  </div>
                </v-card>
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
    <v-dialog v-model="addDialog" max-width="500">
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
            class="mb-4"
            autofocus
          ></v-text-field>
          
          <!-- 标签设置 -->
          <div class="mb-3">
            <div class="text-subtitle-2 mb-2">
              <v-icon size="small" class="mr-1">mdi-tag-multiple</v-icon>
              设置标签（可选）
            </div>
            
            <!-- 已添加的标签 -->
            <div v-if="newLineTags.length > 0" class="mb-2">
              <v-chip
                v-for="(tag, index) in newLineTags"
                :key="index"
                size="small"
                :color="addLineType === 'premium' ? 'amber-darken-2' : 'blue-darken-1'"
                variant="flat"
                closable
                @click:close="removeNewLineTag(index)"
                class="mr-1 mb-1"
              >
                {{ tag }}
              </v-chip>
            </div>
            
            <!-- 添加新标签 -->
            <div class="d-flex gap-2">
              <v-text-field
                v-model="newTagInput"
                label="添加标签"
                placeholder="输入标签名称"
                variant="outlined"
                density="compact"
                hide-details
                @keyup.enter="addNewLineTag"
                class="flex-grow-1"
              ></v-text-field>
              <v-btn
                :color="addLineType === 'premium' ? 'amber-darken-2' : 'blue-darken-1'"
                variant="outlined"
                size="small"
                @click="addNewLineTag"
                :disabled="!newTagInput.trim()"
              >
                <v-icon size="small">mdi-plus</v-icon>
              </v-btn>
            </div>
            
            <!-- 常用标签 -->
            <div class="mt-3">
              <div class="text-caption text-grey mb-2">常用标签：</div>
              <div class="d-flex flex-wrap gap-1">
                <v-chip
                  v-for="tag in commonTags"
                  :key="tag"
                  size="x-small"
                  color="green-darken-1"
                  variant="flat"
                  @click="addCommonTagToNewLine(tag)"
                  :disabled="newLineTags.includes(tag)"
                  class="cursor-pointer tag-chip-common"
                >
                  {{ tag }}
                </v-chip>
              </div>
            </div>
          </div>
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
    
    <!-- 编辑标签对话框 -->
    <v-dialog v-model="editTagsDialog" max-width="500">
      <v-card>
        <v-card-title class="text-center">
          <v-icon 
            start 
            :color="editLineType === 'premium' ? 'amber-darken-2' : 'blue-darken-1'"
          >
            {{ editLineType === 'premium' ? 'mdi-crown' : 'mdi-server' }}
          </v-icon>
          编辑标签 - {{ editLineName }}
        </v-card-title>
        
        <v-card-text>
          <!-- 当前标签 -->
          <div class="mb-3">
            <div class="text-subtitle-2 mb-2">当前标签：</div>
            <div v-if="editingTags.length > 0" class="d-flex flex-wrap gap-1">
              <v-chip
                v-for="(tag, index) in editingTags"
                :key="index"
                size="small"
                :color="editLineType === 'premium' ? 'amber-darken-2' : 'blue-darken-1'"
                variant="flat"
                closable
                @click:close="removeEditingTag(index)"
                class="mr-1 mb-1"
              >
                {{ tag }}
              </v-chip>
            </div>
            <div v-else class="text-grey text-caption">暂无标签</div>
          </div>
          
          <!-- 添加新标签 -->
          <div class="d-flex gap-2 mb-3">
            <v-text-field
              v-model="editTagInput"
              label="添加新标签"
              placeholder="输入标签名称，按回车添加"
              variant="outlined"
              density="compact"
              hide-details
              @keyup.enter="addEditingTag"
              class="flex-grow-1"
            ></v-text-field>
            <v-btn
              :color="editLineType === 'premium' ? 'amber-darken-2' : 'blue-darken-1'"
              variant="outlined"
              size="small"
              @click="addEditingTag"
              :disabled="!editTagInput.trim()"
            >
              <v-icon size="small">mdi-plus</v-icon>
            </v-btn>
          </div>
          
          <!-- 常用标签 -->
          <div>
            <div class="text-caption text-grey mb-2">常用标签：</div>
            <div class="d-flex flex-wrap gap-1">
              <v-chip
                v-for="tag in commonTags"
                :key="tag"
                size="x-small"
                color="green-darken-1"
                variant="flat"
                @click="addCommonTagToEditing(tag)"
                :disabled="editingTags.includes(tag)"
                class="cursor-pointer tag-chip-common"
              >
                {{ tag }}
              </v-chip>
            </div>
          </div>
        </v-card-text>
        
        <v-card-actions>
          <v-btn color="red" variant="text" @click="clearEditingTags">
            <v-icon start size="small">mdi-delete</v-icon>
            清空标签
          </v-btn>
          <v-spacer></v-spacer>
          <v-btn color="grey" variant="text" @click="closeEditTagsDialog">取消</v-btn>
          <v-btn 
            :color="editLineType === 'premium' ? 'amber-darken-2' : 'blue-darken-1'"
            variant="flat"
            @click="saveEditingTags"
            :loading="savingTags"
          >
            保存
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
          <p class="text-caption text-grey">吗？此操作不可撤销，相关标签也会被删除。</p>
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
import { getAllLineTags, setLineTags, deleteLineTags } from '@/services/adminTagService.js';

export default {
  name: 'LineManagementDialog',
  data() {
    return {
      dialog: false,
      loading: false,
      error: null,
      normalLines: [],
      premiumLines: [],
      lineTags: {}, // 存储所有线路的标签
      
      // 常用标签
      commonTags: [
        '香港', '台湾', '日本', '新加坡', '美国', '韩国', '4837', 'CMI', 'GIA', '移动', '联通', '电信', '三网优化'
      ],
      
      // 添加线路相关
      addDialog: false,
      addLineType: 'normal', // 'normal' | 'premium'
      newLineName: '',
      lineNameError: '',
      addingLine: false,
      newLineTags: [], // 新线路的标签
      newTagInput: '', // 标签输入
      
      // 编辑标签相关
      editTagsDialog: false,
      editLineName: '',
      editLineType: 'normal',
      editingTags: [],
      editTagInput: '',
      savingTags: false,
      
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
      await this.fetchData();
    },
    
    close() {
      this.dialog = false;
      this.error = null;
    },
    
    async fetchData() {
      this.loading = true;
      this.error = null;
      
      try {
        // 并行获取线路配置和标签
        const [linesResponse, tagsResponse] = await Promise.all([
          getLinesConfig(),
          getAllLineTags()
        ]);
        
        if (linesResponse) {
          this.normalLines = linesResponse.normal_lines || [];
          this.premiumLines = linesResponse.premium_lines || [];
        } else {
          this.error = '获取线路配置失败';
        }
        
        // 处理标签数据
        if (tagsResponse) {
          this.lineTags = tagsResponse.lines || tagsResponse || {};
        }
        
      } catch (error) {
        this.error = error.response?.data?.message || '获取数据失败，请稍后再试';
        console.error('获取数据失败:', error);
      } finally {
        this.loading = false;
      }
    },
    
    // === 添加线路相关方法 ===
    openAddLineDialog(type) {
      this.addLineType = type;
      this.newLineName = '';
      this.lineNameError = '';
      this.newLineTags = [];
      this.newTagInput = '';
      this.addDialog = true;
    },
    
    closeAddDialog() {
      this.addDialog = false;
      this.newLineName = '';
      this.lineNameError = '';
      this.newLineTags = [];
      this.newTagInput = '';
    },
    
    addNewLineTag() {
      const tag = this.newTagInput.trim();
      if (tag && !this.newLineTags.includes(tag)) {
        this.newLineTags.push(tag);
        this.newTagInput = '';
      }
    },
    
    removeNewLineTag(index) {
      this.newLineTags.splice(index, 1);
    },
    
    addCommonTagToNewLine(tag) {
      if (!this.newLineTags.includes(tag)) {
        this.newLineTags.push(tag);
      }
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
          // 如果有标签，则设置标签
          if (this.newLineTags.length > 0) {
            try {
              await setLineTags(lineName, this.newLineTags);
            } catch (tagError) {
              console.error('设置标签失败:', tagError);
              // 线路添加成功但标签设置失败，仍然继续
            }
          }
          
          this.showMessage(response.message || '线路添加成功');
          this.closeAddDialog();
          await this.fetchData();
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
    
    // === 编辑标签相关方法 ===
    openEditTagsDialog(lineName, lineType) {
      this.editLineName = lineName;
      this.editLineType = lineType;
      this.editingTags = [...(this.lineTags[lineName] || [])];
      this.editTagInput = '';
      this.editTagsDialog = true;
    },
    
    closeEditTagsDialog() {
      this.editTagsDialog = false;
      this.editLineName = '';
      this.editingTags = [];
      this.editTagInput = '';
    },
    
    addEditingTag() {
      const tag = this.editTagInput.trim();
      if (tag && !this.editingTags.includes(tag)) {
        this.editingTags.push(tag);
        this.editTagInput = '';
      }
    },
    
    removeEditingTag(index) {
      this.editingTags.splice(index, 1);
    },
    
    addCommonTagToEditing(tag) {
      if (!this.editingTags.includes(tag)) {
        this.editingTags.push(tag);
      }
    },
    
    clearEditingTags() {
      this.editingTags = [];
    },
    
    async saveEditingTags() {
      this.savingTags = true;
      
      try {
        await setLineTags(this.editLineName, this.editingTags);
        this.showMessage('标签保存成功');
        
        // 更新本地数据
        this.lineTags[this.editLineName] = [...this.editingTags];
        
        this.closeEditTagsDialog();
        this.$emit('tags-updated');
      } catch (error) {
        this.showMessage(error.response?.data?.message || '保存标签失败', 'error');
        console.error('保存标签失败:', error);
      } finally {
        this.savingTags = false;
      }
    },
    
    // === 删除线路相关方法 ===
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
          // 同时删除相关标签
          try {
            await deleteLineTags(this.deleteLineName);
          } catch (tagError) {
            console.error('删除标签失败:', tagError);
            // 忽略标签删除失败
          }
          
          this.showMessage(response.message || '线路删除成功');
          this.closeDeleteDialog();
          await this.fetchData();
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
  max-width: 900px;
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

/* 线路卡片容器 */
.line-cards-container {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

/* 线路卡片样式 */
.line-card {
  cursor: pointer;
  transition: all 0.2s ease;
  padding: 12px;
  border-radius: 8px;
  position: relative;
}

.line-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.line-card-header {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.line-card .line-name {
  flex: 1;
  font-weight: 500;
  word-break: break-all;
  overflow-wrap: break-word;
  font-size: 0.875rem;
}

.line-card .delete-btn {
  opacity: 0;
  transition: opacity 0.2s ease;
}

.line-card:hover .delete-btn {
  opacity: 1;
}

.line-card-tags {
  display: flex;
  flex-wrap: wrap;
  min-height: 24px;
}

/* 普通线路卡片样式 */
.normal-line-card {
  border-left: 3px solid #1565c0 !important;
  background-color: rgba(21, 101, 192, 0.05);
}

.normal-line-card:hover {
  background-color: rgba(21, 101, 192, 0.1);
}

/* 高级线路卡片样式 */
.premium-line-card {
  border-left: 3px solid #ff8f00 !important;
  background-color: rgba(255, 143, 0, 0.05);
}

.premium-line-card:hover {
  background-color: rgba(255, 143, 0, 0.1);
}

/* 标签样式 */
.tag-chip {
  color: white !important;
  font-weight: 500 !important;
}

.tag-chip-common {
  color: white !important;
  font-weight: 500 !important;
  cursor: pointer;
}

.tag-chip-common:disabled {
  opacity: 0.6 !important;
  background-color: grey !important;
  cursor: not-allowed;
}

.cursor-pointer {
  cursor: pointer;
}

.gap-1 > * {
  margin-right: 4px;
  margin-bottom: 4px;
}

.gap-2 {
  gap: 8px;
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
  
  .line-cards-container {
    grid-template-columns: 1fr;
  }
  
  .line-card .delete-btn {
    opacity: 1;
  }
}

@media (max-width: 400px) {
  .btn-text {
    display: none;
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
  
  .normal-line-card {
    background-color: rgba(21, 101, 192, 0.15);
  }
  
  .normal-line-card:hover {
    background-color: rgba(21, 101, 192, 0.25);
  }
  
  .premium-line-card {
    background-color: rgba(255, 143, 0, 0.15);
  }
  
  .premium-line-card:hover {
    background-color: rgba(255, 143, 0, 0.25);
  }
}
</style>
