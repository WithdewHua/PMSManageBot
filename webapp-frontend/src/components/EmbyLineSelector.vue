<template>
  <div>
    <v-menu v-model="menu" :close-on-content-click="false" @update:model-value="onMenuToggle">
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
    // 组件挂载后检查是否需要滚动
    this.$nextTick(() => {
      // 多次尝试，确保在各种情况下都能正确检测
      setTimeout(() => this.checkAndStartScrolling(), 100);
      setTimeout(() => this.checkAndStartScrolling(), 500);
      setTimeout(() => this.checkAndStartScrolling(), 1000);
    });
  },
  
  updated() {
    // 组件更新后也检查滚动
    this.$nextTick(() => {
      this.checkAndStartScrolling();
    });
  },
  
  beforeUnmount() {
    // 组件销毁前清除动画
    this.stopScrolling();
  },
  
  methods: {
    onMenuToggle(isOpen) {
      if (isOpen) {
        this.fetchAvailableLines();
      }
    },
    
    async fetchAvailableLines() {
      this.loadingLines = true;
      try {
        const lines = await getAvailableEmbyLines();
        this.availableLines = lines;
      } catch (error) {
        console.error('获取线路列表失败:', error);
        this.showErrorMessage('获取可用线路列表失败');
      } finally {
        this.loadingLines = false;
      }
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
    
    async selectLine(line) {
      if (this.currentLine === line) {
        this.menu = false;
        return;
      }
      
      this.menu = false;
      this.loading = true;
      
      try {
        let response;
        
        if (line === 'AUTO') {
          // 解绑线路
          response = await unbindEmbyLine();
          if (response.success) {
            this.currentLine = 'AUTO';
            this.showSuccessMessage(response.message || '已切换到自动选择线路');
          } else {
            this.showErrorMessage(response.message || '切换线路失败');
            return;
          }
        } else {
          // 绑定线路
          response = await bindEmbyLine(line);
          if (response.success) {
            this.currentLine = line;
            this.showSuccessMessage(response.message || `已切换到${line}线路`);
          } else {
            this.showErrorMessage(response.message || '切换线路失败');
            return;
          }
        }
        
        // 通知父组件更新
        this.$emit('update:modelValue', this.currentLine === 'AUTO' ? null : this.currentLine);
        this.$emit('line-changed', this.currentLine === 'AUTO' ? null : this.currentLine);
        
        // 线路更改后重新检查滚动
        this.$nextTick(() => {
          this.checkAndStartScrolling();
        });
      } catch (error) {
        console.error('更新线路失败:', error);
        this.showErrorMessage(error.response?.data?.message || '更新线路失败，请稍后再试');
      } finally {
        this.loading = false;
      }
    },
    
    selectCustomLine() {
      if (this.customLine && this.customLine.trim()) {
        this.selectLine(this.customLine.trim());
        this.customLine = '';
      }
    },
    
    showSuccessMessage(message) {
      this.snackbarMessage = message;
      this.snackbarColor = 'success';
      this.showSnackbar = true;
    },
    
    showErrorMessage(message) {
      this.snackbarMessage = message;
      this.snackbarColor = 'error';
      this.showSnackbar = true;
    },
    
    // 检查是否需要滚动并开始滚动动画
    checkAndStartScrolling() {
      // 先停止之前的滚动
      this.stopScrolling();
      
      // 使用 nextTick 确保 DOM 已经更新
      this.$nextTick(() => {
        const container = this.$refs.textContainer;
        const text = this.$refs.lineText;
        
        if (!container || !text) {
          return;
        }
        
        // 重置滚动位置
        container.scrollLeft = 0;
        
        // 使用 ResizeObserver 监听元素大小变化（如果支持）
        if (window.ResizeObserver) {
          const observer = new ResizeObserver(() => {
            this.performScrollCheck();
          });
          observer.observe(container);
          observer.observe(text);
          
          // 初始检查
          setTimeout(() => {
            this.performScrollCheck();
            observer.disconnect(); // 检查完后断开观察
          }, 100);
        } else {
          // 降级方案：多次检查
          setTimeout(() => this.performScrollCheck(), 50);
          setTimeout(() => this.performScrollCheck(), 200);
          setTimeout(() => this.performScrollCheck(), 500);
        }
      });
    },
    
    // 执行实际的滚动检查
    performScrollCheck() {
      const container = this.$refs.textContainer;
      const text = this.$refs.lineText;
      
      if (!container || !text) {
        return;
      }
      
      // 强制重新计算布局
      container.offsetHeight;
      text.offsetHeight;
      
      const containerWidth = container.clientWidth;
      const textWidth = text.scrollWidth;
      
      // 如果容器还没有渲染完成，稍后再试
      if (containerWidth === 0) {
        setTimeout(() => this.performScrollCheck(), 100);
        return;
      }
      
      // 检查文本是否需要滚动（增加一些容差）
      const tolerance = 5; // 5px的容差
      if (textWidth > (containerWidth + tolerance)) {
        // 延迟开始滚动，让用户有时间阅读
        setTimeout(() => this.startScrolling(), 1000); // 增加延迟到1秒
      }
    },
    
    // 开始滚动动画
    startScrolling() {
      const container = this.$refs.textContainer;
      const text = this.$refs.lineText;
      
      if (!container || !text) {
        return;
      }
      
      // 强制重新计算布局
      container.offsetHeight;
      text.offsetHeight;
      
      const containerWidth = container.clientWidth;
      const textScrollWidth = text.scrollWidth;
      
      // 计算实际需要的箭头空间
      const chipElement = container.closest('.v-chip');
      const chipPadding = chipElement ? parseInt(window.getComputedStyle(chipElement).paddingRight, 10) || 16 : 16;
      const arrowWidth = 24; // mdi 图标的宽度
      const extraBuffer = 20; // 额外安全边距
      
      // 动态计算缓冲区大小，确保箭头完全可见
      const buffer = chipPadding + arrowWidth + extraBuffer;
      const maxScroll = Math.max(0, textScrollWidth - containerWidth + buffer);
      
      // 添加调试信息（开发时可用）
      if (process.env.NODE_ENV === 'development') {
        console.log('Scroll debug:', {
          containerWidth,
          textScrollWidth,
          chipPadding,
          arrowWidth,
          extraBuffer,
          buffer,
          maxScroll,
          displayLine: this.displayLine
        });
      }
      
      if (maxScroll <= 0) {
        return;
      }
      
      const scrollSpeed = 40; // 稍微降低滚动速度，更容易阅读
      const pauseDuration = 2000; // 增加停留时间
      
      let currentScroll = 0;
      let direction = 1; // 1 向右滚动，-1 向左滚动
      let lastTime = performance.now();
      let isPaused = false;
      
      const animate = (currentTime) => {
        if (this.scrollAnimation === null) return;
        
        if (isPaused) {
          this.scrollAnimation = requestAnimationFrame(animate);
          return;
        }
        
        const deltaTime = (currentTime - lastTime) / 1000;
        lastTime = currentTime;
        
        currentScroll += direction * scrollSpeed * deltaTime;
        
        // 边界检查和方向切换
        if (direction === 1 && currentScroll >= maxScroll) {
          currentScroll = maxScroll;
          container.scrollLeft = currentScroll;
          
          // 验证滚动是否足够：检查文本右边缘是否在容器可视区域内
          const textRightEdge = text.offsetLeft + text.offsetWidth;
          const containerRightEdge = container.scrollLeft + container.clientWidth;
          
          // 如果文本还没有完全显示，增加一些额外的滚动
          if (textRightEdge > containerRightEdge) {
            const additionalScroll = textRightEdge - containerRightEdge + 10; // 额外10px边距
            container.scrollLeft = Math.min(container.scrollLeft + additionalScroll, text.scrollWidth - container.clientWidth);
          }
          
          direction = -1;
          isPaused = true;
          
          setTimeout(() => {
            if (this.scrollAnimation !== null) {
              isPaused = false;
              lastTime = performance.now();
            }
          }, pauseDuration);
        } else if (direction === -1 && currentScroll <= 0) {
          currentScroll = 0;
          container.scrollLeft = 0;
          direction = 1;
          isPaused = true;
          
          setTimeout(() => {
            if (this.scrollAnimation !== null) {
              isPaused = false;
              lastTime = performance.now();
            }
          }, pauseDuration);
        } else {
          container.scrollLeft = currentScroll;
        }
        
        this.scrollAnimation = requestAnimationFrame(animate);
      };
      
      // 立即开始滚动动画
      this.scrollAnimation = requestAnimationFrame(animate);
    },
    
    // 停止滚动动画
    stopScrolling() {
      if (this.scrollAnimation !== null) {
        cancelAnimationFrame(this.scrollAnimation);
        this.scrollAnimation = null;
      }
    }
  }
}
</script>

