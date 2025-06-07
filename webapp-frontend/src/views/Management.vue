<template>
  <div class="admin-container">
    <div class="content-wrapper">
      <div class="admin-header">
        <h1 class="page-title">管理中心</h1>
        <p class="page-subtitle">系统管理与配置</p>
      </div>
      
      <!-- 加载状态 -->
      <div v-if="loading" class="text-center my-10">
        <v-progress-circular indeterminate color="primary"></v-progress-circular>
        <div class="mt-3">加载中...</div>
      </div>

      <!-- 错误状态 -->
      <div v-else-if="error" class="text-center my-10">
        <v-alert type="error">{{ error }}</v-alert>
      </div>

      <!-- 权限不足 -->
      <div v-else-if="!isAdmin" class="text-center my-10">
        <v-alert type="warning">
          权限不足，需要管理员权限才能访问此页面
        </v-alert>
      </div>

      <!-- 管理员控制面板 -->
      <div v-else>
        <v-tabs
          v-model="currentTab"
          color="primary"
          density="compact"
          class="mb-4"
        >
          <v-tab value="settings">
            <v-icon start size="small">mdi-cog</v-icon>
            设置项
          </v-tab>
          <v-tab value="overview">
            <v-icon start size="small">mdi-view-dashboard</v-icon>
            概览
          </v-tab>
        </v-tabs>

        <v-window v-model="currentTab">
          <!-- 设置项 Tab -->
          <v-window-item value="settings">
            <!-- 服务注册控制 -->
            <v-card class="admin-card-enhanced mb-4">
              <v-card-title class="text-center">
                <v-icon start color="primary">mdi-server-plus</v-icon> 服务注册控制
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
                </div>
              </v-card-text>
            </v-card>

            <!-- 高级线路控制 -->
            <v-card class="admin-card-enhanced mb-4">
              <v-card-title class="text-center">
                <v-icon start color="purple-darken-2">mdi-crown</v-icon> 高级线路控制
              </v-card-title>
              <v-card-text>
                <div v-if="!adminLoading && !adminError">
                  <div class="d-flex justify-space-between mb-3 align-center">
                    <div class="d-flex align-center">
                      <v-icon size="small" color="purple-darken-2" class="mr-2">mdi-crown</v-icon>
                      <span>高级线路开放：</span>
                    </div>
                    <v-switch
                      v-model="adminSettings.premium_free"
                      color="success"
                      density="compact"
                      hide-details
                      @change="updatePremiumFree"
                    ></v-switch>
                  </div>
                  
                  <!-- 免费高级线路选择 -->
                  <div v-if="adminSettings.premium_free" class="mb-3">
                    <div class="d-flex align-center mb-2">
                      <v-icon size="small" color="purple-darken-2" class="mr-2">mdi-server-network</v-icon>
                      <span>免费高级线路选择：</span>
                    </div>
                    <v-select
                      v-model="adminSettings.free_premium_lines"
                      :items="adminSettings.premium_lines"
                      multiple
                      chips
                      closable-chips
                      label="选择免费开放的高级线路"
                      density="compact"
                      variant="outlined"
                      @update:model-value="updateFreePremiumLines"
                    >
                      <template v-slot:selection="{ item, index }">
                        <v-chip
                          v-if="index < 2"
                          size="small"
                          color="purple-lighten-3"
                          closable
                          @click:close="removeFreeLine(item.value)"
                        >
                          {{ item.title }}
                        </v-chip>
                        <span
                          v-if="index === 2"
                          class="text-grey text-caption align-self-center"
                        >
                          (+{{ adminSettings.free_premium_lines.length - 2 }} others)
                        </span>
                      </template>
                    </v-select>
                  </div>
                </div>
              </v-card-text>
            </v-card>

            <!-- 系统管理 -->
            <v-card class="admin-card-enhanced mb-4">
              <v-card-title class="text-center">
                <v-icon start color="blue-darken-2">mdi-cogs</v-icon> 系统管理
              </v-card-title>
              <v-card-text>
                <div v-if="!adminLoading && !adminError">
                  <!-- 捐赠管理 -->
                  <div class="d-flex justify-space-between align-center mb-3">
                    <div class="d-flex align-center">
                      <v-icon size="small" color="red-darken-2" class="mr-2">mdi-gift</v-icon>
                      <span>捐赠记录管理：</span>
                    </div>
                    <v-btn
                      color="red-darken-2"
                      variant="outlined"
                      size="small"
                      @click="openDonationDialog"
                    >
                      <v-icon start size="small">mdi-plus</v-icon>
                      添加捐赠
                    </v-btn>
                  </div>
                  
                  <!-- 线路标签管理 -->
                  <v-divider class="my-3"></v-divider>
                  <div class="d-flex justify-space-between align-center mb-3">
                    <div class="d-flex align-center">
                      <v-icon size="small" color="blue-darken-2" class="mr-2">mdi-tag-multiple</v-icon>
                      <span>线路标签管理：</span>
                    </div>
                    <v-btn
                      color="blue-darken-2"
                      variant="outlined"
                      size="small"
                      @click="openTagManagementDialog"
                    >
                      <v-icon start size="small">mdi-cog</v-icon>
                      管理标签
                    </v-btn>
                  </div>
                  
                  <!-- 线路管理 -->
                  <v-divider class="my-3"></v-divider>
                  <div class="d-flex justify-space-between align-center mb-3">
                    <div class="d-flex align-center">
                      <v-icon size="small" color="green-darken-2" class="mr-2">mdi-server-network</v-icon>
                      <span>线路管理：</span>
                    </div>
                    <v-btn
                      color="green-darken-2"
                      variant="outlined"
                      size="small"
                      @click="openLineManagementDialog"
                    >
                      <v-icon start size="small">mdi-plus-circle</v-icon>
                      管理线路
                    </v-btn>
                  </div>
                </div>
              </v-card-text>
            </v-card>

            <!-- 积分设置 -->
            <v-card class="admin-card-enhanced mb-4">
              <v-card-title class="text-center">
                <v-icon start color="yellow-darken-2">mdi-star</v-icon> 积分设置
              </v-card-title>
              <v-card-text>
                <div v-if="!adminLoading && !adminError">
                  <!-- 邀请码积分设置 -->
                  <div class="d-flex justify-space-between align-center mb-3">
                    <div class="d-flex align-center">
                      <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-ticket-confirmation</v-icon>
                      <span>生成邀请码所需积分：</span>
                    </div>
                    <div class="d-flex align-center">
                      <v-text-field
                        v-model.number="adminSettings.invitation_credits"
                        type="number"
                        density="compact"
                        variant="outlined"
                        hide-details
                        style="width: 100px"
                        min="0"
                        max="10000"
                        @blur="updateInvitationCredits"
                        @keyup.enter="updateInvitationCredits"
                      ></v-text-field>
                    </div>
                  </div>
                  
                  <!-- 解锁NSFW积分设置 -->
                  <div class="d-flex justify-space-between align-center">
                    <div class="d-flex align-center">
                      <v-icon size="small" color="grey-darken-1" class="mr-2">mdi-lock-open</v-icon>
                      <span>解锁 NSFW 所需积分：</span>
                    </div>
                    <div class="d-flex align-center">
                      <v-text-field
                        v-model.number="adminSettings.unlock_credits"
                        type="number"
                        density="compact"
                        variant="outlined"
                        hide-details
                        style="width: 100px"
                        min="0"
                        max="10000"
                        @blur="updateUnlockCredits"
                        @keyup.enter="updateUnlockCredits"
                      ></v-text-field>
                    </div>
                  </div>
                </div>
              </v-card-text>
            </v-card>
          </v-window-item>

          <!-- 概览 Tab -->
          <v-window-item value="overview">
            <v-card class="admin-card-enhanced">
              <v-card-title class="text-center">
                <v-icon start color="info">mdi-information</v-icon> 系统概览
              </v-card-title>
              <v-card-text class="text-center">
                <v-icon size="64" color="grey-lighten-1">mdi-chart-line</v-icon>
                <p class="mt-4 text-h6">系统概览功能</p>
                <p class="text-subtitle-1 text-grey">即将推出，敬请期待</p>
              </v-card-text>
            </v-card>
          </v-window-item>
        </v-window>
      </div>
    </div>

    <!-- 对话框组件 -->
    <donation-dialog
      ref="donationDialog"
      @donation-submitted="handleDonationSubmitted"
    />
    
    <tag-management-dialog
      ref="tagManagementDialog"
      @tags-updated="handleTagsUpdated"
    />
    
    <line-management-dialog
      ref="lineManagementDialog"
      @lines-updated="handleLinesUpdated"
    />
  </div>
