<!-- eslint-disable vue/multi-word-component-names -->
<template>
  <div class="rankings-container">
    <div class="content-wrapper">
      <div class="rankings-header">
        <h1 class="page-title">排行榜</h1>
        <p class="page-subtitle">系统数据榜单</p>
        <v-btn 
          color="primary" 
          variant="tonal"
          size="small"
          @click="forceRefreshData"
          class="refresh-btn"
        >
          <v-icon start>mdi-refresh</v-icon>
          刷新数据
        </v-btn>
      </div>
      
      <div v-if="isCurrentTabLoading()" class="loading-container">
        <div class="loading-content">
          <v-progress-circular indeterminate color="primary" size="50" width="4"></v-progress-circular>
          <div class="loading-text">加载中...</div>
        </div>
      </div>

      <div v-else-if="error" class="error-container">
        <v-alert type="error" class="error-alert" rounded="lg" elevation="4">{{ error }}</v-alert>
        <v-btn color="primary" @click="forceRefreshData" class="mt-3">
          重试
        </v-btn>
      </div>

      <div v-else>
        <div class="rankings-tabs-container">
          <v-tabs 
            v-model="activeTab" 
            grow 
            fixed-tabs 
            color="primary"
            bg-color="transparent"
            class="rankings-tabs"
          >
            <v-tab value="credits" class="tab-item">
              <v-icon start size="18">mdi-star</v-icon>
              <span class="tab-text">积分榜</span>
            </v-tab>
            <v-tab value="donation" class="tab-item">
              <v-icon start size="18">mdi-heart</v-icon>
              <span class="tab-text">捐赠榜</span>
            </v-tab>
            <v-tab value="watched" class="tab-item">
              <v-icon start size="18">mdi-clock</v-icon>
              <span class="tab-text">观看时长榜</span>
            </v-tab>
            <v-tab value="traffic" class="tab-item">
              <v-icon start size="18">mdi-download</v-icon>
              <span class="tab-text">流量榜</span>
            </v-tab>
            <v-tab value="badge" class="tab-item">
              <v-icon start size="18">mdi-shield-star</v-icon>
              <span class="tab-text">勋章榜</span>
            </v-tab>
            <v-tab value="invitation" class="tab-item">
              <v-icon start size="18">mdi-account-plus</v-icon>
              <span class="tab-text">邀请榜</span>
            </v-tab>
          </v-tabs>
        </div>

        <div class="rankings-content-container">
          <v-window v-model="activeTab">
          <!-- 积分榜 -->
          <v-window-item value="credits">
            <v-list lines="two" class="px-2">
              <v-list-item
                v-for="(item, index) in rankings.credits_rank"
                :key="`credits-${index}`"
                :class="{ 'bg-primary-subtle': item.is_self }"
                class="ranking-item mb-2"
                rounded="lg"
                elevation="1"
              >
                <template v-slot:prepend>
                  <div class="rank-container">
                    <div class="rank-number" :class="`rank-${index + 1}`">
                      <span v-if="index < 3" class="rank-icon">{{ ['🥇', '🥈', '🥉'][index] }}</span>
                      <span v-else>{{ index + 1 }}</span>
                    </div>
                  </div>
                </template>
                
                <template v-slot:default>
                  <div class="d-flex align-center">
                    <v-avatar class="user-avatar" size="44" style="margin-right: 16px;">
                      <v-img 
                        v-if="item.avatar" 
                        :src="item.avatar" 
                        :alt="item.name"
                        @error="handleImageError"
                        class="avatar-img"
                      />
                      <v-icon v-else size="24" color="grey-lighten-1">mdi-account-circle</v-icon>
                    </v-avatar>
                    <div class="user-info flex-grow-1">
                      <v-list-item-title class="user-name">
                        <div class="user-name-text-wrapper">
                          <span class="user-name-text">{{ item.name }}</span>
                        </div>
                        <!-- 显示用户勋章 -->
                        <span v-if="getUserBadgesList(item.tg_id).length > 0" class="user-badges ml-2">
                          <v-tooltip
                            v-for="badge in getUserBadgesList(item.tg_id).slice(0, getBadgeDisplayLimit())"
                            :key="badge.badge_id"
                            location="top"
                            :open-on-click="isMobile"
                            :open-on-hover="!isMobile"
                          >
                            <template v-slot:activator="{ props }">
                              <v-avatar v-bind="props" size="20" class="badge-avatar">
                                <v-img :src="badge.badge.icon_url" :alt="badge.badge.name" />
                              </v-avatar>
                            </template>
                            <div>{{ badge.badge.name }}</div>
                          </v-tooltip>
                          <!-- 如果有更多勋章，显示省略提示或点击查看所有勋章 -->
                          <v-tooltip 
                            v-if="getUserBadgesList(item.tg_id).length > getBadgeDisplayLimit()" 
                            location="top"
                            :open-on-click="isMobile"
                            :open-on-hover="!isMobile"
                          >
                            <template v-slot:activator="{ props }">
                              <span 
                                v-bind="props" 
                                class="more-badges-indicator"
                                @click="isMobile && showAllBadges(item.tg_id, item.name)"
                              >
                                +{{ getUserBadgesList(item.tg_id).length - getBadgeDisplayLimit() }}
                              </span>
                            </template>
                            <div v-if="!isMobile">还有 {{ getUserBadgesList(item.tg_id).length - getBadgeDisplayLimit() }} 个勋章</div>
                            <div v-else>点击查看所有勋章</div>
                          </v-tooltip>
                        </span>
                      </v-list-item-title>
                      <v-list-item-subtitle class="user-score">
                        <v-icon size="16" color="amber" class="mr-1">mdi-star</v-icon>
                        {{ item.credits.toFixed(2) }} 积分
                      </v-list-item-subtitle>
                    </div>
                  </div>
                </template>
              </v-list-item>
              <v-list-item v-if="rankings.credits_rank.length === 0" class="text-center">
                <v-list-item-title class="text-grey">暂无数据</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-window-item>

          <!-- 捐赠榜 -->
          <v-window-item value="donation">
            <v-list lines="two" class="px-2">
              <v-list-item
                v-for="(item, index) in rankings.donation_rank"
                :key="`donation-${index}`"
                :class="{ 'bg-primary-subtle': item.is_self }"
                class="ranking-item mb-2"
                rounded="lg"
                elevation="1"
              >
                <template v-slot:prepend>
                  <div class="rank-container">
                    <div class="rank-number" :class="`rank-${index + 1}`">
                      <span v-if="index < 3" class="rank-icon">{{ ['🥇', '🥈', '🥉'][index] }}</span>
                      <span v-else>{{ index + 1 }}</span>
                    </div>
                  </div>
                </template>
                
                <template v-slot:default>
                  <div class="d-flex align-center">
                    <v-avatar class="user-avatar" size="44" style="margin-right: 16px;">
                      <v-img 
                        v-if="item.avatar" 
                        :src="item.avatar" 
                        :alt="item.name"
                        @error="handleImageError"
                        class="avatar-img"
                      />
                      <v-icon v-else size="24" color="grey-lighten-1">mdi-account-circle</v-icon>
                    </v-avatar>
                    <div class="user-info flex-grow-1">
                      <v-list-item-title class="user-name">
                        <div class="user-name-text-wrapper">
                          <span class="user-name-text">{{ item.name }}</span>
                        </div>
                        <!-- 显示用户勋章 -->
                        <span v-if="getUserBadgesList(item.tg_id).length > 0" class="user-badges ml-2">
                          <v-tooltip
                            v-for="badge in getUserBadgesList(item.tg_id).slice(0, getBadgeDisplayLimit())"
                            :key="badge.badge_id"
                            location="top"
                            :open-on-click="isMobile"
                            :open-on-hover="!isMobile"
                          >
                            <template v-slot:activator="{ props }">
                              <v-avatar v-bind="props" size="20" class="badge-avatar">
                                <v-img :src="badge.badge.icon_url" :alt="badge.badge.name" />
                              </v-avatar>
                            </template>
                            <div>{{ badge.badge.name }}</div>
                          </v-tooltip>
                          <!-- 如果有更多勋章，显示省略提示或点击查看所有勋章 -->
                          <v-tooltip 
                            v-if="getUserBadgesList(item.tg_id).length > getBadgeDisplayLimit()" 
                            location="top"
                            :open-on-click="isMobile"
                            :open-on-hover="!isMobile"
                          >
                            <template v-slot:activator="{ props }">
                              <span 
                                v-bind="props" 
                                class="more-badges-indicator"
                                @click="isMobile && showAllBadges(item.tg_id, item.name)"
                              >
                                +{{ getUserBadgesList(item.tg_id).length - getBadgeDisplayLimit() }}
                              </span>
                            </template>
                            <div v-if="!isMobile">还有 {{ getUserBadgesList(item.tg_id).length - getBadgeDisplayLimit() }} 个勋章</div>
                            <div v-else>点击查看所有勋章</div>
                          </v-tooltip>
                        </span>
                      </v-list-item-title>
                      <v-list-item-subtitle class="user-score">
                        <v-icon size="16" color="pink" class="mr-1">mdi-heart</v-icon>
                        {{ item.donation.toFixed(2) }} 元
                      </v-list-item-subtitle>
                    </div>
                  </div>
                </template>
              </v-list-item>
              <v-list-item v-if="rankings.donation_rank.length === 0" class="text-center">
                <v-list-item-title class="text-grey">暂无数据</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-window-item>

          <!-- 观看时长榜 -->
          <v-window-item value="watched">
            <!-- 观看时长数据源加载中 -->
            <div v-if="loading[`watched-${watchedTimeSource}`]" class="text-center my-10">
              <v-progress-circular indeterminate color="primary"></v-progress-circular>
              <div class="mt-3">加载{{ watchedTimeSource.toUpperCase() }}数据中...</div>
            </div>
            
            <!-- 没有数据的情况 -->
            <div v-else-if="(watchedTimeSource === 'plex' && rankings.watched_time_rank_plex.length === 0) || 
                            (watchedTimeSource === 'emby' && rankings.watched_time_rank_emby.length === 0)" 
                 class="text-center my-5">
              <v-list-item>
                <v-list-item-title class="text-grey">暂无{{ watchedTimeSource.toUpperCase() }}数据</v-list-item-title>
              </v-list-item>
            </div>
            
            <!-- 有数据的情况 -->
            <v-row v-else>
              <v-col cols="12">
                <div class="d-flex justify-space-between align-center mb-4">
                  <div class="d-flex align-center gap-2">
                    <h3 class="text-h6 text-primary font-weight-bold">观看时长排行</h3>
                    <v-btn
                      icon
                      size="x-small"
                      variant="text"
                      color="primary"
                      @click="showLevelInfo = true"
                      class="info-btn"
                    >
                      <v-icon size="16">mdi-information</v-icon>
                      <v-tooltip activator="parent" location="top">
                        等级说明
                      </v-tooltip>
                    </v-btn>
                  </div>
                  <v-select
                      v-model="watchedTimeSource"
                      :items="[
                        { title: 'Plex', value: 'plex' },
                        { title: 'Emby', value: 'emby' }
                      ]"
                      item-title="title"
                      item-value="value"
                      density="compact"
                      hide-details
                      variant="outlined"
                      class="control-select watched-source-select"
                      style="max-width: 150px;"
                      color="primary"
                    >
                      <template v-slot:prepend-inner>
                        <v-icon size="16" :color="watchedTimeSource === 'plex' ? 'orange' : 'green'">
                          {{ watchedTimeSource === 'plex' ? 'mdi-plex' : 'mdi-emby' }}
                        </v-icon>
                      </template>
                    </v-select>
                </div>
                
                <!-- Plex 观看时长榜 -->
                <div v-if="watchedTimeSource === 'plex'" class="transparent-list">
                  <v-list lines="two" class="px-2 transparent-list-content">
                    <v-list-item
                      v-for="(item, index) in rankings.watched_time_rank_plex"
                      :key="`plex-watched-${index}`"
                      :class="{ 'bg-primary-subtle': item.is_self }"
                      class="ranking-item mb-2"
                      rounded="lg"
                      elevation="1"
                    >
                      <template v-slot:prepend>
                        <div class="rank-container">
                          <div class="rank-number" :class="`rank-${index + 1}`">
                            <span v-if="index < 3" class="rank-icon">{{ ['🥇', '🥈', '🥉'][index] }}</span>
                            <span v-else>{{ index + 1 }}</span>
                          </div>
                        </div>
                      </template>
                      
                      <template v-slot:default>
                        <div class="d-flex align-center">
                          <v-avatar class="user-avatar" size="44" style="margin-right: 16px;">
                            <v-img 
                              v-if="item.avatar" 
                              :src="item.avatar" 
                              :alt="item.name"
                              @error="handleImageError"
                              class="avatar-img"
                            />
                            <v-icon v-else size="24" color="orange">mdi-plex</v-icon>
                          </v-avatar>
                          <div class="user-info flex-grow-1">
                            <v-list-item-title class="user-name">
                              <div class="user-name-text-wrapper">
                                <span class="user-name-text">{{ item.name }}</span>
                              </div>
                              <v-chip
                                v-if="item.is_premium"
                                size="x-small"
                                color="amber"
                                variant="elevated"
                                class="ml-2 premium-badge"
                              >
                                <v-icon size="12" class="premium-icon">mdi-crown</v-icon>
                                <span class="premium-text d-none d-md-inline">PREMIUM</span>
                                <span class="premium-text-short d-none d-sm-inline d-md-none">VIP</span>
                              </v-chip>
                            </v-list-item-title>
                            <v-list-item-subtitle class="user-score">
                              <div class="d-flex align-center watched-time-container">
                                <v-icon size="16" color="orange" class="mr-1">mdi-clock</v-icon>
                                <span class="watched-time-text">{{ item.watched_time.toFixed(2) }} 小时</span>
                                <div class="level-icons-wrapper ml-2">
                                  <v-tooltip
                                    v-for="(icon, iconIndex) in getWatchLevelIcons(item.watched_time)"
                                    :key="`plex-rank-icon-${index}-${iconIndex}`"
                                    location="top"
                                    :text="getIconTooltip(icon.icon)"
                                  >
                                    <template v-slot:activator="{ props }">
                                      <span 
                                        v-bind="props"
                                        :class="['emoji-icon', icon.class]"
                                      >
                                        {{ icon.icon }}
                                      </span>
                                    </template>
                                  </v-tooltip>
                                </div>
                              </div>
                            </v-list-item-subtitle>
                          </div>
                        </div>
                      </template>
                    </v-list-item>
                    <v-list-item v-if="rankings.watched_time_rank_plex.length === 0" class="text-center">
                      <v-list-item-title class="text-grey">暂无数据</v-list-item-title>
                    </v-list-item>
                  </v-list>
                </div>
                
                <!-- Emby 观看时长榜 -->
                <div v-if="watchedTimeSource === 'emby'" class="transparent-list">
                  <v-list lines="two" class="px-2 transparent-list-content">
                    <v-list-item
                      v-for="(item, index) in rankings.watched_time_rank_emby"
                      :key="`emby-watched-${index}`"
                      :class="{ 'bg-primary-subtle': item.is_self }"
                      class="ranking-item mb-2"
                      rounded="lg"
                      elevation="1"
                    >
                      <template v-slot:prepend>
                        <div class="rank-container">
                          <div class="rank-number" :class="`rank-${index + 1}`">
                            <span v-if="index < 3" class="rank-icon">{{ ['🥇', '🥈', '🥉'][index] }}</span>
                            <span v-else>{{ index + 1 }}</span>
                          </div>
                        </div>
                      </template>
                      
                      <template v-slot:default>
                        <div class="d-flex align-center">
                          <v-avatar class="user-avatar" size="44" style="margin-right: 16px;">
                            <v-img 
                              v-if="item.avatar" 
                              :src="item.avatar" 
                              :alt="item.name"
                              @error="handleImageError"
                              class="avatar-img"
                            />
                            <v-icon v-else size="24" color="green">mdi-emby</v-icon>
                          </v-avatar>
                          <div class="user-info flex-grow-1">
                            <v-list-item-title class="user-name">
                              <div class="user-name-text-wrapper">
                                <span class="user-name-text">{{ item.name }}</span>
                              </div>
                              <v-chip
                                v-if="item.is_premium"
                                size="x-small"
                                color="amber"
                                variant="elevated"
                                class="ml-2 premium-badge"
                              >
                                <v-icon size="12" class="premium-icon">mdi-crown</v-icon>
                                <span class="premium-text d-none d-md-inline">PREMIUM</span>
                                <span class="premium-text-short d-none d-sm-inline d-md-none">VIP</span>
                              </v-chip>
                            </v-list-item-title>
                            <v-list-item-subtitle class="user-score">
                              <div class="d-flex align-center watched-time-container">
                                <v-icon size="16" color="green" class="mr-1">mdi-clock</v-icon>
                                <span class="watched-time-text">{{ item.watched_time.toFixed(2) }} 小时</span>
                                <div class="level-icons-wrapper ml-2">
                                  <v-tooltip
                                    v-for="(icon, iconIndex) in getWatchLevelIcons(item.watched_time)"
                                    :key="`emby-rank-icon-${index}-${iconIndex}`"
                                    location="top"
                                    :text="getIconTooltip(icon.icon)"
                                  >
                                    <template v-slot:activator="{ props }">
                                      <span 
                                        v-bind="props"
                                        :class="['emoji-icon', icon.class]"
                                      >
                                        {{ icon.icon }}
                                      </span>
                                    </template>
                                  </v-tooltip>
                                </div>
                              </div>
                            </v-list-item-subtitle>
                          </div>
                        </div>
                      </template>
                    </v-list-item>
                    <v-list-item v-if="rankings.watched_time_rank_emby.length === 0" class="text-center">
                      <v-list-item-title class="text-grey">暂无数据</v-list-item-title>
                    </v-list-item>
                  </v-list>
                </div>
              </v-col>
            </v-row>
          </v-window-item>

          <!-- 流量日榜 -->
          <v-window-item value="traffic">
            <!-- 流量数据源加载中 -->
            <div v-if="loading[`traffic-${trafficSource}`]" class="text-center my-10">
              <v-progress-circular indeterminate color="primary"></v-progress-circular>
              <div class="mt-3">加载{{ trafficSource.toUpperCase() }}数据中...</div>
            </div>
            
            <!-- 没有数据的情况 -->
            <div v-else-if="(trafficSource === 'plex' && rankings.traffic_rank_plex.length === 0) || 
                            (trafficSource === 'emby' && rankings.traffic_rank_emby.length === 0)" 
                 class="text-center my-5">
              <v-list-item>
                <v-list-item-title class="text-grey">暂无{{ trafficSource.toUpperCase() }}数据</v-list-item-title>
              </v-list-item>
            </div>
            
            <!-- 有数据的情况 -->
            <v-row v-else>
              <v-col cols="12">
                <div class="d-flex justify-space-between align-center mb-4">
                  <div class="d-flex align-center gap-2">
                    <h3 class="text-h6 text-primary font-weight-bold">流量排行</h3>
                    <v-chip size="small" :color="getDateRangeChipColor()" variant="elevated" class="ml-2">
                      <v-icon start size="12">mdi-calendar-today</v-icon>
                      {{ getDateRangeText() }}
                    </v-chip>
                  </div>
                  <div class="d-flex align-center gap-4">
                    <!-- 日期范围选择 -->
                    <v-select
                      v-model="trafficDateRange"
                      :items="[
                        { title: '今日', value: 'today' },
                        { title: '昨日', value: 'yesterday' },
                        { title: '本周', value: 'week' },
                        { title: '本月', value: 'month' },
                        { title: '自定义', value: 'custom' }
                      ]"
                      item-title="title"
                      item-value="value"
                      density="compact"
                      hide-details
                      variant="outlined"
                      class="control-select date-range-select"
                      color="primary"
                    >
                      <template v-slot:prepend-inner>
                        <v-icon size="16" color="primary">mdi-calendar-range</v-icon>
                      </template>
                    </v-select>

                    <!-- 自定义日期按钮 -->
                    <v-btn
                      v-if="trafficDateRange === 'custom'"
                      icon
                      size="small"
                      variant="outlined"
                      color="primary"
                      @click="showDatePicker = true"
                      class="custom-date-btn"
                    >
                      <v-icon size="18">mdi-calendar-edit</v-icon>
                      <v-tooltip activator="parent" location="top">
                        选择日期范围
                      </v-tooltip>
                    </v-btn>

                    <!-- 数据源选择 -->
                    <v-select
                        v-model="trafficSource"
                        :items="[
                          { title: 'Plex', value: 'plex' },
                          { title: 'Emby', value: 'emby' }
                        ]"
                        item-title="title"
                        item-value="value"
                        density="compact"
                        hide-details
                        variant="outlined"
                        class="control-select traffic-source-select"
                        color="primary"
                      >
                        <template v-slot:prepend-inner>
                          <v-icon size="16" :color="trafficSource === 'plex' ? 'orange' : 'green'">
                            {{ trafficSource === 'plex' ? 'mdi-plex' : 'mdi-emby' }}
                          </v-icon>
                        </template>
                      </v-select>
                  </div>
                </div>
                
                <!-- Plex 流量榜 -->
                <div v-if="trafficSource === 'plex'" class="transparent-list">
                  <v-list lines="two" class="px-2 transparent-list-content">
                    <v-list-item
                      v-for="(item, index) in rankings.traffic_rank_plex"
                      :key="`plex-traffic-${index}`"
                      :class="{ 'bg-primary-subtle': item.is_self }"
                      class="ranking-item mb-2"
                      rounded="lg"
                      elevation="1"
                    >
                      <template v-slot:prepend>
                        <div class="rank-container">
                          <div class="rank-number" :class="`rank-${index + 1}`">
                            <span v-if="index < 3" class="rank-icon">{{ ['🥇', '🥈', '🥉'][index] }}</span>
                            <span v-else>{{ index + 1 }}</span>
                          </div>
                        </div>
                      </template>
                      
                      <template v-slot:default>
                        <div class="d-flex align-center">
                          <v-avatar class="user-avatar" size="44" style="margin-right: 16px;">
                            <v-img 
                              v-if="item.avatar" 
                              :src="item.avatar" 
                              :alt="item.name"
                              @error="handleImageError"
                              class="avatar-img"
                            />
                            <v-icon v-else size="24" color="orange">mdi-plex</v-icon>
                          </v-avatar>
                          <div class="user-info flex-grow-1">
                            <v-list-item-title class="user-name">
                              <div class="user-name-text-wrapper">
                                <span class="user-name-text">{{ item.name }}</span>
                              </div>
                              <v-chip
                                v-if="item.is_premium"
                                size="x-small"
                                color="amber"
                                variant="elevated"
                                class="ml-2 premium-badge"
                              >
                                <v-icon size="12" class="premium-icon">mdi-crown</v-icon>
                                <span class="premium-text d-none d-md-inline">PREMIUM</span>
                                <span class="premium-text-short d-none d-sm-inline d-md-none">VIP</span>
                              </v-chip>
                            </v-list-item-title>
                            <v-list-item-subtitle class="user-score">
                              <div class="d-flex align-center traffic-container">
                                <v-icon size="16" color="orange" class="mr-1">mdi-download</v-icon>
                                <span class="traffic-text">{{ formatTraffic(item.traffic) }}</span>
                                <div class="ml-2">
                                  <v-chip size="x-small" color="orange" variant="tonal">
                                    {{ getDateRangeText() }}
                                  </v-chip>
                                </div>
                              </div>
                            </v-list-item-subtitle>
                          </div>
                        </div>
                      </template>
                    </v-list-item>
                    <v-list-item v-if="rankings.traffic_rank_plex.length === 0" class="text-center">
                      <v-list-item-title class="text-grey">暂无数据</v-list-item-title>
                    </v-list-item>
                  </v-list>
                </div>
                
                <!-- Emby 流量榜 -->
                <div v-if="trafficSource === 'emby'" class="transparent-list">
                  <v-list lines="two" class="px-2 transparent-list-content">
                    <v-list-item
                      v-for="(item, index) in rankings.traffic_rank_emby"
                      :key="`emby-traffic-${index}`"
                      :class="{ 'bg-primary-subtle': item.is_self }"
                      class="ranking-item mb-2"
                      rounded="lg"
                      elevation="1"
                    >
                      <template v-slot:prepend>
                        <div class="rank-container">
                          <div class="rank-number" :class="`rank-${index + 1}`">
                            <span v-if="index < 3" class="rank-icon">{{ ['🥇', '🥈', '🥉'][index] }}</span>
                            <span v-else>{{ index + 1 }}</span>
                          </div>
                        </div>
                      </template>
                      
                      <template v-slot:default>
                        <div class="d-flex align-center">
                          <v-avatar class="user-avatar" size="44" style="margin-right: 16px;">
                            <v-img 
                              v-if="item.avatar" 
                              :src="item.avatar" 
                              :alt="item.name"
                              @error="handleImageError"
                              class="avatar-img"
                            />
                            <v-icon v-else size="24" color="green">mdi-emby</v-icon>
                          </v-avatar>
                          <div class="user-info flex-grow-1">
                            <v-list-item-title class="user-name">
                              <div class="user-name-text-wrapper">
                                <span class="user-name-text">{{ item.name }}</span>
                              </div>
                              <v-chip
                                v-if="item.is_premium"
                                size="x-small"
                                color="amber"
                                variant="elevated"
                                class="ml-2 premium-badge"
                              >
                                <v-icon size="12" class="premium-icon">mdi-crown</v-icon>
                                <span class="premium-text d-none d-md-inline">PREMIUM</span>
                                <span class="premium-text-short d-none d-sm-inline d-md-none">VIP</span>
                              </v-chip>
                            </v-list-item-title>
                            <v-list-item-subtitle class="user-score">
                              <div class="d-flex align-center traffic-container">
                                <v-icon size="16" color="green" class="mr-1">mdi-download</v-icon>
                                <span class="traffic-text">{{ formatTraffic(item.traffic) }}</span>
                                <div class="ml-2">
                                  <v-chip size="x-small" color="green" variant="tonal">
                                    {{ getDateRangeText() }}
                                  </v-chip>
                                </div>
                              </div>
                            </v-list-item-subtitle>
                          </div>
                        </div>
                      </template>
                    </v-list-item>
                    <v-list-item v-if="rankings.traffic_rank_emby.length === 0" class="text-center">
                      <v-list-item-title class="text-grey">暂无数据</v-list-item-title>
                    </v-list-item>
                  </v-list>
                </div>
              </v-col>
            </v-row>
          </v-window-item>

          <!-- 勋章榜 -->
          <v-window-item value="badge">
            <v-list lines="two" class="px-2">
              <v-list-item
                v-for="(item, index) in rankings.badge_rank"
                :key="`badge-${index}`"
                :class="{ 'bg-primary-subtle': item.is_self }"
                class="ranking-item mb-2"
                rounded="lg"
                elevation="1"
              >
                <template v-slot:prepend>
                  <div class="rank-container">
                    <div class="rank-number" :class="`rank-${index + 1}`">
                      <span v-if="index < 3" class="rank-icon">{{ ['🥇', '🥈', '🥉'][index] }}</span>
                      <span v-else>{{ index + 1 }}</span>
                    </div>
                  </div>
                </template>
                
                <template v-slot:default>
                  <div class="d-flex align-center">
                    <v-avatar class="user-avatar" size="44" style="margin-right: 16px;">
                      <v-img 
                        v-if="item.avatar" 
                        :src="item.avatar" 
                        :alt="item.name"
                        @error="handleImageError"
                        class="avatar-img"
                      />
                      <v-icon v-else size="24" color="grey-lighten-1">mdi-account-circle</v-icon>
                    </v-avatar>
                    <div class="user-info flex-grow-1">
                      <v-list-item-title class="user-name">
                        <div class="user-name-text-wrapper">
                          <span class="user-name-text">{{ item.name }}</span>
                        </div>
                        <v-chip
                          size="x-small"
                          color="amber"
                          variant="tonal"
                          class="ml-2"
                        >
                          <v-icon size="12" start>mdi-shield-star</v-icon>
                          {{ item.badge_count }} 枚
                        </v-chip>
                      </v-list-item-title>
                      <v-list-item-subtitle class="user-score">
                        <div class="badge-list-container d-flex flex-wrap align-center gap-1">
                          <v-tooltip
                            v-for="userBadge in item.badges.slice(0, 6)"
                            :key="userBadge.badge_id"
                            location="top"
                            :open-on-click="isMobile"
                            :open-on-hover="!isMobile"
                          >
                            <template v-slot:activator="{ props }">
                              <v-avatar v-bind="props" size="24" class="badge-avatar-item">
                                <v-img :src="userBadge.badge.icon_url" :alt="userBadge.badge.name" />
                              </v-avatar>
                            </template>
                            <div class="text-center">
                              <div class="font-weight-medium">{{ userBadge.badge.name }}</div>
                              <div class="text-caption">{{ userBadge.badge.description }}</div>
                              <div v-if="userBadge.bonus_active" class="text-caption text-success">
                                <v-icon size="12">mdi-lightning-bolt</v-icon>
                                加成生效中
                              </div>
                            </div>
                          </v-tooltip>
                          <v-tooltip 
                            v-if="item.badges.length > 6" 
                            location="top"
                            :open-on-click="isMobile"
                            :open-on-hover="!isMobile"
                          >
                            <template v-slot:activator="{ props }">
                              <span 
                                v-bind="props" 
                                class="more-badges-indicator"
                                @click="isMobile && showBadgeRankBadges(item.tg_id, item.name, item.badges)"
                              >
                                +{{ item.badges.length - 6 }}
                              </span>
                            </template>
                            <div>还有 {{ item.badges.length - 6 }} 个勋章</div>
                          </v-tooltip>
                        </div>
                      </v-list-item-subtitle>
                    </div>
                  </div>
                </template>
              </v-list-item>
              <v-list-item v-if="rankings.badge_rank.length === 0" class="text-center">
                <v-list-item-title class="text-grey">暂无数据</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-window-item>

          <!-- 邀请榜 -->
          <v-window-item value="invitation">
            <v-list lines="two" class="px-2">
              <v-list-item
                v-for="(item, index) in rankings.invitation_rank"
                :key="`invitation-${index}`"
                :class="{ 'bg-primary-subtle': item.is_self }"
                class="ranking-item mb-2"
                rounded="lg"
                elevation="1"
              >
                <template v-slot:prepend>
                  <div class="rank-container">
                    <div class="rank-number" :class="`rank-${index + 1}`">
                      <span v-if="index < 3" class="rank-icon">{{ ['🥇', '🥈', '🥉'][index] }}</span>
                      <span v-else>{{ index + 1 }}</span>
                    </div>
                  </div>
                </template>
                
                <template v-slot:default>
                  <div class="d-flex align-center">
                    <v-avatar class="user-avatar" size="44" style="margin-right: 16px;">
                      <v-img 
                        v-if="item.avatar" 
                        :src="item.avatar" 
                        :alt="item.name"
                        @error="handleImageError"
                        class="avatar-img"
                      />
                      <v-icon v-else size="24" color="grey-lighten-1">mdi-account-circle</v-icon>
                    </v-avatar>
                    <div class="user-info flex-grow-1">
                      <v-list-item-title class="user-name">
                        <div class="user-name-text-wrapper">
                          <span class="user-name-text">{{ item.name }}</span>
                        </div>
                      </v-list-item-title>
                      <v-list-item-subtitle class="user-score">
                        <v-icon size="16" color="green" class="mr-1">mdi-account-plus</v-icon>
                        {{ item.invite_count }} 人
                      </v-list-item-subtitle>
                    </div>
                  </div>
                </template>
              </v-list-item>
              <v-list-item v-if="rankings.invitation_rank.length === 0" class="text-center">
                <v-list-item-title class="text-grey">暂无数据</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-window-item>
        </v-window>
        </div>
      </div>
    </div>

    <!-- 等级说明对话框 -->
    <v-dialog v-model="showLevelInfo" max-width="720">
      <v-card class="level-dialog">
        <v-card-title class="text-h6 d-flex align-center justify-center pa-6">
          <v-icon color="primary" class="mr-2" size="28">mdi-star-circle</v-icon>
          <span class="dialog-title">观看等级说明</span>
        </v-card-title>
        
        <v-card-text class="py-6">
          <div class="level-explanation">
            <!-- 级别进度条示意 -->
            <div class="level-progress-demo mb-6">
              <div class="d-flex align-center justify-center gap-3">
                <div class="level-demo-icon crown-icon">👑</div>
                <v-icon size="12" color="grey-lighten-1">mdi-arrow-left</v-icon>
                <div class="level-demo-icon sun-icon">☀️</div>
                <v-icon size="12" color="grey-lighten-1">mdi-arrow-left</v-icon>
                <div class="level-demo-icon moon-icon">🌙</div>
                <v-icon size="12" color="grey-lighten-1">mdi-arrow-left</v-icon>
                <div class="level-demo-icon star-icon">⭐</div>
              </div>
              <div class="text-center mt-2">
                <span class="level-progress-text">等级进阶路径</span>
              </div>
            </div>

            <!-- 等级详细说明 -->
            <v-row>
              <v-col cols="12" sm="6">
                <div class="level-item">
                  <div class="level-header">
                    <div class="level-emoji-container star-bg">
                      <span class="level-emoji star-icon">⭐</span>
                    </div>
                    <div class="level-info">
                      <div class="level-title">星星</div>
                      <div class="level-subtitle">入门等级</div>
                    </div>
                  </div>
                  <div class="level-desc">
                    <div class="level-requirement">每 100 小时 = 1 颗星星</div>
                    <div class="level-example">例：300 小时 = 3 颗星星</div>
                  </div>
                </div>
              </v-col>
              
              <v-col cols="12" sm="6">
                <div class="level-item">
                  <div class="level-header">
                    <div class="level-emoji-container moon-bg">
                      <span class="level-emoji moon-icon">🌙</span>
                    </div>
                    <div class="level-info">
                      <div class="level-title">月亮</div>
                      <div class="level-subtitle">进阶等级</div>
                    </div>
                  </div>
                  <div class="level-desc">
                    <div class="level-requirement">4 颗星星 = 1 个月亮</div>
                    <div class="level-example">需要观看 400 小时</div>
                  </div>
                </div>
              </v-col>
              
              <v-col cols="12" sm="6">
                <div class="level-item">
                  <div class="level-header">
                    <div class="level-emoji-container sun-bg">
                      <span class="level-emoji sun-icon">☀️</span>
                    </div>
                    <div class="level-info">
                      <div class="level-title">太阳</div>
                      <div class="level-subtitle">高级等级</div>
                    </div>
                  </div>
                  <div class="level-desc">
                    <div class="level-requirement">4 个月亮 = 1 个太阳</div>
                    <div class="level-example">需要观看 1600 小时</div>
                  </div>
                </div>
              </v-col>
              
              <v-col cols="12" sm="6">
                <div class="level-item">
                  <div class="level-header">
                    <div class="level-emoji-container crown-bg">
                      <span class="level-emoji crown-icon">👑</span>
                    </div>
                    <div class="level-info">
                      <div class="level-title">皇冠</div>
                      <div class="level-subtitle">至尊等级</div>
                    </div>
                  </div>
                  <div class="level-desc">
                    <div class="level-requirement">4 个太阳 = 1 个皇冠</div>
                    <div class="level-example">需要观看 6400 小时</div>
                  </div>
                </div>
              </v-col>
            </v-row>

            <!-- 等级计算说明 -->
            <v-divider class="my-4"></v-divider>
            <div class="calculation-note">
              <v-icon size="16" color="info" class="mr-2">mdi-information</v-icon>
              <span class="text-caption text-medium-emphasis">
                等级图标会根据您的总观看时长自动显示，多个等级可以同时拥有
              </span>
            </div>
          </div>
        </v-card-text>
        
        <v-card-actions class="pa-6">
          <v-spacer></v-spacer>
          <v-btn 
            color="primary" 
            variant="elevated"
            size="large"
            rounded="lg"
            @click="showLevelInfo = false"
            class="px-8"
          >
            <v-icon class="mr-2">mdi-check</v-icon>
            知道了
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 自定义日期选择对话框 -->
    <v-dialog v-model="showDatePicker" max-width="480">
      <v-card class="date-picker-dialog">
        <v-card-title class="text-h6 d-flex align-center justify-center pa-6">
          <v-icon color="primary" class="mr-2" size="28">mdi-calendar-range</v-icon>
          <span class="dialog-title">选择日期范围</span>
        </v-card-title>
        
        <v-card-text class="py-6">
          <v-row>
            <v-col cols="12">
              <v-text-field
                v-model="trafficStartDate"
                label="开始日期"
                type="date"
                variant="outlined"
                :min="getMinDate()"
                :max="getMaxDate()"
                color="primary"
                prepend-inner-icon="mdi-calendar-start"
                hide-details="auto"
                class="mb-4"
              />
            </v-col>
            <v-col cols="12">
              <v-text-field
                v-model="trafficEndDate"
                label="结束日期"
                type="date"
                variant="outlined"
                :min="trafficStartDate || getMinDate()"
                :max="getMaxDate()"
                color="primary"
                prepend-inner-icon="mdi-calendar-end"
                hide-details="auto"
              />
            </v-col>
          </v-row>
          
          <div class="mt-4 pa-3 bg-blue-lighten-5 rounded">
            <div class="d-flex align-center">
              <v-icon size="16" color="info" class="mr-2">mdi-information</v-icon>
              <span class="text-caption text-medium-emphasis">
                日期范围限制在当月内，最晚到今天
              </span>
            </div>
          </div>
        </v-card-text>
        
        <v-card-actions class="pa-6">
          <v-btn 
            color="grey" 
            variant="text"
            @click="showDatePicker = false"
            class="mr-2"
          >
            取消
          </v-btn>
          <v-spacer></v-spacer>
          <v-btn 
            color="primary" 
            variant="elevated"
            @click="confirmDateSelection"
            :disabled="!trafficStartDate || !trafficEndDate"
            class="px-6"
          >
            <v-icon class="mr-2">mdi-check</v-icon>
            确定
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 所有勋章展示对话框（移动端） -->
    <v-dialog v-model="showAllBadgesDialog" max-width="480">
      <v-card class="all-badges-dialog">
        <v-card-title class="text-h6 d-flex align-center justify-space-between pa-6">
          <div class="d-flex align-center">
            <v-icon color="amber" class="mr-2" size="28">mdi-shield-star</v-icon>
            <div>
              <div class="dialog-title">{{ selectedUserName }} 的勋章</div>
              <div class="text-caption text-medium-emphasis mt-1">共 {{ selectedUserBadges.length }} 个勋章</div>
            </div>
          </div>
          <v-btn icon size="small" variant="text" @click="showAllBadgesDialog = false">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </v-card-title>
        
        <v-card-text class="py-4">
          <v-row>
            <v-col 
              v-for="badge in selectedUserBadges" 
              :key="badge.badge_id"
              cols="6"
              sm="4"
            >
              <div class="badge-item">
                <v-avatar size="48" class="badge-item-avatar">
                  <v-img :src="badge.badge.icon_url" :alt="badge.badge.name" />
                </v-avatar>
                <div class="badge-item-name">{{ badge.badge.name }}</div>
                <div class="badge-item-desc text-caption text-medium-emphasis">
                  {{ badge.badge.description }}
                </div>
                <div v-if="badge.bonus_active" class="badge-item-bonus">
                  <v-chip size="x-small" color="success" variant="tonal">
                    <v-icon size="12" start>mdi-lightning-bolt</v-icon>
                    加成生效中
                  </v-chip>
                </div>
              </div>
            </v-col>
          </v-row>
          
          <div v-if="selectedUserBadges.length === 0" class="text-center py-8">
            <v-icon size="64" color="grey-lighten-2">mdi-shield-off</v-icon>
            <div class="text-body-2 text-medium-emphasis mt-2">暂无勋章</div>
          </div>
        </v-card-text>
        
        <v-card-actions class="pa-6">
          <v-spacer></v-spacer>
          <v-btn 
            color="primary" 
            variant="elevated"
            @click="showAllBadgesDialog = false"
            class="px-6"
          >
            关闭
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script>
import { getCreditsRankings, getDonationRankings, getPlexWatchedTimeRankings, getEmbyWatchedTimeRankings, getPlexTrafficRankings, getEmbyTrafficRankings, getInvitationRankings, getBadgeRankings } from '@/api'
import { getWatchLevelIcons } from '@/utils/watchLevel.js'
import { getUserBadges } from '@/services/badgeService.js'

