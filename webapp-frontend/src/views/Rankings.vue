<!-- eslint-disable vue/multi-word-component-names -->
<template>
  <div class="rankings-container">
    <v-container>
      <div v-if="loading" class="text-center my-10">
        <v-progress-circular indeterminate color="primary"></v-progress-circular>
        <div class="mt-3">加载中...</div>
      </div>

      <div v-else-if="error" class="text-center my-10">
        <v-alert type="error">{{ error }}</v-alert>
      </div>

      <div v-else>
        <v-tabs 
          v-model="activeTab" 
          grow 
          fixed-tabs 
          color="primary"
          bg-color="transparent"
          class="mb-4"
        >
          <v-tab value="credits" class="tab-item">
            <v-icon start size="20">mdi-star</v-icon>
            积分榜
          </v-tab>
          <v-tab value="donation" class="tab-item">
            <v-icon start size="20">mdi-heart</v-icon>
            捐赠榜
          </v-tab>
          <v-tab value="watched" class="tab-item">
            <v-icon start size="20">mdi-clock</v-icon>
            观看时长榜
          </v-tab>
        </v-tabs>

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
            <div v-if="rankings.watched_time_rank_plex.length === 0 && rankings.watched_time_rank_emby.length === 0" class="text-center my-5">
              <v-list-item>
                <v-list-item-title>暂无数据</v-list-item-title>
              </v-list-item>
            </div>
            <v-row v-else>
              <v-col cols="12">
                <div class="d-flex justify-space-between align-center mb-4">
                  <h3 class="text-h6 text-primary font-weight-bold">观看时长排行</h3>
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
                <v-card v-if="watchedTimeSource === 'plex'" elevation="0" class="transparent">
                  <v-list lines="two" class="px-2">
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
                            <v-icon size="24" color="orange">mdi-plex</v-icon>
                          </v-avatar>
                          <div class="user-info flex-grow-1">
                            <v-list-item-title class="user-name">{{ item.name }}</v-list-item-title>
                            <v-list-item-subtitle class="user-score">
                              <div class="d-flex align-center watched-time-container">
                                <v-icon size="16" color="orange" class="mr-1">mdi-clock</v-icon>
                                <span class="watched-time-text">{{ item.watched_time.toFixed(2) }} 小时</span>
                                <div class="level-icons-wrapper ml-2">
                                  <span 
                                    v-for="(icon, iconIndex) in getWatchLevelIcons(item.watched_time)" 
                                    :key="`plex-rank-icon-${index}-${iconIndex}`"
                                    :class="['emoji-icon', icon.class]"
                                  >
                                    {{ icon.icon }}
                                  </span>
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
                </v-card>
                
                <!-- Emby 观看时长榜 -->
                <v-card v-if="watchedTimeSource === 'emby'" elevation="0" class="transparent">
                  <v-list lines="two" class="px-2">
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
                            <v-icon size="24" color="green">mdi-server</v-icon>
                          </v-avatar>
                          <div class="user-info flex-grow-1">
                            <v-list-item-title class="user-name">{{ item.name }}</v-list-item-title>
                            <v-list-item-subtitle class="user-score">
                              <div class="d-flex align-center watched-time-container">
                                <v-icon size="16" color="green" class="mr-1">mdi-clock</v-icon>
                                <span class="watched-time-text">{{ item.watched_time.toFixed(2) }} 小时</span>
                                <div class="level-icons-wrapper ml-2">
                                  <span 
                                    v-for="(icon, iconIndex) in getWatchLevelIcons(item.watched_time)" 
                                    :key="`emby-rank-icon-${index}-${iconIndex}`"
                                    :class="['emoji-icon', icon.class]"
                                  >
                                    {{ icon.icon }}
                                  </span>
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
                </v-card>
              </v-col>
            </v-row>
          </v-window-item>
        </v-window>
      </div>
    </v-container>
  </div>
</template>

<script>
import { getRankings } from '@/api'
import { getWatchLevelIcons } from '@/utils/watchLevel.js'

export default {
  name: "Rankings",
  data() {
    return {
      activeTab: 'credits',
      watchedTimeSource: 'plex',
      rankings: {
        credits_rank: [],
        donation_rank: [],
        watched_time_rank_plex: [],
        watched_time_rank_emby: []
      },
      loading: true,
      error: null
    }
  },
  mounted() {
    this.fetchRankings()
  },
  methods: {
    async fetchRankings() {
      try {
        this.loading = true
        const response = await getRankings()
        this.rankings = response.data
        this.loading = false
      } catch (err) {
        this.error = err.response?.data?.detail || '获取排行榜信息失败'
        this.loading = false
        console.error('获取排行榜信息失败:', err)
      }
    },
    
    // 使用导入的工具函数，直接传递观看时间参数
    getWatchLevelIcons(watchedTime) {
      return getWatchLevelIcons(watchedTime);
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
  padding-bottom: 56px; /* 为底部导航栏留出空间 */
}

.tab-item {
  font-weight: 600;
  transition: all 0.3s ease;
}

.tab-item:hover {
  background-color: rgba(var(--v-theme-primary), 0.1);
}

.ranking-item {
  transition: all 0.3s ease;
  border: 1px solid rgba(0, 0, 0, 0.05);
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(10px);
}

.ranking-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
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
  display: flex;
  align-items: center;
  font-size: 14px;
  color: rgba(0, 0, 0, 0.6);
  font-weight: 500;
}

.bg-primary-subtle {
  background: linear-gradient(135deg, rgba(var(--v-theme-primary), 0.08), rgba(var(--v-theme-primary), 0.12)) !important;
  border-color: rgba(var(--v-theme-primary), 0.2) !important;
}

.watched-source-select {
  min-width: 180px;
}

.watched-time-container {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
}

.watched-time-text {
  margin-right: 10px;
  white-space: nowrap;
}

.level-icons-wrapper {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: nowrap;
}

.emoji-icon {
  font-size: 15px;
  line-height: 1;
  display: inline-flex;
  margin: 0 1px;
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
}
</style>