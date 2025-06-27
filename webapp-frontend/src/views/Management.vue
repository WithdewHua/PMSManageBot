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
                  
                  <div class="d-flex justify-space-between mb-3 align-center">
                    <div class="d-flex align-center">
                      <v-icon size="small" color="purple-darken-2" class="mr-2">mdi-lock-open</v-icon>
                      <span>Premium 解锁开放：</span>
                    </div>
                    <v-switch
                      v-model="adminSettings.premium_unlock_enabled"
                      color="success"
                      density="compact"
                      hide-details
                      @change="updatePremiumUnlockEnabled"
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
                  
                  <!-- 邀请码管理 -->
                  <v-divider class="my-3"></v-divider>
                  <div class="d-flex justify-space-between align-center mb-3">
                    <div class="d-flex align-center">
                      <v-icon size="small" color="blue-darken-2" class="mr-2">mdi-ticket-confirmation</v-icon>
                      <span>邀请码管理：</span>
                    </div>
                    <v-btn
                      color="blue-darken-2"
                      variant="outlined"
                      size="small"
                      @click="openInviteCodeDialog"
                    >
                      <v-icon start size="small">mdi-plus</v-icon>
                      生成邀请码
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
                  <div class="d-flex justify-space-between align-center mb-3">
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
                  
                  <!-- 解锁Premium每日积分设置 -->
                  <div class="d-flex justify-space-between align-center mb-3">
                    <div class="d-flex align-center">
                      <v-icon size="small" color="amber-darken-2" class="mr-2">mdi-crown</v-icon>
                      <span>解锁 Premium 每日积分：</span>
                    </div>
                    <div class="d-flex align-center">
                      <v-text-field
                        v-model.number="adminSettings.premium_daily_credits"
                        type="number"
                        density="compact"
                        variant="outlined"
                        hide-details
                        style="width: 100px"
                        min="0"
                        max="10000"
                        @blur="updatePremiumDailyCredits"
                        @keyup.enter="updatePremiumDailyCredits"
                      ></v-text-field>
                    </div>
                  </div>
                  
                  <!-- 积分转移功能开关 -->
                  <div class="d-flex justify-space-between align-center">
                    <div class="d-flex align-center">
                      <v-icon size="small" color="blue-darken-1" class="mr-2">mdi-bank-transfer</v-icon>
                      <span>积分转移功能：</span>
                    </div>
                    <v-switch
                      v-model="adminSettings.credits_transfer_enabled"
                      color="success"
                      density="compact"
                      hide-details
                      @change="updateCreditsTransferEnabled"
                    ></v-switch>
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

              <!-- 竞拍活动卡片 -->
              <v-card class="activity-card-enhanced">
                <v-card-title class="d-flex align-center">
                  <v-icon class="mr-2" color="blue-darken-2">mdi-gavel</v-icon>
                  <span>竞拍活动</span>
                  <v-spacer></v-spacer>
                  <v-chip color="success" size="small" variant="flat">
                    <v-icon start size="12">mdi-check-circle</v-icon>
                    运行中
                  </v-chip>
                </v-card-title>
                
                <v-card-text>
                  <p class="text-body-2 text-medium-emphasis mb-4">
                    管理竞拍活动、设置拍品和起拍价格，查看竞拍统计数据
                  </p>
                  
                  <div class="activity-stats mb-4">
                    <v-row dense>
                      <v-col cols="6">
                        <div class="stat-item">
                          <div class="stat-value">{{ auctionStats.total_auctions || 0 }}</div>
                          <div class="stat-label">总竞拍数</div>
                        </div>
                      </v-col>
                      <v-col cols="6">
                        <div class="stat-item">
                          <div class="stat-value">{{ auctionStats.active_auctions || 0 }}</div>
                          <div class="stat-label">进行中</div>
                        </div>
                      </v-col>
                    </v-row>
                    
                    <v-row dense>
                      <v-col cols="6">
                        <div class="stat-item">
                          <div class="stat-value">{{ auctionStats.total_bids || 0 }}</div>
                          <div class="stat-label">总出价次数</div>
                        </div>
                      </v-col>
                      <v-col cols="6">
                        <div class="stat-item">
                          <div class="stat-value text-warning">{{ auctionStats.total_value?.toFixed(2) || '0.00' }}</div>
                          <div class="stat-label">总成交金额</div>
                        </div>
                      </v-col>
                    </v-row>
                  </div>
                </v-card-text>
                
                <v-card-actions class="pa-4 pt-0">
                  <v-btn
                    color="blue-darken-2"
                    variant="elevated"
                    block
                    @click="openAuctionManagement"
                  >
                    <v-icon start>mdi-gavel</v-icon>
                    进入竞拍管理
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
            <div v-if="systemStatsLoading || premiumStatsLoading || trafficOverviewLoading" class="text-center my-10">
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
                @click="refreshOverviewStats"
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
              
              <!-- Premium 用户统计卡片 -->
              <v-card class="admin-card-enhanced mb-4">
                <v-card-title class="text-center">
                  <v-icon start color="purple">mdi-crown</v-icon> Premium 用户统计
                </v-card-title>
                <v-card-text>
                  <!-- 加载状态 -->
                  <div v-if="premiumStatsLoading" class="text-center py-4">
                    <v-progress-circular indeterminate size="small" color="purple"></v-progress-circular>
                    <div class="mt-2">加载Premium统计中...</div>
                  </div>
                  
                  <!-- 错误状态 -->
                  <div v-else-if="premiumStatsError" class="text-center py-4">
                    <v-alert type="error" density="compact">{{ premiumStatsError }}</v-alert>
                    <v-btn 
                      color="purple" 
                      variant="outlined" 
                      size="small"
                      class="mt-2"
                      @click="fetchPremiumStats"
                    >
                      重试
                    </v-btn>
                  </div>
                  
                  <!-- Premium统计数据 -->
                  <div v-else>
                    <v-row>
                      <v-col cols="12" sm="6" md="3">
                        <div class="stat-item">
                          <div class="stat-value text-purple-darken-2">{{ premiumStats.total_premium_users }}</div>
                          <div class="stat-label">总 Premium 用户</div>
                        </div>
                      </v-col>
                      <v-col cols="12" sm="6" md="3">
                        <div class="stat-item">
                          <div class="stat-value text-purple">{{ premiumStats.active_premium_users }}</div>
                          <div class="stat-label">活跃 Premium 用户</div>
                        </div>
                      </v-col>
                      <v-col cols="12" sm="6" md="3">
                        <div class="stat-item">
                          <div class="stat-value text-orange-darken-2">{{ premiumStats.premium_plex_users }}</div>
                          <div class="stat-label">Plex Premium 用户</div>
                        </div>
                      </v-col>
                      <v-col cols="12" sm="6" md="3">
                        <div class="stat-item">
                          <div class="stat-value text-green-darken-2">{{ premiumStats.premium_emby_users }}</div>
                          <div class="stat-label">Emby Premium 用户</div>
                        </div>
                      </v-col>
                    </v-row>
                  </div>
                </v-card-text>
              </v-card>
              
              <!-- 全平台流量统计卡片 -->
              <v-card class="admin-card-enhanced mb-4">
                <v-card-title class="text-center">
                  <v-icon start color="blue-darken-2">mdi-chart-bar</v-icon> 全站流量统计
                </v-card-title>
                <v-card-text>
                  <!-- 加载状态 -->
                  <div v-if="trafficOverviewLoading" class="text-center py-4">
                    <v-progress-circular indeterminate size="small" color="blue-darken-2"></v-progress-circular>
                    <div class="mt-2">加载流量概览中...</div>
                  </div>
                  
                  <!-- 错误状态 -->
                  <div v-else-if="trafficOverviewError" class="text-center py-4">
                    <v-alert type="error" density="compact">{{ trafficOverviewError }}</v-alert>
                    <v-btn 
                      color="blue-darken-2" 
                      variant="outlined" 
                      size="small"
                      class="mt-2"
                      @click="fetchTrafficOverview"
                    >
                      重试
                    </v-btn>
                  </div>
                  
                  <!-- 流量概览数据 -->
                  <div v-else>
                    <!-- 今日流量统计 -->
                    <div class="mb-6">
                      <div class="d-flex align-center mb-3">
                        <v-icon size="20" color="success" class="mr-2">mdi-calendar-today</v-icon>
                        <span class="text-subtitle1 font-weight-medium">今日流量</span>
                        <v-spacer></v-spacer>
                        <v-chip size="small" color="success" variant="tonal">
                          <v-icon start size="12">mdi-trending-up</v-icon>
                          实时
                        </v-chip>
                      </div>
                      <v-row>
                        <v-col cols="12" sm="4">
                          <div class="stat-item">
                            <div class="stat-value text-primary">{{ formatTrafficSize(trafficOverview.today.total) }}</div>
                            <div class="stat-label">总计</div>
                          </div>
                        </v-col>
                        <v-col cols="12" sm="4">
                          <div class="stat-item">
                            <div class="stat-value text-green-darken-2">{{ formatTrafficSize(trafficOverview.today.emby) }}</div>
                            <div class="stat-label">Emby 流量</div>
                          </div>
                        </v-col>
                        <v-col cols="12" sm="4">
                          <div class="stat-item">
                            <div class="stat-value text-orange-darken-2">{{ formatTrafficSize(trafficOverview.today.plex) }}</div>
                            <div class="stat-label">Plex 流量</div>
                          </div>
                        </v-col>
                      </v-row>
                    </div>
                    
                    <!-- 本周流量统计 -->
                    <div class="mb-6">
                      <div class="d-flex align-center mb-3">
                        <v-icon size="20" color="info" class="mr-2">mdi-calendar-week</v-icon>
                        <span class="text-subtitle1 font-weight-medium">本周流量</span>
                        <v-spacer></v-spacer>
                        <v-chip size="small" color="info" variant="tonal">
                          <v-icon start size="12">mdi-chart-timeline-variant</v-icon>
                          周统计
                        </v-chip>
                      </div>
                      <v-row>
                        <v-col cols="12" sm="4">
                          <div class="stat-item">
                            <div class="stat-value text-primary">{{ formatTrafficSize(trafficOverview.week.total) }}</div>
                            <div class="stat-label">总计</div>
                          </div>
                        </v-col>
                        <v-col cols="12" sm="4">
                          <div class="stat-item">
                            <div class="stat-value text-green-darken-2">{{ formatTrafficSize(trafficOverview.week.emby) }}</div>
                            <div class="stat-label">Emby 流量</div>
                          </div>
                        </v-col>
                        <v-col cols="12" sm="4">
                          <div class="stat-item">
                            <div class="stat-value text-orange-darken-2">{{ formatTrafficSize(trafficOverview.week.plex) }}</div>
                            <div class="stat-label">Plex 流量</div>
                          </div>
                        </v-col>
                      </v-row>
                    </div>
                    
                    <!-- 本月流量统计 -->
                    <div>
                      <div class="d-flex align-center mb-3">
                        <v-icon size="20" color="deep-purple" class="mr-2">mdi-calendar-month</v-icon>
                        <span class="text-subtitle1 font-weight-medium">本月流量</span>
                        <v-spacer></v-spacer>
                        <v-chip size="small" color="deep-purple" variant="tonal">
                          <v-icon start size="12">mdi-chart-box</v-icon>
                          月度汇总
                        </v-chip>
                      </div>
                      <v-row>
                        <v-col cols="12" sm="4">
                          <div class="stat-item">
                            <div class="stat-value text-primary">{{ formatTrafficSize(trafficOverview.month.total) }}</div>
                            <div class="stat-label">总计</div>
                          </div>
                        </v-col>
                        <v-col cols="12" sm="4">
                          <div class="stat-item">
                            <div class="stat-value text-green-darken-2">{{ formatTrafficSize(trafficOverview.month.emby) }}</div>
                            <div class="stat-label">Emby 流量</div>
                          </div>
                        </v-col>
                        <v-col cols="12" sm="4">
                          <div class="stat-item">
                            <div class="stat-value text-orange-darken-2">{{ formatTrafficSize(trafficOverview.month.plex) }}</div>
                            <div class="stat-label">Plex 流量</div>
                          </div>
                        </v-col>
                      </v-row>
                    </div>
                    
                    <!-- 查看线路详情按钮 -->
                    <div class="text-center mt-4">
                      <v-btn 
                        color="blue-darken-2" 
                        variant="outlined" 
                        size="small"
                        @click="showLineTrafficDialog = true"
                      >
                        <v-icon start>mdi-lan</v-icon>
                        查看线路流量详情
                      </v-btn>
                    </div>
                  </div>
                </v-card-text>
              </v-card>
              
              <!-- Premium 线路流量统计卡片 -->
              <v-card class="admin-card-enhanced mb-4">
                <v-card-title class="text-center">
                  <v-icon start color="deep-purple">mdi-chart-line</v-icon> Premium 线路流量统计
                </v-card-title>
                <v-card-text>
                  <!-- 加载状态 -->
                  <div v-if="trafficStatsLoading" class="text-center py-4">
                    <v-progress-circular indeterminate size="small" color="deep-purple"></v-progress-circular>
                    <div class="mt-2">加载流量统计中...</div>
                  </div>
                  
                  <!-- 错误状态 -->
                  <div v-else-if="trafficStatsError" class="text-center py-4">
                    <v-alert type="error" density="compact">{{ trafficStatsError }}</v-alert>
                    <v-btn 
                      color="deep-purple" 
                      variant="outlined" 
                      size="small"
                      class="mt-2"
                      @click="fetchTrafficStats"
                    >
                      重试
                    </v-btn>
                  </div>
                  
                  <!-- 无数据状态 -->
                  <div v-else-if="!trafficStats || trafficStats.length === 0" class="text-center py-4">
                    <v-alert type="info" density="compact">
                      暂无 Premium 线路流量数据
                    </v-alert>
                  </div>
                  
                  <!-- 流量统计数据 -->
                  <div v-else>
                    <div class="premium-traffic-grid">
                      <div 
                        v-for="lineStat in trafficStats" 
                        :key="lineStat.line"
                        class="premium-line-card"
                      >
                        <!-- 线路卡片标题栏 -->
                        <div class="premium-line-header">
                          <div class="line-title-wrapper">
                            <v-icon color="deep-purple" class="line-icon">mdi-server-network</v-icon>
                            <v-tooltip :text="lineStat.line" location="top">
                              <template v-slot:activator="{ props }">
                                <h3 class="line-title" v-bind="props">{{ lineStat.line }}</h3>
                              </template>
                            </v-tooltip>
                          </div>
                          <v-chip size="small" color="deep-purple" variant="tonal" class="status-chip">
                            <v-icon start size="12">mdi-check-circle</v-icon>
                            运行中
                          </v-chip>
                        </div>
                        
                        <!-- 流量统计区域 -->
                        <div class="traffic-stats-section">
                          <div class="stats-header">
                            <v-icon size="16" color="deep-purple" class="mr-2">mdi-chart-line</v-icon>
                            <span class="section-title">流量统计</span>
                          </div>
                          
                          <div class="traffic-metrics">
                            <div class="metric-item today">
                              <div class="metric-label">
                                <v-icon size="12" color="success">mdi-calendar-today</v-icon>
                                今日
                              </div>
                              <div class="metric-value success">
                                {{ formatTrafficSize(lineStat.today_traffic) }}
                              </div>
                            </div>
                            
                            <div class="metric-item week">
                              <div class="metric-label">
                                <v-icon size="12" color="info">mdi-calendar-week</v-icon>
                                本周
                              </div>
                              <div class="metric-value info">
                                {{ formatTrafficSize(lineStat.week_traffic) }}
                              </div>
                            </div>
                            
                            <div class="metric-item month">
                              <div class="metric-label">
                                <v-icon size="12" color="warning">mdi-calendar-month</v-icon>
                                本月
                              </div>
                              <div class="metric-value warning">
                                {{ formatTrafficSize(lineStat.month_traffic) }}
                              </div>
                            </div>
                          </div>
                        </div>
                        
                        <!-- 用户排行区域 -->
                        <div v-if="lineStat.top_users && lineStat.top_users.length > 0" class="ranking-section">
                          <div class="stats-header">
                            <v-icon size="16" color="amber-darken-2" class="mr-2">mdi-trophy</v-icon>
                            <span class="section-title">流量排行</span>
                            <v-chip size="x-small" color="amber-darken-2" variant="tonal" class="ml-2">
                              本月
                            </v-chip>
                          </div>
                          
                          <div class="ranking-list">
                            <div 
                              v-for="(user, index) in lineStat.top_users.slice(0, 3)" 
                              :key="user.username"
                              class="ranking-item"
                            >
                              <div class="user-info">
                                <div class="rank-badge" :class="`rank-${index + 1}`">
                                  <v-icon 
                                    :color="getUserRankColor(index)" 
                                    size="14"
                                  >
                                    {{ getUserRankIcon(index) }}
                                  </v-icon>
                                </div>
                                <span class="username">{{ formatUsername(user.username) }}</span>
                              </div>
                              <div class="traffic-amount">
                                {{ formatTrafficSize(user.traffic) }}
                              </div>
                            </div>
                            
                            <!-- 查看更多按钮 -->
                            <div v-if="lineStat.top_users.length > 3" class="view-more-section">
                              <v-btn
                                size="small"
                                variant="outlined"
                                color="deep-purple"
                                class="view-more-btn"
                                @click="showLineUsersDialog(lineStat)"
                              >
                                <v-icon start size="16">mdi-account-group</v-icon>
                                查看全部 {{ lineStat.top_users.length }} 用户
                              </v-btn>
                            </div>
                          </div>
                        </div>
                        
                        <!-- 无数据状态 -->
                        <div v-else class="no-data-section">
                          <div class="no-data-content">
                            <v-icon size="32" color="grey-lighten-1">mdi-account-off-outline</v-icon>
                            <p class="no-data-text">暂无用户使用数据</p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
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
    
    <admin-invite-code-dialog
      ref="inviteCodeDialog"
      @invite-codes-generated="handleInviteCodesGenerated"
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

    <!-- 竞拍管理弹窗 -->
    <v-dialog 
      v-model="showAuctionManagement" 
      fullscreen
      transition="dialog-bottom-transition"
      :persistent="true"
    >
      <v-card>
        <v-toolbar color="blue-darken-2" dark>
          <v-btn icon dark @click="closeAuctionManagement">
            <v-icon>mdi-close</v-icon>
          </v-btn>
          <v-toolbar-title>
            <v-icon class="mr-2">mdi-gavel</v-icon>
            竞拍管理
          </v-toolbar-title>
          <v-spacer></v-spacer>
          <v-btn icon dark @click="refreshAuctionStats">
            <v-icon>mdi-refresh</v-icon>
          </v-btn>
        </v-toolbar>
        
        <div style="height: calc(100vh - 64px); overflow-y: auto; padding: 20px;">
          <!-- 权限检查 -->
          <div v-if="!isAdmin" class="text-center my-10">
            <v-alert type="warning">
              权限不足，需要管理员权限才能访问竞拍管理
            </v-alert>
          </div>
          
          <!-- 竞拍管理内容 -->
          <div v-else class="auction-management">
            <!-- 竞拍统计卡片 -->
            <v-card class="admin-card-enhanced mb-6">
              <v-card-title class="d-flex align-center">
                <v-icon class="mr-2" color="primary">mdi-chart-line</v-icon>
                <span>竞拍统计</span>
                <v-spacer></v-spacer>
                <v-btn 
                  @click="refreshAuctionStats" 
                  :loading="auctionStatsLoading"
                  size="small"
                  variant="text"
                  icon="mdi-refresh"
                ></v-btn>
              </v-card-title>
              
              <v-card-text>
                <div v-if="auctionStatsLoading" class="text-center py-4">
                  <v-progress-circular indeterminate size="small" color="primary"></v-progress-circular>
                  <div class="mt-2">加载统计数据中...</div>
                </div>
                
                <div v-else-if="auctionStatsError">
                  <v-alert type="error" density="compact">{{ auctionStatsError }}</v-alert>
                </div>
                
                <div v-else>
                  <v-row dense>
                    <v-col cols="6" md="3">
                      <div class="stat-card">
                        <div class="stat-number text-primary">{{ auctionStats.total_auctions || 0 }}</div>
                        <div class="stat-label">总竞拍数</div>
                      </div>
                    </v-col>
                    <v-col cols="6" md="3">
                      <div class="stat-card">
                        <div class="stat-number text-success">{{ auctionStats.active_auctions || 0 }}</div>
                        <div class="stat-label">进行中</div>
                      </div>
                    </v-col>
                    <v-col cols="6" md="3">
                      <div class="stat-card">
                        <div class="stat-number text-warning">{{ auctionStats.total_bids || 0 }}</div>
                        <div class="stat-label">总出价次数</div>
                      </div>
                    </v-col>
                    <v-col cols="6" md="3">
                      <div class="stat-card">
                        <div class="stat-number text-info">{{ auctionStats.total_credits || 0 }}</div>
                        <div class="stat-label">总积分流通</div>
                      </div>
                    </v-col>
                  </v-row>
                </div>
              </v-card-text>
            </v-card>

            <!-- 快速操作卡片 -->
            <v-card class="admin-card-enhanced mb-6">
              <v-card-title class="d-flex align-center">
                <v-icon class="mr-2" color="orange">mdi-lightning-bolt</v-icon>
                <span>快速操作</span>
              </v-card-title>
              
              <v-card-text>
                <v-row dense>
                  <v-col cols="12" md="6">
                    <v-btn
                      @click="showCreateAuctionDialog = true"
                      color="primary"
                      variant="flat"
                      block
                      prepend-icon="mdi-plus"
                    >
                      创建竞拍活动
                    </v-btn>
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-btn
                      @click="finishExpiredAuctionsAction"
                      :loading="finishingExpired"
                      color="warning"
                      variant="flat"
                      block
                      prepend-icon="mdi-clock-end"
                    >
                      结束过期竞拍
                    </v-btn>
                  </v-col>
                </v-row>
              </v-card-text>
            </v-card>

            <!-- 竞拍活动列表 -->
            <v-card class="admin-card-enhanced">
              <v-card-title class="d-flex align-center">
                <v-icon class="mr-2" color="green">mdi-gavel</v-icon>
                <span>竞拍活动管理</span>
                <v-spacer></v-spacer>
                <v-btn-toggle
                  v-model="auctionStatusFilter"
                  @update:modelValue="filterAuctions"
                  density="compact"
                  variant="outlined"
                >
                  <v-btn value="all" size="small">全部</v-btn>
                  <v-btn value="active" size="small">进行中</v-btn>
                  <v-btn value="ended" size="small">已结束</v-btn>
                </v-btn-toggle>
              </v-card-title>
              
              <v-card-text>
                <div v-if="auctionsLoading" class="text-center py-4">
                  <v-progress-circular indeterminate size="small" color="primary"></v-progress-circular>
                  <div class="mt-2">加载竞拍列表中...</div>
                </div>
                
                <div v-else-if="auctionsError">
                  <v-alert type="error" density="compact">{{ auctionsError }}</v-alert>
                </div>
                
                <div v-else-if="filteredAuctions.length === 0">
                  <v-alert type="info" density="compact">
                    暂无竞拍活动
                  </v-alert>
                </div>
                
                <div v-else>
                  <v-data-table
                    :headers="auctionTableHeaders"
                    :items="filteredAuctions"
                    :loading="auctionsLoading"
                    density="compact"
                    class="auction-table"
                  >
                    <template #item.status="{ item }">
                      <v-chip
                        :color="getAuctionStatusColor(item.status)"
                        size="small"
                        variant="flat"
                      >
                        {{ getAuctionStatusText(item.status) }}
                      </v-chip>
                    </template>
                    
                    <template #item.title="{ item }">
                      <div class="d-flex align-center">
                        <v-icon
                          size="small"
                          class="mr-2"
                          :color="getItemTypeColor(item.item_type)"
                        >
                          {{ getItemTypeIcon(item.item_type) }}
                        </v-icon>
                        <span>{{ item.title || `ID: ${item.id}` || '未知竞拍活动' }}</span>
                      </div>
                    </template>
                    
                    <template #item.starting_price="{ item }">
                      <span class="text-success">{{ item.starting_price || 0 }} 积分</span>
                    </template>
                    
                    <template #item.current_price="{ item }">
                      <span class="text-primary font-weight-bold">
                        {{ item.current_price || item.starting_price || 0 }} 积分
                      </span>
                    </template>
                    
                    <template #item.end_time="{ item }">
                      <div>
                        <div>{{ formatDateTime(item.end_time) }}</div>
                        <div class="text-caption text-medium-emphasis">
                          {{ getTimeStatus(item.end_time) }}
                        </div>
                      </div>
                    </template>
                    
                    <template #item.actions="{ item }">
                      <div class="d-flex gap-2">
                        <v-btn
                          @click="viewAuctionDetails(item)"
                          size="small"
                          variant="text"
                          icon="mdi-eye"
                          color="primary"
                        ></v-btn>
                        <v-btn
                          @click="editAuction(item)"
                          size="small"
                          variant="text"
                          icon="mdi-pencil"
                          color="orange"
                        ></v-btn>
                        <v-btn
                          v-if="item.status === 'active'"
                          @click="finishAuction(item)"
                          size="small"
                          variant="text"
                          icon="mdi-stop"
                          color="warning"
                        ></v-btn>
                        <v-btn
                          @click="deleteAuction(item)"
                          size="small"
                          variant="text"
                          icon="mdi-delete"
                          color="error"
                        ></v-btn>
                      </div>
                    </template>
                  </v-data-table>
                </div>
              </v-card-text>
            </v-card>
          </div>
        </div>
      </v-card>
    </v-dialog>

    <!-- 创建竞拍对话框 -->
    <v-dialog v-model="showCreateAuctionDialog" max-width="600px" persistent>
      <v-card>
        <v-toolbar color="primary" dark flat>
          <v-btn icon dark @click="showCreateAuctionDialog = false">
            <v-icon>mdi-close</v-icon>
          </v-btn>
          <v-toolbar-title>
            <v-icon class="mr-2">mdi-plus</v-icon>
            创建竞拍活动
          </v-toolbar-title>
        </v-toolbar>
        
        <v-card-text class="pa-6">
          <v-form ref="createAuctionForm">
            <v-row>
              <v-col cols="12">
                <v-text-field
                  v-model="createAuctionForm.item_name"
                  label="物品名称"
                  :rules="[v => !!v || '物品名称不能为空']"
                  outlined
                  dense
                  required
                ></v-text-field>
              </v-col>
              
              <v-col cols="12" md="6">
                <v-select
                  v-model="createAuctionForm.item_type"
                  :items="[
                    { text: 'Plex 账号', value: 'plex' },
                    { text: 'Emby 账号', value: 'emby' },
                    { text: '积分', value: 'credits' },
                    { text: '邀请码', value: 'invite' }
                  ]"
                  item-title="text"
                  item-value="value"
                  label="物品类型"
                  outlined
                  dense
                  required
                ></v-select>
              </v-col>
              
              <v-col cols="12" md="6">
                <v-text-field
                  v-model.number="createAuctionForm.start_price"
                  label="起拍价格（积分）"
                  :rules="[v => v > 0 || '起拍价格必须大于0']"
                  type="number"
                  outlined
                  dense
                  min="1"
                  required
                ></v-text-field>
              </v-col>
              
              <v-col cols="12">
                <v-text-field
                  v-model.number="createAuctionForm.duration_hours"
                  label="竞拍时长（小时）"
                  :rules="[v => v > 0 || '竞拍时长必须大于0']"
                  type="number"
                  outlined
                  dense
                  min="1"
                  max="168"
                  required
                ></v-text-field>
              </v-col>
              
              <v-col cols="12">
                <v-textarea
                  v-model="createAuctionForm.description"
                  label="物品描述"
                  outlined
                  dense
                  rows="3"
                  placeholder="请描述竞拍物品的详细信息..."
                  hint="如果不填写，将使用默认描述"
                  persistent-hint
                ></v-textarea>
              </v-col>
            </v-row>
          </v-form>
        </v-card-text>
        
        <v-card-actions class="pa-6 pt-0">
          <v-spacer></v-spacer>
          <v-btn @click="showCreateAuctionDialog = false" variant="text">
            取消
          </v-btn>
          <v-btn @click="createNewAuction" color="primary" variant="flat">
            创建竞拍
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 竞拍详情对话框 -->
    <v-dialog v-model="showAuctionDetailDialog" max-width="800px">
      <v-card v-if="selectedAuction">
        <v-toolbar color="info" dark flat>
          <v-btn icon dark @click="closeAuctionDetailDialog">
            <v-icon>mdi-close</v-icon>
          </v-btn>
          <v-toolbar-title>
            <v-icon class="mr-2">mdi-eye</v-icon>
            竞拍详情
          </v-toolbar-title>
        </v-toolbar>
        
        <v-card-text class="pa-6">
          <v-row>
            <v-col cols="12" md="6">
              <div class="detail-item">
                <div class="text-caption text-medium-emphasis">竞拍ID</div>
                <div class="text-body-1">#{{ selectedAuction.id }}</div>
              </div>
            </v-col>
            <v-col cols="12" md="6">
              <div class="detail-item">
                <div class="text-caption text-medium-emphasis">状态</div>
                <v-chip
                  :color="getAuctionStatusColor(selectedAuction.status)"
                  size="small"
                  variant="flat"
                >
                  {{ getAuctionStatusText(selectedAuction.status) }}
                </v-chip>
              </div>
            </v-col>
            <v-col cols="12">
              <div class="detail-item">
                <div class="text-caption text-medium-emphasis">物品名称</div>
                <div class="text-h6">{{ selectedAuction.title || `ID: ${selectedAuction.id}` || '未知竞拍活动' }}</div>
              </div>
            </v-col>
            <v-col cols="12" md="6">
              <div class="detail-item">
                <div class="text-caption text-medium-emphasis">起拍价</div>
                <div class="text-body-1 text-success">{{ selectedAuction.starting_price || 0 }} 积分</div>
              </div>
            </v-col>
            <v-col cols="12" md="6">
              <div class="detail-item">
                <div class="text-caption text-medium-emphasis">当前价格</div>
                <div class="text-body-1 text-primary font-weight-bold">
                  {{ selectedAuction.current_price || selectedAuction.starting_price || 0 }} 积分
                </div>
              </div>
            </v-col>
            <v-col cols="12" md="6">
              <div class="detail-item">
                <div class="text-caption text-medium-emphasis">结束时间</div>
                <div class="text-body-1">{{ formatDateTime(selectedAuction.end_time) }}</div>
              </div>
            </v-col>
            <v-col cols="12" md="6">
              <div class="detail-item">
                <div class="text-caption text-medium-emphasis">出价次数</div>
                <div class="text-body-1">{{ auctionBids.length }} 次</div>
              </div>
            </v-col>
          </v-row>
          
          <!-- 出价历史 -->
          <div v-if="auctionBids.length > 0" class="mt-6">
            <div class="text-h6 mb-3">出价历史</div>
            <v-data-table
              :headers="[
                { title: '用户', key: 'bidder_name' },
                { title: '出价金额', key: 'bid_amount' },
                { title: '出价时间', key: 'bid_time' }
              ]"
              :items="auctionBids"
              density="compact"
              :items-per-page="10"
            >
              <template #item.bid_amount="{ item }">
                <span class="text-warning font-weight-bold">{{ item.bid_amount }} 积分</span>
              </template>
              <template #item.bid_time="{ item }">
                {{ formatDateTime(item.bid_time) }}
              </template>
            </v-data-table>
          </div>
          
          <div v-else class="mt-6 text-center">
            <v-alert type="info" density="compact">
              暂无出价记录
            </v-alert>
          </div>
        </v-card-text>
        
        <v-card-actions class="pa-6 pt-0">
          <v-spacer></v-spacer>
          <v-btn @click="closeAuctionDetailDialog" variant="outlined">
            关闭
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 编辑竞拍对话框 -->
    <v-dialog v-model="showEditAuctionDialog" max-width="600px" persistent>
      <v-card v-if="selectedAuction">
        <v-toolbar color="orange" dark flat>
          <v-btn icon dark @click="closeEditAuctionDialog">
            <v-icon>mdi-close</v-icon>
          </v-btn>
          <v-toolbar-title>
            <v-icon class="mr-2">mdi-pencil</v-icon>
            编辑竞拍
          </v-toolbar-title>
        </v-toolbar>
        
        <v-card-text class="pa-6">
          <v-form ref="editAuctionForm">
            <v-row>
              <v-col cols="12">
                <v-text-field
                  v-model="editAuctionForm.title"
                  label="物品名称"
                  :rules="[v => !!v || '物品名称不能为空']"
                  outlined
                  dense
                  required
                ></v-text-field>
              </v-col>
              
              <v-col cols="12">
                <v-text-field
                  v-model.number="editAuctionForm.starting_price"
                  label="起拍价格（积分）"
                  :rules="[v => v > 0 || '起拍价格必须大于0']"
                  type="number"
                  outlined
                  dense
                  min="1"
                  required
                ></v-text-field>
              </v-col>
              
              <v-col cols="12">
                <v-text-field
                  v-model.number="editAuctionForm.duration_hours"
                  label="延长时长（小时）"
                  :rules="[v => v > 0 || '时长必须大于0']"
                  type="number"
                  outlined
                  dense
                  min="1"
                  max="168"
                  hint="修改此项将从现在开始重新计算结束时间"
                  persistent-hint
                ></v-text-field>
              </v-col>
              
              <v-col cols="12">
                <v-textarea
                  v-model="editAuctionForm.description"
                  label="物品描述"
                  outlined
                  dense
                  rows="3"
                  placeholder="请描述竞拍物品的详细信息..."
                  hint="如果不填写，将使用默认描述"
                  persistent-hint
                ></v-textarea>
              </v-col>
            </v-row>
          </v-form>
        </v-card-text>
        
        <v-card-actions class="pa-6 pt-0">
          <v-spacer></v-spacer>
          <v-btn @click="closeEditAuctionDialog" variant="text">
            取消
          </v-btn>
          <v-btn @click="saveAuctionEdit" color="orange" variant="flat">
            保存修改
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 线路用户详情对话框 -->
    <v-dialog v-model="showLineUsersDialogVisible" max-width="500px">
      <v-card v-if="selectedLineStat">
        <v-toolbar color="deep-purple" dark flat>
          <v-btn icon dark @click="closeLineUsersDialog">
            <v-icon>mdi-close</v-icon>
          </v-btn>
          <v-toolbar-title>
            <v-icon class="mr-2">mdi-server-network</v-icon>
            {{ selectedLineStat.line }} - 用户流量排行
          </v-toolbar-title>
        </v-toolbar>
        
        <v-card-text class="pa-4">
          <div class="text-caption text-medium-emphasis mb-3">
            本月流量消耗排行（前{{ selectedLineStat.top_users.length }}名用户）
          </div>
          
          <div class="user-ranking-list">
            <div 
              v-for="(user, index) in selectedLineStat.top_users" 
              :key="user.username"
              class="d-flex align-center justify-space-between py-2"
              :class="{ 'border-b': index < selectedLineStat.top_users.length - 1 }"
            >
              <div class="d-flex align-center">
                <div class="rank-badge mr-3">
                  <v-avatar 
                    :color="getUserRankColor(index)" 
                    size="24"
                  >
                    <span class="text-caption font-weight-bold text-white">
                      {{ index + 1 }}
                    </span>
                  </v-avatar>
                </div>
                <div>
                  <div class="text-body-2 font-weight-medium">{{ user.username }}</div>
                  <div class="text-caption text-medium-emphasis">
                    流量占比: {{ ((user.traffic / selectedLineStat.month_traffic) * 100).toFixed(1) }}%
                  </div>
                </div>
              </div>
              
              <div class="text-right">
                <v-chip 
                  :color="getUserRankColor(index)" 
                  size="small" 
                  variant="tonal"
                  class="font-weight-medium"
                >
                  {{ formatTrafficSize(user.traffic) }}
                </v-chip>
              </div>
            </div>
          </div>
          
          <div class="mt-4 pt-2 border-t">
            <div class="d-flex justify-space-between align-center">
              <span class="text-body-2 font-weight-medium">线路总流量（本月）</span>
              <v-chip color="primary" variant="flat" size="small">
                {{ formatTrafficSize(selectedLineStat.month_traffic) }}
              </v-chip>
            </div>
          </div>
        </v-card-text>
        
        <v-card-actions class="pa-4 pt-0">
          <v-spacer></v-spacer>
          <v-btn @click="closeLineUsersDialog" variant="outlined">
            关闭
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 线路流量详情对话框 -->
    <v-dialog v-model="showLineTrafficDialog" max-width="900">
      <v-card>
        <v-card-title class="text-center bg-blue-darken-2 text-white">
          <v-icon start>mdi-lan</v-icon>
          各线路流量详情
        </v-card-title>
        
        <v-card-text class="pa-6">
          <!-- 标签页切换 -->
          <v-tabs v-model="lineTrafficTab" align-tabs="center" color="blue-darken-2" class="mb-4">
            <v-tab value="today">
              <v-icon start>mdi-calendar-today</v-icon>
              今日
            </v-tab>
            <v-tab value="week">
              <v-icon start>mdi-calendar-week</v-icon>
              本周
            </v-tab>
            <v-tab value="month">
              <v-icon start>mdi-calendar-month</v-icon>
              本月
            </v-tab>
          </v-tabs>

          <!-- 标签页内容 -->
          <v-window v-model="lineTrafficTab">
            <!-- 今日流量 -->
            <v-window-item value="today">
              <div v-if="trafficOverview.today.lines.length === 0" class="text-center py-8">
                <v-icon size="64" color="grey-lighten-1">mdi-database-off</v-icon>
                <div class="text-grey-darken-1 mt-2">暂无今日线路流量数据</div>
              </div>
              <v-row v-else>
                <v-col cols="12" md="6" lg="4" v-for="(line, index) in trafficOverview.today.lines" :key="'today-' + index">
                  <v-card class="line-traffic-card" variant="outlined">
                    <v-card-title class="text-center bg-success text-white py-2">
                      <v-icon start>mdi-server</v-icon>
                      {{ line.line }}
                    </v-card-title>
                    <v-card-text class="text-center py-4">
                      <div class="text-h6 text-success">{{ formatTrafficSize(line.traffic) }}</div>
                      <div class="text-caption text-grey-darken-1">今日流量</div>
                    </v-card-text>
                  </v-card>
                </v-col>
              </v-row>
            </v-window-item>

            <!-- 本周流量 -->
            <v-window-item value="week">
              <div v-if="trafficOverview.week.lines.length === 0" class="text-center py-8">
                <v-icon size="64" color="grey-lighten-1">mdi-database-off</v-icon>
                <div class="text-grey-darken-1 mt-2">暂无本周线路流量数据</div>
              </div>
              <v-row v-else>
                <v-col cols="12" md="6" lg="4" v-for="(line, index) in trafficOverview.week.lines" :key="'week-' + index">
                  <v-card class="line-traffic-card" variant="outlined">
                    <v-card-title class="text-center bg-info text-white py-2">
                      <v-icon start>mdi-server</v-icon>
                      {{ line.line }}
                    </v-card-title>
                    <v-card-text class="text-center py-4">
                      <div class="text-h6 text-info">{{ formatTrafficSize(line.traffic) }}</div>
                      <div class="text-caption text-grey-darken-1">本周流量</div>
                    </v-card-text>
                  </v-card>
                </v-col>
              </v-row>
            </v-window-item>

            <!-- 本月流量 -->
            <v-window-item value="month">
              <div v-if="trafficOverview.month.lines.length === 0" class="text-center py-8">
                <v-icon size="64" color="grey-lighten-1">mdi-database-off</v-icon>
                <div class="text-grey-darken-1 mt-2">暂无本月线路流量数据</div>
              </div>
              <v-row v-else>
                <v-col cols="12" md="6" lg="4" v-for="(line, index) in trafficOverview.month.lines" :key="'month-' + index">
                  <v-card class="line-traffic-card" variant="outlined">
                    <v-card-title class="text-center bg-deep-purple text-white py-2">
                      <v-icon start>mdi-server</v-icon>
                      {{ line.line }}
                    </v-card-title>
                    <v-card-text class="text-center py-4">
                      <div class="text-h6 text-deep-purple">{{ formatTrafficSize(line.traffic) }}</div>
                      <div class="text-caption text-grey-darken-1">本月流量</div>
                    </v-card-text>
                  </v-card>
                </v-col>
              </v-row>
            </v-window-item>
          </v-window>
        </v-card-text>
        
        <v-card-actions class="pa-4 pt-0">
          <v-spacer></v-spacer>
          <v-btn @click="showLineTrafficDialog = false" variant="outlined">
            关闭
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script>
import { getUserInfo, getSystemStats, getPremiumStatistics } from '@/api'
import DonationDialog from '@/components/DonationDialog.vue'
import AdminInviteCodeDialog from '@/components/AdminInviteCodeDialog.vue'
import TagManagementDialog from '@/components/TagManagementDialog.vue'
import LineManagementDialog from '@/components/LineManagementDialog.vue'
import WheelAdminPanel from '@/components/WheelAdminPanel.vue'
import { getAdminSettings, setPlexRegister, setEmbyRegister, setPremiumFree, setFreePremiumLines, setInvitationCredits, setUnlockCredits, setPremiumDailyCredits, setPremiumUnlockEnabled, setCreditsTransferEnabled } from '@/services/adminService.js'
import { getWheelStats } from '@/services/wheelService.js'
import { getAuctionStats, getAllAuctions, finishExpiredAuctions, finishAuction, deleteAuction, createAuction, getAuctionBids, updateAuction } from '@/services/auctionService.js'
import { getPremiumLineTrafficStats, formatTrafficSize, formatUsername, getTrafficOverview } from '@/services/trafficService.js'

