<template>
  <v-app>
    <v-main>
      <router-view />
    </v-main>
    <v-bottom-navigation v-model="activeTab" color="primary" grow>
      <v-btn value="user-info">
        <v-icon>mdi-account</v-icon>
        个人信息
      </v-btn>
      <v-btn value="rankings">
        <v-icon>mdi-trophy</v-icon>
        排行榜
      </v-btn>
    </v-bottom-navigation>
  </v-app>
</template>

<script>
export default {
  name: 'App',
  data() {
    return {
      activeTab: 'user-info'
    }
  },
  watch: {
    activeTab(val) {
      if (this.$route.name !== val) {
        this.$router.push({ name: val })
      }
    },
    '$route'(to) {
      // 监听路由变化，更新底部导航
      if (to.name) {
        this.activeTab = to.name;
      }
    }
  },
  mounted() {
    // 初始化时强制导航到正确路由
    const routeName = this.$route.name
    if (routeName) {
      this.activeTab = routeName
    } else {
      // 如果当前没有路由名称（在根路径），强制导航到user-info
      this.$nextTick(() => {
        this.$router.replace({ name: 'user-info' });
      });
    }
  }
}
</script>

<style>
html, body {
  overflow-x: hidden;
  margin: 0;
  padding: 0;
  height: 100%;
  width: 100%;
}

html {
  overflow-y: auto;
}

.theme--dark {
  background-color: #212121;
  color: #ffffff;
}

.theme--light {
  background-color: #ffffff;
  color: #212121;
}

/* 自定义滑动条样式 */
::-webkit-scrollbar {
  width: 5px; /* 设置滑动条宽度 */
}

::-webkit-scrollbar-track {
  background: transparent; /* 滑动条轨道背景 */
}

::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.2); /* 滑动条颜色 */
  border-radius: 3px; /* 滑动条圆角 */
}

/* 修复滑动条可能引起的边缘问题 */
::-webkit-scrollbar-corner {
  background: transparent;
}

/* 深色模式下滑动条颜色 */
.theme--dark ::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
}

/* 确保没有右侧边距 */
.v-application {
  max-width: 100% !important;
  overflow-x: hidden !important;
}

.v-main {
  padding-right: 0 !important;
}

/* 修改选中tab的颜色为 #9333ea */
.v-bottom-navigation .v-btn--active {
  color: #9333ea !important;
}

.v-bottom-navigation .v-btn--active .v-icon {
  color: #9333ea !important;
}

/* 修改排行榜内部标签栏选中的颜色 */
.v-tab--selected {
  color: #9333ea !important;
}

.v-tab--selected .v-icon {
  color: #9333ea !important;
}

/* 修改标签滑动条颜色 */
.v-tabs-slider {
  background-color: #9333ea !important;
}

/* 确保底部导航栏延伸到边缘 */
.v-bottom-navigation {
  width: 100% !important;
  margin: 0 !important;
  left: 0 !important;
  right: 0 !important;
}
</style>