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
              <div class="d-flex">
                <v-btn
                  icon
                  size="x-small"
                  color="amber-darken-2"
                  variant="outlined"
                  @click="openCreditsTransferDialog"
                  title="积分转移"
                  class="mr-2"
                >
                  <v-icon size="small">mdi-bank-transfer</v-icon>
                </v-btn>
                <div class="value-display credits-value">{{ userInfo.credits.toFixed(2) }}</div>
              </div>
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
                <div class="invitation-code-row-horizontal">
                  <div class="invitation-code-container-horizontal">
                    <div class="invitation-code-with-tag">
                      <v-chip 
                        size="small" 
                        :color="privilegedCodes[index] ? 'amber-darken-2' : 'primary'"
                        @click="copyToClipboard(code)"
                        class="invitation-chip-horizontal"
                        elevation="2"
                        rounded="lg"
                        :title="code"
                      >
                        <span class="code-text">{{ code.length > 16 ? code.substring(0, 10) + '...' + code.substring(code.length - 4) : code }}</span>
                        <v-icon end icon="mdi-content-copy" size="small"></v-icon>
                      </v-chip>
                      <!-- 特权码提示文字 - 放在邀请码右侧 -->
                      <div v-if="privilegedCodes[index]" class="privilege-tag-horizontal">
                        <v-icon size="x-small" color="amber-darken-2">mdi-crown</v-icon>
                        <span class="privilege-text">特权</span>
                      </div>
                    </div>
                  </div>
                  <v-btn
                    size="x-small"
                    color="success"
                    variant="outlined"
                    @click="redeemCodeForCredits(code, index)"
                    :loading="redeemingCodes[index]"
                    :disabled="redeemingCodes[index]"
                    class="redeem-button-horizontal"
                    title="兑换为积分"
                  >
                    <v-icon size="small" start>mdi-star</v-icon>
                    兑换积分
                  </v-btn>
                </div>
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
                <v-icon size="small" color="blue-darken-1" class="mr-2">mdi-account</v-icon>
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
                <v-icon size="small" color="red-darken-1" class="mr-2">mdi-email</v-icon>
                <span>邮箱：</span>
              </div>
              <div>{{ userInfo.plex_info.email }}</div>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="purple-darken-1" class="mr-2">mdi-clock-time-four-outline</v-icon>
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
                <v-icon size="small" color="indigo-darken-1" class="mr-2">mdi-folder-multiple</v-icon>
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
                <v-icon size="small" color="teal-darken-1" class="mr-2">mdi-connection</v-icon>
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
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="amber-darken-2" class="mr-2">mdi-crown</v-icon>
                <span>Premium 会员：</span>
              </div>
              <v-btn
                size="small"
                :color="userInfo.plex_info.is_premium ? 'success' : 'blue-grey-lighten-1'"
                :variant="userInfo.plex_info.is_premium ? 'flat' : 'tonal'"
                @click="openPremiumUnlockDialog('plex')"
                :title="!systemStatus.premium_unlock_enabled ? 'Premium 解锁功能暂未开放' : (userInfo.plex_info.is_premium ? '续费 Premium' : '解锁 Premium')"
                :disabled="!systemStatus.premium_unlock_enabled"
                elevation="2"
                rounded="xl"
                class="premium-button"
                :class="{ 'premium-active': userInfo.plex_info.is_premium }"
              >
                <v-icon start size="small">{{ userInfo.plex_info.is_premium ? 'mdi-crown' : 'mdi-crown-outline' }}</v-icon>
                {{ userInfo.plex_info.is_premium ? '已激活 - 续费' : '未激活 - 解锁' }}
              </v-btn>
            </div>
            <div v-if="userInfo.plex_info.is_premium" class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="deep-orange-darken-1" class="mr-2">mdi-clock-outline</v-icon>
                <span>Premium 到期时间：</span>
              </div>
              <div class="text-caption" :class="isPremiumExpiringSoon(userInfo.plex_info.premium_expiry) ? 'text-warning' : ''">
                {{ formatPremiumExpiry(userInfo.plex_info.premium_expiry) }}
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
                <v-icon size="small" color="blue-darken-1" class="mr-2">mdi-account</v-icon>
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
            <div v-if="userInfo.emby_info.created_at" class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="pink-darken-1" class="mr-2">mdi-cake-variant</v-icon>
                <span>破壳日：</span>
              </div>
              <div>{{ userInfo.emby_info.created_at }}</div>
            </div>
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="purple-darken-1" class="mr-2">mdi-clock-time-four-outline</v-icon>
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
                <v-icon size="small" color="indigo-darken-1" class="mr-2">mdi-folder-multiple</v-icon>
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
                <v-icon size="small" color="deep-orange-darken-1" class="mr-2">mdi-web</v-icon>
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
                <v-icon size="small" color="teal-darken-1" class="mr-2">mdi-connection</v-icon>
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
            <div class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="amber-darken-2" class="mr-2">mdi-crown</v-icon>
                <span>Premium 会员：</span>
              </div>
              <v-btn
                size="small"
                :color="userInfo.emby_info.is_premium ? 'success' : 'blue-grey-lighten-1'"
                :variant="userInfo.emby_info.is_premium ? 'flat' : 'tonal'"
                @click="openPremiumUnlockDialog('emby')"
                :title="!systemStatus.premium_unlock_enabled ? 'Premium 解锁功能暂未开放' : (userInfo.emby_info.is_premium ? '续费 Premium' : '解锁 Premium')"
                :disabled="!systemStatus.premium_unlock_enabled"
                elevation="2"
                rounded="xl"
                class="premium-button"
                :class="{ 'premium-active': userInfo.emby_info.is_premium }"
              >
                <v-icon start size="small">{{ userInfo.emby_info.is_premium ? 'mdi-crown' : 'mdi-crown-outline' }}</v-icon>
                {{ userInfo.emby_info.is_premium ? '已激活 - 续费' : '未激活 - 解锁' }}
              </v-btn>
            </div>
            <div v-if="userInfo.emby_info.is_premium" class="d-flex justify-space-between mb-2 align-center">
              <div class="d-flex align-center">
                <v-icon size="small" color="deep-orange-darken-1" class="mr-2">mdi-clock-outline</v-icon>
                <span>Premium 到期时间：</span>
              </div>
              <div class="text-caption" :class="isPremiumExpiringSoon(userInfo.emby_info.premium_expiry) ? 'text-warning' : ''">
                {{ formatPremiumExpiry(userInfo.emby_info.premium_expiry) }}
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
                <v-icon size="small" color="red-darken-1" class="mr-2">mdi-email</v-icon>
                <span>邮箱：</span>
              </div>
              <div>{{ userInfo.overseerr_info.email }}</div>
            </div>
          </v-card-text>
        </v-card>

        <!-- 个人活动数据卡片 -->
        <v-card class="user-info-card mb-4">
          <v-card-title class="card-title-section">
            <v-icon start color="deep-purple-darken-2">mdi-chart-line</v-icon> 个人活动数据
          </v-card-title>
          <v-card-text>
            <!-- 幸运大转盘数据 -->
            <div class="activity-section">
              <div class="section-header">
                <v-icon size="small" color="purple-darken-1" class="mr-2">mdi-wheel-barrow</v-icon>
                <span class="section-title">幸运大转盘</span>
              </div>
              
              <div v-if="activityLoading" class="activity-loading">
                <v-progress-circular 
                  indeterminate 
                  color="primary" 
                  size="30"
                  width="3"
                ></v-progress-circular>
                <span class="ml-2">加载中...</span>
              </div>
              
              <div v-else class="activity-stats-grid">
                <!-- 今日数据 -->
                <div class="stats-card today-stats">
                  <div class="stats-card-header">
                    <v-icon size="small" color="orange-darken-2">mdi-weather-sunny</v-icon>
                    <span>今日数据</span>
                  </div>
                  <div class="stats-items">
                    <div class="stat-item">
                      <span class="stat-label">游戏次数</span>
                      <span class="stat-value today-value">{{ activityStats.today_spins }}</span>
                    </div>
                    <div class="stat-item">
                      <span class="stat-label">积分变化</span>
                      <span 
                        class="stat-value today-value"
                        :class="activityStats.today_credits_change >= 0 ? 'positive' : 'negative'"
                      >
                        {{ activityStats.today_credits_change >= 0 ? '+' : '' }}{{ activityStats.today_credits_change.toFixed(1) }}
                      </span>
                    </div>
                    <div class="stat-item">
                      <span class="stat-label">邀请码获得</span>
                      <span class="stat-value today-value">{{ activityStats.today_invite_codes }}</span>
                    </div>
                  </div>
                </div>

                <!-- 本周数据 -->
                <div class="stats-card week-stats">
                  <div class="stats-card-header">
                    <v-icon size="small" color="blue-darken-2">mdi-calendar-week</v-icon>
                    <span>本周数据</span>
                  </div>
                  <div class="stats-items">
                    <div class="stat-item">
                      <span class="stat-label">游戏次数</span>
                      <span class="stat-value week-value">{{ activityStats.week_spins }}</span>
                    </div>
                    <div class="stat-item">
                      <span class="stat-label">积分变化</span>
                      <span 
                        class="stat-value week-value"
                        :class="activityStats.week_credits_change >= 0 ? 'positive' : 'negative'"
                      >
                        {{ activityStats.week_credits_change >= 0 ? '+' : '' }}{{ activityStats.week_credits_change.toFixed(1) }}
                      </span>
                    </div>
                    <div class="stat-item">
                      <span class="stat-label">邀请码获得</span>
                      <span class="stat-value week-value">{{ activityStats.week_invite_codes }}</span>
                    </div>
                  </div>
                </div>

                <!-- 总计数据 -->
                <div class="stats-card total-stats">
                  <div class="stats-card-header">
                    <v-icon size="small" color="green-darken-2">mdi-chart-box</v-icon>
                    <span>历史总计</span>
                  </div>
                  <div class="stats-items">
                    <div class="stat-item">
                      <span class="stat-label">游戏次数</span>
                      <span class="stat-value total-value">{{ activityStats.total_spins }}</span>
                    </div>
                    <div class="stat-item">
                      <span class="stat-label">积分变化</span>
                      <span 
                        class="stat-value total-value"
                        :class="activityStats.total_credits_change >= 0 ? 'positive' : 'negative'"
                      >
                        {{ activityStats.total_credits_change >= 0 ? '+' : '' }}{{ activityStats.total_credits_change.toFixed(1) }}
                      </span>
                    </div>
                    <div class="stat-item">
                      <span class="stat-label">邀请码获得</span>
                      <span class="stat-value total-value">{{ activityStats.total_invite_codes }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 最近游戏记录 -->
              <div v-if="!activityLoading && activityStats.recent_games && activityStats.recent_games.length > 0" class="recent-games-section">
                <v-divider class="my-3"></v-divider>
                <div class="section-header">
                  <v-icon size="small" color="indigo-darken-1" class="mr-2">mdi-history</v-icon>
                  <span class="section-title">最近游戏记录</span>
                </div>
                <div class="recent-games-list">
                  <div 
                    v-for="(game, index) in activityStats.recent_games" 
                    :key="index" 
                    class="recent-game-item"
                  >
                    <div class="game-result">
                      <v-chip 
                        size="small" 
                        :color="getGameResultColor(game.item_name)"
                        class="game-chip"
                        :title="game.item_name"
                      >
                        {{ game.item_name }}
                      </v-chip>
                    </div>
                    <div class="game-change">
                      <span 
                        class="change-value"
                        :class="game.credits_change >= 0 ? 'positive' : 'negative'"
                      >
                        {{ game.credits_change >= 0 ? '+' : '' }}{{ game.credits_change }}
                      </span>
                    </div>
                    <div class="game-date">
                      {{ formatGameDate(game.date) }}
                    </div>
                  </div>
                </div>
              </div>
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
            您尚未绑定任何媒体服务账户，请先进行绑定
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
    
    <!-- 使用积分转移对话框组件 -->
    <credits-transfer-dialog
      ref="creditsTransferDialog"
      :current-credits="userInfo.credits"
      @transfer-completed="handleCreditsTransferCompleted"
    />
    
    <!-- 使用Premium解锁对话框组件 -->
    <premium-unlock-dialog
      ref="premiumUnlockDialog"
      :current-credits="userInfo.credits"
      :current-premium-expiry="currentPremiumExpiry"
      :is-premium="currentIsPremium"
      @unlock-completed="handlePremiumUnlockCompleted"
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
import { getSystemStatus } from '@/services/systemService'
import EmbyLineSelector from '@/components/EmbyLineSelector.vue'
import PlexLineSelector from '@/components/PlexLineSelector.vue'
import NsfwDialog from '@/components/NsfwDialog.vue'
import DonationDialog from '@/components/DonationDialog.vue'
import CreditsTransferDialog from '@/components/CreditsTransferDialog.vue'
import PremiumUnlockDialog from '@/components/PremiumUnlockDialog.vue'
import TagManagementDialog from '@/components/TagManagementDialog.vue'
import LineManagementDialog from '@/components/LineManagementDialog.vue'
import { getWatchLevelIcons, showNoWatchTimeText } from '@/utils/watchLevel.js'
import { redeemInviteCodeForCredits } from '@/services/inviteCodeService.js'
import { checkPrivilegedInviteCode } from '@/services/mediaServiceApi.js'
import { getUserActivityStats } from '@/services/wheelService.js'

export default {
  name: 'UserInfo',
  components: {
    EmbyLineSelector,
    PlexLineSelector,
    NsfwDialog,
    DonationDialog,
    CreditsTransferDialog,
    PremiumUnlockDialog,
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
      error: null,
      redeemingCodes: {}, // 用于跟踪每个邀请码的兑换状态
      privilegedCodes: {}, // 用于跟踪特权邀请码状态
      activityStats: {
        today_spins: 0,
        total_spins: 0,
        week_spins: 0,
        total_credits_change: 0.0,
        today_credits_change: 0.0,
        week_credits_change: 0.0,
        total_invite_codes: 0,
        today_invite_codes: 0,
        week_invite_codes: 0,
        recent_games: []
      },
      activityLoading: false,
      systemStatus: {
        premium_unlock_enabled: true
      },
      currentPremiumExpiry: null,
      currentIsPremium: false
    }
  },
  mounted() {
    this.fetchUserInfo()
    this.fetchActivityStats()
    this.fetchSystemStatus()
  },
  methods: {
    async fetchUserInfo() {
      try {
        this.loading = true
        const response = await getUserInfo()
        this.userInfo = response.data
        
        // 检查每个邀请码的特权状态
        if (this.userInfo.invitation_codes && this.userInfo.invitation_codes.length > 0) {
          await this.checkPrivilegedCodes()
        }
        
        this.loading = false
      } catch (err) {
        this.error = err.response?.data?.detail || '获取用户信息失败'
        this.loading = false
        console.error('获取用户信息失败:', err)
      }
    },

    // 获取活动数据
    async fetchActivityStats() {
      try {
        this.activityLoading = true
        const response = await getUserActivityStats()
        if (response.data && response.data.success) {
          this.activityStats = response.data.data
        }
      } catch (err) {
        console.error('获取活动统计数据失败:', err)
        // 不显示错误，使用默认值
      } finally {
        this.activityLoading = false
      }
    },

    // 获取系统状态
    async fetchSystemStatus() {
      try {
        const response = await getSystemStatus()
        this.systemStatus = response
      } catch (err) {
        console.error('获取系统状态失败:', err)
        // 使用默认值，不影响用户体验
      }
    },

    // 检查特权邀请码
    async checkPrivilegedCodes() {
      // 重置特权码状态映射
      this.privilegedCodes = {};
      
      for (let i = 0; i < this.userInfo.invitation_codes.length; i++) {
        const code = this.userInfo.invitation_codes[i]
        try {
          const result = await checkPrivilegedInviteCode(code)
          this.privilegedCodes[i] = result.privileged
        } catch (error) {
          console.error(`检查邀请码 ${code} 特权状态失败:`, error)
          this.privilegedCodes[i] = false
        }
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

    // 兑换邀请码为积分
    async redeemCodeForCredits(code, index) {
      // 显示确认提示框
      const confirmed = await this.showConfirmDialog(
        '确认兑换',
        `确定要兑换邀请码 "${code}" 为积分吗？\n\n兑换后将获得该邀请码价值 80% 的积分，且邀请码将被消耗。`
      );

      if (!confirmed) {
        return; // 用户取消了操作
      }

      try {
        // 设置加载状态
        this.redeemingCodes[index] = true;
        
        const response = await redeemInviteCodeForCredits(code);
        
        if (response.success) {
          // 更新用户积分
          this.userInfo.credits = response.current_credits;
          
          // 从邀请码列表中移除已兑换的邀请码
          this.userInfo.invitation_codes.splice(index, 1);
          
          // 更新特权码状态映射 - 移除对应索引，并重新映射后续索引
          const newPrivilegedCodes = {};
          Object.keys(this.privilegedCodes).forEach(key => {
            const keyIndex = parseInt(key);
            if (keyIndex < index) {
              // 保持原索引
              newPrivilegedCodes[keyIndex] = this.privilegedCodes[keyIndex];
            } else if (keyIndex > index) {
              // 索引向前移动
              newPrivilegedCodes[keyIndex - 1] = this.privilegedCodes[keyIndex];
            }
            // 跳过被删除的索引
          });
          this.privilegedCodes = newPrivilegedCodes;
          
          // 同样更新兑换状态映射
          const newRedeemingCodes = {};
          Object.keys(this.redeemingCodes).forEach(key => {
            const keyIndex = parseInt(key);
            if (keyIndex < index) {
              newRedeemingCodes[keyIndex] = this.redeemingCodes[keyIndex];
            } else if (keyIndex > index) {
              newRedeemingCodes[keyIndex - 1] = this.redeemingCodes[keyIndex];
            }
          });
          this.redeemingCodes = newRedeemingCodes;
          
          // 显示成功消息
          const message = `成功兑换！获得 ${response.credits_earned.toFixed(2)} 积分`;
          this.showMessage(message, 'success');
          
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showPopup({
              title: '兑换成功',
              message: message
            });
          }
        } else {
          // 显示错误消息
          this.showMessage(response.message, 'error');
        }
      } catch (error) {
        console.error('兑换邀请码失败:', error);
        this.showMessage('兑换失败，请稍后重试', 'error');
      } finally {
        // 清除加载状态
        if (this.redeemingCodes[index] !== undefined) {
          this.redeemingCodes[index] = false;
        }
      }
    },

    // 显示确认对话框
    showConfirmDialog(title, message) {
      return new Promise((resolve) => {
        if (window.Telegram?.WebApp) {
          // 在 Telegram 环境中使用原生确认对话框
          window.Telegram.WebApp.showConfirm(message, (confirmed) => {
            resolve(confirmed);
          });
        } else {
          // 在开发环境中使用浏览器的 confirm
          const confirmed = confirm(`${title}\n\n${message}`);
          resolve(confirmed);
        }
      });
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
    
    // 打开积分转移对话框
    openCreditsTransferDialog() {
      this.$refs.creditsTransferDialog.open();
    },
    
    // 处理积分转移完成事件
    handleCreditsTransferCompleted(result) {
      const { amount, target_user, current_credits } = result;
      
      // 更新用户积分
      this.userInfo.credits = current_credits;
      
      // 显示成功消息
      this.showMessage(`成功转移 ${amount} 积分给用户 ${target_user}`, 'success');
    },
    
    // 处理捐赠提交事件
    handleDonationSubmitted() {
      // 重新获取用户信息以更新捐赠金额
      this.fetchUserInfo();
    },
    
    // 打开标签管理对话框
    openTagManagementDialog() {
      this.$refs.tagManagementDialog.open();
    },
    
    // 打开线路管理对话框
    openLineManagementDialog() {
      this.$refs.lineManagementDialog.open();
    },
    
    // 打开Premium解锁对话框
    openPremiumUnlockDialog(serviceType) {
      const serviceInfo = serviceType === 'plex' ? 
        this.userInfo.plex_info : 
        this.userInfo.emby_info;
      
      this.currentPremiumExpiry = serviceInfo?.premium_expiry || null;
      this.currentIsPremium = serviceInfo?.is_premium || false;
      
      this.$refs.premiumUnlockDialog.open(serviceType);
    },

    // 处理Premium解锁完成事件
    handlePremiumUnlockCompleted(result) {
      const { service, days, cost, current_credits, premium_expiry } = result;
      
      // 更新用户积分
      this.userInfo.credits = current_credits;
      
      // 更新Premium状态和到期时间
      if (service === 'plex' && this.userInfo.plex_info) {
        this.userInfo.plex_info.is_premium = true;
        this.userInfo.plex_info.premium_expiry = premium_expiry;
      } else if (service === 'emby' && this.userInfo.emby_info) {
        this.userInfo.emby_info.is_premium = true;
        this.userInfo.emby_info.premium_expiry = premium_expiry;
      }

      this.showMessage(`成功解锁 ${days} 天 Premium 会员，消耗 ${cost} 积分`);
    },

    // 格式化Premium到期时间
    formatPremiumExpiry(expiryTime) {
      if (!expiryTime) return '永久';
      try {
        return new Date(expiryTime).toLocaleString('zh-CN', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        });
      } catch (error) {
        return expiryTime;
      }
    },

    // 检查Premium是否即将到期
    isPremiumExpiringSoon(expiryTime) {
      if (!expiryTime) return false;
      try {
        const expiry = new Date(expiryTime);
        const now = new Date();
        const diffDays = Math.ceil((expiry - now) / (1000 * 60 * 60 * 24));
        return diffDays <= 3 && diffDays > 0;
      } catch (error) {
        return false;
      }
    },

    // 根据游戏结果获取颜色
    getGameResultColor(itemName) {
      if (itemName.includes('邀请码')) {
        return 'amber-darken-2'
      } else if (itemName.includes('+')) {
        return 'success'
      } else if (itemName.includes('-')) {
        return 'error'
      } else if (itemName.includes('翻倍')) {
        return 'purple'
      } else if (itemName.includes('减半')) {
        return 'orange-darken-2'
      } else {
        return 'grey'
      }
    },

    // 格式化游戏日期
    formatGameDate(dateString) {
      try {
        const today = new Date().toDateString()
        const gameDate = new Date(dateString).toDateString()
        
        if (today === gameDate) {
          return '今天'
        }
        
        const yesterday = new Date()
        yesterday.setDate(yesterday.getDate() - 1)
        if (yesterday.toDateString() === gameDate) {
          return '昨天'
        }
        
        return dateString
      } catch (error) {
        return dateString
      }
    },
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

/* 加载状态样式 */
.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
  padding: 40px;
}

.loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 30px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
}

.loading-text {
  font-size: 14px;
  color: #666;
  font-weight: 500;
}

/* 错误状态样式 */
.error-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 200px;
  padding: 20px;
}

