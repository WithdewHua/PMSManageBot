<template>
  <div class="user-info-container">
    <div class="content-wrapper">
      <div class="user-info-header">
        <h1 class="page-title">FunMedia 用户中心</h1>
        <p class="page-subtitle">账户信息与服务管理</p>
      </div>
      
      <v-container class="transparent-container">
      <div v-if="loading" class="loading-container">
        <div class="loading-content">
          <v-progress-circular 
            indeterminate 
            color="primary" 
            size="50"
            width="4"
          ></v-progress-circular>
          <div class="loading-text">加载中...</div>
        </div>
      </div>

      <div v-else-if="error" class="error-container">
        <v-alert 
          type="error" 
          class="error-alert"
          rounded="lg"
          elevation="4"
        >
          {{ error }}
        </v-alert>
      </div>

      <div v-else>
        <v-card class="user-info-card mb-4">
          <v-card-title class="card-title-section">
            <v-icon start color="primary">mdi-account-circle</v-icon> 个人信息
          </v-card-title>
          <v-card-text>
            <div class="d-flex justify-space-between mb-3 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="primary" class="mr-2">mdi-star-circle</v-icon>
                <span>可用积分：</span>
              </div>
              <div class="value-display credits-value">{{ userInfo.credits.toFixed(2) }}</div>
            </div>
            <div class="d-flex justify-space-between mb-3 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="success" class="mr-2">mdi-currency-usd</v-icon>
                <span>捐赠金额：</span>
              </div>
              <div class="value-display donation-value">{{ userInfo.donation.toFixed(2) }}</div>
            </div>
            <v-divider class="my-3"></v-divider>

            <div v-if="userInfo.invitation_codes && userInfo.invitation_codes.length > 0">
              <div class="font-weight-bold mb-2 d-flex align-center">
                <v-icon size="small" color="info" class="mr-2">mdi-ticket-account</v-icon>
                <span>可用邀请码：</span>
              </div>
              <div v-for="(code, index) in userInfo.invitation_codes" :key="index" class="mb-2">
                <v-chip 
                  size="small" 
                  color="primary" 
                  @click="copyToClipboard(code)"
                  class="invitation-chip"
                  elevation="2"
                  rounded="lg"
                >
                  {{ code }}
                  <v-icon end icon="mdi-content-copy" size="small"></v-icon>
                </v-chip>
              </div>
            </div>
            <div v-else class="text-center text-subtitle-2 my-2">
              <v-icon color="grey" class="mr-1">mdi-ticket-confirmation-outline</v-icon>
              暂无可用邀请码
            </div>
          </v-card-text>
        </v-card>

        <!-- Plex 账户信息 -->
        <v-card v-if="userInfo.plex_info" class="user-info-card mb-4">
          <v-card-title class="card-title-section">
            <v-icon start color="orange-darken-2">mdi-plex</v-icon> Plex 账户
          </v-card-title>
          <v-card-text>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-account</v-icon>
                <span>用户名：</span>
              </div>
              <div class="d-flex align-center justify-end">
                {{ userInfo.plex_info.username }}
                <v-icon 
                  v-if="userInfo.plex_info.is_premium" 
                  size="small" 
                  color="amber-darken-2" 
                  class="ml-1" 
                  title="会员用户"
                >
                  mdi-crown
                </v-icon>
              </div>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-email</v-icon>
                <span>邮箱：</span>
              </div>
              <div>{{ userInfo.plex_info.email }}</div>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-clock-time-four-outline</v-icon>
                <span>观看等级：</span>
              </div>
              <div class="d-flex align-center justify-end" :title="`观看时长: ${userInfo.plex_info.watched_time.toFixed(2)}小时`">
                <template v-if="watchLevelIcons(userInfo.plex_info.watched_time).length > 0">
                  <div class="level-icons-container" @click="showWatchTimeDialog(userInfo.plex_info.watched_time)">
                    <span 
                      v-for="(icon, index) in watchLevelIcons(userInfo.plex_info.watched_time)" 
                      :key="`plex-icon-${index}`"
                      :class="['emoji-icon', icon.class]"
                    >
                      {{ icon.icon }}
                    </span>
                  </div>
                </template>
                <span v-else-if="showNoWatchTimeText(userInfo.plex_info.watched_time)" class="text-grey">暂无观看记录</span>
              </div>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-folder-multiple</v-icon>
                <span>资料库权限：</span>
              </div>
              <v-chip 
                :color="userInfo.plex_info.all_lib ? 'success' : 'warning'" 
                size="small"
                @click="openNsfwDialog('plex', userInfo.plex_info.all_lib)"
                class="clickable-chip"
                elevation="1"
              >
                {{ userInfo.plex_info.all_lib ? '全部' : '部分' }}
                <v-icon end size="x-small" class="ml-1">mdi-pencil</v-icon>
              </v-chip>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-connection</v-icon>
                <span>绑定线路：</span>
              </div>
              <div class="line-selector-wrapper">
                <plex-line-selector 
                  ref="plexLineSelector"
                  :current-value="userInfo.plex_info.line" 
                  @line-changed="updatePlexLine"
                ></plex-line-selector>
              </div>
            </div>
          </v-card-text>
        </v-card>

        <!-- Emby 账户信息 -->
        <v-card v-if="userInfo.emby_info" class="user-info-card mb-4">
          <v-card-title class="card-title-section">
            <v-icon start color="green-darken-2">mdi-emby</v-icon> Emby 账户
          </v-card-title>
          <v-card-text>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-account</v-icon>
                <span>用户名：</span>
              </div>
              <div class="d-flex align-center justify-end">
                {{ userInfo.emby_info.username }}
                <v-icon 
                  v-if="userInfo.emby_info.is_premium" 
                  size="small" 
                  color="amber-darken-2" 
                  class="ml-1" 
                  title="会员用户"
                >
                  mdi-crown
                </v-icon>
              </div>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-clock-time-four-outline</v-icon>
                <span>观看等级：</span>
              </div>
              <div class="d-flex align-center justify-end" :title="`观看时长: ${userInfo.emby_info.watched_time.toFixed(2)}小时`">
                <template v-if="watchLevelIcons(userInfo.emby_info.watched_time).length > 0">
                  <div class="level-icons-container" @click="showWatchTimeDialog(userInfo.emby_info.watched_time)">
                    <span 
                      v-for="(icon, index) in watchLevelIcons(userInfo.emby_info.watched_time)" 
                      :key="`emby-icon-${index}`"
                      :class="['emoji-icon', icon.class]"
                    >
                      {{ icon.icon }}
                    </span>
                  </div>
                </template>
                <span v-else-if="showNoWatchTimeText(userInfo.emby_info.watched_time)" class="text-grey">暂无观看记录</span>
              </div>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-folder-multiple</v-icon>
                <span>资料库权限：</span>
              </div>
              <v-chip 
                :color="userInfo.emby_info.all_lib ? 'success' : 'warning'" 
                size="small"
                @click="openNsfwDialog('emby', userInfo.emby_info.all_lib)"
                class="clickable-chip"
                elevation="1"
              >
                {{ userInfo.emby_info.all_lib ? '全部' : '部分' }}
                <v-icon end size="x-small" class="ml-1">mdi-pencil</v-icon>
              </v-chip>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center entrance-url-row">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-web</v-icon>
                <span>入口线路：</span>
              </div>
              <div 
                class="entrance-url-chip"
                @click="copyToClipboard('auto.emby.funmedia.10101.io')"
                title="点击复制线路地址"
              >
                auto.emby.funmedia.10101.io
                <v-icon size="x-small" class="ml-1">mdi-content-copy</v-icon>
              </div>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-connection</v-icon>
                <span>绑定线路：</span>
              </div>
              <div class="line-selector-wrapper">
                <emby-line-selector 
                  ref="embyLineSelector"
                  :current-value="userInfo.emby_info.line" 
                  @line-changed="updateEmbyLine"
                ></emby-line-selector>
              </div>
            </div>
          </v-card-text>
        </v-card>

        <!-- Overseerr 账户信息 -->
        <v-card v-if="userInfo.overseerr_info" class="user-info-card mb-4">
          <v-card-title class="card-title-section">
            <v-icon start color="blue-darken-2">mdi-movie-search</v-icon> Overseerr 账户
          </v-card-title>
          <v-card-text>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-email</v-icon>
                <span>邮箱：</span>
              </div>
              <div>{{ userInfo.overseerr_info.email }}</div>
            </div>
          </v-card-text>
        </v-card>

        <div v-if="!userInfo.plex_info && !userInfo.emby_info" class="no-accounts-message">
          <v-alert 
            type="info" 
            class="info-alert"
            rounded="lg"
            elevation="4"
          >
            <v-icon start>mdi-information</v-icon>
            您尚未绑定任何媒体服务账户，请使用 /bind_plex 或 /bind_emby 命令进行绑定
          </v-alert>
        </div>
      </div>
      </v-container>
    </div>
    
    <!-- 使用NSFW对话框组件 -->
    <nsfw-dialog 
      ref="nsfwDialog" 
      :current-credits="userInfo.credits"
      @operation-completed="handleNsfwOperationCompleted"
    />
    
    <!-- 使用捐赠对话框组件 -->
    <donation-dialog
      ref="donationDialog"
      @donation-submitted="handleDonationSubmitted"
    />
    
    <!-- 使用标签管理对话框组件 -->
    <tag-management-dialog
      ref="tagManagementDialog"
      @tags-updated="handleTagsUpdated"
    />
    
    <!-- 使用线路管理对话框组件 -->
    <line-management-dialog
      ref="lineManagementDialog"
      @lines-updated="handleLinesUpdated"
    />
  </div>
