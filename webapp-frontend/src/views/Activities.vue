<template>
  <div class="activities-container">
    <div class="content-wrapper">
      <div class="empty-state">
        <v-icon class="empty-icon" size="80" color="grey lighten-1">
          mdi-calendar-blank
        </v-icon>
        <h2 class="empty-title">暂无活动</h2>
        <p class="empty-description">敬请期待</p>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'Activities',
  data() {
    return {
      // 页面数据
    }
  },
  mounted() {
    // 页面加载时的逻辑
  }
}
</script>

<style scoped>
.activities-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
  padding-bottom: 80px; /* 为底部导航栏留出空间 */
}

.content-wrapper {
  max-width: 600px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 120px);
}

.empty-state {
  text-align: center;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  padding: 60px 40px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
}

.empty-icon {
  margin-bottom: 20px;
  opacity: 0.7;
}

.empty-title {
  font-size: 24px;
  font-weight: 600;
  color: #333;
  margin-bottom: 10px;
}

.empty-description {
  font-size: 16px;
  color: #666;
  margin: 0;
}

/* 深色模式样式 */
:deep(.v-theme--dark) .empty-state {
  background: rgba(30, 30, 30, 0.95) !important;
}

:deep(.v-theme--dark) .empty-title {
  color: #ffffff !important;
}

:deep(.v-theme--dark) .empty-description {
  color: #e0e0e0 !important;
}

/* 深色模式下的图标 */
:deep(.v-theme--dark) .empty-icon {
  color: #bdbdbd !important;
}

/* 响应式设计 */
@media (max-width: 480px) {
  .activities-container {
    padding: 10px;
  }
  
  .empty-state {
    padding: 40px 20px;
  }
  
  .empty-title {
    font-size: 20px;
  }
  
  .empty-description {
    font-size: 14px;
  }
}
</style>