.error-alert {
  background: rgba(255, 255, 255, 0.95) !important;
  backdrop-filter: blur(10px);
  border: none !important;
  max-width: 500px;
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

/* 通用芯片样式 */
.v-chip {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  border: 1px solid rgba(102, 126, 234, 0.2);
  backdrop-filter: blur(5px);
  transition: all 0.3s ease;
  font-weight: 500;
}

.v-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.v-chip.v-chip--size-small {
  height: 28px !important;
  font-size: 12px !important;
  padding: 0 12px !important;
}

/* Vuetify 主题颜色覆盖 */
.v-chip.v-chip--variant-flat.text-success {
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.15) 0%, rgba(76, 175, 80, 0.08) 100%) !important;
  color: #2E7D32 !important;
  border: 1px solid rgba(76, 175, 80, 0.3) !important;
}

.v-chip.v-chip--variant-flat.text-warning {
  background: linear-gradient(135deg, rgba(255, 152, 0, 0.15) 0%, rgba(255, 152, 0, 0.08) 100%) !important;
  color: #E65100 !important;
  border: 1px solid rgba(255, 152, 0, 0.3) !important;
}

.v-chip.v-chip--variant-flat.text-primary {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 100%) !important;
  color: #3F51B5 !important;
  border: 1px solid rgba(102, 126, 234, 0.3) !important;
}

