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
          <v-card-title class="text-center">个人信息</v-card-title>
          <v-card-text>
            <div class="d-flex justify-space-between mb-2">
              <div>可用积分：</div>
              <div class="font-weight-bold">{{ userInfo.credits.toFixed(2) }}</div>
            </div>
            <div class="d-flex justify-space-between mb-2">
              <div>捐赠金额：</div>
              <div class="font-weight-bold">{{ userInfo.donation.toFixed(2) }}</div>
            </div>
            <v-divider class="my-3"></v-divider>

            <div v-if="userInfo.invitation_codes && userInfo.invitation_codes.length > 0">
              <div class="font-weight-bold mb-2">可用邀请码：</div>
              <div v-for="(code, index) in userInfo.invitation_codes" :key="index" class="mb-1">
                <v-chip size="small" color="primary" @click="copyToClipboard(code)">
                  {{ code }}
                  <v-icon end icon="mdi-content-copy" size="small"></v-icon>
                </v-chip>
              </div>
            </div>
            <div v-else class="text-center text-subtitle-2 my-2">暂无可用邀请码</div>
          </v-card-text>
        </v-card>

        <!-- Plex 账户信息 -->
        <v-card v-if="userInfo.plex_info" class="mb-4">
          <v-card-title class="text-center">
            <v-icon start>mdi-plex</v-icon> Plex 账户
          </v-card-title>
          <v-card-text>
            <div class="d-flex justify-space-between mb-2">
              <div>用户名：</div>
              <div>{{ userInfo.plex_info.username }}</div>
            </div>
            <div class="d-flex justify-space-between mb-2">
              <div>邮箱：</div>
              <div>{{ userInfo.plex_info.email }}</div>
            </div>
            <div class="d-flex justify-space-between mb-2">
              <div>观看时长：</div>
              <div>{{ userInfo.plex_info.watched_time.toFixed(2) }} 小时</div>
            </div>
            <div class="d-flex justify-space-between mb-2">
              <div>资料库权限：</div>
              <v-chip :color="userInfo.plex_info.all_lib ? 'success' : 'warning'" size="small">
                {{ userInfo.plex_info.all_lib ? '全部' : '部分' }}
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
            <div class="d-flex justify-space-between mb-2">
              <div>用户名：</div>
              <div>{{ userInfo.emby_info.username }}</div>
            </div>
            <div class="d-flex justify-space-between mb-2">
              <div>观看时长：</div>
              <div>{{ userInfo.emby_info.watched_time.toFixed(2) }} 小时</div>
            </div>
            <div class="d-flex justify-space-between mb-2">
              <div>资料库权限：</div>
              <v-chip :color="userInfo.emby_info.all_lib ? 'success' : 'warning'" size="small">
                {{ userInfo.emby_info.all_lib ? '全部' : '部分' }}
              </v-chip>
            </div>
            <div class="d-flex justify-space-between mb-2" v-if="userInfo.emby_info.line">
              <div>绑定线路：</div>
              <div>{{ userInfo.emby_info.line }}</div>
            </div>
          </v-card-text>
        </v-card>

        <!-- Overseerr 账户信息 -->
        <v-card v-if="userInfo.overseerr_info" class="mb-4">
          <v-card-title class="text-center">
            <v-icon start>mdi-movie-search</v-icon> Overseerr 账户
          </v-card-title>
          <v-card-text>
            <div class="d-flex justify-space-between mb-2">
              <div>邮箱：</div>
              <div>{{ userInfo.overseerr_info.email }}</div>
            </div>
          </v-card-text>
        </v-card>

        <div v-if="!userInfo.plex_info && !userInfo.emby_info" class="text-center my-8">
          <v-alert type="info">
            您尚未绑定任何媒体服务账户，请使用 /bind_plex 或 /bind_emby 命令进行绑定
          </v-alert>
        </div>
      </div>
    </v-container>
  </div>
</template>

<script>
import { getUserInfo } from '@/api'

export default {
  name: 'UserInfo',
  data() {
    return {
      userInfo: {
        credits: 0,
        donation: 0,
        invitation_codes: [],
        plex_info: null,
        emby_info: null,
        overseerr_info: null
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
    }
  }
}
</script>

<style scoped>
.user-info-container {
  padding-bottom: 56px; /* 为底部导航栏留出空间 */
}
</style>