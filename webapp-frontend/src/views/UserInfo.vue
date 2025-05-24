<template>
  <div class="user-info-container">
    <v-container>
      <div v-if="loading" class="text-center my-10">
        <v-progress-circular indeterminate color="primary"></v-progress-circular>
        <div class="mt-3">加载中...</div>
      </div>

      <div v-else-if="error" class="text-center my-10">
        <v-alert type="error">{{ error }}</v-alert>
      </div>

      <div v-else>
        <v-card class="mb-4">
          <v-card-title class="text-center">
            <v-icon start>mdi-account-circle</v-icon> 个人信息
          </v-card-title>
          <v-card-text>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="primary" class="mr-2">mdi-star-circle</v-icon>
                <span>可用积分：</span>
              </div>
              <div class="font-weight-bold">{{ userInfo.credits.toFixed(2) }}</div>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="success" class="mr-2">mdi-currency-usd</v-icon>
                <span>捐赠金额：</span>
              </div>
              <div class="font-weight-bold">{{ userInfo.donation.toFixed(2) }}</div>
            </div>
            <v-divider class="my-3"></v-divider>

            <div v-if="userInfo.invitation_codes && userInfo.invitation_codes.length > 0">
              <div class="font-weight-bold mb-2 d-flex align-center">
                <v-icon size="small" color="info" class="mr-2">mdi-ticket-account</v-icon>
                <span>可用邀请码：</span>
              </div>
              <div v-for="(code, index) in userInfo.invitation_codes" :key="index" class="mb-1">
                <v-chip size="small" color="primary" @click="copyToClipboard(code)">
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
        <v-card v-if="userInfo.plex_info" class="mb-4">
          <v-card-title class="text-center">
            <v-icon start>mdi-plex</v-icon> Plex 账户
          </v-card-title>
          <v-card-text>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-account</v-icon>
                <span>用户名：</span>
              </div>
              <div>{{ userInfo.plex_info.username }}</div>
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
              <div class="d-flex align-center" :title="`观看时长: ${userInfo.plex_info.watched_time.toFixed(2)}小时`">
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
          </v-card-text>
        </v-card>

        <!-- Emby 账户信息 -->
        <v-card v-if="userInfo.emby_info" class="mb-4">
          <v-card-title class="text-center">
            <v-icon start>mdi-server</v-icon> Emby 账户
          </v-card-title>
          <v-card-text>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-account</v-icon>
                <span>用户名：</span>
              </div>
              <div class="d-flex align-center">
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
              <div class="d-flex align-center" :title="`观看时长: ${userInfo.emby_info.watched_time.toFixed(2)}小时`">
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
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-connection</v-icon>
                <span>绑定线路：</span>
              </div>
              <emby-line-selector 
                :current-value="userInfo.emby_info.line" 
                @line-changed="updateEmbyLine"
              ></emby-line-selector>
            </div>
          </v-card-text>
        </v-card>

        <!-- Overseerr 账户信息 -->
        <v-card v-if="userInfo.overseerr_info" class="mb-4">
          <v-card-title class="text-center">
            <v-icon start>mdi-movie-search</v-icon> Overseerr 账户
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

        <!-- 管理员模块 -->
        <v-card v-if="userInfo.is_admin" class="mb-4">
          <v-card-title class="text-center">
            <v-icon start color="red-darken-2">mdi-shield-crown</v-icon> 管理员控制面板
          </v-card-title>
          <v-card-text>
            <div v-if="adminLoading" class="text-center my-4">
              <v-progress-circular indeterminate size="small" color="primary"></v-progress-circular>
              <span class="ml-2">加载管理员设置中...</span>
            </div>
            
            <div v-else-if="adminError" class="mb-4">
              <v-alert type="error" density="compact">{{ adminError }}</v-alert>
            </div>
            
            <div v-else>
              <div class="d-flex justify-space-between mb-3 align-center">
                <div class="d-flex align-center">
                  <v-icon size="small" color="orange-darken-2" class="mr-2">mdi-plex</v-icon>
                  <span>Plex 注册开放：</span>
                </div>
                <v-switch
                  v-model="adminSettings.plex_register"
                  color="success"
                  density="compact"
                  hide-details
                  @change="updatePlexRegister"
                ></v-switch>
              </div>
              
              <div class="d-flex justify-space-between mb-3 align-center">
                <div class="d-flex align-center">
                  <v-icon size="small" color="green-darken-2" class="mr-2">mdi-server</v-icon>
                  <span>Emby 注册开放：</span>
                </div>
                <v-switch
                  v-model="adminSettings.emby_register"
                  color="success"
                  density="compact"
                  hide-details
                  @change="updateEmbyRegister"
                ></v-switch>
              </div>
              
              <div class="d-flex justify-space-between mb-2 align-center">
                <div class="d-flex align-center">
                  <v-icon size="small" color="purple-darken-2" class="mr-2">mdi-crown</v-icon>
                  <span>Emby 高级线路开放：</span>
                </div>
                <v-switch
                  v-model="adminSettings.emby_premium_free"
                  color="success"
                  density="compact"
                  hide-details
                  @change="updateEmbyPremiumFree"
                ></v-switch>
              </div>
            </div>
          </v-card-text>
        </v-card>

        <div v-if="!userInfo.plex_info && !userInfo.emby_info" class="text-center my-8">
          <v-alert type="info">
            <v-icon start>mdi-information</v-icon>
            您尚未绑定任何媒体服务账户，请使用 /bind_plex 或 /bind_emby 命令进行绑定
          </v-alert>
        </div>
      </div>
    </v-container>
    
    <!-- 使用NSFW对话框组件 -->
    <nsfw-dialog 
      ref="nsfwDialog" 
      :current-credits="userInfo.credits"
      @operation-completed="handleNsfwOperationCompleted"
    />
  </div>