.v-chip.v-chip--variant-flat.text-amber-darken-2 {
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.15) 0%, rgba(255, 193, 7, 0.08) 100%) !important;
  color: #F57C00 !important;
  border: 1px solid rgba(255, 193, 7, 0.3) !important;
}

/* 特权邀请码芯片样式 - 移除蓝色边框 */
.invitation-chip-horizontal.text-amber-darken-2 {
  border: 1px solid rgba(255, 193, 7, 0.3) !important;
  box-shadow: none !important;
}

.invitation-chip-horizontal.text-amber-darken-2:hover {
  border: 1px solid rgba(255, 193, 7, 0.5) !important;
  box-shadow: 0 4px 12px rgba(255, 193, 7, 0.2) !important;
}

/* 可点击的芯片样式 */
.clickable-chip {
  cursor: pointer;
  transition: all 0.3s ease;
}

.clickable-chip:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15);
}

/* 邀请码芯片样式 */
.invitation-chip {
  cursor: pointer;
  transition: all 0.3s ease;
  font-weight: 500;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 100%) !important;
  border: 1px solid rgba(102, 126, 234, 0.3) !important;
  backdrop-filter: blur(8px);
}

/* 新增：水平布局的邀请码芯片样式 */
.invitation-chip-horizontal {
  cursor: pointer;
  transition: all 0.3s ease;
  font-weight: 500;
  max-width: 100%;
  min-width: 0;
}

