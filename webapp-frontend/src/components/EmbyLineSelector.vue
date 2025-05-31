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
                    v-for="tag in lineInfo.tags.slice(0, 3)"
                    :key="tag"
                    size="x-small"
                    :color="getTagColor(tag)"
                    variant="outlined"
                    class="mr-1"
                  >
                    {{ tag }}
                  </v-chip>
                  <span v-if="lineInfo.tags.length > 3" class="text-caption text-grey">
                    +{{ lineInfo.tags.length - 3 }}
                  </span>
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
      // 根据标签类型返回不同的颜色
      const tagColors = {
        // 地区标签
        '香港': 'red-lighten-3',
        '新加坡': 'green-lighten-3',
        '日本': 'pink-lighten-3',
        '美国': 'blue-lighten-3',
        '德国': 'orange-lighten-3',
        '澳洲': 'teal-lighten-3',
        '英国': 'indigo-lighten-3',
        '加拿大': 'purple-lighten-3',
        
        // 性能标签
        '高级': 'amber-darken-2',
        '4K': 'deep-purple-lighten-3',
        '8K': 'deep-purple-darken-2',
        '高速': 'light-green-lighten-3',
        '稳定': 'blue-grey-lighten-3',
        '直连': 'cyan-lighten-3',
        'CDN': 'lime-lighten-3',
        '原生IP': 'brown-lighten-3',
        
        // 特殊标签
        '免费': 'green-darken-2',
        '免费高级': 'amber-lighten-3',
        '全球加速': 'deep-orange-lighten-3',
        '自动选择': 'grey-lighten-3',
        '智能切换': 'grey-lighten-2',
        '标准': 'grey-lighten-4'
      };
      
      return tagColors[tag] || 'grey-lighten-3';
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
  max-width: 280px;
}

.tags-container .v-chip {
  height: 18px !important;
  font-size: 10px !important;
  padding: 0 6px !important;
}
</style>
