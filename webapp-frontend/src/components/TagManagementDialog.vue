<template>
  <v-dialog v-model="dialog" max-width="800" persistent class="responsive-dialog">
    <v-card>
      <v-card-title class="text-center bg-blue-darken-2 text-white">
        <v-icon start>mdi-tag-multiple</v-icon>
        线路标签管理
      </v-card-title>
      
      <v-card-text class="pa-4">
        <div v-if="loading" class="text-center py-8">
          <v-progress-circular indeterminate color="primary"></v-progress-circular>
          <div class="mt-3">加载中...</div>
        </div>
        
        <div v-else>
          <!-- 标签管理说明 -->
          <v-alert type="info" density="compact" class="mb-4">
            <v-icon start>mdi-information-outline</v-icon>
            为每个线路添加标签，用户在选择线路时可以看到相应的标签信息
          </v-alert>
          
          <!-- 线路标签列表 -->
          <div v-for="line in linesList" :key="line" class="mb-4">
            <v-card variant="outlined" class="pa-3">
              <!-- 线路标题部分 - 支持响应式布局 -->
              <div class="line-header mb-3">
                <div class="line-info">
                  <v-icon 
                    size="small" 
                    :color="isPremiumLine(line) ? 'amber-darken-2' : 'blue-darken-1'" 
                    class="mr-2"
                  >
                    {{ isPremiumLine(line) ? 'mdi-crown' : 'mdi-server' }}
                  </v-icon>
                  <span class="font-weight-medium line-name">{{ line }}</span>
                  <v-chip 
                    v-if="isPremiumLine(line)" 
                    size="x-small" 
                    color="amber-lighten-3" 
                    class="ml-2 premium-chip"
                  >
                    高级线路
                  </v-chip>
                </div>
                <v-btn
                  color="red"
                  variant="text"
                  size="small"
                  @click="clearLineTags(line)"
                  :disabled="!lineTags[line] || lineTags[line].length === 0"
                  class="clear-btn"
                >
                  <v-icon size="small">mdi-delete</v-icon>
                  <span class="clear-btn-text">清空标签</span>
                </v-btn>
              </div>
              
              <!-- 当前标签显示 -->
              <div class="mb-3">
                <div class="text-caption text-grey mb-2">当前标签：</div>
                <div v-if="lineTags[line] && lineTags[line].length > 0" class="d-flex flex-wrap gap-1">
                  <v-chip
                    v-for="tag in lineTags[line]"
                    :key="tag"
                    size="small"
                    color="blue-darken-1"
                    variant="flat"
                    closable
                    @click:close="removeTag(line, tag)"
                    class="tag-chip-current"
                  >
                    {{ tag }}
                  </v-chip>
                </div>
                <div v-else class="text-grey text-caption">暂无标签</div>
              </div>
              
              <!-- 添加标签 -->
              <div class="d-flex gap-2">
                <v-text-field
                  v-model="newTags[line]"
                  label="添加新标签"
                  placeholder="输入标签名称，按回车或点击添加"
                  density="compact"
                  variant="outlined"
                  hide-details
                  @keyup.enter="addTag(line)"
                  class="flex-grow-1"
                ></v-text-field>
                <v-btn
                  color="primary"
                  size="small"
                  @click="addTag(line)"
                  :disabled="!newTags[line] || !newTags[line].trim()"
                >
                  <v-icon size="small">mdi-plus</v-icon>
                  添加
                </v-btn>
              </div>
              
              <!-- 常用标签快捷添加 -->
              <div class="mt-3">
                <div class="text-caption text-grey mb-2">常用标签：</div>
                <div class="d-flex flex-wrap gap-1">
                  <v-chip
                    v-for="commonTag in commonTags"
                    :key="commonTag"
                    size="small"
                    color="green-darken-1"
                    variant="flat"
                    @click="addCommonTag(line, commonTag)"
                    :disabled="lineTags[line] && lineTags[line].includes(commonTag)"
                    class="cursor-pointer tag-chip-common"
                  >
                    {{ commonTag }}
                  </v-chip>
                </div>
              </div>
            </v-card>
          </div>
        </div>
      </v-card-text>
      
      <v-card-actions class="pa-4">
        <v-spacer></v-spacer>
        <v-btn color="grey" variant="text" @click="close">
          取消
        </v-btn>
        <v-btn color="primary" @click="saveAllTags" :loading="saving">
          保存所有更改
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { getAllLineTags, setLineTags, deleteLineTags } from '@/services/adminTagService.js'

