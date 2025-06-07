<template>
  <div>
    <div class="custom-bottom-nav">
      <!-- 左侧第一个按钮 -->
      <div class="nav-item" :class="{ active: activeTab === 'user-info' }" @click="navigateTo('user-info')">
        <v-icon class="nav-icon">mdi-account</v-icon>
        <div class="nav-label">个人信息</div>
      </div>
      
      <!-- 左侧第二个按钮 -->
      <div class="nav-item" :class="{ active: activeTab === 'activities' }" @click="navigateTo('activities')">
        <v-icon class="nav-icon">mdi-calendar-clock</v-icon>
        <div class="nav-label">活动</div>
      </div>
      
      <!-- 中间按钮 -->
      <div class="center-btn-wrapper">
        <button class="center-btn" @click="toggleMenu">
          <v-icon color="white" size="24">{{ showActionMenu ? 'mdi-close' : 'mdi-plus' }}</v-icon>
        </button>
      </div>
      
      <!-- 右侧第一个按钮 -->
      <div class="nav-item" :class="{ active: activeTab === 'management' }" @click="navigateTo('management')">
        <v-icon class="nav-icon">mdi-cog</v-icon>
        <div class="nav-label">管理</div>
      </div>
      
      <!-- 右侧第二个按钮 -->
      <div class="nav-item" :class="{ active: activeTab === 'rankings' }" @click="navigateTo('rankings')">
        <v-icon class="nav-icon">mdi-trophy</v-icon>
        <div class="nav-label">排行榜</div>
      </div>
      
      <!-- 菜单层 -->
      <transition name="fade">
        <div v-if="showActionMenu" class="action-menu-overlay" @click="closeMenu"></div>
      </transition>
      
      <!-- 菜单内容 - 改为列表样式并使用滑动动画 -->
      <transition name="slide-up">
        <div v-if="showActionMenu" class="action-menu">
          <div class="menu-grid">
            <div class="menu-item" @click="openRedeemCodeDialog()">
              <div class="menu-icon-wrapper">
                <v-icon color="white" size="18">mdi-ticket-confirmation</v-icon>
              </div>
              <span>兑换邀请码</span>
            </div>

            <div class="menu-item" @click="openInviteCodeDialog">
              <div class="menu-icon-wrapper">
                <v-icon color="white" size="18">mdi-ticket-account</v-icon>
              </div>
              <span>生成邀请码</span>
            </div>
            
            <div class="menu-item" @click="openBindAccountDialog()">
              <div class="menu-icon-wrapper">
                <v-icon color="white" size="18">mdi-link-variant</v-icon>
              </div>
              <span>绑定媒体账户</span>
            </div>
            
            <div class="menu-item" @click="openBindLineDialog()">
              <div class="menu-icon-wrapper">
                <v-icon color="white" size="18">mdi-road</v-icon>
              </div>
              <span>绑定线路</span>
            </div>
          </div>
        </div>
      </transition>
    </div>
    
    <!-- 使用邀请码对话框组件 -->
    <invite-code-dialog ref="inviteCodeDialog" />
    
    <!-- 使用兑换码对话框组件 -->
    <redeem-code-dialog ref="redeemCodeDialog" />
    
    <!-- 绑定账户对话框组件 -->
    <bind-account-dialog ref="bindAccountDialog" />
    
    <!-- 绑定线路对话框组件 -->
    <bind-line-dialog ref="bindLineDialog" @line-bound="handleLineBound" />
  </div>
</template>

<script>
// 导入邀请码对话框组件
import InviteCodeDialog from './InviteCodeDialog.vue';
// 导入兑换对话框组件
import RedeemCodeDialog from './RedeemCodeDialog.vue';
// 导入绑定账户对话框组件
import BindAccountDialog from './BindAccountDialog.vue';
// 导入绑定线路对话框组件
import BindLineDialog from './BindLineDialog.vue';

export default {
  name: 'BottomMenu',
  components: {
    InviteCodeDialog,
    RedeemCodeDialog,
    BindAccountDialog,
    BindLineDialog
  },
  props: {
    // 当前激活的标签，从父组件传入
    currentActiveTab: {
      type: String,
      default: 'user-info'
    }
  },
  data() {
    return {
      // 内部状态
      activeTab: this.currentActiveTab,
      showActionMenu: false
    }
  },
  watch: {
    // 监听父组件传入的当前标签更新
    currentActiveTab(newValue) {
      this.activeTab = newValue;
      // 关闭菜单（如果打开）
      if (this.showActionMenu) {
        this.showActionMenu = false;
      }
    }
  },
  methods: {
    navigateTo(route) {
      // 通知父组件进行导航
      this.$emit('navigate', route);
      this.activeTab = route;
    },
    toggleMenu() {
      this.showActionMenu = !this.showActionMenu;
    },
    closeMenu() {
      this.showActionMenu = false;
    },
    handleAction(action) {
      // 处理菜单动作
      this.showActionMenu = false;
      
      // 根据Telegram WebApp调用相应的命令
      if (window.Telegram && window.Telegram.WebApp) {
        // 通知Telegram Bot执行相应命令
        window.Telegram.WebApp.sendData(JSON.stringify({
          action: action
        }));
      } else {
        console.log('非Telegram环境，动作：', action);
        // 开发环境下显示一个提示
        alert(`将执行命令: /${action}`);
      }
    },
    
    // 打开邀请码对话框
    openInviteCodeDialog() {
      this.showActionMenu = false;
      this.$refs.inviteCodeDialog.open();
    },
    
    // 打开兑换码对话框
    openRedeemCodeDialog(type = null) {
      this.showActionMenu = false;
      this.$refs.redeemCodeDialog.open(type);
    },
    
    // 打开绑定账户对话框
    openBindAccountDialog(type = null) {
      this.showActionMenu = false;
      this.$refs.bindAccountDialog.open(type);
    },
    
    // 打开绑定线路对话框
    openBindLineDialog(type = null) {
      this.showActionMenu = false;
      this.$refs.bindLineDialog.open(type);
    },
    
    // 处理线路绑定完成事件
    handleLineBound(data) {
      // 通知父组件线路绑定成功
      this.$emit('line-bound', data);
    }
  }
}
</script>

