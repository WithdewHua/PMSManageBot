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

      <v-card min-width="200">
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
            v-for="line in availableLines" 
            :key="line" 
            @click="selectLine(line)" 
            :active="currentLine === line"
            :color="currentLine === line ? '#9333ea' : undefined"
          >
            <v-list-item-title>
              {{ line }}
              <v-icon v-if="currentLine === line" color="success" size="small" end>mdi-check</v-icon>
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
    
    async selectLine(line) {
      if (this.currentLine === line) {
        this.menu = false;
        return;
      }
      
      this.menu = false;
      this.loading = true;
      
      try {
        if (line === 'AUTO') {
          // 解绑线路
          await unbindEmbyLine();
          this.currentLine = 'AUTO';
          this.showSuccessMessage('已切换到自动选择线路');
        } else {
          // 绑定线路
          await bindEmbyLine(line);
          this.currentLine = line;
          this.showSuccessMessage(`已切换到${line}线路`);
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
</style>
