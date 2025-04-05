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
      this.$router.push({ name: val })
    }
  },
  mounted() {
    // 根据当前路由设置活动标签
    const routeName = this.$route.name
    if (routeName) {
      this.activeTab = routeName
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
</style>