/* 普通邀请码的样式 */
.invitation-chip-horizontal:not(.text-amber-darken-2) {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 100%) !important;
  border: 1px solid rgba(102, 126, 234, 0.3) !important;
  backdrop-filter: blur(8px);
}

.invitation-chip:hover,
.invitation-chip-horizontal:not(.text-amber-darken-2):hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15);
}

/* 邀请码文本样式 */
.code-text {
  font-family: 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 160px;
  letter-spacing: 0.5px;
}

/* 值显示样式 */
.value-display {
  padding: 4px 12px;
  border-radius: 12px;
  font-weight: 600;
  font-size: 14px;
  min-width: 60px;
  text-align: center;
  backdrop-filter: blur(5px);
}

.credits-value {
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.1) 0%, rgba(255, 193, 7, 0.05) 100%);
  color: #F57C00;
  border: 1px solid rgba(255, 193, 7, 0.2);
}

.donation-value {
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.1) 0%, rgba(76, 175, 80, 0.05) 100%);
  color: #388E3C;
  border: 1px solid rgba(76, 175, 80, 0.2);
}

/* 观看等级图标样式 */
.level-icons-container {
  display: flex;
  align-items: center;
  gap: 2px;
  cursor: pointer;
  transition: all 0.3s ease;
  padding: 2px 6px;
  border-radius: 8px;
}

