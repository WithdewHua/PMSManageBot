<template>
  <div>
    <v-menu v-model="menu" :close-on-content-click="false" @update:model-value="onMenuToggle" origin="top end">
      <template v-slot:activator="{ props }">
        <v-chip
          :color="currentLine ? 'primary' : 'default'"
          v-bind="props"
          class="line-selector-chip"
          variant="outlined"
          @mouseenter="stopScrolling"
          @mouseleave="checkAndStartScrolling"
        >
          <div class="line-text-container" ref="textContainer">
            <span class="line-text" ref="lineText">{{ displayLine }}</span>
          </div>
          <v-icon end size="small">mdi-chevron-down</v-icon>
        </v-chip>
      </template>

      <v-card min-width="320" max-width="400">
        <v-list class="line-selector-list">
          <v-list-item 
            @click="selectLine('AUTO')" 
            :active="currentLine === 'AUTO'"
            :color="currentLine === 'AUTO' ? '#9333ea' : undefined"
          >
            <v-list-item-title>
              自动选择
              <v-icon v-if="currentLine === 'AUTO'" color="success" size="small" end>mdi-check</v-icon>
            </v-list-item-title>
          </v-list-item>
          
          <v-list-item 
            v-for="lineInfo in availableLines" 
            :key="lineInfo.name" 
            @click="selectLine(lineInfo.name)" 
            :active="currentLine === lineInfo.name"
            :color="currentLine === lineInfo.name ? '#9333ea' : undefined"
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
              <v-icon v-if="currentLine === lineInfo.name" color="success" size="small">mdi-check</v-icon>
            </v-list-item-title>
          </v-list-item>
          
          <v-divider></v-divider>
          
          <v-list-item>
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
    
    <!-- 加载中显示 -->
    <v-dialog v-model="loading" persistent max-width="300">
      <v-card>
        <v-card-text class="text-center py-4">
          <v-progress-circular indeterminate color="primary" class="mb-3"></v-progress-circular>
          <div>正在更新线路...</div>
        </v-card-text>
      </v-card>
    </v-dialog>
    
    <!-- 结果提示 -->
    <v-snackbar v-model="showSnackbar" :color="snackbarColor" :timeout="3000">
      {{ snackbarMessage }}
    </v-snackbar>
  </div>
</template>

<script>
import { bindEmbyLine, unbindEmbyLine, getAvailableEmbyLines } from '@/services/embyService';