export default {
  name: "Rankings",
  data() {
    return {
      activeTab: 'credits',
      watchedTimeSource: 'emby',
      trafficSource: 'emby',
      showLevelInfo: false,
      // 流量榜日期选择
      trafficDateRange: 'today', // 'today', 'yesterday', 'week', 'custom'
      trafficStartDate: null,
      trafficEndDate: null,
      showDatePicker: false,
      rankings: {
        credits_rank: [],
        donation_rank: [],
        watched_time_rank_plex: [],
        watched_time_rank_emby: [],
        traffic_rank_plex: [],
        traffic_rank_emby: [],
        badge_rank: [],
        invitation_rank: []
      },
      loading: {
        credits: false,
        donation: false,
        watched: false,
        traffic: false,
        badge: false,
        invitation: false,
        'watched-plex': false,
        'watched-emby': false,
        'traffic-plex': false,
        'traffic-emby': false
      },
      loaded: {
        credits: false,
        donation: false,
        watched: false,
        traffic: false,
        badge: false,
        invitation: false,
        'watched-plex': false,
        'watched-emby': false,
        'traffic-plex': false,
        'traffic-emby': false
      },
      error: null,
      userBadgesMap: {}, // 用户ID到勋章列表的映射
      windowWidth: window.innerWidth, // 窗口宽度，用于响应式显示勋章数量
      // 所有勋章对话框相关
      showAllBadgesDialog: false,
      selectedUserName: '',
      selectedUserBadges: []
    }
  },
  computed: {
    // 判断是否为移动端
    isMobile() {
      return this.windowWidth < 600
    }
  },
  watch: {
    activeTab(newTab) {
      console.log(`切换到标签页: ${newTab}`)
      this.loadTabData(newTab)
    },
    watchedTimeSource(newSource) {
      console.log(`切换观看时长数据源到: ${newSource}`)
      if (this.activeTab === 'watched') {
        // 检查新数据源是否已加载，如果没有则加载
        const watchedKey = `watched-${newSource}`
        if (!this.loaded[watchedKey]) {
          this.loadWatchedTimeData(newSource)
        }
      }
    },
    trafficSource(newSource) {
      console.log(`切换流量数据源到: ${newSource}`)
      if (this.activeTab === 'traffic') {
        // 检查新数据源是否已加载，如果没有则加载
        const trafficKey = `traffic-${newSource}`
        if (!this.loaded[trafficKey]) {
          this.loadTrafficData(newSource)
        }
      }
    },
    trafficDateRange(newRange) {
      console.log(`切换流量日期范围到: ${newRange}`)
      this.updateTrafficDatesByRange(newRange)
      if (this.activeTab === 'traffic') {
        // 重置加载状态并重新加载数据
        const trafficKey = `traffic-${this.trafficSource}`
        this.loaded[trafficKey] = false
        this.loadTrafficData(this.trafficSource)
      }
    },
    trafficStartDate() {
      this.onTrafficDateChange()
    },
    trafficEndDate() {
      this.onTrafficDateChange()
    }
  },
  created() {
    console.log('Rankings组件创建')
    // 确保API函数已正确导入
    console.log('API函数检查:', {
      getCreditsRankings: typeof getCreditsRankings,
      getDonationRankings: typeof getDonationRankings,
      getEmbyWatchedTimeRankings: typeof getEmbyWatchedTimeRankings,
      getPlexWatchedTimeRankings: typeof getPlexWatchedTimeRankings,
      getEmbyTrafficRankings: typeof getEmbyTrafficRankings,
      getPlexTrafficRankings: typeof getPlexTrafficRankings
    })
    
    // 初始化流量日期为今日
    this.updateTrafficDatesByRange('today')
  },
  mounted() {
    // 默认加载积分榜数据
    this.loadTabData(this.activeTab)
    // 强制刷新一次，确保数据加载
    this.$nextTick(() => {
      if (!this.rankings.credits_rank.length) {
        this.loadTabData('credits')
      }
      this.checkMarqueeOverflows()
    })
    
    // 监听窗口大小变化，用于响应式调整勋章显示数量
    window.addEventListener('resize', this.handleResize)
  },
  updated() {
    this.$nextTick(() => {
      this.checkMarqueeOverflows()
    })
  },
  beforeUnmount() {
    // 清理事件监听
    window.removeEventListener('resize', this.handleResize)
  },
  methods: {
    // 处理窗口大小变化
    handleResize() {
      this.windowWidth = window.innerWidth
      this.$nextTick(() => {
        this.checkMarqueeOverflows()
      })
    },
    
    // 检测所有用户名文本是否溢出，如果溢出则添加跑马灯效果
    checkMarqueeOverflows() {
      const wrappers = this.$el?.querySelectorAll('.user-name-text-wrapper')
      if (!wrappers) return
      wrappers.forEach((wrapper) => {
        const textEl = wrapper.querySelector('.user-name-text')
        if (!textEl) return
        const isOverflowing = textEl.scrollWidth > wrapper.clientWidth
        if (isOverflowing) {
          wrapper.classList.add('is-overflowing')
          // Calculate how far to scroll: the excess amount
          const distance = -(textEl.scrollWidth - wrapper.clientWidth)
          wrapper.style.setProperty('--marquee-distance', `${distance}px`)
        } else {
          wrapper.classList.remove('is-overflowing')
          wrapper.style.removeProperty('--marquee-distance')
        }
      })
    },
    
    // 根据屏幕宽度返回勋章显示数量限制
    getBadgeDisplayLimit() {
      // 移动端（小于600px）：显示3个
      if (this.windowWidth < 600) {
        return 3
      }
      // 平板（600-960px）：显示4个
      else if (this.windowWidth < 960) {
        return 4
      }
      // 桌面端（大于960px）：显示5个
      else {
        return 5
      }
    },
    
    async loadTabData(tab) {
      console.log(`开始加载 ${tab} 数据...`)
      
      // 如果已经加载过该tab的数据，直接返回
      if (this.loaded[tab]) {
        console.log(`${tab} 数据已加载，跳过`)
        return
      }

      this.loading[tab] = true
      this.error = null

      try {
        let response
        switch (tab) {
          case 'credits':
            console.log('调用积分排行API...')
            response = await getCreditsRankings()
            this.rankings.credits_rank = response.data.credits_rank || []
            console.log('积分排行数据:', this.rankings.credits_rank)
            // 加载积分榜用户的勋章
            await this.loadBadgesForRankings(this.rankings.credits_rank)
            break
          case 'donation':
            console.log('调用捐赠排行API...')
            response = await getDonationRankings()
            this.rankings.donation_rank = response.data.donation_rank || []
            console.log('捐赠排行数据:', this.rankings.donation_rank)
            // 加载捐赠榜用户的勋章
            await this.loadBadgesForRankings(this.rankings.donation_rank)
            break
          case 'watched':
            // 观看时长tab被激活时，加载当前选中的数据源
            console.log(`加载观看时长数据 - ${this.watchedTimeSource}`)
            await this.loadWatchedTimeData(this.watchedTimeSource)
            break
          case 'traffic':
            // 流量tab被激活时，加载当前选中的数据源
            console.log(`加载流量数据 - ${this.trafficSource}`)
            await this.loadTrafficData(this.trafficSource)
            break
          case 'badge':
            console.log('调用勋章排行API...')
            response = await getBadgeRankings()
            this.rankings.badge_rank = response.data.badge_rank || []
            console.log('勋章排行数据:', this.rankings.badge_rank)
            break
          case 'invitation':
            console.log('调用邀请排行API...')
            response = await getInvitationRankings()
            this.rankings.invitation_rank = response.data.invitation_rank || []
            console.log('邀请排行数据:', this.rankings.invitation_rank)
            break
        }
        this.loaded[tab] = true
        console.log(`${tab} 数据加载完成`)
      } catch (err) {
        this.error = err.response?.data?.detail || `获取${this.getTabName(tab)}失败`
        console.error(`获取${this.getTabName(tab)}失败:`, err)
      } finally {
        this.loading[tab] = false
      }
    },

    async loadWatchedTimeData(source) {
      console.log(`开始加载观看时长数据 - ${source}`)
      
      const watchedKey = `watched-${source}`
      // 如果已经加载过该数据源的观看时长数据，直接返回
      if (this.loaded[watchedKey]) {
        console.log(`${source} 观看时长数据已加载，跳过`)
        return
      }

      this.loading[watchedKey] = true
      this.error = null

      try {
        let response
        if (source === 'plex') {
          console.log('调用Plex观看时长API...')
          response = await getPlexWatchedTimeRankings()
          this.rankings.watched_time_rank_plex = response.data.watched_time_rank_plex || []
          console.log('Plex观看时长数据:', this.rankings.watched_time_rank_plex)
        } else if (source === 'emby') {
          console.log('调用Emby观看时长API...')
          response = await getEmbyWatchedTimeRankings()
          this.rankings.watched_time_rank_emby = response.data.watched_time_rank_emby || []
          console.log('Emby观看时长数据:', this.rankings.watched_time_rank_emby)
        }
        this.loaded[watchedKey] = true
        console.log(`${source} 观看时长数据加载完成`)
      } catch (err) {
        this.error = err.response?.data?.detail || `获取${source.toUpperCase()}观看时长排行失败`
        console.error(`获取${source.toUpperCase()}观看时长排行失败:`, err)
      } finally {
        this.loading[watchedKey] = false
      }
    },

    async loadTrafficData(source) {
      console.log(`开始加载流量数据 - ${source}`)
      
      const trafficKey = `traffic-${source}`
      // 如果已经加载过该数据源的流量数据，直接返回
      if (this.loaded[trafficKey]) {
        console.log(`${source} 流量数据已加载，跳过`)
        return
      }

      this.loading[trafficKey] = true
      this.error = null

      try {
        let response
        if (source === 'plex') {
          console.log('调用Plex流量API...', { startDate: this.trafficStartDate, endDate: this.trafficEndDate })
          response = await getPlexTrafficRankings(this.trafficStartDate, this.trafficEndDate)
          this.rankings.traffic_rank_plex = response.data.traffic_rank_plex || []
          console.log('Plex流量数据:', this.rankings.traffic_rank_plex)
        } else if (source === 'emby') {
          console.log('调用Emby流量API...', { startDate: this.trafficStartDate, endDate: this.trafficEndDate })
          response = await getEmbyTrafficRankings(this.trafficStartDate, this.trafficEndDate)
          this.rankings.traffic_rank_emby = response.data.traffic_rank_emby || []
          console.log('Emby流量数据:', this.rankings.traffic_rank_emby)
        }
        this.loaded[trafficKey] = true
        console.log(`${source} 流量数据加载完成`)
      } catch (err) {
        this.error = err.response?.data?.detail || `获取${source.toUpperCase()}流量排行失败`
        console.error(`获取${source.toUpperCase()}流量排行失败:`, err)
      } finally {
        this.loading[trafficKey] = false
      }
    },

    getTabName(tab) {
      const names = {
        credits: '积分排行榜',
        donation: '捐赠排行榜',
        watched: '观看时长排行榜',
        traffic: '流量排行榜',
        badge: '勋章排行榜',
        invitation: '邀请排行榜'
      }
      return names[tab] || '排行榜'
    },

    isCurrentTabLoading() {
      if (this.activeTab === 'watched') {
        return this.loading[`watched-${this.watchedTimeSource}`]
      }
      if (this.activeTab === 'traffic') {
        return this.loading[`traffic-${this.trafficSource}`]
      }
      return this.loading[this.activeTab]
    },

    // 强制重新加载当前标签页数据
    async forceRefreshData() {
      console.log('强制刷新数据...')
      
      // 重置加载状态
      if (this.activeTab === 'watched') {
        const watchedKey = `watched-${this.watchedTimeSource}`
        this.loaded[watchedKey] = false
        await this.loadWatchedTimeData(this.watchedTimeSource)
      } else if (this.activeTab === 'traffic') {
        const trafficKey = `traffic-${this.trafficSource}`
        this.loaded[trafficKey] = false
        await this.loadTrafficData(this.trafficSource)
      } else {
        this.loaded[this.activeTab] = false
        await this.loadTabData(this.activeTab)
      }
    },
    
    // 使用导入的工具函数，直接传递观看时间参数
    getWatchLevelIcons(watchedTime) {
      const icons = getWatchLevelIcons(watchedTime);
      // 添加调试输出（仅在开发模式下）
      if (process.env.NODE_ENV === 'development') {
        console.log(`观看时长: ${watchedTime}小时, 等级图标:`, icons);
      }
      return icons;
    },
    
    // 获取图标的工具提示文本
    getIconTooltip(iconEmoji) {
      const tooltips = {
        '👑': '皇冠 (6400小时+)',
        '☀️': '太阳 (1600小时+)', 
        '🌙': '月亮 (400小时+)',
        '⭐': '星星 (100小时+)',
        '☆': '新手 (100小时以下)'
      };
      return tooltips[iconEmoji] || '等级图标';
    },
    
    // 格式化流量显示
    formatTraffic(bytes) {
      if (bytes === 0) return '0 B'
      
      const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
      const i = Math.floor(Math.log(bytes) / Math.log(1024))
      
      return parseFloat((bytes / Math.pow(1024, i)).toFixed(2)) + ' ' + sizes[i]
    },
    
    // 处理头像图片加载错误
    handleImageError(event) {
      // 头像加载失败时，隐藏图片，显示默认图标
      event.target.style.display = 'none';
    },

    // 获取用户的勋章列表
    async loadUserBadges(tgId) {
      if (!tgId || this.userBadgesMap[tgId]) {
        return // 已经加载过或无需加载
      }
      
      try {
        const response = await getUserBadges(tgId)
        // API直接返回勋章数组，response.data 就是 List[UserBadgeResponse]
        const badges = response.data || []
        // 使用 Vue 3 的响应式方式更新对象
        this.userBadgesMap = {
          ...this.userBadgesMap,
          [tgId]: badges
        }
        console.log(`用户 ${tgId} 的勋章加载成功:`, badges)
      } catch (err) {
        console.error(`获取用户 ${tgId} 的勋章失败:`, err)
        this.userBadgesMap = {
          ...this.userBadgesMap,
          [tgId]: []
        }
      }
    },

    // 批量加载排行榜用户的勋章
    async loadBadgesForRankings(rankings) {
      const tgIds = rankings
        .map(item => item.tg_id)
        .filter(tgId => tgId && !this.userBadgesMap[tgId])
      
      console.log('需要加载勋章的用户ID列表:', tgIds)
      
      if (tgIds.length === 0) {
        console.log('所有用户勋章已加载或无需加载')
        return
      }
      
      // 并发加载所有用户的勋章
      await Promise.all(tgIds.map(tgId => this.loadUserBadges(tgId)))
      console.log('批量加载勋章完成，当前勋章映射:', this.userBadgesMap)
    },

    // 获取用户的勋章列表（用于模板）
    getUserBadgesList(tgId) {
      const badges = this.userBadgesMap[tgId] || []
      if (badges.length > 0 && process.env.NODE_ENV === 'development') {
        console.log(`获取用户 ${tgId} 的勋章:`, badges)
      }
      return badges
    },

    // 显示所有勋章（移动端点击时）
    showAllBadges(tgId, userName) {
      this.selectedUserName = userName
      this.selectedUserBadges = this.getUserBadgesList(tgId)
      this.showAllBadgesDialog = true
    },

    // 显示勋章榜中用户的所有勋章（移动端点击时）
    showBadgeRankBadges(tgId, userName, badges) {
      this.selectedUserName = userName
      this.selectedUserBadges = badges
      this.showAllBadgesDialog = true
    },

    // 根据日期范围设置开始和结束日期
    updateTrafficDatesByRange(range) {
      const today = new Date()
      const year = today.getFullYear()
      const month = today.getMonth()
      const date = today.getDate()

      switch (range) {
        case 'today': {
          this.trafficStartDate = this.formatDate(new Date(year, month, date))
          this.trafficEndDate = this.formatDate(new Date(year, month, date))
          break
        }
        case 'yesterday': {
          const yesterday = new Date(year, month, date - 1)
          this.trafficStartDate = this.formatDate(yesterday)
          this.trafficEndDate = this.formatDate(yesterday)
          break
        }
        case 'week': {
          // 本周（周一到今天）
          const weekStart = new Date(today)
          const dayOfWeek = today.getDay()
          const diff = today.getDate() - dayOfWeek + (dayOfWeek === 0 ? -6 : 1) // 如果是周日，则减6天到周一
          weekStart.setDate(diff)
          this.trafficStartDate = this.formatDate(weekStart)
          this.trafficEndDate = this.formatDate(today)
          break
        }
        case 'month': {
          // 本月1号到今天
          const monthStart = new Date(year, month, 1)
          this.trafficStartDate = this.formatDate(monthStart)
          this.trafficEndDate = this.formatDate(today)
          break
        }
        case 'custom': {
          // 自定义日期，不在这里设置
          break
        }
      }
    },

    // 格式化日期为 YYYY-MM-DD
    formatDate(date) {
      const year = date.getFullYear()
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      return `${year}-${month}-${day}`
    },

    // 当自定义日期改变时触发
    onTrafficDateChange() {
      if (this.trafficDateRange === 'custom' && this.trafficStartDate && this.trafficEndDate) {
        // 确保结束日期不早于开始日期
        if (new Date(this.trafficEndDate) < new Date(this.trafficStartDate)) {
          this.trafficEndDate = this.trafficStartDate
        }
        
        // 确保日期范围在当月内
        const today = new Date()
        const currentMonthStart = new Date(today.getFullYear(), today.getMonth(), 1)
        
        if (new Date(this.trafficStartDate) < currentMonthStart) {
          this.trafficStartDate = this.formatDate(currentMonthStart)
        }
        
        if (new Date(this.trafficEndDate) > today) {
          this.trafficEndDate = this.formatDate(today)
        }

        if (this.activeTab === 'traffic') {
          // 重置加载状态并重新加载数据
          const trafficKey = `traffic-${this.trafficSource}`
          this.loaded[trafficKey] = false
          this.loadTrafficData(this.trafficSource)
        }
      }
    },

    // 获取日期范围的显示文本
    getDateRangeText() {
      if (!this.trafficStartDate || !this.trafficEndDate) {
        return '今日'
      }

      if (this.trafficStartDate === this.trafficEndDate) {
        return this.trafficStartDate === this.formatDate(new Date()) ? '今日' : this.trafficStartDate
      }

      return `${this.trafficStartDate} 至 ${this.trafficEndDate}`
    },

    // 获取当月最大日期（今天）
    getMaxDate() {
      return this.formatDate(new Date())
    },

    // 获取当月最小日期（本月1号）
    getMinDate() {
      const today = new Date()
      return this.formatDate(new Date(today.getFullYear(), today.getMonth(), 1))
    },

    // 确认日期选择
    confirmDateSelection() {
      this.showDatePicker = false
      // 触发数据重新加载
      if (this.activeTab === 'traffic') {
        const trafficKey = `traffic-${this.trafficSource}`
        this.loaded[trafficKey] = false
        this.loadTrafficData(this.trafficSource)
      }
    },

    // 获取日期范围芯片的颜色
    getDateRangeChipColor() {
      switch (this.trafficDateRange) {
        case 'today':
          return 'success'
        case 'yesterday':
          return 'info'
        case 'week':
          return 'warning'
        case 'month':
          return 'secondary'
        case 'custom':
          return 'primary'
        default:
          return 'info'
      }
    }
  }
}
</script>

