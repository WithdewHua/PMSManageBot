<template>
  <!-- 加载中 -->
  <div v-if="loading" class="loading-container">
    <div class="loading-content">
      <v-progress-circular indeterminate color="primary" size="50" width="4"></v-progress-circular>
      <div class="loading-text">加载{{ label ? `${label}` : '' }}数据中...</div>
    </div>
  </div>

  <!-- 加载失败 -->
  <div v-else-if="error" class="error-container">
    <v-alert type="error" class="error-alert" rounded="lg" elevation="4">{{ error }}</v-alert>
    <v-btn color="primary" @click="$emit('retry')" class="mt-3">
      重试
    </v-btn>
  </div>

  <!-- 加载成功但无数据 -->
  <div v-else-if="empty" class="text-center my-5">
    <v-list-item>
      <v-list-item-title class="text-grey">暂无{{ label ? `${label}` : '' }}数据</v-list-item-title>
    </v-list-item>
  </div>

  <!-- 加载成功且有数据 -->
  <slot v-else></slot>
</template>

<script>
export default {
  name: 'RankingStateBlock',
  props: {
    // 是否正在获取数据
    loading: {
      type: Boolean,
      default: false
    },
    // 失败原因，为空表示未失败
    error: {
      type: String,
      default: null
    },
    // 是否获取成功但结果为空
    empty: {
      type: Boolean,
      default: false
    },
    // 展示名称，用于标示正在获取或无数据的对象，如 'PLEX'
    label: {
      type: String,
      default: ''
    }
  },
  emits: ['retry', 'content-rendered'],
  mounted() {
    // 挂载时 slot 内容可能已就绪（数据来自本次访问的缓存）
    this.$emit('content-rendered')
  },
  updated() {
    // 状态分支切换（如加载中 → 内容）后，slot 的 DOM 才真正生成。
    // 父组件需要此时机来测量文本溢出等依赖真实布局的效果。
    this.$emit('content-rendered')
  }
}
</script>

<style scoped>
/* 加载状态样式 */
.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 200px;
  margin: 40px 0;
}

.loading-content {
  text-align: center;
  padding: 30px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
}

.loading-text {
  margin-top: 16px;
  font-size: 16px;
  color: #666;
  font-weight: 500;
}

/* 错误状态样式 */
.error-container {
  text-align: center;
  margin: 40px 0;
}

.error-alert {
  background: rgba(255, 255, 255, 0.95) !important;
  backdrop-filter: blur(10px);
  border: none !important;
}
</style>