.level-icons-container:hover {
  background: rgba(102, 126, 234, 0.1);
  transform: scale(1.05);
}

.emoji-icon {
  font-size: 16px;
  transition: transform 0.2s ease;
}

.emoji-icon:hover {
  transform: scale(1.1);
}

/* 入口线路样式 */
.entrance-url-row {
  position: relative;
}

.entrance-url-chip {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  background: linear-gradient(135deg, rgba(255, 87, 34, 0.1) 0%, rgba(255, 87, 34, 0.05) 100%);
  border: 1px solid rgba(255, 87, 34, 0.2);
  border-radius: 20px;
  color: #D84315;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
  backdrop-filter: blur(5px);
  font-family: 'Monaco', 'Courier New', monospace;
  letter-spacing: 0.3px;
}

.entrance-url-chip:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(255, 87, 34, 0.2);
  background: linear-gradient(135deg, rgba(255, 87, 34, 0.15) 0%, rgba(255, 87, 34, 0.08) 100%);
  border-color: rgba(255, 87, 34, 0.3);
}

/* 线路选择器包装样式 */
.line-selector-wrapper {
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

/* 邀请码容器样式 */
.invitation-code-container {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

/* 新增：水平布局的邀请码容器样式 */
.invitation-code-container-horizontal {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  flex: 1;
  min-width: 0; /* 允许收缩 */
}

/* 新增：邀请码和特权标签的水平容器 */
.invitation-code-with-tag {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

/* 特权码标签样式 */
.privilege-tag {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px 6px;
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.1) 0%, rgba(255, 193, 7, 0.05) 100%);
  border: 1px solid rgba(255, 193, 7, 0.3);
  border-radius: 8px;
  font-size: 10px;
  color: #FF8F00;
  font-weight: 500;
  box-shadow: none !important;
  filter: none !important;
  backdrop-filter: none !important;
}

/* 新增：水平布局的特权码标签样式 */
.privilege-tag-horizontal {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px 6px;
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.15) 0%, rgba(255, 193, 7, 0.08) 100%);
  border: 1px solid rgba(255, 193, 7, 0.4);
  border-radius: 10px;
  font-size: 9px;
  color: #FF8F00;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  box-shadow: none !important;
  filter: none !important;
  backdrop-filter: none !important;
}