</template>

<script>
import { getUserInfo } from '@/api'
import DonationDialog from '@/components/DonationDialog.vue'
import TagManagementDialog from '@/components/TagManagementDialog.vue'
import LineManagementDialog from '@/components/LineManagementDialog.vue'
import { getAdminSettings, setPlexRegister, setEmbyRegister, setPremiumFree, setFreePremiumLines, setInvitationCredits, setUnlockCredits } from '@/services/adminService.js'

export default {
  name: 'Management',
  components: {
    DonationDialog,
    TagManagementDialog,
    LineManagementDialog
  },
  data() {
    return {
      loading: true,
      error: null,
      isAdmin: false,
      currentTab: 'settings', // 默认显示设置项tab
      adminSettings: {
        plex_register: false,
        emby_register: false,
        lines: [],
        premium_free: false,
        premium_lines: [],
        free_premium_lines: [],
        invitation_credits: 288,
        unlock_credits: 100
      },
      adminLoading: false,
      adminError: null
    }
  },
  mounted() {
    this.checkAdminStatus()
  },
  methods: {
    async checkAdminStatus() {
      try {
        this.loading = true
        // 通过获取用户信息来检查管理员权限
        const response = await getUserInfo()
        this.isAdmin = response.data.is_admin
        
        if (this.isAdmin) {
          await this.fetchAdminSettings()
        }
        this.loading = false
      } catch (err) {
        this.error = err.response?.data?.detail || '检查权限失败'
        this.loading = false
        console.error('检查管理员权限失败:', err)
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
    
    async updatePremiumFree() {
      try {
        await setPremiumFree(this.adminSettings.premium_free)
        this.showMessage('高级线路免费使用设置已更新')
      } catch (err) {
        // 回滚状态
        this.adminSettings.premium_free = !this.adminSettings.premium_free
        this.showMessage('更新高级线路免费开放设置失败', 'error')
        console.error('更新高级线路免费开放设置失败:', err)
      }
    },
    
    async updateFreePremiumLines() {
      try {
        await setFreePremiumLines(this.adminSettings.free_premium_lines)
        this.showMessage(`免费高级线路设置已更新，共 ${this.adminSettings.free_premium_lines.length} 条线路`)
      } catch (err) {
        this.showMessage('更新免费高级线路设置失败', 'error')
        console.error('更新免费高级线路设置失败:', err)
        // 重新获取设置以恢复状态
        await this.fetchAdminSettings()
      }
    },
    
    async updateInvitationCredits() {
      try {
        const credits = parseInt(this.adminSettings.invitation_credits)
        if (isNaN(credits) || credits < 0) {
          this.showMessage('积分值必须是正整数', 'error')
          // 重新获取设置以恢复状态
          await this.fetchAdminSettings()
          return
        }
        await setInvitationCredits(credits)
        this.showMessage(`邀请码生成所需积分已设置为 ${credits}`)
      } catch (err) {
        this.showMessage('更新邀请码积分设置失败', 'error')
        console.error('更新邀请码积分设置失败:', err)
        // 重新获取设置以恢复状态
        await this.fetchAdminSettings()
      }
    },
    
    async updateUnlockCredits() {
      try {
        const credits = parseInt(this.adminSettings.unlock_credits)
        if (isNaN(credits) || credits < 0) {
          this.showMessage('积分值必须是正整数', 'error')
          // 重新获取设置以恢复状态
          await this.fetchAdminSettings()
          return
        }
        await setUnlockCredits(credits)
        this.showMessage(`解锁 NSFW 所需积分已设置为 ${credits}`)
      } catch (err) {
        this.showMessage('更新解锁积分设置失败', 'error')
        console.error('更新解锁积分设置失败:', err)
        // 重新获取设置以恢复状态
        await this.fetchAdminSettings()
      }
    },
    
    removeFreeLine(line) {
      const index = this.adminSettings.free_premium_lines.indexOf(line)
      if (index > -1) {
        this.adminSettings.free_premium_lines.splice(index, 1)
        this.updateFreePremiumLines()
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
      // 线路更新后刷新管理员设置以获取最新的线路列表
      if (this.isAdmin) {
        this.fetchAdminSettings();
      }
      this.showMessage('线路配置已更新');
    },
    
    // 处理标签更新完成事件
    handleTagsUpdated() {
      // 可以在这里刷新数据或显示成功提示
      this.showMessage('标签设置已更新');
    },
    
    // 处理捐赠提交完成事件
    handleDonationSubmitted() {
      this.showMessage('捐赠记录已添加');
    }
  }
}
</script>

<style scoped>
.admin-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
  padding-bottom: 80px; /* 为底部导航栏留出空间 */
}

.content-wrapper {
  max-width: 800px;
  margin: 0 auto;
}

.admin-header {
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

.admin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  margin-bottom: 40px;
}

.admin-card {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  padding: 30px 24px;
  text-align: center;
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.admin-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.15);
}

/* 美化后的管理卡片样式 */
.admin-card-enhanced {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  padding: 30px 24px;
  text-align: center;
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(15px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  transition: all 0.3s ease;
}

.admin-card-enhanced:hover {
  transform: translateY(-8px);
  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2);
  background: rgba(255, 255, 255, 0.98);
}

/* 卡片标题样式 */
.admin-card-enhanced .v-card-title {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  backdrop-filter: blur(10px);
  border-radius: 16px 16px 0 0;
  border-bottom: 1px solid rgba(102, 126, 234, 0.2);
  font-weight: 600;
  color: #333;
  padding: 16px 24px;
  margin: -30px -24px 20px;
}

.card-icon {
  margin-bottom: 16px;
}

.card-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
  margin-bottom: 8px;
}