</template>

<script>
import { getUserInfo } from '@/api'
import EmbyLineSelector from '@/components/EmbyLineSelector.vue'
import PlexLineSelector from '@/components/PlexLineSelector.vue'
import NsfwDialog from '@/components/NsfwDialog.vue'
import DonationDialog from '@/components/DonationDialog.vue'
import TagManagementDialog from '@/components/TagManagementDialog.vue'
import LineManagementDialog from '@/components/LineManagementDialog.vue'
import { getWatchLevelIcons, showNoWatchTimeText } from '@/utils/watchLevel.js'

export default {
  name: 'UserInfo',
  components: {
    EmbyLineSelector,
    PlexLineSelector,
    NsfwDialog,
    DonationDialog,
    TagManagementDialog,
    LineManagementDialog
  },
  data() {
    return {
      userInfo: {
        credits: 0,
        donation: 0,
        invitation_codes: [],
        plex_info: {
          line: null
        },
        emby_info: {
          line: null
        },
        overseerr_info: null,
        is_admin: false
      },
      loading: true,
      error: null
    }
  },
  mounted() {
    this.fetchUserInfo()
  },
  methods: {
    async fetchUserInfo() {
      try {
        this.loading = true
        const response = await getUserInfo()
        this.userInfo = response.data
        this.loading = false
      } catch (err) {
        this.error = err.response?.data?.detail || '获取用户信息失败'
        this.loading = false
        console.error('获取用户信息失败:', err)
      }
    },
    
    showMessage(message, type = 'success') {
      if (window.Telegram?.WebApp) {
        window.Telegram.WebApp.showPopup({
          title: type === 'error' ? '错误' : '成功',
          message: message
        })
      } else {
        alert(message)
      }
    },
    copyToClipboard(text) {
      navigator.clipboard.writeText(text).then(() => {
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.showPopup({
            title: '复制成功',
            message: '已复制到剪贴板'
          })
        } else {
          alert('已复制到剪贴板')
        }
      }).catch(err => {
        console.error('复制失败:', err)
      })
    },
    updateEmbyLine(line) {
      if (this.userInfo && this.userInfo.emby_info) {
        this.userInfo.emby_info.line = line;
      }
    },
    
    updatePlexLine(line) {
      if (this.userInfo && this.userInfo.plex_info) {
        this.userInfo.plex_info.line = line;
      }
    },
    
    // 打开NSFW权限管理对话框
    openNsfwDialog(service, isAllLib) {
      // 通过引用调用子组件方法
      this.$refs.nsfwDialog.open(service, isAllLib);
    },
    
    // 处理NSFW操作完成后的状态更新
    handleNsfwOperationCompleted(result) {
      const { service, isUnlock, cost } = result;
      
      // 更新资料库权限状态
      if (service === 'plex' && this.userInfo.plex_info) {
        this.userInfo.plex_info.all_lib = isUnlock;
      } else if (service === 'emby' && this.userInfo.emby_info) {
        this.userInfo.emby_info.all_lib = isUnlock;
      }
      
      // 更新用户积分
      this.userInfo.credits -= cost;
    },
    // 使用导入的方法获取观看等级图标
    watchLevelIcons(watchedTime) {
      return getWatchLevelIcons(watchedTime);
    },
    
    // 检查是否显示"暂无观看记录"文本
    showNoWatchTimeText(watchedTime) {
      return showNoWatchTimeText(watchedTime);
    },

    // 显示观看时长对话框
    showWatchTimeDialog(watchedTime) {
      const message = `观看时长：${watchedTime.toFixed(2)} 小时`;
      
      if (window.Telegram?.WebApp) {
        window.Telegram.WebApp.showPopup({
          title: '观看时长信息',
          message: message
        });
      } else {
        alert(message);
      }
    },
    
    // 打开捐赠对话框
    openDonationDialog() {
      this.$refs.donationDialog.open();
    },
    
    // 打开标签管理对话框
    openTagManagementDialog() {
      this.$refs.tagManagementDialog.open();
    },
    
    // 打开线路管理对话框
    openLineManagementDialog() {
      this.$refs.lineManagementDialog.open();
    },
    
    // 处理线路更新完成事件
    handleLinesUpdated() {
      // 线路配置已在管理页面更新
      this.showMessage('线路配置已更新');
    },
    
    // 处理标签更新完成事件
    handleTagsUpdated() {
      // 可以在这里刷新数据或显示成功提示
      this.showMessage('标签设置已更新');
    },
    
    // 处理捐赠提交完成事件
    handleDonationSubmitted() {
      // 刷新用户信息以获取最新的捐赠数据
      this.fetchUserInfo();
      this.showMessage('捐赠记录已添加');
    }
  }
}
</script>