<style scoped>
/* 重新设计的底部导航 */
.custom-bottom-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 60px;
  display: flex;
  align-items: center;
  background-color: white;
  box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.08);
  padding: 0 20px;
  z-index: 100;
}

/* 导航项目样式 */
.nav-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 4px;
  cursor: pointer;
  transition: all 0.2s;
  margin-top: 2px;
  min-width: 0;
  width: 60px;
  position: relative;
}

/* 左侧第一个按钮 */
.nav-item:nth-child(1) {
  position: absolute;
  left: 15%;
  transform: translateX(-50%);
}

/* 左侧第二个按钮 */
.nav-item:nth-child(2) {
  position: absolute;
  left: 35%;
  transform: translateX(-50%);
}

/* 右侧第一个按钮 */
.nav-item:nth-child(4) {
  position: absolute;
  right: 35%;
  transform: translateX(50%);
}

/* 右侧第二个按钮 */
.nav-item:nth-child(5) {
  position: absolute;
  right: 15%;
  transform: translateX(50%);
}

.nav-icon {
  color: #757575;
  font-size: 22px;
  margin-bottom: 2px;
  transition: color 0.2s;
}

.nav-label {
  color: #757575;
  font-size: 9px;
  transition: color 0.2s;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 50px;
  line-height: 1.2;
}

/* 活跃状态 */
.nav-item.active .nav-icon,
.nav-item.active .nav-label {
  color: #9333ea;
}

/* 中间按钮包装器 */
.center-btn-wrapper {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  top: -20px; /* 增加上移距离，使按钮更突出 */
}

/* 中间按钮样式 */
.center-btn {
  width: 54px; /* 增大按钮尺寸 */
  height: 54px;
  border-radius: 27px;
  background-color: #9333ea;
  border: none;
  outline: none;
  box-shadow: 0 4px 12px rgba(147, 51, 234, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.center-btn:active {
  transform: scale(0.95);
  box-shadow: 0 2px 8px rgba(147, 51, 234, 0.3);
}

/* 菜单遮罩层 - 半透明背景，不覆盖底栏和中间按钮 */
.action-menu-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 60px; /* 不覆盖底栏 */
  background-color: rgba(0, 0, 0, 0.5); /* 半透明黑色遮罩 */
  z-index: 90;
  /* 添加中心挖孔效果，不遮挡中间按钮 */
  mask-image: radial-gradient(
    circle at 50% calc(100% + 15px), /* 位置调整为底部中央偏上 */
    transparent 35px, /* 透明圆半径设置为比按钮大一点，考虑阴影效果 */
    black 36px /* 从这里开始是黑色遮罩部分，形成锐利的边缘 */
  );
  -webkit-mask-image: radial-gradient(
    circle at 50% calc(100% + 15px),
    transparent 35px,
    black 36px
  );
  mask-size: 100% 100%;
  -webkit-mask-size: 100% 100%;
  mask-repeat: no-repeat;
  -webkit-mask-repeat: no-repeat;
}

/* 菜单容器 - 列表风格 */
.action-menu {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 60px; /* 与底栏高度匹配 */
  background-color: transparent; /* 完全透明背景 */
  z-index: 95;
  padding: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* 菜单网格改为列表 */
.menu-grid {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 300px; /* 限制菜单最大宽度 */
  margin-bottom: 15px; /* 与底栏保持一定距离 */
}

/* 菜单项目 - 透明背景 */
.menu-item {
  display: flex;
  flex-direction: row; /* 横向排列 */
  align-items: center;
  gap: 15px;
  cursor: pointer;
  background-color: transparent; /* 透明背景 */
  margin-bottom: 10px; /* 项目间距 */
  border-radius: 12px; /* 保持圆角 */
  padding: 12px 15px;
  box-shadow: none; /* 移除阴影 */
  transition: transform 0.2s;
}

.menu-item:active {
  transform: scale(0.98);
}

/* 菜单图标包装器 */
.menu-icon-wrapper {
  width: 40px; /* 适当增加图标尺寸 */
  height: 40px;
  min-width: 40px; /* 防止收缩 */
  border-radius: 20px;
  background-color: #9333ea;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(147, 51, 234, 0.3);
}

/* 菜单项目文本 */
.menu-item span {
  color: white; /* 更改为白色文本 */
  font-size: 15px; /* 稍微增大字体 */
  font-weight: 500;
  text-align: left; /* 左对齐 */
  flex: 1;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2); /* 添加文字阴影增强可读性 */
}

/* 动画效果 */
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

.slide-up-enter-active, .slide-up-leave-active {
  transition: transform 0.4s cubic-bezier(0.25, 0.8, 0.5, 1); /* 缓动函数调整为更平滑 */
}

.slide-up-enter-from, .slide-up-leave-to {
  transform: translateY(30px); /* 只需要小幅度的平移效果 */
}

.error-message {
  color: #ff5252;
  font-size: 14px;
}
</style>
