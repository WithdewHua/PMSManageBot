<!-- eslint-disable vue/multi-word-component-names -->
<template>
  <div class="rankings-container">
    <div class="content-wrapper">
      <div class="rankings-header">
        <h1 class="page-title">排行榜</h1>
        <p class="page-subtitle">积分、捐赠与观看时长排行</p>
      </div>
      
      <div v-if="isCurrentTabLoading()" class="loading-container">
        <div class="loading-content">
          <v-progress-circular indeterminate color="primary" size="50" width="4"></v-progress-circular>
          <div class="loading-text">加载中...</div>
        </div>
      </div>

      <div v-else-if="error" class="error-container">
        <v-alert type="error" class="error-alert" rounded="lg" elevation="4">{{ error }}</v-alert>
        <v-btn color="primary" @click="loadTabData(activeTab)" class="mt-3">
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
                      <v-list-item-title class="user-name">{{ item.name }}</v-list-item-title>
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
                      <v-list-item-title class="user-name">{{ item.name }}</v-list-item-title>
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
            <div v-if="loading[watchedTimeSource]" class="text-center my-10">
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
                      class="watched-source-select"
                      style="max-width: 150px;"
                      color="primary"
                    >
                      <template v-slot:prepend-inner>
                        <v-icon size="16" :color="watchedTimeSource === 'plex' ? 'orange' : 'green'">
                          {{ watchedTimeSource === 'plex' ? 'mdi-plex' : 'mdi-server' }}
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
                            <v-list-item-title class="user-name">{{ item.name }}</v-list-item-title>
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
                            <v-icon v-else size="24" color="green">mdi-server</v-icon>
                          </v-avatar>
                          <div class="user-info flex-grow-1">
                            <v-list-item-title class="user-name">{{ item.name }}</v-list-item-title>
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
  </div>
</template>

<script>
import { getCreditsRankings, getDonationRankings, getPlexWatchedTimeRankings, getEmbyWatchedTimeRankings } from '@/api'
import { getWatchLevelIcons } from '@/utils/watchLevel.js'

export default {
  name: "Rankings",
  data() {
    return {
      activeTab: 'credits',
      watchedTimeSource: 'emby',
      showLevelInfo: false,
      rankings: {
        credits_rank: [],
        donation_rank: [],
        watched_time_rank_plex: [],
        watched_time_rank_emby: []
      },
      loading: {
        credits: false,
        donation: false,
        watched: false,
        plex: false,
        emby: false
      },
      loaded: {
        credits: false,
        donation: false,
        watched: false,
        plex: false,
        emby: false
      },
      error: null
    }
  },
  watch: {
    activeTab(newTab) {
      this.loadTabData(newTab)
    },
    watchedTimeSource(newSource) {
      if (this.activeTab === 'watched') {
        this.loadWatchedTimeData(newSource)
      }
    }
  },
  mounted() {
    // 默认加载积分榜数据
    this.loadTabData(this.activeTab)
  },
  methods: {
    async loadTabData(tab) {
      // 如果已经加载过该tab的数据，直接返回
      if (this.loaded[tab]) {
        return
      }

      this.loading[tab] = true
      this.error = null

      try {
        let response
        switch (tab) {
          case 'credits':
            response = await getCreditsRankings()
            this.rankings.credits_rank = response.data.credits_rank
            break
          case 'donation':
            response = await getDonationRankings()
            this.rankings.donation_rank = response.data.donation_rank
            break
          case 'watched':
            // 观看时长tab被激活时，加载当前选中的数据源
            await this.loadWatchedTimeData(this.watchedTimeSource)
            break
        }
        this.loaded[tab] = true
      } catch (err) {
        this.error = err.response?.data?.detail || `获取${this.getTabName(tab)}失败`
        console.error(`获取${this.getTabName(tab)}失败:`, err)
      } finally {
        this.loading[tab] = false
      }
    },

    async loadWatchedTimeData(source) {
      // 如果已经加载过该数据源的数据，直接返回
      if (this.loaded[source]) {
        return
      }

      this.loading[source] = true
      this.error = null

      try {
        let response
        if (source === 'plex') {
          response = await getPlexWatchedTimeRankings()
          this.rankings.watched_time_rank_plex = response.data.watched_time_rank_plex
        } else if (source === 'emby') {
          response = await getEmbyWatchedTimeRankings()
          this.rankings.watched_time_rank_emby = response.data.watched_time_rank_emby
        }
        this.loaded[source] = true
      } catch (err) {
        this.error = err.response?.data?.detail || `获取${source.toUpperCase()}观看时长排行失败`
        console.error(`获取${source.toUpperCase()}观看时长排行失败:`, err)
      } finally {
        this.loading[source] = false
      }
    },

    getTabName(tab) {
      const names = {
        credits: '积分排行榜',
        donation: '捐赠排行榜',
        watched: '观看时长排行榜'
      }
      return names[tab] || '排行榜'
    },

    isCurrentTabLoading() {
      if (this.activeTab === 'watched') {
        return this.loading[this.watchedTimeSource]
      }
      return this.loading[this.activeTab]
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
    
    // 处理头像图片加载错误
    handleImageError(event) {
      // 头像加载失败时，隐藏图片，显示默认图标
      event.target.style.display = 'none';
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
  margin: 0;
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
}

.user-name {
  font-weight: 600;
  font-size: 16px;
  color: rgba(0, 0, 0, 0.87);
  margin-bottom: 4px;
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

/* 优化观看时长选择器样式 */
.watched-source-select :deep(.v-field) {
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(10px);
  border-radius: 12px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease;
}

.watched-source-select :deep(.v-field):hover {
  background: rgba(255, 255, 255, 0.95);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
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
</style>