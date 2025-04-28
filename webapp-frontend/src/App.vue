<template>
  <v-app>
    <v-main>
      <router-view />
    </v-main>
    <!-- 使用底部菜单组件 -->
    <bottom-menu 
      :current-active-tab="activeTab"
      @navigate="navigateTo" 
    />
  </v-app>
</template>

<script>
// 导入底部菜单组件
import BottomMenu from './components/BottomMenu.vue';

export default {
  name: 'App',
  components: {
    BottomMenu
  },
  data() {
    return {
      activeTab: 'user-info'
    }
  },
  watch: {
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
  },
  methods: {
    navigateTo(route) {
      if (this.$route.name !== route) {
        this.$router.push({ name: route });
      }
      this.activeTab = route;
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
  padding-bottom: 75px !important; /* 调整底部间距，与新底栏高度匹配 */
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

/* 全局样式 */
:root {
  --bottom-menu-height: 56px;
}

/* QQ风格的等级图标样式 */
.level-icon {
  margin-right: 2px !important;
  transform: scale(1.1);
}

.star-icon {
  color: #ffd700 !important; /* 明亮的金色星星 */
  filter: drop-shadow(0 0 1px rgba(255, 215, 0, 0.7));
}

.moon-icon {
  color: #5b9bd5 !important; /* 明亮的蓝色月亮 */
  filter: drop-shadow(0 0 1px rgba(91, 155, 213, 0.7));
}

.sun-icon {
  color: #ff9933 !important; /* 明亮的橙色太阳 */
  filter: drop-shadow(0 0 1px rgba(255, 153, 51, 0.7));
}

.crown-icon {
  color: #ffcc00 !important; /* 明亮的金色皇冠 */
  filter: drop-shadow(0 0 2px rgba(255, 204, 0, 0.8));
  transform: scale(1.2);
}

.level-icons-container {
  display: inline-flex !important;
  align-items: center;
  padding: 1px 4px;
  background-color: rgba(0,0,0,0.03);
  border-radius: 10px;
  margin-left: 5px;
}

[class*="theme--dark"] .level-icons-container {
  background-color: rgba(255,255,255,0.05);
}
</style>