<style scoped>
.user-info-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
  padding-bottom: 80px; /* 为底部导航栏留出空间 */
}

.content-wrapper {
  max-width: 800px;
  margin: 0 auto;
}

.user-info-header {
  text-align: center;
  margin-bottom: 40px;
  padding: 30px 20px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
}

.page-title {
  font-size: 28px;
  font-weight: 700;
  color: #333;
  margin-bottom: 8px;
}

.page-subtitle {
  font-size: 16px;
  color: #666;
  margin: 0;
}

.transparent-container {
  background: transparent !important;
  padding: 0 !important;
}

.user-info-card {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  border: none;
}

.user-info-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.15);
}

.card-title-section {
  text-align: center;
  font-size: 18px;
  font-weight: 600;
  color: #333;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  backdrop-filter: blur(10px);
  border-radius: 16px 16px 0 0;
  border-bottom: 1px solid rgba(102, 126, 234, 0.2);
  padding: 20px 24px 16px;
}

/* 确保卡片内容左对齐 */
.user-info-card .v-card-text {
  text-align: left;
  padding: 24px;
}

/* 无账户消息样式 */
.no-accounts-message {
  text-align: center;
  margin: 40px 0;
}

.info-alert {
  background: rgba(255, 255, 255, 0.95) !important;
  backdrop-filter: blur(10px);
  border: none !important;
}