<style scoped>
.rankings-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
  padding-bottom: 80px; /* 为底部导航栏留出空间 */
}

.content-wrapper {
  max-width: 800px;
  margin: 0 auto;
}

.rankings-header {
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
  margin: 0 0 16px 0;
}

.refresh-btn {
  margin-top: 16px;
  font-weight: 600;
  border-radius: 12px;
  transition: all 0.3s ease;
}

.transparent-container {
  background: transparent !important;
}

/* 标签页容器样式 */
.rankings-tabs-container {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
  margin-bottom: 24px;
  padding: 12px 20px;
  overflow: visible; /* 确保内容不被裁剪 */
}

/* 内容容器样式 */
.rankings-content-container {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
  padding: 20px;
}

/* 标签页样式 */
.rankings-tabs {
  background: transparent !important;
  border-radius: 16px;
  margin-bottom: 0;
  padding: 0;
  overflow: visible !important; /* 确保tab内容不被裁剪 */
  min-width: 100%; /* 确保有足够宽度 */
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

.ranking-item {
  transition: all 0.3s ease;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(15px);
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
}

/* Ensure the default slot content area constrains child widths */
.ranking-item :deep(.v-list-item__content) {
  min-width: 0;
  overflow: hidden;
}

.ranking-item:hover {
  transform: translateY(-4px);
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2) !important;
  background: rgba(255, 255, 255, 0.98);
}

