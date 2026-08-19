<template>
  <v-app>
    <v-main>
      <router-view />
    </v-main>
    <!-- 使用底部菜单组件 -->
    <bottom-menu
      ref="bottomMenu"
      :current-active-tab="activeTab"
      @navigate="navigateTo"
    />
    <!-- 礼包开屏汇总提醒 -->
    <gift-pack-prompt-dialog ref="giftPackPrompt" @go-claim="openGiftPackCenter" />
  </v-app>
</template>

<script>
// 导入底部菜单组件
import BottomMenu from './components/BottomMenu.vue';
// 导入礼包开屏提醒组件
import GiftPackPromptDialog from './components/GiftPackPromptDialog.vue';
import { promptCheckGiftPacks } from './services/giftPackService';

export default {
  name: 'App',
  components: {
    BottomMenu,
    GiftPackPromptDialog
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
    this.checkGiftPackPrompt()
  },
  methods: {
    navigateTo(route) {
      if (this.$route.name !== route) {
        this.$router.push({ name: route });
      }
      this.activeTab = route;
    },

    /**
     * 礼包开屏提醒判定。
     *
     * 这是一个独立请求，不与 getUserInfo / systemStatus 合并——礼包是运营活动，
     * 与用户信息、系统状态的生命周期无关，合并会让三者互相牵连。
     * 后端在返回时已完成提醒记账；返回空数组表示不弹窗。
     */
    async checkGiftPackPrompt() {
      try {
        const res = await promptCheckGiftPacks()
        const packs = res.data?.packs || []
        if (packs.length) {
          this.$refs.giftPackPrompt?.open(packs)
        }
      } catch (e) {
        // 提醒是锦上添花，失败时静默跳过，不打断启动流程
        console.warn('礼包提醒判定失败:', e)
      }
    },

    // 「前往领取」→ 关闭提醒弹窗（组件内已关闭）→ 打开礼包中心
    openGiftPackCenter() {
      this.$refs.bottomMenu?.openGiftPackDialog()
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
</style>