/* 邀请码芯片样式 */
.invitation-chip {
  cursor: pointer;
  transition: all 0.3s ease;
  font-weight: 500;
}

.invitation-chip:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(116, 185, 255, 0.3) !important;
}

/* 数值显示样式 */
.value-display {
  font-weight: 700;
  font-size: 16px;
  padding: 6px 12px;
  border-radius: 8px;
  text-align: center;
  min-width: 60px;
  background: linear-gradient(135deg, rgba(116, 185, 255, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  border: 1px solid rgba(116, 185, 255, 0.2);
  transition: all 0.3s ease;
}

.credits-value {
  color: #1976d2;
  background: linear-gradient(135deg, rgba(25, 118, 210, 0.1) 0%, rgba(25, 118, 210, 0.05) 100%);
  border-color: rgba(25, 118, 210, 0.2);
}

.donation-value {
  color: #388e3c;
  background: linear-gradient(135deg, rgba(56, 142, 60, 0.1) 0%, rgba(56, 142, 60, 0.05) 100%);
  border-color: rgba(56, 142, 60, 0.2);
}

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

/* 确保所有d-flex内的项目垂直居中 */
.d-flex {
  align-items: center;
}

/* 增强线路选择行的布局 */
.d-flex.justify-space-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

/* 确保左侧标签部分不会过度拉伸 */
.d-flex.justify-space-between > .d-flex.align-center {
  flex: 1 1 auto;
  min-width: 0; /* 允许文本截断 */
}

.cursor-pointer {
  cursor: pointer;
}

/* 添加图标右侧边距 */
.mr-2 {
  margin-right: 8px;
}

/* 左侧边距 */
.ml-1 {
  margin-left: 4px;
}

/* 可点击chip样式 */
.clickable-chip {
  cursor: pointer;
  transition: all 0.3s ease;
  border: 1px solid transparent;
}

.clickable-chip:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15) !important;
  border-color: currentColor;
}