export default {
  name: 'EmbyLineSelector',
  props: {
    currentValue: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      menu: false,
      loading: false,
      customLine: '',
      showSnackbar: false,
      snackbarMessage: '',
      snackbarColor: 'success',
      currentLine: this.currentValue || 'AUTO',
      availableLines: [],
      loadingLines: false,
      scrollAnimation: null
    }
  },
  computed: {
    displayLine() {
      // 在文本末尾添加额外空白，确保滚动时完全可见
      const text = this.currentLine || 'AUTO';
      return text + '      '; // 增加到6个空格的缓冲
    }
  },
  watch: {
    currentValue(newValue) {
      this.currentLine = newValue || 'AUTO';
      // 当外部值改变时，重新检查滚动
      this.$nextTick(() => {
        this.checkAndStartScrolling();
      });
    },
    
    displayLine() {
      // 当显示的线路改变时，重新检查是否需要滚动
      this.$nextTick(() => {
        this.checkAndStartScrolling();
      });
    },
    
    menu(isOpen) {
      // 菜单关闭时重新检查滚动
      if (!isOpen) {
        this.$nextTick(() => {
          this.checkAndStartScrolling();
        });
      }
    }
  },
  mounted() {
    this.$nextTick(() => {
      this.checkAndStartScrolling();
    });
  },
  beforeUnmount() {
    this.stopScrolling();
  },
  methods: {
    async onMenuToggle(isOpen) {
      if (isOpen && !this.loadingLines) {
        await this.loadAvailableLines();
      }
    },
    
    async loadAvailableLines() {
      this.loadingLines = true;
      try {
        this.availableLines = await getAvailableEmbyLines();
      } catch (error) {
        console.error('获取 Emby 线路列表失败:', error);
        this.showMessage('获取线路列表失败', 'error');
      } finally {
        this.loadingLines = false;
      }
    },
    
    async selectLine(line) {
      if (line === this.currentLine) {
        this.menu = false;
        return;
      }
      
      this.menu = false;
      this.loading = true;
      
      try {
        let result;
        if (line === 'AUTO') {
          result = await unbindEmbyLine();
        } else {
          result = await bindEmbyLine(line);
        }
        
        if (result.success) {
          this.currentLine = line;
          this.$emit('line-changed', line);
          this.showMessage(result.message, 'success');
        } else {
          this.showMessage(result.message || '操作失败', 'error');
        }
      } catch (error) {
        console.error('线路操作失败:', error);
        this.showMessage('操作失败，请稍后再试', 'error');
      } finally {
        this.loading = false;
        this.customLine = '';
      }
    },
    
    async selectCustomLine() {
      if (!this.customLine.trim()) {
        this.showMessage('请输入线路名称', 'warning');
        return;
      }
      
      await this.selectLine(this.customLine.trim());
    },
    
    showMessage(message, type = 'success') {
      this.snackbarMessage = message;
      this.snackbarColor = type;
      this.showSnackbar = true;
    },
    
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
    
    checkAndStartScrolling() {
      if (!this.$refs.textContainer || !this.$refs.lineText) {
        return;
      }
      
      const container = this.$refs.textContainer;
      const text = this.$refs.lineText;
      
      // 检查文本是否超出容器宽度
      if (text.scrollWidth > container.clientWidth) {
        this.startScrolling();
      } else {
        this.stopScrolling();
      }
    },
    
    startScrolling() {
      this.stopScrolling(); // 先停止之前的动画
      
      const text = this.$refs.lineText;
      if (!text) return;
      
      const maxScroll = text.scrollWidth - text.parentElement.clientWidth;
      let currentScroll = 0;
      let direction = 1; // 1 表示向右滚动，-1 表示向左滚动
      
      const scroll = () => {
        currentScroll += direction * 0.5; // 滚动速度
        
        if (currentScroll >= maxScroll) {
          direction = -1;
          currentScroll = maxScroll;
        } else if (currentScroll <= 0) {
          direction = 1;
          currentScroll = 0;
        }
        
        text.style.transform = `translateX(-${currentScroll}px)`;
        this.scrollAnimation = requestAnimationFrame(scroll);
      };
      
      // 延迟开始滚动
      setTimeout(() => {
        if (!this.menu) { // 只有在菜单关闭时才开始滚动
          this.scrollAnimation = requestAnimationFrame(scroll);
        }
      }, 1000);
    },
    
    stopScrolling() {
      if (this.scrollAnimation) {
        cancelAnimationFrame(this.scrollAnimation);
        this.scrollAnimation = null;
      }
      
      // 重置文本位置
      if (this.$refs.lineText) {
        this.$refs.lineText.style.transform = 'translateX(0)';
      }
    }
  }
}
</script>

<style scoped>
.line-selector-chip {
  min-width: 80px;
  max-width: 200px;
  font-size: 0.875rem;
  height: 32px;
}

.line-text-container {
  overflow: hidden;
  white-space: nowrap;
  flex: 1;
  position: relative;
  max-width: 150px;
}

.line-text {
  display: inline-block;
  transition: transform 0.3s ease;
  white-space: nowrap;
}

.line-selector-list {
  max-height: 60vh;
  overflow-y: auto;
}

/* 自定义滚动条样式 */
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

/* 对于Firefox浏览器 */
.line-selector-list {
  scrollbar-width: thin;
  scrollbar-color: #c1c1c1 #f1f1f1;
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

/* 自定义滚动条样式 */
.line-selector-list::-webkit-scrollbar {
  width: 4px;
}

.line-selector-list::-webkit-scrollbar-track {
  background: transparent;
}

.line-selector-list::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 2px;
}

.line-selector-list::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.3);
}
</style>