.card-description {
  font-size: 14px;
  color: #666;
  margin-bottom: 20px;
  line-height: 1.5;
}

.coming-soon {
  text-align: center;
  padding: 40px 20px;
  background: rgba(255, 255, 255, 0.9);
  border-radius: 16px;
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
}

.coming-soon-text {
  font-size: 16px;
  color: #666;
  margin-top: 16px;
  margin-bottom: 0;
}

/* 管理控制面板样式 */
.d-flex {
  align-items: center;
}

.d-flex.justify-space-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.mr-2 {
  margin-right: 8px;
}

.ml-2 {
  margin-left: 8px;
}

/* 确保卡片文本左对齐 */
.admin-card .v-card-text {
  text-align: left;
}

/* Tab 样式优化 */
:deep(.v-tabs) {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 12px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
}

:deep(.v-tab) {
  border-radius: 8px;
  margin: 4px;
  transition: all 0.3s ease;
}

:deep(.v-tab--selected) {
  background: rgba(116, 185, 255, 0.15);
}

/* 深色模式样式 */
:deep(.v-theme--dark) .admin-header,
:deep(.v-theme--dark) .admin-card,
:deep(.v-theme--dark) .coming-soon {
  background: rgba(30, 30, 30, 0.95) !important;
}

:deep(.v-theme--dark) .v-tabs {
  background: rgba(30, 30, 30, 0.95) !important;
}