/* 入口线路地址样式 */
.entrance-url-chip {
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.1) 0%, rgba(76, 175, 80, 0.05) 100%);
  border: 1px solid rgba(76, 175, 80, 0.2);
  color: #388e3c;
  font-weight: 500;
  font-size: 14px;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: fit-content;
  white-space: nowrap;
  flex-shrink: 0;
  max-width: none;
}

/* 入口线路行样式 - 确保不换行 */
.entrance-url-row {
  flex-wrap: nowrap !important;
}

.entrance-url-row .d-flex.align-center {
  flex-shrink: 0;
  white-space: nowrap;
}

.entrance-url-chip:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(76, 175, 80, 0.3);
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.15) 0%, rgba(76, 175, 80, 0.1) 100%);
  border-color: rgba(76, 175, 80, 0.4);
}

.entrance-url-chip:active {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(76, 175, 80, 0.2);
}

.emoji-icon {
  font-size: 14px;
  margin-left: 4px;
  line-height: 1;
}

.level-icons-container {
  display: flex;
  align-items: center;
  gap: 1px;
  cursor: pointer;
  padding: 3px 6px;
  border-radius: 4px;
  transition: background-color 0.2s;
}

.level-icons-container:hover {
  background-color: rgba(0, 0, 0, 0.05);
}

.level-icons-container:active {
  background-color: rgba(0, 0, 0, 0.1);
}

/* 等级图标样式 */
.crown-icon {
  margin-right: 2px;
}

.star-icon {
  margin-right: 1px;
}

/* 线路选择器容器样式 */
.line-selector-wrapper {
  min-width: 150px;
  max-width: 250px;
  flex: 0 0 auto; /* 防止收缩 */
  margin-left: auto; /* 确保选择器靠右对齐 */
  display: flex;
  justify-content: flex-end;
  align-items: center;
}

/* 为线路选择器行增加更好的flex布局 */
.d-flex.justify-space-between .line-selector-wrapper {
  flex-shrink: 0; /* 防止选择器被压缩 */
}

/* 在小屏幕上调整线路选择器 */
@media (max-width: 600px) {
  .line-selector-wrapper {
    max-width: 180px;
    min-width: 120px;
  }
}

@media (max-width: 480px) {
  .line-selector-wrapper {
    max-width: 140px;
    min-width: 100px;
  }
  
  /* 在小屏幕上允许标签文本换行 */
  .d-flex.justify-space-between {
    flex-wrap: wrap;
    gap: 8px;
  }
  
  /* 入口线路行在小屏幕上的特殊处理 */
  .entrance-url-row {
    flex-wrap: nowrap !important;
    gap: 4px !important;
  }
  
  .entrance-url-chip {
    font-size: 12px;
    padding: 4px 8px;
  }
}

@media (max-width: 400px) {
  .line-selector-wrapper {
    max-width: 120px;
    min-width: 90px;
  }
  
  /* 入口线路在超小屏幕上的进一步优化 */
  .entrance-url-chip {
    font-size: 11px;
    padding: 3px 6px;
  }
}
</style>