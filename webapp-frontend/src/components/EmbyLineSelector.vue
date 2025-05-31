<template>
  <div>
    <v-menu v-model="menu" :close-on-content-click="false" @update:model-value="onMenuToggle">
      <template v-slot:activator="{ props }">
        <v-chip
          :color="currentLine ? 'primary' : 'default'"
          v-bind="props"
          class="line-selector-chip"
          variant="outlined"
        >
          {{ displayLine }}
          <v-icon end size="small">mdi-chevron-down</v-icon>
        </v-chip>
      </template>

      <v-card min-width="320" max-width="400">
        <v-list>
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
      loadingLines: false
    }
  },
  computed: {
    displayLine() {
      return this.currentLine || 'AUTO';
    }
  },
  watch: {
    currentValue(newValue) {
      this.currentLine = newValue || 'AUTO';
    }
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
    }
  }
}
</script>

<style scoped>
.line-selector-chip {
  cursor: pointer;
}

.line-item {
  min-height: 56px;
}

.line-name-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.line-name {
  font-weight: 500;
  font-size: 14px;
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
</style>