:deep(.v-theme--dark) .v-tab--selected {
  background: rgba(116, 185, 255, 0.25) !important;
}

:deep(.v-theme--dark) .page-title,
:deep(.v-theme--dark) .card-title {
  color: #fff !important;
}

:deep(.v-theme--dark) .page-subtitle,
:deep(.v-theme--dark) .card-description,
:deep(.v-theme--dark) .coming-soon-text {
  color: #ccc !important;
}

/* 深色模式下的卡片标题部分 */
:deep(.v-theme--dark) .v-card-title {
  background: rgba(40, 40, 40, 0.8) !important;
  color: #fff !important;
}

/* 深色模式下的页面标题和容器 */
:deep(.v-theme--dark) .admin-header {
  background: rgba(30, 30, 30, 0.95) !important;
}

:deep(.v-theme--dark) .page-title {
  color: #ffffff !important;
}

:deep(.v-theme--dark) .page-subtitle {
  color: #e0e0e0 !important;
}

/* 深色模式下的标签页 */
:deep(.v-theme--dark) .v-tab {
  color: #ffffff !important;
}

:deep(.v-theme--dark) .v-tabs {
  background: rgba(30, 30, 30, 0.8) !important;
}

/* 深色模式下的卡片文本 */
:deep(.v-theme--dark) .admin-card-enhanced .v-card-text {
  color: #ffffff !important;
}

:deep(.v-theme--dark) .admin-card-enhanced span {
  color: #ffffff !important;
}

:deep(.v-theme--dark) .admin-card-enhanced div {
  color: #ffffff !important;
}

