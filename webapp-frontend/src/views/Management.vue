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

      <!-- 主要内容区域 -->
      <div v-else>
        <div class="management-tabs-container">
          <v-tabs
            v-model="currentTab"
            grow
            fixed-tabs
            color="primary"
            bg-color="transparent"
            class="management-tabs"
          >
            <v-tab value="overview" class="tab-item">
              <v-icon start size="18">mdi-view-dashboard</v-icon>
              <span class="tab-text">概览</span>
            </v-tab>
            <v-tab value="settings" class="tab-item">
              <v-icon start size="18">mdi-cog</v-icon>
              <span class="tab-text">系统设置项</span>
            </v-tab>
            <v-tab value="wheel" class="tab-item">
              <v-icon start size="18">mdi-ferris-wheel</v-icon>
              <span class="tab-text">活动管理</span>
            </v-tab>
          </v-tabs>
        </div>

        <v-window v-model="currentTab">
          <!-- 设置项 Tab - 需要管理员权限 -->
          <v-window-item value="settings">
            <!-- 权限检查 -->
            <div v-if="!isAdmin" class="text-center my-10">
              <v-alert type="warning">
                权限不足，需要管理员权限才能访问设置项
              </v-alert>
            </div>
            
            <!-- 管理员设置内容 -->
            <div v-else>
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
                      <v-icon size="small" color="green-darken-2" class="mr-2">mdi-emby</v-icon>
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
            </div>
          </v-window-item>

          <!-- 活动管理 Tab - 需要管理员权限 -->
          <v-window-item value="wheel">
            <!-- 权限检查 -->
            <div v-if="!isAdmin" class="text-center my-10">
              <v-alert type="warning">
                权限不足，需要管理员权限才能访问活动管理
              </v-alert>
            </div>
            
            <!-- 活动管理内容 -->
            <div v-else class="activities-grid">
              <!-- 幸运大转盘活动卡片 -->
              <v-card class="activity-card-enhanced">
                <v-card-title class="d-flex align-center">
                  <v-icon class="mr-2" color="purple-darken-2">mdi-ferris-wheel</v-icon>
                  <span>幸运大转盘</span>
                  <v-spacer></v-spacer>
                  <v-chip color="success" size="small" variant="flat">
                    <v-icon start size="12">mdi-check-circle</v-icon>
                    运行中
                  </v-chip>
                </v-card-title>
                
                <v-card-text>
                  <p class="text-body-2 text-medium-emphasis mb-4">
                    管理转盘奖品配置、概率设置和随机性参数，查看抽奖统计数据
                  </p>
                  
                  <div class="activity-stats mb-4">
                    <v-row dense>
                      <v-col cols="6">
                        <div class="stat-item">
                          <div class="stat-value">{{ wheelStats.totalSpins || 0 }}</div>
                          <div class="stat-label">总抽奖次数</div>
                        </div>
                      </v-col>
                      <v-col cols="6">
                        <div class="stat-item">
                          <div class="stat-value">{{ wheelStats.activeUsers || 0 }}</div>
                          <div class="stat-label">参与用户</div>
                        </div>
                      </v-col>
                    </v-row>
                    <v-row dense class="mt-2">
                      <v-col cols="6">
                        <div class="stat-item">
                          <div class="stat-value text-success">{{ wheelStats.todaySpins || 0 }}</div>
                          <div class="stat-label">今日抽奖</div>
                        </div>
                      </v-col>
                      <v-col cols="6">
                        <div class="stat-item">
                          <div class="stat-value text-info">{{ wheelStats.lastWeekSpins || 0 }}</div>
                          <div class="stat-label">本周抽奖</div>
                        </div>
                      </v-col>
                    </v-row>
                    
                    <v-row dense>
                      <v-col cols="6">
                        <div class="stat-item">
                          <div class="stat-value text-warning">{{ wheelStats.totalCreditsChange?.toFixed(2) || '0.00' }}</div>
                          <div class="stat-label">转盘总积分变化</div>
                        </div>
                      </v-col>
                      <v-col cols="6">
                        <div class="stat-item">
                          <div class="stat-value text-secondary">{{ wheelStats.totalInviteCodes || 0 }}</div>
                          <div class="stat-label">转盘总邀请码发放</div>
                        </div>
                      </v-col>
                    </v-row>
                  </div>
                </v-card-text>
                
                <v-card-actions class="pa-4 pt-0">
                  <v-btn
                    color="purple-darken-2"
                    variant="elevated"
                    block
                    @click="openWheelManagement"
                  >
                    <v-icon start>mdi-cog</v-icon>
                    进入转盘管理
                  </v-btn>
                </v-card-actions>
              </v-card>

              <!-- 其他活动卡片占位 -->
              <v-card class="activity-card-enhanced activity-placeholder">
                <v-card-title class="d-flex align-center">
                  <v-icon class="mr-2" color="grey-lighten-1">mdi-plus-circle-outline</v-icon>
                  <span>新活动</span>
                  <v-spacer></v-spacer>
                  <v-chip color="grey-lighten-1" size="small" variant="flat">
                    即将推出
                  </v-chip>
                </v-card-title>
                
                <v-card-text>
                  <p class="text-body-2 text-medium-emphasis mb-4">
                    更多精彩活动正在开发中，敬请期待
                  </p>
                  
                  <div class="text-center">
                    <v-icon size="48" color="grey-lighten-2">mdi-gift-outline</v-icon>
                  </div>
                </v-card-text>
                
                <v-card-actions class="pa-4 pt-0">
                  <v-btn
                    color="grey-lighten-1"
                    variant="outlined"
                    block
                    disabled
                  >
                    <v-icon start>mdi-clock-outline</v-icon>
                    敬请期待
                  </v-btn>
                </v-card-actions>
              </v-card>
            </div>
          </v-window-item>

          <!-- 概览 Tab -->
          <v-window-item value="overview">
            <!-- 加载状态 -->
            <div v-if="systemStatsLoading" class="text-center my-10">
              <v-progress-circular indeterminate color="primary"></v-progress-circular>
              <div class="mt-3">加载系统统计中...</div>
            </div>
            
            <!-- 错误状态 -->
            <div v-else-if="systemStatsError" class="text-center my-10">
              <v-alert type="error">{{ systemStatsError }}</v-alert>
              <v-btn 
                color="primary" 
                variant="outlined" 
                class="mt-3"
                @click="fetchSystemStats"
              >
                重试
              </v-btn>
            </div>
            
            <!-- 系统统计内容 -->
            <div v-else>
              <v-card class="admin-card-enhanced mb-4">
                <v-card-title class="text-center">
                  <v-icon start color="info">mdi-account-group</v-icon> 用户统计
                </v-card-title>
                <v-card-text>
                  <v-row>
                    <v-col cols="12" sm="4">
                      <div class="stat-item">
                        <div class="stat-value text-orange-darken-2">{{ systemStats.plex_users }}</div>
                        <div class="stat-label">Plex 用户</div>
                      </div>
                    </v-col>
                    <v-col cols="12" sm="4">
                      <div class="stat-item">
                        <div class="stat-value text-green-darken-2">{{ systemStats.emby_users }}</div>
                        <div class="stat-label">Emby 用户</div>
                      </div>
                    </v-col>
                    <v-col cols="12" sm="4">
                      <div class="stat-item">
                        <div class="stat-value text-primary">{{ systemStats.total_users }}</div>
                        <div class="stat-label">总用户数</div>
                      </div>
                    </v-col>
                  </v-row>
                </v-card-text>
              </v-card>
              
              <!-- 系统信息卡片 -->
              <v-card class="admin-card-enhanced">
                <v-card-title class="text-center">
                  <v-icon start color="blue">mdi-information</v-icon> 系统信息
                </v-card-title>
                <v-card-text class="text-center">
                  <p class="text-body-1 mb-3">系统运行状态良好</p>
                  <v-chip color="success" variant="flat">
                    <v-icon start>mdi-check-circle</v-icon>
                    正常运行
                  </v-chip>
                </v-card-text>
              </v-card>
            </div>
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

    <!-- 转盘管理弹窗 -->
    <v-dialog 
      v-model="showWheelManagement" 
      fullscreen
      transition="dialog-bottom-transition"
      :persistent="true"
    >
      <v-card>
        <v-toolbar color="purple-darken-2" dark>
          <v-btn icon dark @click="closeWheelManagement">
            <v-icon>mdi-close</v-icon>
          </v-btn>
          <v-toolbar-title>
            <v-icon class="mr-2">mdi-ferris-wheel</v-icon>
            幸运大转盘管理
          </v-toolbar-title>
          <v-spacer></v-spacer>
          <v-btn icon dark @click="refreshWheelStats">
            <v-icon>mdi-refresh</v-icon>
          </v-btn>
        </v-toolbar>
        
        <div style="height: calc(100vh - 64px); overflow-y: auto;">
          <WheelAdminPanel @show-message="showMessage" />
        </div>
      </v-card>
    </v-dialog>
  </div>