/* 确保特权标签不继承任何阴影效果 */
.privilege-tag-horizontal *,
.privilege-tag * {
  box-shadow: none !important;
  filter: none !important;
}

/* 特权标签内的图标样式 */
.privilege-tag-horizontal .v-icon,
.privilege-tag .v-icon {
  box-shadow: none !important;
  filter: none !important;
  text-shadow: none !important;
}

.privilege-text {
  font-size: 10px;
  line-height: 1;
  text-shadow: none !important;
}

/* 邀请码行样式 */
.invitation-code-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

/* 新增：水平布局的邀请码行样式 */
.invitation-code-row-horizontal {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.invitation-code-row:last-child {
  border-bottom: none;
}

.invitation-code-row-horizontal:last-child {
  border-bottom: none;
}

/* 兑换按钮样式 */
.redeem-button {
  flex-shrink: 0;
  font-size: 12px;
  height: 28px;
  border-radius: 14px;
  transition: all 0.3s ease;
}

/* 新增：水平布局的兑换按钮样式 */
.redeem-button-horizontal {
  flex-shrink: 0;
  font-size: 11px;
  height: 32px;
  border-radius: 16px;
  transition: all 0.3s ease;
  min-width: 90px;
}

.redeem-button:hover,
.redeem-button-horizontal:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(76, 175, 80, 0.3);
}