.rank-container {
  display: flex;
  align-items: center;
  margin-right: 8px;
}

.rank-number {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #e0e0e0, #f5f5f5);
  color: #333;
  font-weight: bold;
  font-size: 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  position: relative;
  transition: all 0.3s ease;
}

.rank-1 {
  background: linear-gradient(135deg, #FFD700, #FFA500);
  color: #000;
  width: 46px;
  height: 46px;
  font-size: 18px;
  box-shadow: 0 4px 16px rgba(255, 215, 0, 0.4);
  animation: pulse-gold 2s infinite;
}

.rank-2 {
  background: linear-gradient(135deg, #C0C0C0, #E5E5E5);
  color: #000;
  width: 44px;
  height: 44px;
  font-size: 17px;
  box-shadow: 0 3px 12px rgba(192, 192, 192, 0.4);
  animation: pulse-silver 2s infinite;
}

.rank-3 {
  background: linear-gradient(135deg, #CD7F32, #D2691E);
  color: #000;
  width: 44px;
  height: 44px;
  font-size: 17px;
  box-shadow: 0 3px 12px rgba(205, 127, 50, 0.4);
  animation: pulse-bronze 2s infinite;
}

.rank-icon {
  font-size: 20px;
  animation: bounce 1s infinite alternate;
}

@keyframes pulse-gold {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.05); }
}

@keyframes pulse-silver {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.03); }
}