export default {
  name: 'Management',
  components: {
    DonationDialog,
    AdminInviteCodeDialog,
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
        premium_unlock_enabled: false,
        credits_transfer_enabled: true,
        invitation_credits: 288,
        unlock_credits: 100,
        premium_daily_credits: 15,
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
      auctionStats: {
        total_auctions: 0,
        active_auctions: 0,
        total_bids: 0,
        total_value: 0.0
      },
      // 竞拍管理相关数据
      auctionStatsLoading: false,
      auctionStatsError: null,
      auctionsLoading: false,
      auctionsError: null,
      auctions: [],
      filteredAuctions: [],
      auctionStatusFilter: 'all',
      finishingExpired: false,
      showCreateAuctionDialog: false,
      showAuctionDetailDialog: false,
      showEditAuctionDialog: false,
      selectedAuction: null,
      auctionBids: [],
      createAuctionForm: {
        item_name: '',
        item_type: 'plex',
        start_price: 100,
        duration_hours: 72,
        description: ''
      },
      editAuctionForm: {
        title: '',
        description: '',
        starting_price: 100,
        duration_hours: 72
      },
      auctionTableHeaders: [
        { title: 'ID', key: 'id', sortable: true, width: 80 },
        { title: '物品', key: 'title', sortable: true },
        { title: '状态', key: 'status', sortable: true, width: 100 },
        { title: '起拍价', key: 'starting_price', sortable: true, width: 120 },
        { title: '当前价', key: 'current_price', sortable: true, width: 120 },
        { title: '结束时间', key: 'end_time', sortable: true, width: 180 },
        { title: '操作', key: 'actions', sortable: false, width: 160 }
      ],
      showWheelManagement: false,
      showAuctionManagement: false,
      systemStats: {
        plex_users: 0,
        emby_users: 0,
        total_users: 0
      },
      systemStatsLoading: false,
      systemStatsError: null,
      premiumStats: {
        total_premium_users: 0,
        active_premium_users: 0,
        premium_plex_users: 0,
        premium_emby_users: 0,
      },
      premiumStatsLoading: false,
      premiumStatsError: null,
      // Premium 线路流量统计相关数据
      trafficStats: [],
      trafficStatsLoading: false,
      trafficStatsError: null,
      showLineUsersDialogVisible: false,
      selectedLineStat: null,
      // 流量概览统计数据
      trafficOverview: {
        today: { total: 0, emby: 0, plex: 0, lines: [] },
        week: { total: 0, emby: 0, plex: 0, lines: [] },
        month: { total: 0, emby: 0, plex: 0, lines: [] }
      },
      trafficOverviewLoading: false,
      trafficOverviewError: null,
      // 线路流量详情对话框
      showLineTrafficDialog: false,
      lineTrafficTab: 'today'
    }
  },
  mounted() {
    this.checkUserStatus()
  },
  watch: {
    // 监听tab切换
    currentTab(newTab) {
      console.log('标签页切换到:', newTab, '是否为管理员:', this.isAdmin)
      // 如果切换到概览tab，则获取系统统计数据
      if (newTab === 'overview') {
        this.fetchSystemStats()
        this.fetchPremiumStats()
        this.fetchTrafficStats()
        this.fetchTrafficOverview()
      }
      // 如果切换到设置项tab且是管理员，则获取管理员设置
      if (newTab === 'settings' && this.isAdmin && !this.adminSettings.loaded) {
        this.fetchAdminSettings()
      }
      // 如果切换到活动管理tab且是管理员，则加载活动统计数据
      if (newTab === 'wheel' && this.isAdmin) {
        console.log('切换到活动管理标签页，开始加载活动数据...')
        this.loadWheelStats()
        this.loadAuctionStats()
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
          await this.fetchPremiumStats()
          await this.fetchTrafficStats()
          await this.fetchTrafficOverview()
        }
        // 如果是管理员且当前在设置项tab，则获取管理员设置
        if (this.isAdmin && this.currentTab === 'settings') {
          await this.fetchAdminSettings()
        }
        // 如果是管理员且当前在活动管理tab，则加载活动统计数据
        if (this.isAdmin && this.currentTab === 'wheel') {
          await this.loadWheelStats()
          await this.loadAuctionStats()
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
    
    async fetchPremiumStats() {
      try {
        this.premiumStatsLoading = true
        this.premiumStatsError = null
        const response = await getPremiumStatistics()
        this.premiumStats = response.data
        this.premiumStatsLoading = false
      } catch (err) {
        this.premiumStatsError = err.response?.data?.detail || '获取Premium统计失败'
        this.premiumStatsLoading = false
        console.error('获取Premium统计失败:', err)
      }
    },
    
    async refreshOverviewStats() {
      await this.fetchSystemStats()
      await this.fetchPremiumStats()
      await this.fetchTrafficStats()
      await this.fetchTrafficOverview()
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
    
    async updatePremiumUnlockEnabled() {
      try {
        await setPremiumUnlockEnabled(this.adminSettings.premium_unlock_enabled)
        this.showMessage('Premium 解锁开放设置已更新')
      } catch (err) {
        // 回滚状态
        this.adminSettings.premium_unlock_enabled = !this.adminSettings.premium_unlock_enabled
        this.showMessage('更新 Premium 解锁开放设置失败', 'error')
        console.error('更新 Premium 解锁开放设置失败:', err)
      }
    },
    
    async updateCreditsTransferEnabled() {
      try {
        await setCreditsTransferEnabled(this.adminSettings.credits_transfer_enabled)
        this.showMessage('积分转移功能设置已更新')
      } catch (err) {
        // 回滚状态
        this.adminSettings.credits_transfer_enabled = !this.adminSettings.credits_transfer_enabled
        this.showMessage('更新积分转移功能设置失败', 'error')
        console.error('更新积分转移功能设置失败:', err)
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
    
    async updatePremiumDailyCredits() {
      try {
        const credits = parseInt(this.adminSettings.premium_daily_credits)
        if (isNaN(credits) || credits < 0) {
          this.showMessage('积分值必须是正整数', 'error')
          // 重新获取设置以恢复状态
          await this.fetchAdminSettings()
          return
        }
        await setPremiumDailyCredits(credits)
        this.showMessage(`解锁 Premium 每日所需积分已设置为 ${credits}`)
      } catch (err) {
        this.showMessage('更新 Premium 每日积分设置失败', 'error')
        console.error('更新 Premium 每日积分设置失败:', err)
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
    
    // 打开邀请码管理对话框
    openInviteCodeDialog() {
      this.$refs.inviteCodeDialog.open();
    },
    
    // 处理邀请码生成完成事件
    handleInviteCodesGenerated(data) {
      console.log('邀请码生成完成:', data);
      // 可以在这里添加额外的处理逻辑，比如刷新统计数据等
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

    // 打开竞拍管理
    openAuctionManagement() {
      this.showAuctionManagement = true;
      // 打开时加载竞拍数据
      if (this.isAdmin) {
        this.loadAuctionData();
      }
    },

    // 关闭竞拍管理
    closeAuctionManagement() {
      this.showAuctionManagement = false;
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
    },

    // 加载竞拍数据
    async loadAuctionData() {
      await Promise.all([
        this.loadAuctionStats(),
        this.loadAuctions()
      ])
    },

    // 加载竞拍统计数据
    async loadAuctionStats() {
      console.log('开始加载竞拍统计数据...')
      try {
        this.auctionStatsLoading = true
        this.auctionStatsError = null
        console.log('调用getAuctionStats API...')
        const response = await getAuctionStats()
        console.log('竞拍统计数据响应:', response.data)
        this.auctionStats = response.data
      } catch (error) {
        console.error('加载竞拍统计失败:', error)
        this.auctionStatsError = error.response?.data?.detail || '加载统计数据失败'
        // 使用默认数据
        this.auctionStats = {
          total_auctions: 0,
          active_auctions: 0,
          total_bids: 0,
          total_value: 0.0
        }
      } finally {
        this.auctionStatsLoading = false
        console.log('竞拍统计数据加载完成:', this.auctionStats)
      }
    },

    // 刷新竞拍统计
    async refreshAuctionStats() {
      await this.loadAuctionStats()
    },

    // 加载竞拍列表
    async loadAuctions() {
      try {
        this.auctionsLoading = true
        this.auctionsError = null
        const response = await getAllAuctions()
        this.auctions = response.data.auctions || []
        this.filterAuctions()
      } catch (error) {
        console.error('加载竞拍列表失败:', error)
        this.auctionsError = error.response?.data?.detail || '加载竞拍列表失败'
        this.auctions = []
        this.filteredAuctions = []
      } finally {
        this.auctionsLoading = false
      }
    },

    // 过滤竞拍活动
    filterAuctions() {
      if (this.auctionStatusFilter === 'all') {
        this.filteredAuctions = [...this.auctions]
      } else {
        this.filteredAuctions = this.auctions.filter(auction => auction.status === this.auctionStatusFilter)
      }
    },

    // 结束过期竞拍
    async finishExpiredAuctionsAction() {
      try {
        this.finishingExpired = true
        await finishExpiredAuctions()
        this.showMessage('已处理过期竞拍活动', 'success')
        await this.loadAuctionData()
      } catch (error) {
        console.error('结束过期竞拍失败:', error)
        this.showMessage('处理过期竞拍失败: ' + (error.response?.data?.detail || error.message), 'error')
      } finally {
        this.finishingExpired = false
      }
    },

    // 查看竞拍详情
    async viewAuctionDetails(auction) {
      try {
        this.selectedAuction = auction
        // 获取竞拍的出价历史
        const response = await getAuctionBids(auction.id)
        this.auctionBids = response.data.bids || []
        this.showAuctionDetailDialog = true
      } catch (error) {
        console.error('获取竞拍详情失败:', error)
        this.showMessage('获取竞拍详情失败: ' + (error.response?.data?.detail || error.message), 'error')
      }
    },

    // 编辑竞拍
    editAuction(auction) {
      this.selectedAuction = auction
      // 填充编辑表单
      this.editAuctionForm = {
        title: auction.title || '',
        description: auction.description || '',
        starting_price: auction.starting_price,
        duration_hours: 72 // 默认72小时
      }
      this.showEditAuctionDialog = true
    },

    // 保存竞拍编辑
    async saveAuctionEdit() {
      if (!this.selectedAuction) return

      try {
        // 确保描述字段不为空
        const updateData = {
          ...this.editAuctionForm,
          description: this.editAuctionForm.description || '竞拍物品'
        }
        await updateAuction(this.selectedAuction.id, updateData)
        this.showMessage('竞拍更新成功', 'success')
        this.showEditAuctionDialog = false
        this.selectedAuction = null
        await this.loadAuctions()
      } catch (error) {
        console.error('更新竞拍失败:', error)
        this.showMessage('更新竞拍失败: ' + (error.response?.data?.detail || error.message), 'error')
      }
    },

    // 关闭竞拍详情对话框
    closeAuctionDetailDialog() {
      this.showAuctionDetailDialog = false
      this.selectedAuction = null
      this.auctionBids = []
    },

    // 关闭编辑竞拍对话框
    closeEditAuctionDialog() {
      this.showEditAuctionDialog = false
      this.selectedAuction = null
      this.editAuctionForm = {
        title: '',
        description: '',
        starting_price: 100,
        duration_hours: 72
      }
    },

    // 结束竞拍
    async finishAuction(auction) {
      const auctionTitle = auction.title || `ID: ${auction.id}` || '未知竞拍活动'
      if (!confirm(`确定要结束竞拍活动 "${auctionTitle}" 吗？`)) {
        return
      }
      
      try {
        await finishAuction(auction.id)
        this.showMessage('竞拍活动已结束', 'success')
        await this.loadAuctions()
      } catch (error) {
        console.error('结束竞拍失败:', error)
        this.showMessage('结束竞拍失败: ' + (error.response?.data?.detail || error.message), 'error')
      }
    },

    // 删除竞拍
    async deleteAuction(auction) {
      const auctionTitle = auction.title || `ID: ${auction.id}` || '未知竞拍活动'
      if (!confirm(`确定要删除竞拍活动 "${auctionTitle}" 吗？此操作不可撤销！`)) {
        return
      }
      
      try {
        await deleteAuction(auction.id)
        this.showMessage('竞拍活动已删除', 'success')
        await this.loadAuctions()
      } catch (error) {
        console.error('删除竞拍失败:', error)
        this.showMessage('删除竞拍失败: ' + (error.response?.data?.detail || error.message), 'error')
      }
    },

    // 获取竞拍状态颜色
    getAuctionStatusColor(status) {
      const colors = {
        active: 'success',
        ended: 'grey',
        cancelled: 'error'
      }
      return colors[status] || 'primary'
    },

    // 获取竞拍状态文本
    getAuctionStatusText(status) {
      const texts = {
        active: '进行中',
        ended: '已结束',
        cancelled: '已取消'
      }
      return texts[status] || status
    },

    // 获取物品类型图标
    getItemTypeIcon(type) {
      const icons = {
        plex: 'mdi-plex',
        emby: 'mdi-emby',
        credits: 'mdi-coin',
        invite: 'mdi-account-plus'
      }
      return icons[type] || 'mdi-package-variant'
    },

    // 获取物品类型颜色
    getItemTypeColor(type) {
      const colors = {
        plex: 'orange',
        emby: 'green',
        credits: 'amber',
        invite: 'blue'
      }
      return colors[type] || 'grey'
    },

    // 格式化日期时间
    formatDateTime(dateTime) {
      if (!dateTime) return '-'
      return new Date(dateTime).toLocaleString('zh-CN')
    },

    // 获取时间状态
    getTimeStatus(endTime) {
      if (!endTime) return ''
      const now = new Date()
      const end = new Date(endTime)
      if (end < now) {
        return '已过期'
      }
      const diff = end - now
      const days = Math.floor(diff / (1000 * 60 * 60 * 24))
      const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
      if (days > 0) {
        return `剩余 ${days} 天 ${hours} 小时`
      } else {
        return `剩余 ${hours} 小时`
      }
    },

    // 创建新竞拍
    async createNewAuction() {
      // 简单验证
      if (!this.createAuctionForm.item_name || 
          this.createAuctionForm.start_price <= 0 || 
          this.createAuctionForm.duration_hours <= 0) {
        this.showMessage('请填写完整的竞拍信息', 'error')
        return
      }
      
      try {
        // 转换字段名以匹配后端API
        const auctionData = {
          title: this.createAuctionForm.item_name,
          description: this.createAuctionForm.description || '竞拍物品',
          starting_price: this.createAuctionForm.start_price,
          duration_hours: this.createAuctionForm.duration_hours
        }
        
        await createAuction(auctionData)
        this.showMessage('竞拍活动创建成功', 'success')
        this.showCreateAuctionDialog = false
        this.resetCreateAuctionForm()
        await this.loadAuctionData()
      } catch (error) {
        console.error('创建竞拍失败:', error)
        this.showMessage('创建竞拍失败: ' + (error.response?.data?.detail || error.message), 'error')
      }
    },

    // 重置创建竞拍表单
    resetCreateAuctionForm() {
      this.createAuctionForm = {
        item_name: '',
        item_type: 'plex',
        start_price: 100,
        duration_hours: 72,
        description: ''
      }
    },
    
    // Premium 线路流量统计相关方法
    async fetchTrafficStats() {
      try {
        this.trafficStatsLoading = true
        this.trafficStatsError = null
        const response = await getPremiumLineTrafficStats()
        this.trafficStats = response.data || []
        this.trafficStatsLoading = false
      } catch (err) {
        this.trafficStatsError = err.response?.data?.detail || '获取流量统计失败'
        this.trafficStatsLoading = false
        console.error('获取Premium线路流量统计失败:', err)
      }
    },
    
    async fetchTrafficOverview() {
      try {
        this.trafficOverviewLoading = true
        this.trafficOverviewError = null
        const response = await getTrafficOverview()
        this.trafficOverview = response.data || {
          today: { total: 0, emby: 0, plex: 0, lines: [] },
          week: { total: 0, emby: 0, plex: 0, lines: [] },
          month: { total: 0, emby: 0, plex: 0, lines: [] }
        }
        this.trafficOverviewLoading = false
      } catch (err) {
        this.trafficOverviewError = err.response?.data?.detail || '获取流量概览失败'
        this.trafficOverviewLoading = false
        console.error('获取流量概览失败:', err)
      }
    },
    
    // 格式化流量大小
    formatTrafficSize(bytes) {
      return formatTrafficSize(bytes)
    },
    
    // 格式化用户名
    formatUsername(username, maxLength = 15) {
      return formatUsername(username, maxLength)
    },
    
    // 获取用户排名颜色
    getUserRankColor(index) {
      const colors = ['amber', 'grey-lighten-1', 'deep-orange-lighten-1', 'blue-lighten-1', 'green-lighten-1']
      return colors[index] || 'grey-lighten-2'
    },
    
    // 获取用户排名图标
    getUserRankIcon(index) {
      const icons = ['mdi-trophy', 'mdi-medal', 'mdi-podium-bronze', 'mdi-numeric-4-circle', 'mdi-numeric-5-circle']
      return icons[index] || 'mdi-account'
    },
    
    // 显示线路用户详情对话框
    showLineUsersDialog(lineStat) {
      this.selectedLineStat = lineStat
      this.showLineUsersDialogVisible = true
    },
    
    // 关闭线路用户详情对话框
    closeLineUsersDialog() {
      this.showLineUsersDialogVisible = false
      this.selectedLineStat = null
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

/* Premium流量统计网格布局 */
.premium-traffic-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 24px;
  margin-top: 8px;
}

/* Premium线路卡片样式 */
.premium-line-card {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(255, 255, 255, 0.98) 100%);
  border-radius: 20px;
  box-shadow: 0 15px 35px rgba(103, 58, 183, 0.1);
  backdrop-filter: blur(15px);
  border: 1px solid rgba(103, 58, 183, 0.15);
  transition: all 0.3s ease;
  overflow: hidden;
  position: relative;
  min-height: 320px;
}

.premium-line-card:hover {
  transform: translateY(-8px);
  box-shadow: 0 25px 50px rgba(103, 58, 183, 0.2);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.98) 0%, rgba(255, 255, 255, 1) 100%);
}

.premium-line-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(135deg, #673ab7 0%, #9c27b0 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.premium-line-card:hover::before {
  opacity: 1;
}

/* 线路标题栏样式 */
.premium-line-header {
  background: linear-gradient(135deg, rgba(103, 58, 183, 0.08) 0%, rgba(156, 39, 176, 0.08) 100%);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(103, 58, 183, 0.15);
  padding: 20px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.line-title-wrapper {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
}

.line-icon {
  margin-right: 12px;
  flex-shrink: 0;
}

.line-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #333;
  margin: 0;
  word-break: break-word;
  line-height: 1.3;
  cursor: help;
}

.status-chip {
  flex-shrink: 0;
  margin-left: 12px;
}

/* 统计区域通用样式 */
.traffic-stats-section,
.ranking-section {
  padding: 20px 24px;
}

.stats-header {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
}

.section-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: #333;
}

/* 流量指标样式 */
.traffic-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.metric-item {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.7) 0%, rgba(255, 255, 255, 0.9) 100%);
  border-radius: 12px;
  padding: 16px 12px;
  text-align: center;
  border: 1px solid rgba(0, 0, 0, 0.06);
  transition: all 0.2s ease;
}

.metric-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.1);
}

.metric-label {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  color: #666;
  margin-bottom: 8px;
  gap: 4px;
}

.metric-value {
  font-size: 1rem;
  font-weight: 700;
  line-height: 1.2;
}

.metric-value.success { color: #2e7d32; }
.metric-value.info { color: #1976d2; }
.metric-value.warning { color: #f57c00; }

/* 排行榜样式 */
.ranking-section {
  border-top: 1px solid rgba(103, 58, 183, 0.1);
  background: linear-gradient(135deg, rgba(103, 58, 183, 0.02) 0%, rgba(156, 39, 176, 0.02) 100%);
}

.ranking-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 10px;
  border: 1px solid rgba(103, 58, 183, 0.1);
  transition: all 0.2s ease;
  margin-bottom: 8px;
}

.ranking-item:hover {
  background: rgba(255, 255, 255, 0.9);
  transform: translateX(4px);
  box-shadow: 0 4px 12px rgba(103, 58, 183, 0.15);
}

.user-info {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
}

.rank-badge {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 12px;
  flex-shrink: 0;
}

.rank-badge.rank-1 { background: linear-gradient(135deg, #ffd700, #ffed4e); }
.rank-badge.rank-2 { background: linear-gradient(135deg, #c0c0c0, #e5e5e5); }
.rank-badge.rank-3 { background: linear-gradient(135deg, #cd7f32, #deb887); }

.username {
  font-size: 0.85rem;
  font-weight: 500;
  color: #333;
  word-break: break-word;
}

.traffic-amount {
  font-size: 0.8rem;
  font-weight: 600;
  color: #666;
  flex-shrink: 0;
}

/* 查看更多按钮 */
.view-more-section {
  text-align: center;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(103, 58, 183, 0.1);
}

.view-more-btn {
  border-radius: 12px;
  text-transform: none;
  font-weight: 500;
}

/* 无数据状态 */
.no-data-section {
  padding: 40px 24px;
  text-align: center;
}

.no-data-content {
  opacity: 0.6;
}

.no-data-text {
  margin-top: 12px;
  font-size: 0.9rem;
  color: #666;
  margin-bottom: 0;
}

/* 响应式适配 */
@media (max-width: 768px) {
  .premium-traffic-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  
  .premium-line-card {
    min-height: 280px;
  }
  
  .premium-line-header {
    padding: 16px 20px;
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }
  
  .status-chip {
    margin-left: 0;
    align-self: flex-end;
  }
  
  .traffic-stats-section,
  .ranking-section {
    padding: 16px 20px;
  }
  
  .traffic-metrics {
    grid-template-columns: 1fr;
    gap: 8px;
  }
  
  .metric-item {
    padding: 12px 10px;
  }
  
  .metric-value {
    font-size: 0.9rem;
  }
  
  .ranking-item {
    padding: 10px 12px;
  }
  
  .username {
    font-size: 0.8rem;
  }
  
  .traffic-amount {
    font-size: 0.75rem;
  }
}

@media (max-width: 480px) {
  .premium-line-header {
    padding: 12px 16px;
  }
  
  .line-title {
    font-size: 1rem;
  }
  
  .traffic-stats-section,
  .ranking-section {
    padding: 12px 16px;
  }
  
  .metric-item {
    padding: 10px 8px;
  }
  
  .metric-label {
    font-size: 0.7rem;
  }
  
  .metric-value {
    font-size: 0.85rem;
  }
}

/* 流量统计卡片样式 - 保留原有的简单卡片样式作为备用 */
.line-traffic-card {
  transition: all 0.3s ease;
  border: 1px solid rgba(0, 0, 0, 0.08);
  height: 100%;
  overflow: hidden;
}

.line-traffic-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

/* 线路标题样式 */
.line-header {
  display: flex;
  align-items: center;
  padding: 16px 16px 8px 16px;
  min-height: 48px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
  background-color: rgba(103, 58, 183, 0.02);
  width: 100%;
  box-sizing: border-box;
}

.line-name {
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.2;
  word-wrap: break-word;
  word-break: break-all;
  overflow-wrap: anywhere;
  hyphens: auto;
  flex: 1;
  color: rgba(0, 0, 0, 0.87);
  max-width: calc(100% - 32px);
  white-space: normal;
  display: block;
  cursor: help;
}

.card-content {
  padding: 16px !important;
}

.traffic-stats .v-chip {
  font-weight: 500;
  font-size: 0.75rem;
  min-width: 60px;
  justify-content: center;
}

.traffic-stats .d-flex {
  min-height: 28px;
}

.top-users-list {
  max-height: 120px;
  overflow-y: auto;
}

.user-ranking-list {
  max-height: 400px;
  overflow-y: auto;
}

.user-ranking-list .border-b {
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}

.rank-badge {
  flex-shrink: 0;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .line-traffic-card {
    margin-bottom: 16px;
  }
  
  .line-header {
    padding: 12px 12px 6px 12px;
    min-height: 40px;
  }
  
  .line-name {
    font-size: 0.9rem;
  }
  
  .card-content {
    padding: 12px !important;
  }
  
  .traffic-stats .v-chip {
    font-size: 0.7rem;
  }
  
  .top-users-list {
    max-height: 100px;
  }
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

/* 小屏幕适配 */
@media (max-width: 960px) {
  .auction-management {
    padding: 0 8px;
  }
  
  .stat-card {
    padding: 12px;
  }
  
  .stat-number {
    font-size: 24px;
  }
  
  .stat-label {
    font-size: 11px;
  }
}

@media (max-width: 600px) {
  .auction-table :deep(.v-data-table) {
    font-size: 13px;
  }
  
  .stat-card {
    padding: 8px;
  }
  
  .stat-number {
    font-size: 20px;
  }
}

/* 线路流量卡片样式 */
.line-traffic-card {
  transition: all 0.3s ease;
  border-radius: 8px;
  overflow: hidden;
}

.line-traffic-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.line-traffic-card .v-card-title {
  font-size: 14px;
  font-weight: 600;
}

.line-traffic-card .text-h6 {
  font-weight: 700;
  font-size: 18px;
}
</style>