.redeem-button:disabled,
.redeem-button-horizontal:disabled {
  opacity: 0.6;
}

/* 个人活动数据卡片样式 */
.activity-section {
  margin-bottom: 20px;
}

.section-header {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid rgba(102, 126, 234, 0.1);
}

.section-title {
  font-weight: 600;
  font-size: 16px;
  color: #333;
}

.activity-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 30px;
  font-size: 14px;
  color: #666;
}

.activity-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.stats-card {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.9) 100%);
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  padding: 16px;
  transition: all 0.3s ease;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.stats-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
}

.stats-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  font-weight: 600;
  font-size: 14px;
  color: #555;
}

.stats-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}

.stat-label {
  font-size: 13px;
  color: #666;
  font-weight: 500;
}

.stat-value {
  font-weight: 700;
  font-size: 15px;
  padding: 2px 8px;
  border-radius: 6px;
  min-width: 50px;
  text-align: center;
}

.today-value {
  background: linear-gradient(135deg, rgba(255, 152, 0, 0.1) 0%, rgba(255, 152, 0, 0.05) 100%);
  color: #F57C00;
  border: 1px solid rgba(255, 152, 0, 0.2);
}

.week-value {
  background: linear-gradient(135deg, rgba(33, 150, 243, 0.1) 0%, rgba(33, 150, 243, 0.05) 100%);
  color: #1976D2;
  border: 1px solid rgba(33, 150, 243, 0.2);
}

.total-value {
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.1) 0%, rgba(76, 175, 80, 0.05) 100%);
  color: #388E3C;
  border: 1px solid rgba(76, 175, 80, 0.2);
}

.stat-value.positive {
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.15) 0%, rgba(76, 175, 80, 0.08) 100%) !important;
  color: #2E7D32 !important;
  border-color: rgba(76, 175, 80, 0.3) !important;
}

.stat-value.negative {
  background: linear-gradient(135deg, rgba(244, 67, 54, 0.15) 0%, rgba(244, 67, 54, 0.08) 100%) !important;
  color: #C62828 !important;
  border-color: rgba(244, 67, 54, 0.3) !important;
}