@keyframes pulse-bronze {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.03); }
}

@keyframes bounce {
  0% { transform: translateY(0); }
  100% { transform: translateY(-2px); }
}

.user-avatar {
  border: 3px solid rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease;
}

.user-avatar:hover {
  border-color: rgba(var(--v-theme-primary), 0.5);
  transform: scale(1.05);
}

.avatar-img {
  border-radius: 50%;
}

.user-info {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0; /* Allow flex children to shrink below content size */
}

.user-name {
  font-weight: 600;
  font-size: 16px;
  color: rgba(0, 0, 0, 0.87);
  margin-bottom: 4px;
  display: flex !important;
  align-items: center;
  flex-wrap: nowrap;
  min-width: 0; /* Critical for flex child truncation */
}

/* Wrapper for the user name text - takes remaining space, allows overflow scroll */
.user-name-text-wrapper {
  flex: 1 1 0;
  min-width: 0;
  overflow: hidden;
  position: relative;
}

/* Only apply fade mask when text is overflowing */
.user-name-text-wrapper.is-overflowing {
  mask-image: linear-gradient(to right, black calc(100% - 16px), transparent 100%);
  -webkit-mask-image: linear-gradient(to right, black calc(100% - 16px), transparent 100%);
}

.user-name-text {
  display: inline-block;
  white-space: nowrap;
  padding-right: 12px;
}