export default {
  name: 'TagManagementDialog',
  data() {
    return {
      dialog: false,
      loading: false,
      saving: false,
      lineTags: {}, // 存储每个线路的标签
      newTags: {}, // 存储每个线路正在输入的新标签
      linesList: [], // 所有线路列表
      originalTags: {}, // 保存原始标签数据，用于检查是否有更改
      // 常用标签
      commonTags: [
        '香港', '台湾', '日本', '新加坡', '美国', '韩国', "4837", "CMI", "GIA", "移动", "联通", "电信", "三网优化"
      ]
    }
  },
  computed: {
    premiumLines() {
      // 这里需要从父组件或API获取高级线路列表
      return this.$parent?.adminSettings?.emby_premium_lines || []
    }
  },
  methods: {
    async open() {
      this.dialog = true
      await this.loadLineTags()
    },
    
    close() {
      this.dialog = false
      this.reset()
    },
    
    reset() {
      this.lineTags = {}
      this.newTags = {}
      this.linesList = []
      this.originalTags = {}
      this.loading = false
      this.saving = false
    },
    
    async loadLineTags() {
      try {
        this.loading = true
        console.log('开始加载线路标签...')
        const response = await getAllLineTags()
        console.log('API响应:', response)
        
        // 检查响应格式
        if (!response || typeof response !== 'object') {
          throw new Error(`无效的响应格式: ${JSON.stringify(response)}`)
        }
        
        // 兼容不同的响应格式
        let linesData = response.lines || response
        console.log('线路数据:', linesData)
        
        if (!linesData || typeof linesData !== 'object') {
          throw new Error(`无效的线路数据格式: ${JSON.stringify(linesData)}`)
        }
        
        this.lineTags = { ...linesData }
        this.originalTags = JSON.parse(JSON.stringify(linesData)) // 深拷贝
        this.linesList = Object.keys(linesData).sort()
        
        console.log('解析的线路列表:', this.linesList)
        console.log('解析的标签数据:', this.lineTags)
        
        // 初始化newTags对象
        this.linesList.forEach(line => {
          this.newTags[line] = ''
        })
        
        console.log('标签加载成功')
        
      } catch (error) {
        console.error('加载线路标签失败:', error)
        console.error('错误详情:', {
          message: error.message,
          response: error.response,
          stack: error.stack
        })
        this.showMessage(`加载线路标签失败: ${error.message}`, 'error')
      } finally {
        this.loading = false
      }
    },
    
    isPremiumLine(line) {
      return this.premiumLines.includes(line)
    },
    
    addTag(line) {
      const newTag = this.newTags[line]?.trim()
      if (!newTag) return
      
      if (!this.lineTags[line]) {
        this.lineTags[line] = []
      }
      
      if (!this.lineTags[line].includes(newTag)) {
        this.lineTags[line].push(newTag)
        this.newTags[line] = ''
      } else {
        this.showMessage('该标签已存在', 'warning')
      }
    },
    
    addCommonTag(line, tag) {
      if (!this.lineTags[line]) {
        this.lineTags[line] = []
      }
      
      if (!this.lineTags[line].includes(tag)) {
        this.lineTags[line].push(tag)
      }
    },
    
    removeTag(line, tag) {
      if (this.lineTags[line]) {
        const index = this.lineTags[line].indexOf(tag)
        if (index > -1) {
          this.lineTags[line].splice(index, 1)
        }
      }
    },
    
    async clearLineTags(line) {
      try {
        const confirmed = await this.confirmAction(
          `确认清空线路 ${line} 的所有标签？`,
          '清空标签'
        )
        
        if (confirmed) {
          await deleteLineTags(line)
          this.lineTags[line] = []
          this.showMessage(`线路 ${line} 的标签已清空`)
        }
      } catch (error) {
        console.error('清空标签失败:', error)
        this.showMessage('清空标签失败', 'error')
      }
    },
    
    async saveAllTags() {
      try {
        this.saving = true
        
        // 只保存有更改的线路
        const promises = []
        for (const line of this.linesList) {
          const currentTags = this.lineTags[line] || []
          const originalTags = this.originalTags[line] || []
          
          // 检查是否有更改
          if (JSON.stringify(currentTags.sort()) !== JSON.stringify(originalTags.sort())) {
            promises.push(setLineTags(line, currentTags))
          }
        }
        
        if (promises.length === 0) {
          this.showMessage('没有需要保存的更改')
          this.close()
          return
        }
        
        await Promise.all(promises)
        this.showMessage(`成功保存 ${promises.length} 个线路的标签设置`)
        this.close()
        
        // 通知父组件刷新
        this.$emit('tags-updated')
        
      } catch (error) {
        console.error('保存标签失败:', error)
        this.showMessage('保存标签失败', 'error')
      } finally {
        this.saving = false
      }
    },
    
    async confirmAction(message, title = '确认操作') {
      return new Promise((resolve) => {
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.showPopup({
            title: title,
            message: message,
            buttons: [
              { id: 'cancel', type: 'cancel' },
              { id: 'confirm', type: 'destructive', text: '确认' }
            ]
          }, (buttonId) => {
            resolve(buttonId === 'confirm')
          })
        } else {
          resolve(confirm(message))
        }
      })
    },
    
    showMessage(message, type = 'success') {
      if (window.Telegram?.WebApp) {
        window.Telegram.WebApp.showPopup({
          title: type === 'error' ? '错误' : type === 'warning' ? '警告' : '成功',
          message: message
        })
      } else {
        alert(message)
      }
    }
  }
}
</script>