</template>

<script>
import { getUserInfo } from '@/api'
import EmbyLineSelector from '@/components/EmbyLineSelector.vue'
import NsfwDialog from '@/components/NsfwDialog.vue'
import { getWatchLevelIcons, showNoWatchTimeText } from '@/utils/watchLevel.js'
import { getAdminSettings, setPlexRegister, setEmbyRegister, setEmbyPremiumFree } from '@/services/adminService.js'

export default {
  name: 'UserInfo',
  components: {
    EmbyLineSelector,
    NsfwDialog
  },
  data() {
    return {
      userInfo: {
        credits: 0,
        donation: 0,
        invitation_codes: [],
        plex_info: null,
        emby_info: null,
        overseerr_info: null,
        is_admin: false
      },
      loading: true,
      error: null,
      adminSettings: {
        plex_register: false,
        emby_register: false,
        emby_premium_free: false
      },
      adminLoading: false,
      adminError: null
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
        
        // 如果用户是管理员，获取管理员设置
        if (this.userInfo.is_admin) {
          await this.fetchAdminSettings()
        }
      } catch (err) {
        this.error = err.response?.data?.detail || '获取用户信息失败'
        this.loading = false
        console.error('获取用户信息失败:', err)
      }
    },
    
    async fetchAdminSettings() {
      try {
        this.adminLoading = true
        this.adminError = null
        const response = await getAdminSettings()
        this.adminSettings = response.data
        this.adminLoading = false
      } catch (err) {
        this.adminError = err.response?.data?.detail || '获取管理员设置失败'
        this.adminLoading = false
        console.error('获取管理员设置失败:', err)
      }
    },
    
    async updatePlexRegister() {
      try {
        await setPlexRegister(this.adminSettings.plex_register)
        this.showMessage('Plex 注册设置已更新')
      } catch (err) {
        // 回滚状态
        this.adminSettings.plex_register = !this.adminSettings.plex_register
        this.showMessage('更新 Plex 注册设置失败', 'error')
        console.error('更新 Plex 注册设置失败:', err)
      }
    },
    
    async updateEmbyRegister() {
      try {
        await setEmbyRegister(this.adminSettings.emby_register)
        this.showMessage('Emby 注册设置已更新')
      } catch (err) {
        // 回滚状态
        this.adminSettings.emby_register = !this.adminSettings.emby_register
        this.showMessage('更新 Emby 注册设置失败', 'error')
        console.error('更新 Emby 注册设置失败:', err)
      }
    },
    
    async updateEmbyPremiumFree() {
      try {
        await setEmbyPremiumFree(this.adminSettings.emby_premium_free)
        this.showMessage('Emby 会员线路免费设置已更新')
      } catch (err) {
        // 回滚状态
        this.adminSettings.emby_premium_free = !this.adminSettings.emby_premium_free
        this.showMessage('更新 Emby 会员线路免费设置失败', 'error')
        console.error('更新 Emby 会员线路免费设置失败:', err)
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
            message: '邀请码已复制到剪贴板'
          })
        } else {
          alert('邀请码已复制到剪贴板')
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
    }
  }
}
</script>

<style scoped>
.user-info-container {
  padding-bottom: 56px; /* 为底部导航栏留出空间 */
}

/* 确保所有d-flex内的项目垂直居中 */
.d-flex {
  align-items: center;
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
  transition: transform 0.2s, box-shadow 0.2s;
  border: 1px solid transparent;
}

.clickable-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  border-color: currentColor;
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
</style>