/* When the text overflows, animate it as a marquee */
.user-name-text-wrapper:hover .user-name-text,
.user-name-text-wrapper.is-overflowing .user-name-text {
  animation: marquee-scroll 5s linear infinite;
}

/* Remove fade mask during animation so scrolling text is fully visible */
.user-name-text-wrapper.is-overflowing:hover {
  mask-image: none;
  -webkit-mask-image: none;
}

/* On non-hover (mobile), only animate if overflowing - always remove mask during animation */
@media (hover: none) {
  .user-name-text-wrapper .user-name-text {
    animation: none;
  }
  .user-name-text-wrapper.is-overflowing .user-name-text {
    animation: marquee-scroll 5s linear infinite;
  }
  .user-name-text-wrapper.is-overflowing {
    mask-image: none;
    -webkit-mask-image: none;
  }
}

@keyframes marquee-scroll {
  0% {
    transform: translateX(0);
  }
  /* Pause at the start for readability */
  15% {
    transform: translateX(0);
  }
  /* Scroll to the end */
  85% {
    transform: translateX(var(--marquee-distance, -30%));
  }
  /* Pause at the end */
  100% {
    transform: translateX(var(--marquee-distance, -30%));
  }
}

/* Ensure all chips / badges inside user-name row don't shrink */
.user-name > .v-chip,
.user-name > .user-badges,
.user-name > .more-badges-indicator {
  flex-shrink: 0;
}

.user-score {
  display: flex !important;
  align-items: center !important;
  font-size: 14px;
  color: rgba(0, 0, 0, 0.6);
  font-weight: 500;
  width: 100%;
  min-height: 28px;
}

.bg-primary-subtle {
  background: linear-gradient(135deg, rgba(var(--v-theme-primary), 0.08), rgba(var(--v-theme-primary), 0.12)) !important;
  border-color: rgba(var(--v-theme-primary), 0.2) !important;
}

.watched-source-select {
  min-width: 180px;
}