</template>

<script>
import { getUserInfo, getSystemStats } from '@/api'
import DonationDialog from '@/components/DonationDialog.vue'
import TagManagementDialog from '@/components/TagManagementDialog.vue'
import LineManagementDialog from '@/components/LineManagementDialog.vue'
import WheelAdminPanel from '@/components/WheelAdminPanel.vue'
import { getAdminSettings, setPlexRegister, setEmbyRegister, setPremiumFree, setFreePremiumLines, setInvitationCredits, setUnlockCredits } from '@/services/adminService.js'
import { getWheelStats } from '@/services/wheelService.js'

export default {
  name: 'Management',
  components: {
    DonationDialog,
    TagManagementDialog,
    LineManagementDialog,
    WheelAdminPanel
  },
  data() {
    return {
      loading: true,
      error: null,
      isAdmin: false,
      currentTab: 'overview', // 默认显示概览tab
      adminSettings: {
        plex_register: false,
        emby_register: false,
        lines: [],
        premium_free: false,
        premium_lines: [],
        free_premium_lines: [],
        invitation_credits: 288,
        unlock_credits: 100,
        loaded: false // 添加标记，避免重复加载
      },
      adminLoading: false,
      adminError: null,
      wheelStats: {
        totalSpins: 0,
        activeUsers: 0,
        todaySpins: 0,
        lastWeekSpins: 0,
        totalCreditsChange: 0.0,
        totalInviteCodes: 0
      },
      showWheelManagement: false,
      systemStats: {
        plex_users: 0,
        emby_users: 0,
        total_users: 0
      },
      systemStatsLoading: false,
      systemStatsError: null
    }
  },
  mounted() {
    this.checkUserStatus()
  },
  watch: {
    // 监听tab切换
    currentTab(newTab) {
      // 如果切换到概览tab，则获取系统统计数据
      if (newTab === 'overview') {
        this.fetchSystemStats()
      }
      // 如果切换到设置项tab且是管理员，则获取管理员设置
      if (newTab === 'settings' && this.isAdmin && !this.adminSettings.loaded) {
        this.fetchAdminSettings()
      }
      // 如果切换到活动管理tab且是管理员，则加载转盘统计数据
      if (newTab === 'wheel' && this.isAdmin) {
        this.loadWheelStats()
      }
    }
  },
  methods: {
    async checkUserStatus() {
      try {
        this.loading = true
        // 获取用户信息来检查管理员权限
        const response = await getUserInfo()
        this.isAdmin = response.data.is_admin
        
        // 如果当前在概览tab，则获取系统统计数据
        if (this.currentTab === 'overview') {
          await this.fetchSystemStats()
        }
        // 如果是管理员且当前在设置项tab，则获取管理员设置
        if (this.isAdmin && this.currentTab === 'settings') {
          await this.fetchAdminSettings()
        }
        // 如果是管理员且当前在活动管理tab，则加载转盘统计数据
        if (this.isAdmin && this.currentTab === 'wheel') {
          await this.loadWheelStats()
        }
        this.loading = false
      } catch (err) {
        this.error = err.response?.data?.detail || '检查用户状态失败'
        this.loading = false
        console.error('检查用户状态失败:', err)
      }
    },
    
    async fetchAdminSettings() {
      try {
        this.adminLoading = true
        this.adminError = null
        const response = await getAdminSettings()
        this.adminSettings = { ...response.data, loaded: true }
        this.adminLoading = false
      } catch (err) {
        this.adminError = err.response?.data?.detail || '获取管理员设置失败'
        this.adminLoading = false
        console.error('获取管理员设置失败:', err)
      }
    },
    
    async fetchSystemStats() {
      try {
        this.systemStatsLoading = true
        this.systemStatsError = null
        const response = await getSystemStats()
        this.systemStats = response.data
        this.systemStatsLoading = false
      } catch (err) {
        this.systemStatsError = err.response?.data?.detail || '获取系统统计失败'
        this.systemStatsLoading = false
        console.error('获取系统统计失败:', err)
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
    },

    // 打开转盘管理
    openWheelManagement() {
      this.showWheelManagement = true;
    },

    // 关闭转盘管理
    closeWheelManagement() {
      this.showWheelManagement = false;
      // 关闭时刷新统计数据
      this.loadWheelStats();
    },

    // 刷新转盘统计数据
    async refreshWheelStats() {
      await this.loadWheelStats();
      this.showMessage('统计数据已刷新');
    },

    // 加载转盘统计数据
    async loadWheelStats() {
      try {
        const response = await getWheelStats()
        this.wheelStats = response.data
      } catch (error) {
        console.error('加载转盘统计失败:', error);
        // 使用默认数据
        this.wheelStats = {
          totalSpins: 0,
          activeUsers: 0
        };
      }
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
/* 标签页容器样式 */
.management-tabs-container {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
  margin-bottom: 24px;
  padding: 12px 20px;
  overflow: visible; /* 确保内容不被裁剪 */
}

/* 标签页样式 */
.management-tabs {
  background: transparent !important;
  border-radius: 16px;
  margin-bottom: 0;
  padding: 0;
  overflow: visible !important; /* 确保tab内容不被裁剪 */
  min-width: 100%; /* 确保有足够宽度 */
}

.tab-item {
  font-weight: 600;
  transition: all 0.3s ease;
  border-radius: 12px;
  margin: 0 4px;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  min-height: 48px;
  text-align: center !important;
  flex-direction: row !important; /* 改为水平排列 */
  gap: 6px !important; /* 添加图标和文字之间的间距 */
  padding: 8px 12px !important; /* 增加内边距确保文字有足够空间 */
  white-space: nowrap !important; /* 防止文字换行 */
  min-width: fit-content !important; /* 确保有足够宽度显示完整文字 */
}

.tab-item .v-icon {
  margin-bottom: 0 !important; /* 移除底部边距 */
  margin-right: 4px !important; /* 添加右边距 */
  flex-shrink: 0 !important; /* 防止图标被压缩 */
}

.tab-text {
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
  overflow: visible;
}

/* 覆盖Vuetify默认的tab样式 */
:deep(.v-tab) {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  text-align: center !important;
  flex-direction: row !important; /* 改为水平排列 */
  min-height: 48px !important;
  gap: 6px !important;
  padding: 8px 12px !important;
  white-space: nowrap !important;
  min-width: fit-content !important;
  border-radius: 8px;
  margin: 4px;
  transition: all 0.3s ease;
}

:deep(.v-tab .v-btn__content) {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  flex-direction: row !important; /* 改为水平排列 */
  width: 100% !important;
  text-align: center !important;
  gap: 6px !important;
  white-space: nowrap !important;
}

:deep(.v-tab .v-icon) {
  margin-right: 4px !important; /* 右边距用于分隔图标和文字 */
  margin-bottom: 0 !important; /* 移除底部边距 */
  flex-shrink: 0 !important; /* 防止图标被压缩 */
}

:deep(.v-tab--selected) {
  background: none !important;
  box-shadow: none !important;
}

/* 响应式设计 */
@media (max-width: 600px) {
  .tab-item {
    padding: 6px 8px !important;
    margin: 0 2px;
    font-size: 13px;
  }
  
  .tab-text {
    font-size: 13px;
  }
  
  .tab-item .v-icon {
    margin-right: 3px !important;
  }
  
  :deep(.v-tab) {
    padding: 6px 8px !important;
    gap: 4px !important;
  }
  
  :deep(.v-tab .v-btn__content) {
    gap: 4px !important;
  }
}

@media (max-width: 480px) {
  .tab-item {
    padding: 4px 6px !important;
    margin: 0 1px;
    font-size: 12px;
  }
  
  .tab-text {
    font-size: 12px;
  }
  
  .tab-item .v-icon {
    margin-right: 2px !important;
  }
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
  
  /* 活动卡片小屏幕优化 */
  .activity-card-enhanced .v-card-title {
    padding: 12px 16px;
    font-size: 16px;
  }
  
  .stat-value {
    font-size: 18px;
  }
  
  .stat-label {
    font-size: 10px;
  }
  
  .activity-stats {
    padding: 12px;
  }
}

/* 活动网格布局 */
.activities-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 24px;
  margin-bottom: 40px;
}

/* 活动卡片样式 */
.activity-card-enhanced {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(15px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  transition: all 0.3s ease;
  overflow: hidden;
  position: relative;
}

.activity-card-enhanced:hover {
  transform: translateY(-8px);
  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2);
  background: rgba(255, 255, 255, 0.98);
}

.activity-card-enhanced::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.activity-card-enhanced:hover::before {
  opacity: 1;
}

.activity-card-enhanced .v-card-title {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(102, 126, 234, 0.1);
  font-weight: 600;
  color: #333;
  padding: 20px 24px;
}

/* 活动统计样式 */
.activity-stats {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.05) 0%, rgba(118, 75, 162, 0.05) 100%);
  border-radius: 12px;
  padding: 16px;
  border: 1px solid rgba(102, 126, 234, 0.1);
}

.stat-item {
  text-align: center;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #333;
  line-height: 1;
}

.stat-label {
  font-size: 12px;
  color: #666;
  margin-top: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* 占位卡片样式 */
.activity-placeholder {
  opacity: 0.7;
}

.activity-placeholder .v-card-title {
  background: linear-gradient(135deg, rgba(158, 158, 158, 0.1) 0%, rgba(189, 189, 189, 0.1) 100%);
  border-bottom: 1px solid rgba(158, 158, 158, 0.1);
}

/* 响应式设计 */
@media (max-width: 768px) {
  .activities-grid {
    grid-template-columns: 1fr;
    gap: 16px;
    margin-bottom: 30px;
  }
  
  .activity-card-enhanced .v-card-title {
    padding: 16px 20px;
  }
  
  .stat-value {
    font-size: 20px;
  }
  
  .stat-label {
    font-size: 11px;
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
  
  /* 活动卡片小屏幕优化 */
  .activity-card-enhanced .v-card-title {
    padding: 12px 16px;
    font-size: 16px;
  }
  
  .stat-value {
    font-size: 18px;
  }
  
  .stat-label {
    font-size: 10px;
  }
  
  .activity-stats {
    padding: 12px;
  }
}
</style>