<style scoped>
.cursor-pointer {
  cursor: pointer;
}

.gap-1 > * {
  margin-right: 4px;
  margin-bottom: 4px;
}

.gap-2 > * {
  margin-right: 8px;
}

.tag-chip-current {
  color: white !important;
  font-weight: 500 !important;
}

.tag-chip-common {
  color: white !important;
  font-weight: 500 !important;
}

.tag-chip-common:disabled {
  opacity: 0.6 !important;
  background-color: grey !important;
}

/* 响应式线路标题布局 */
.line-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.line-info {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0; /* 允许文本缩收 */
  flex-wrap: wrap;
  gap: 4px;
}

.line-name {
  word-break: break-all;
  overflow-wrap: break-word;
  min-width: 0;
  flex: 1;
  line-height: 1.2;
}

.premium-chip {
  flex-shrink: 0;
}

.clear-btn {
  flex-shrink: 0;
  min-width: auto;
}

/* 响应式对话框 */
.responsive-dialog {
  width: 95vw;
  max-width: 800px;
}

/* 标签输入区域优化 */
.d-flex.gap-2 {
  display: flex;
  gap: 8px;
  align-items: stretch;
}

/* 小屏幕适配 */
@media (max-width: 600px) {
  .line-header {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  
  .line-info {
    justify-content: flex-start;
  }
  
  .clear-btn {
    align-self: flex-end;
  }
  
  .clear-btn-text {
    display: none;
  }
}

/* 超小屏幕适配 */
@media (max-width: 400px) {
  .line-info {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
  
  .premium-chip {
    margin-left: 0 !important;
  }
  
  /* 对话框宽度优化 */
  :deep(.v-dialog) {
    margin: 12px;
  }
  
  /* 标签输入区域优化 */
  .gap-2 {
    flex-direction: column;
    gap: 8px;
  }
  
  .gap-2 > * {
    margin-right: 0;
    width: 100%;
  }
}
</style>