/* 等级说明对话框样式 */
.level-dialog {
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(15px);
  border-radius: 20px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
}

.level-dialog .v-card-title {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
}

.dialog-title {
  font-weight: 700;
  color: #333;
}

/* 等级项目样式 */
.level-item {
  background: rgba(255, 255, 255, 0.6);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
  border: 1px solid rgba(0, 0, 0, 0.05);
  transition: all 0.3s ease;
}

.level-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.1);
  background: rgba(255, 255, 255, 0.8);
}

.level-header {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}

.level-emoji-container {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 16px;
  transition: all 0.3s ease;
}

.star-bg {
  background: linear-gradient(135deg, #FFE082 0%, #FFD54F 100%);
  box-shadow: 0 4px 15px rgba(255, 193, 7, 0.3);
}

.moon-bg {
  background: linear-gradient(135deg, #E1F5FE 0%, #B3E5FC 100%);
  box-shadow: 0 4px 15px rgba(3, 169, 244, 0.3);
}

.sun-bg {
  background: linear-gradient(135deg, #FFF3E0 0%, #FFCC80 100%);
  box-shadow: 0 4px 15px rgba(255, 204, 128, 0.3);
}

.crown-bg {
  background: linear-gradient(135deg, #FFF8E1 0%, #FFD54F 100%);
  box-shadow: 0 4px 15px rgba(255, 213, 79, 0.4);
}

.level-emoji {
  font-size: 24px;
}

.level-info {
  flex: 1;
}

.level-title {
  font-weight: 600;
  font-size: 18px;
  color: #333;
  margin-bottom: 4px;
}

.level-desc {
  color: #666;
}

.level-requirement {
  font-weight: 500;
  margin-bottom: 4px;
}

.level-example {
  font-size: 14px;
  color: #888;
}

/* 等级进度演示样式 */
.level-progress-demo {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  border-radius: 16px;
  padding: 24px;
  border: 1px solid rgba(102, 126, 234, 0.2);
}

.level-demo-icon {
  font-size: 28px;
  animation: float 2s ease-in-out infinite alternate;
}

@keyframes float {
  0% { transform: translateY(0px); }
  100% { transform: translateY(-6px); }
}

.level-progress-text {
  font-size: 14px;
  color: #666;
  font-weight: 500;
}

/* 计算说明样式 */
.calculation-note {
  display: flex;
  align-items: center;
  background: rgba(33, 150, 243, 0.1);
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid rgba(33, 150, 243, 0.2);
}

.toolbar-controls {
  gap: 24px !important; /* 增加到24px的间距 */
}

.toolbar-controls .v-btn {
  margin-right: 8px; /* 为信息按钮添加额外的右边距 */
}

/* 信息按钮样式 */
.info-btn {
  opacity: 0.7;
  transition: all 0.2s ease;
  min-width: 24px !important;
  width: 24px !important;
  height: 24px !important;
}

.info-btn:hover {
  opacity: 1;
  transform: scale(1.1);
}

/* 用户勋章样式 */
.user-badges {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  vertical-align: middle;
  flex-wrap: nowrap;
  flex-shrink: 0; /* 不允许勋章区域被压缩 */
}

.badge-avatar {
  border: 2px solid #FFA000;
  transition: all 0.2s ease;
  cursor: pointer;
  flex-shrink: 0; /* 防止勋章被压缩 */
}

.badge-avatar:hover {
  transform: scale(1.15);
  box-shadow: 0 2px 8px rgba(255, 160, 0, 0.4);
}

/* 勋章榜中的勋章列表样式 */
.badge-list-container {
  margin-top: 4px;
}

.badge-avatar-item {
  border: 2px solid #FFA000;
  transition: all 0.2s ease;
  cursor: pointer;
  flex-shrink: 0;
}

.badge-avatar-item:hover {
  transform: scale(1.15);
  box-shadow: 0 2px 8px rgba(255, 160, 0, 0.4);
}

/* 更多勋章指示器样式 */
.more-badges-indicator {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 20px;
  padding: 0 6px;
  background: linear-gradient(135deg, #FFA000, #FF6F00);
  color: white;
  font-size: 11px;
  font-weight: 600;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  flex-shrink: 0;
}

.more-badges-indicator:hover {
  transform: scale(1.1);
  box-shadow: 0 2px 8px rgba(255, 160, 0, 0.4);
  background: linear-gradient(135deg, #FF8F00, #FF5722);
}

/* 所有勋章对话框样式 */
.all-badges-dialog {
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: blur(15px);
  border-radius: 20px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
}

.all-badges-dialog .v-card-title {
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.1) 0%, rgba(255, 152, 0, 0.1) 100%);
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

.badge-item {
  text-align: center;
  padding: 16px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(0, 0, 0, 0.05);
  transition: all 0.3s ease;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.badge-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(255, 160, 0, 0.15);
  background: rgba(255, 255, 255, 0.9);
  border-color: rgba(255, 160, 0, 0.2);
}

.badge-item-avatar {
  border: 2px solid #FFA000;
  margin-bottom: 8px;
}

.badge-item-name {
  font-weight: 600;
  font-size: 14px;
  color: #333;
  word-break: break-word;
}

.badge-item-desc {
  font-size: 12px;
  color: #666;
  line-height: 1.4;
  word-break: break-word;
}

.badge-item-bonus {
  margin-top: auto;
}

.watched-time-container {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: nowrap;
  gap: 8px;
  min-height: 24px;
  width: 100%;
}

.watched-time-text {
  white-space: nowrap;
  font-weight: 500;
  flex-shrink: 0;
  min-width: fit-content;
}

.level-icons-wrapper {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: nowrap;
  min-height: 20px;
  padding: 2px 4px;
  margin-left: auto;
  background: rgba(0, 0, 0, 0.03);
  border-radius: 12px;
  border: 1px solid rgba(0, 0, 0, 0.08);
}

.emoji-icon {
  font-size: 16px;
  line-height: 1.2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  min-width: 18px;
  min-height: 18px;
  text-align: center;
  transition: all 0.2s ease;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(4px);
}

.emoji-icon:hover {
  transform: scale(1.2);
  background: rgba(255, 255, 255, 0.2);
}

/* 等级图标的特定样式 */
.level-icon {
  transition: all 0.3s ease;
  display: inline-block;
}

.crown-icon {
  filter: drop-shadow(0 0 3px rgba(255, 215, 0, 0.6));
  animation: crown-glow 2s ease-in-out infinite alternate;
}

.sun-icon {
  filter: drop-shadow(0 0 2px rgba(255, 165, 0, 0.5));
  animation: sun-rotate 4s linear infinite;
}

.moon-icon {
  filter: drop-shadow(0 0 2px rgba(173, 216, 230, 0.5));
  animation: moon-phase 3s ease-in-out infinite alternate;
}

.star-icon {
  filter: drop-shadow(0 0 1px rgba(255, 255, 0, 0.4));
  animation: star-twinkle 1.5s ease-in-out infinite alternate;
}

@keyframes crown-glow {
  0% { transform: scale(1); filter: drop-shadow(0 0 3px rgba(255, 215, 0, 0.6)); }
  100% { transform: scale(1.1); filter: drop-shadow(0 0 6px rgba(255, 215, 0, 0.9)); }
}

@keyframes sun-rotate {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

@keyframes moon-phase {
  0% { opacity: 0.7; transform: scale(1); }
  100% { opacity: 1; transform: scale(1.05); }
}

@keyframes star-twinkle {
  0% { opacity: 0.6; transform: scale(0.9); }
  100% { opacity: 1; transform: scale(1); }
}

.text-grey {
  color: rgba(0, 0, 0, 0.6) !important;
}

/* 确保图标不会被遮挡或压缩 */
.v-list-item-subtitle {
  overflow: visible !important;
  white-space: normal !important;
  display: block;
}

/* 增加列表项的内边距 */
.v-list-item {
  padding: 12px 16px !important;
}

/* 工具提示样式 */
.v-tooltip .v-overlay__content {
  background: rgba(0, 0, 0, 0.8);
  color: white;
  border-radius: 6px;
  font-size: 12px;
  padding: 6px 10px;
}

:deep(.v-tooltip .v-overlay__content) {
  background: rgba(0, 0, 0, 0.9) !important;
  color: white !important;
  border-radius: 6px !important;
  padding: 6px 10px !important;
  font-size: 12px !important;
  font-weight: 500 !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important;
}

/* 等级说明对话框样式 */
.level-dialog {
  border-radius: 16px !important;
  overflow: hidden;
}

.dialog-title {
  font-size: 20px;
  font-weight: 600;
  color: rgba(var(--v-theme-primary), 1);
}

.level-explanation {
  padding: 0;
}

/* 等级进度演示 */
.level-progress-demo {
  background: linear-gradient(135deg, rgba(var(--v-theme-primary), 0.05), rgba(var(--v-theme-secondary), 0.05));
  border-radius: 16px;
  padding: 20px;
  border: 1px solid rgba(var(--v-theme-primary), 0.1);
}

.level-demo-icon {
  font-size: 28px;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease;
}

.level-demo-icon:hover {
  transform: scale(1.1);
}

.level-progress-text {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.6);
  font-weight: 500;
}

/* 等级项目样式 */
.level-item {
  padding: 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(0, 0, 0, 0.06);
  transition: all 0.3s ease;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.level-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
  border-color: rgba(var(--v-theme-primary), 0.2);
}

.level-header {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}

.level-emoji-container {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 12px;
  position: relative;
  transition: all 0.3s ease;
}

.level-emoji {
  font-size: 24px;
  line-height: 1;
  z-index: 2;
}

/* 等级背景颜色 */
.star-bg {
  background: linear-gradient(135deg, #FFF59D, #FFEE58);
  box-shadow: 0 2px 8px rgba(255, 238, 88, 0.3);
}

.moon-bg {
  background: linear-gradient(135deg, #E1F5FE, #B3E5FC);
  box-shadow: 0 2px 8px rgba(179, 229, 252, 0.3);
}

.sun-bg {
  background: linear-gradient(135deg, #FFF3E0, #FFCC80);
  box-shadow: 0 2px 8px rgba(255, 204, 128, 0.3);
}

.crown-bg {
  background: linear-gradient(135deg, #FFF8E1, #FFD54F);
  box-shadow: 0 2px 8px rgba(255, 213, 79, 0.4);
}

.level-info {
  flex: 1;
}

.level-title {
  font-size: 16px;
  font-weight: 600;
  color: rgba(0, 0, 0, 0.87);
  margin-bottom: 2px;
}

.level-subtitle {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.6);
  font-weight: 500;
}

.level-desc {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.level-requirement {
  font-size: 14px;
  color: rgba(0, 0, 0, 0.87);
  font-weight: 500;
}

.level-example {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.6);
  font-style: italic;
}

.calculation-note {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
  background: rgba(var(--v-theme-info), 0.05);
  border-radius: 8px;
  border: 1px solid rgba(var(--v-theme-info), 0.1);
}

/* 响应式设计 */
@media (max-width: 768px) {
  .user-avatar {
    margin-right: 12px !important;
  }
  
  .rank-number {
    width: 36px;
    height: 36px;
    font-size: 14px;
  }
  
  .rank-1 {
    width: 42px;
    height: 42px;
    font-size: 16px;
  }
  
  .rank-2, .rank-3 {
    width: 40px;
    height: 40px;
    font-size: 15px;
  }
  
  .watched-time-container {
    flex-direction: row;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  
  .level-icons-wrapper {
    gap: 2px;
    padding: 1px 3px;
    margin-left: 8px;
    margin-top: 2px;
  }
  
  .emoji-icon {
    font-size: 14px;
    min-width: 16px;
    min-height: 16px;
  }
  
  .watched-time-text {
    font-size: 13px;
  }

  .traffic-container {
    flex-direction: row;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  
  .traffic-text {
    font-size: 13px;
  }

  /* 等级对话框移动端适配 */
  .level-progress-demo {
    padding: 16px;
  }
  
  .level-demo-icon {
    width: 32px;
    height: 32px;
    font-size: 20px;
  }
  
  .level-emoji-container {
    width: 40px;
    height: 40px;
    margin-right: 8px;
  }
  
  .level-emoji {
    font-size: 20px;
  }
  
  .level-item {
    padding: 12px;
  }
  
  .level-title {
    font-size: 15px;
  }
  
  .level-subtitle {
    font-size: 11px;
  }
  
  .level-requirement {
    font-size: 13px;
  }
  
  .level-example {
    font-size: 11px;
  }
}

@media (max-width: 480px) {
  .watched-time-container {
    font-size: 12px;
    gap: 4px;
  }
  
  .emoji-icon {
    font-size: 12px;
    min-width: 14px;
    min-height: 14px;
  }
  
  .level-icons-wrapper {
    gap: 1px;
    padding: 1px 2px;
  }
  
  .watched-time-text {
    font-size: 12px;
  }

  .traffic-container {
    font-size: 12px;
    gap: 4px;
  }
  
  .traffic-text {
    font-size: 12px;
  }

  /* 小屏幕等级对话框适配 */
  .level-progress-demo {
    padding: 12px;
  }
  
  .level-demo-icon {
    width: 28px;
    height: 28px;
    font-size: 16px;
  }
  
  .level-emoji-container {
    width: 36px;
    height: 36px;
    margin-right: 6px;
  }
  
  .level-emoji {
    font-size: 18px;
  }
  
  .level-item {
    padding: 10px;
  }
  
  .level-title {
    font-size: 14px;
  }
  
  .level-subtitle {
    font-size: 10px;
  }
  
  .level-requirement {
    font-size: 12px;
  }
  
  .level-example {
    font-size: 10px;
  }
  
  .dialog-title {
    font-size: 18px;
  }
  
  .calculation-note {
    padding: 8px;
    font-size: 11px;
  }
}

/* 响应式样式 */
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

/* 提升视觉效果的额外样式 */
.ranking-item.bg-primary-subtle {
  background: linear-gradient(135deg, rgba(var(--v-theme-primary), 0.15), rgba(var(--v-theme-primary), 0.08)) !important;
  border-color: rgba(var(--v-theme-primary), 0.3) !important;
  box-shadow: 0 8px 25px rgba(var(--v-theme-primary), 0.2) !important;
}

.ranking-item.bg-primary-subtle:hover {
  background: linear-gradient(135deg, rgba(var(--v-theme-primary), 0.2), rgba(var(--v-theme-primary), 0.1)) !important;
  transform: translateY(-6px);
  box-shadow: 0 15px 35px rgba(var(--v-theme-primary), 0.3) !important;
}

/* 统一的控件选择器样式 */
.control-select {
  min-width: 150px;
}

.control-select :deep(.v-field) {
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(10px);
  border-radius: 12px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease;
}

.control-select :deep(.v-field):hover {
  background: rgba(255, 255, 255, 0.95);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
}

/* 观看时长选择器特殊设置 */
.watched-source-select {
  min-width: 180px;
}

/* 流量榜日期选择器特殊设置 */
.date-range-select {
  min-width: 120px;
}

/* 自定义日期按钮样式 */
.custom-date-btn {
  background: rgba(255, 255, 255, 0.9) !important;
  backdrop-filter: blur(10px);
  border-radius: 12px !important;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1) !important;
  transition: all 0.3s ease !important;
  height: 40px !important; /* 与选择器高度保持一致 */
}

.custom-date-btn:hover {
  background: rgba(255, 255, 255, 0.95) !important;
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15) !important;
}

/* 流量容器样式 */
.traffic-container {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: nowrap;
  gap: 8px;
  min-height: 24px;
  width: 100%;
}

.traffic-text {
  white-space: nowrap;
  font-weight: 500;
  flex-shrink: 0;
  min-width: fit-content;
  color: rgba(0, 0, 0, 0.87);
}

/* 信息按钮增强样式 */
.info-btn {
  background: rgba(255, 255, 255, 0.2);
  backdrop-filter: blur(10px);
  border-radius: 50%;
  transition: all 0.3s ease;
}

.info-btn:hover {
  background: rgba(255, 255, 255, 0.3);
  transform: scale(1.1) translateY(-2px);
  box-shadow: 0 6px 15px rgba(0, 0, 0, 0.2);
}

/* 等级图标容器增强 */
.level-icons-wrapper {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.05));
  backdrop-filter: blur(5px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  transition: all 0.3s ease;
}

.level-icons-wrapper:hover {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.2), rgba(255, 255, 255, 0.1));
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

/* 透明榜单容器样式 */
.transparent-list {
  background: transparent !important;
}

.transparent-list-content {
  background: transparent !important;
}

/* 确保v-list组件背景透明 */
.transparent-list-content :deep(.v-list) {
  background: transparent !important;
}

/* 覆盖Vuetify默认的列表背景色 */
:deep(.v-list) {
  background: transparent !important;
}

/* 确保窗口项目背景透明 */
:deep(.v-window-item) {
  background: transparent !important;
}

/* 确保标签窗口背景透明 */
:deep(.v-window) {
  background: transparent !important;
}

/* Premium 标识样式 */
.premium-badge {
  animation: premium-glow 2s ease-in-out infinite alternate;
  background: linear-gradient(135deg, #FFD700, #FFA500) !important;
  border: 1px solid #FFD700;
  box-shadow: 0 2px 8px rgba(255, 215, 0, 0.3);
  font-weight: 600;
  letter-spacing: 0.5px;
  transition: all 0.3s ease;
  min-height: 20px !important;
  height: auto !important;
  flex-shrink: 0; /* 不允许被压缩 */
}

.premium-badge:hover {
  transform: scale(1.05);
  box-shadow: 0 4px 15px rgba(255, 215, 0, 0.5);
}

.premium-badge .v-chip__content {
  padding: 2px 4px !important;
  font-size: 10px;
  font-weight: 700;
  color: #000 !important;
  display: flex !important;
  align-items: center !important;
  gap: 2px !important;
  line-height: 1 !important;
}

.premium-icon {
  margin: 0 !important;
  color: #000 !important;
  flex-shrink: 0 !important;
}

.premium-text {
  font-size: 9px;
  font-weight: 700;
  color: #000;
  text-shadow: 1px 1px 2px rgba(255, 255, 255, 0.3);
}

.premium-text-short {
  font-size: 9px;
  font-weight: 700;
  color: #000;
  text-shadow: 1px 1px 2px rgba(255, 255, 255, 0.3);
}

@keyframes premium-glow {
  0% { 
    box-shadow: 0 2px 8px rgba(255, 215, 0, 0.3);
  }
  100% { 
    box-shadow: 0 2px 12px rgba(255, 215, 0, 0.6);
  }
}

/* 响应式设计 - Premium 标识 */
@media (max-width: 768px) {
  .premium-badge {
    margin-left: 6px !important;
    min-height: 18px !important;
  }
  
  .premium-badge .v-chip__content {
    padding: 1px 3px !important;
    font-size: 9px;
    gap: 1px !important;
  }
  
  .premium-icon {
    font-size: 10px !important;
  }
  
  .premium-text {
    font-size: 8px;
  }
  
  .premium-text-short {
    font-size: 8px;
  }
}

@media (max-width: 480px) {
  .premium-badge {
    margin-left: 2px !important;
    padding: 0 !important;
    min-height: 16px !important;
  }
  
  .premium-badge .v-chip__content {
    padding: 1px 2px !important;
    font-size: 8px;
    min-width: auto !important;
    gap: 0px !important;
  }
  
  .premium-icon {
    font-size: 10px !important;
    margin: 0 !important;
  }
  
  .premium-text {
    font-size: 7px;
  }
  
  .premium-text-short {
    font-size: 7px;
  }
}

/* 日期选择器样式 */
.date-picker-dialog {
  border-radius: 16px !important;
  overflow: hidden;
}

.date-picker-dialog .v-card-title {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
}

/* 控件间距统一设置 */
.gap-4 {
  gap: 16px !important;
}

.date-range-select {
  min-width: 120px;
  margin-right: 0 !important; /* 移除右边距，使用gap代替 */
}

.traffic-source-select {
  min-width: 150px !important;
}

/* 日期范围控件容器 */
.toolbar-controls {
  gap: 16px !important;
}

/* 流量榜控件间距 - 移除，使用通用gap设置 */

/* 日期输入框样式 */
:deep(.v-text-field input[type="date"]) {
  padding: 8px 12px;
}

:deep(.v-text-field input[type="date"]::-webkit-calendar-picker-indicator) {
  opacity: 0.6;
  transition: all 0.2s ease;
}

:deep(.v-text-field input[type="date"]::-webkit-calendar-picker-indicator:hover) {
  opacity: 1;
  transform: scale(1.1);
}

/* 信息提示框样式 */
.bg-blue-lighten-5 {
  background-color: rgba(33, 150, 243, 0.08) !important;
}

/* 移动端响应式设计 - 控件间距 */
@media (max-width: 768px) {
  /* 移动端控件间距调整 */
  .d-flex.align-center.gap-4,
  .gap-4 {
    gap: 12px !important;
    flex-wrap: wrap;
  }

  .control-select {
    min-width: 120px !important;
  }

  .date-range-select {
    min-width: 100px !important;
  }

  .traffic-source-select {
    min-width: 120px !important;
  }

  .watched-source-select {
    min-width: 140px !important;
  }

  .custom-date-btn {
    height: 36px !important;
  }

  /* 移动端工具栏调整 */
  .d-flex.justify-space-between.align-center.mb-4 {
    flex-direction: column;
    align-items: flex-start !important;
    gap: 12px;
  }

  .d-flex.justify-space-between.align-center.mb-4 > div:last-child {
    align-self: flex-end;
  }
}

@media (max-width: 480px) {
  .control-select {
    min-width: 100px !important;
    font-size: 12px;
  }

  .date-range-select {
    min-width: 90px !important;
  }

  .traffic-source-select {
    min-width: 100px !important;
  }

  .watched-source-select {
    min-width: 120px !important;
  }

  .custom-date-btn {
    height: 32px !important;
    width: 32px !important;
  }

  .d-flex.align-center.gap-4,
  .gap-4 {
    gap: 8px !important;
  }
}
</style>