/* 深色模式下的开关组件 */
:deep(.v-theme--dark) .v-switch {
  color: #ffffff !important;
}

/* 深色模式下的加载和错误状态 */
:deep(.v-theme--dark) .v-progress-circular {
  color: #90caf9 !important;
}

:deep(.v-theme--dark) .v-alert {
  background: rgba(30, 30, 30, 0.95) !important;
  color: #ffffff !important;
}

/* 深色模式下的按钮 */
:deep(.v-theme--dark) .v-btn {
  color: #ffffff !important;
}

/* 深色模式下的文本字段和选择器保持当前样式 */
:deep(.v-theme--dark) .v-text-field {
  color: #ffffff !important;
}

:deep(.v-theme--dark) .v-text-field .v-field__input {
  color: #ffffff !important;
}

:deep(.v-theme--dark) .v-select {
  color: #ffffff !important;
}

:deep(.v-theme--dark) .v-select .v-field__input {
  color: #ffffff !important;
}

/* 深色模式下通用文本颜色规则 */
:deep(.v-theme--dark) .admin-container,
:deep(.v-theme--dark) .admin-container * {
  color: #ffffff !important;
}

/* 深色模式下的图标颜色保持 */
:deep(.v-theme--dark) .v-icon[color="primary"] {
  color: #90caf9 !important;
}

:deep(.v-theme--dark) .v-icon[color="orange-darken-2"] {
  color: #ffb74d !important;
}

:deep(.v-theme--dark) .v-icon[color="green-darken-2"] {
  color: #81c784 !important;
}

:deep(.v-theme--dark) .v-icon[color="purple-darken-2"] {
  color: #ba68c8 !important;
}

/* 深色模式下的芯片样式 */
:deep(.v-theme--dark) .v-chip {
  color: #ffffff !important;
}

/* 深色模式下的按钮样式 */
:deep(.v-theme--dark) .v-btn {
  color: #ffffff !important;
}

/* 深色模式下的加载和错误状态 */
:deep(.v-theme--dark) .v-alert {
  background: rgba(30, 30, 30, 0.95) !important;
  color: #fff !important;
}

/* 深色模式下的表格和列表 */
:deep(.v-theme--dark) .v-table {
  background: rgba(30, 30, 30, 0.95) !important;
  color: #fff !important;
}

:deep(.v-theme--dark) .v-list {
  background: rgba(30, 30, 30, 0.95) !important;
  color: #fff !important;
}

:deep(.v-theme--dark) .v-list-item {
  color: #fff !important;
}

/* 深色模式下的开关组件 */
:deep(.v-theme--dark) .v-switch {
  color: #fff !important;
}

/* 深色模式下的输入框 */
:deep(.v-theme--dark) .v-text-field {
  color: #fff !important;
}

:deep(.v-theme--dark) .v-text-field .v-field__input {
  color: #fff !important;
}

/* 深色模式下的选择器 */
:deep(.v-theme--dark) .v-select {
  color: #fff !important;
}

:deep(.v-theme--dark) .v-select .v-field__input {
  color: #fff !important;
}

/* 深色模式下的美化卡片样式 */
:deep(.v-theme--dark) .admin-card-enhanced {
  background: rgba(30, 30, 30, 0.95) !important;
  border-color: rgba(116, 185, 255, 0.2) !important;
}

:deep(.v-theme--dark) .admin-card-enhanced:hover {
  background: rgba(40, 40, 40, 0.98) !important;
}

:deep(.v-theme--dark) .admin-card-enhanced .v-card-title {
  background: rgba(40, 40, 40, 0.8) !important;
  color: #fff !important;
  border-bottom-color: rgba(116, 185, 255, 0.3) !important;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .admin-container {
    padding: 10px;
  }
  
  .admin-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  
  .admin-header {
    padding: 20px 16px;
    margin-bottom: 30px;
  }
  
  .page-title {
    font-size: 24px;
  }
  
  .admin-card {
    padding: 24px 20px;
  }
}

@media (max-width: 480px) {
  .page-title {
    font-size: 22px;
  }
  
  .page-subtitle {
    font-size: 14px;
  }
  
  .card-title {
    font-size: 16px;
  }
  
  .card-description {
    font-size: 13px;
  }
  
  /* 小屏幕上确保控制面板布局正确 */
  .d-flex.justify-space-between {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
