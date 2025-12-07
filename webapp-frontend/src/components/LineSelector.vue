<template>
  <div>
    <v-select
      :model-value="currentValue"
      :items="lineItems"
      item-title="name"
      item-value="name"
      :label="label"
      :placeholder="currentValue === null || currentValue === undefined ? 'AUTO (自动选择)' : ''"
      outlined
      dense
      clearable
      :disabled="loadingLines"
      :loading="loadingLines"
      @update:model-value="onLineChange"
      @click="loadLinesIfNeeded"
    >
      <template v-slot:selection="{ item }">
        <v-chip small :color="item.raw.is_premium ? 'purple' : 'blue'" dark>
          {{ item.raw.name }}
        </v-chip>
      </template>
      <template v-slot:item="{ item, props }">
        <v-list-item v-bind="props">
          <template v-slot:title>
            <div class="d-flex align-center justify-space-between">
              <div>
                {{ item.raw.name }}
                <v-chip
                  v-if="item.raw.is_premium"
                  x-small
                  color="purple"
                  dark
                  class="ml-2"
                >
                  Premium
                </v-chip>
              </div>
            </div>
          </template>
          <template v-slot:subtitle v-if="item.raw.tags && item.raw.tags.length">
            <v-chip
              v-for="tag in item.raw.tags"
              :key="tag"
              x-small
              outlined
              class="mr-1"
            >
              {{ tag }}
            </v-chip>
          </template>
        </v-list-item>
      </template>
      <template v-slot:prepend-item>
        <v-list-item @click="selectAuto">
          <v-list-item-title>
            <v-chip small color="grey" dark>AUTO</v-chip>
            <span class="ml-2">自动选择</span>
          </v-list-item-title>
        </v-list-item>
        <v-divider class="my-2"></v-divider>
      </template>
    </v-select>
  </div>
</template>

<script>
import { getAvailableLines } from '@/services/userLineService';

export default {
  name: 'LineSelector',
  props: {
    currentValue: {
      type: String,
      default: null
    },
    service: {
      type: String,
      required: true,
      validator: (value) => ['plex', 'emby'].includes(value)
    },
    label: {
      type: String,
      default: '选择线路'
    }
  },
  data() {
    return {
      availableLines: [],
      loadingLines: false,
      linesLoaded: false
    }
  },
  computed: {
    lineItems() {
      // 添加 AUTO 选项和可用线路
      return this.availableLines;
    }
  },
  methods: {
    async loadLinesIfNeeded() {
      if (!this.linesLoaded && !this.loadingLines) {
        await this.loadAvailableLines();
      }
    },
    
    async loadAvailableLines() {
      if (this.loadingLines) return;
      
      this.loadingLines = true;
      try {
        const lines = await getAvailableLines(this.service);
        this.availableLines = lines || [];
        this.linesLoaded = true;
        
        if (this.availableLines.length === 0) {
          console.warn('未获取到任何可用线路');
        }
      } catch (error) {
        console.error('加载可用线路失败:', error);
        this.availableLines = [];
      } finally {
        this.loadingLines = false;
      }
    },
    
    onLineChange(value) {
      // 只触发事件，不执行实际的绑定操作
      this.$emit('update:currentValue', value);
      this.$emit('line-selected', value);
    },
    
    selectAuto() {
      // 选择 AUTO 时传递 null，表示不设置默认线路（真正的自动选择）
      this.onLineChange(null);
    }
  }
};
</script>

<style scoped>
.v-select {
  min-width: 200px;
}
</style>