<style scoped>
.line-selector-chip {
  cursor: pointer;
  max-width: 100%;
  min-width: 80px;
}

.line-text-container {
  flex: 1;
  overflow: hidden;
  white-space: nowrap;
  position: relative;
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE and Edge */
  min-width: 0; /* 确保可以收缩 */
  height: 20px; /* 固定高度避免布局抖动 */
  display: flex;
  align-items: center;
  max-width: calc(100% - 32px); /* 为箭头预留精确空间：16px图标 + 16px边距 */
}

.line-text-container::-webkit-scrollbar {
  display: none; /* Chrome, Safari and Opera */
}

.line-text {
  font-size: 14px;
  line-height: 1.2;
  white-space: nowrap;
  word-break: keep-all;
  user-select: none; /* 防止选择文本影响滚动 */
  flex-shrink: 0; /* 防止文本被压缩 */
  display: inline-block;
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

/* 小屏幕优化 */
@media (max-width: 600px) {
  .line-selector-chip {
    max-width: 100%;
    min-width: 70px;
  }
  
  .line-text {
    font-size: 12px;
  }
  
  .line-selector-list {
    max-height: 65vh;
  }
  
  .tags-container {
    max-width: 250px;
  }
  
  :deep(.v-card) {
    max-width: 90vw !important;
    min-width: 280px !important;
  }
}

@media (max-width: 400px) {
  .line-selector-chip {
    max-width: 100%;
    min-width: 60px;
  }
  
  .line-text {
    font-size: 11px;
  }
  
  .line-selector-list {
    max-height: 70vh;
  }
  
  .line-name {
    font-size: 13px;
  }
  
  .tags-container {
    max-width: 200px;
  }
  
  .tags-container .v-chip {
    height: 16px !important;
    font-size: 9px !important;
    padding: 0 4px !important;
  }
}

/* 针对手机纵向屏幕的特殊优化 */
@media screen and (max-width: 480px) and (orientation: portrait) {
  .line-selector-list {
    max-height: min(75vh, 500px);
  }
  
  :deep(.v-card) {
    max-width: 95vw !important;
    min-width: 250px !important;
  }
}

/* 针对手机横向屏幕的优化 */
@media screen and (max-height: 600px) and (orientation: landscape) {
  .line-selector-list {
    max-height: 50vh;
  }
}
</style>