/* 最近游戏记录样式 */
.recent-games-section {
  margin-top: 16px;
}

.recent-games-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.recent-game-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: linear-gradient(135deg, rgba(245, 245, 245, 0.6) 0%, rgba(250, 250, 250, 0.8) 100%);
  border-radius: 8px;
  border: 1px solid rgba(0, 0, 0, 0.04);
  transition: all 0.2s ease;
}

.recent-game-item:hover {
  background: linear-gradient(135deg, rgba(240, 240, 240, 0.8) 0%, rgba(248, 248, 248, 0.9) 100%);
  transform: translateX(2px);
}

.game-result {
  flex: 2;
}

.game-chip {
  font-size: 12px !important;
  height: 24px !important;
  max-width: 200px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.game-change {
  flex: 1;
  text-align: center;
}

.change-value {
  font-weight: 600;
  font-size: 14px;
  padding: 2px 6px;
  border-radius: 4px;
}

.change-value.positive {
  color: #2E7D32;
  background: rgba(76, 175, 80, 0.1);
}

.change-value.negative {
  color: #C62828;
  background: rgba(244, 67, 54, 0.1);
}

.game-date {
  flex: 1;
  text-align: right;
  font-size: 12px;
  color: #888;
  font-weight: 500;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .activity-stats-grid {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  
  .stats-card {
    padding: 12px;
  }
  
  .stats-card-header {
    font-size: 13px;
  }
  
  .stat-value {
    font-size: 14px;
    min-width: 45px;
  }
  
  .recent-game-item {
    padding: 8px 10px;
  }
  
  .game-chip {
    font-size: 11px !important;
    height: 22px !important;
    max-width: 150px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .change-value {
    font-size: 13px;
  }
  
  .game-date {
    font-size: 11px;
  }
}

@media (max-width: 480px) {
  .activity-stats-grid {
    gap: 10px;
  }
  
  .stats-card {
    padding: 10px;
  }
  
  .stat-item {
    gap: 8px;
  }
  
  .stat-label {
    font-size: 12px;
  }
  
  .stat-value {
    font-size: 13px;
    min-width: 40px;
    padding: 1px 6px;
  }
  
  .recent-game-item {
    padding: 8px 6px;
    gap: 4px;
  }
  
  .game-result {
    flex: 1.5;
    min-width: 0;
  }
  
  .game-chip {
    font-size: 10px !important;
    height: 20px !important;
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .game-change {
    flex: 1;
    text-align: center;
    min-width: 0;
  }
  
  .change-value {
    font-size: 12px;
    padding: 1px 4px;
  }
  
  .game-date {
    flex: 1;
    text-align: right;
    font-size: 10px;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

/* 超小屏幕优化 */
@media (max-width: 360px) {
  .recent-game-item {
    padding: 6px 4px;
    gap: 2px;
  }
  
  .game-result {
    flex: 1.2;
  }
  
  .game-chip {
    font-size: 9px !important;
    height: 18px !important;
    max-width: 100px;
    padding: 0 4px !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .change-value {
    font-size: 11px;
    padding: 1px 3px;
  }
  
  .game-date {
    font-size: 9px;
  }
}

/* 特殊的卡片颜色变化 */
.today-stats {
  border-left: 4px solid #FF9800;
}

.week-stats {
  border-left: 4px solid #2196F3;
}

.total-stats {
  border-left: 4px solid #4CAF50;
}

/* Premium 按钮美化 */
.premium-button {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  letter-spacing: 0.5px;
  font-weight: 500;
  text-transform: none;
  min-width: 120px;
}

.premium-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.premium-button.premium-active {
  background: linear-gradient(135deg, #4CAF50 0%, #66BB6A 100%);
  color: white;
  box-shadow: 0 2px 8px rgba(76, 175, 80, 0.3);
}

.premium-button.premium-active:hover {
  background: linear-gradient(135deg, #43A047 0%, #5CB85C 100%);
  box-shadow: 0 6px 16px rgba(76, 175, 80, 0.4);
}

.premium-button:not(.premium-active) {
  background: linear-gradient(135deg, #ECEFF1 0%, #CFD8DC 100%);
  color: #263238 !important;
  border: 1px solid rgba(69, 90, 100, 0.3);
  font-weight: 600;
}

.premium-button:not(.premium-active):hover {
  background: linear-gradient(135deg, #E0E7EA 0%, #B0BEC5 100%);
  color: #1A1A1A !important;
  border-color: rgba(69, 90, 100, 0.4);
}

.premium-button .v-icon {
  transition: transform 0.2s ease;
}

.premium-button:hover .v-icon {
  transform: scale(1.1);
}
</style>