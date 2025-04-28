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
        <v-tabs v-model="activeTab" grow fixed-tabs>
          <v-tab value="credits">积分榜</v-tab>
          <v-tab value="donation">捐赠榜</v-tab>
          <v-tab value="watched">观看时长榜</v-tab>
        </v-tabs>

        <v-window v-model="activeTab">
          <!-- 积分榜 -->
          <v-window-item value="credits">
            <v-list lines="two">
              <!-- <v-list-subheader>积分榜</v-list-subheader> -->
              <v-list-item
                v-for="(item, index) in rankings.credits_rank"
                :key="`credits-${index}`"
                :class="{ 'bg-primary-subtle': item.is_self }"
              >
                <template v-slot:prepend>
                  <div class="rank-number" :class="`rank-${index + 1}`">{{ index + 1 }}</div>
                </template>
                <v-list-item-title>{{ item.name }}</v-list-item-title>
                <v-list-item-subtitle>
                  {{ item.credits.toFixed(2) }} 积分
                </v-list-item-subtitle>
              </v-list-item>
              <v-list-item v-if="rankings.credits_rank.length === 0" class="text-center">
                <v-list-item-title>暂无数据</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-window-item>

          <!-- 捐赠榜 -->
          <v-window-item value="donation">
            <v-list lines="two">
              <!-- <v-list-subheader>捐赠榜</v-list-subheader> -->
              <v-list-item
                v-for="(item, index) in rankings.donation_rank"
                :key="`donation-${index}`"
                :class="{ 'bg-primary-subtle': item.is_self }"
              >
                <template v-slot:prepend>
                  <div class="rank-number" :class="`rank-${index + 1}`">{{ index + 1 }}</div>
                </template>
                <v-list-item-title>{{ item.name }}</v-list-item-title>
                <v-list-item-subtitle>
                  {{ item.donation.toFixed(2) }} 元
                </v-list-item-subtitle>
              </v-list-item>
              <v-list-item v-if="rankings.donation_rank.length === 0" class="text-center">
                <v-list-item-title>暂无数据</v-list-item-title>
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
                  <!-- <h3 class="text-h6">观看时长榜</h3> -->
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
                    class="watched-source-select"
                    style="max-width: 200px;"
                  ></v-select>
                </div>
                
                <!-- Plex 观看时长榜 -->
                <v-card v-if="watchedTimeSource === 'plex'">
                  <v-list lines="two">
                    <v-list-item
                      v-for="(item, index) in rankings.watched_time_rank_plex"
                      :key="`plex-watched-${index}`"
                      :class="{ 'bg-primary-subtle': item.is_self }"
                    >
                      <template v-slot:prepend>
                        <div class="rank-number" :class="`rank-${index + 1}`">{{ index + 1 }}</div>
                      </template>
                      <v-list-item-title>{{ item.name }}</v-list-item-title>
                      <v-list-item-subtitle>
                        <div class="d-flex align-center watched-time-container">
                          <span class="watched-time-text">{{ item.watched_time.toFixed(2) }} 小时</span>
                          <div class="level-icons-wrapper">
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
                    </v-list-item>
                    <v-list-item v-if="rankings.watched_time_rank_plex.length === 0" class="text-center">
                      <v-list-item-title>暂无数据</v-list-item-title>
                    </v-list-item>
                  </v-list>
                </v-card>
                
                <!-- Emby 观看时长榜 -->
                <v-card v-if="watchedTimeSource === 'emby'">
                  <v-list lines="two">
                    <v-list-item
                      v-for="(item, index) in rankings.watched_time_rank_emby"
                      :key="`emby-watched-${index}`"
                      :class="{ 'bg-primary-subtle': item.is_self }"
                    >
                      <template v-slot:prepend>
                        <div class="rank-number" :class="`rank-${index + 1}`">{{ index + 1 }}</div>
                      </template>
                      <v-list-item-title>{{ item.name }}</v-list-item-title>
                      <v-list-item-subtitle>
                        <div class="d-flex align-center watched-time-container">
                          <span class="watched-time-text">{{ item.watched_time.toFixed(2) }} 小时</span>
                          <div class="level-icons-wrapper">
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
                    </v-list-item>
                    <v-list-item v-if="rankings.watched_time_rank_emby.length === 0" class="text-center">
                      <v-list-item-title>暂无数据</v-list-item-title>
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
    }
  }
}
</script>

<style scoped>
.rankings-container {
  padding-bottom: 56px; /* 为底部导航栏留出空间 */
}

.rank-number {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #e0e0e0;
  color: #333;
  font-weight: bold;
  font-size: 16px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  margin-right: 16px; /* 增加右边距 */
}

.rank-1 {
  background-color: #FFD700; /* 金色 */
  color: #000;
  width: 36px;
  height: 36px;
  font-size: 18px;
  box-shadow: 0 2px 6px rgba(255, 215, 0, 0.5);
}

.rank-2 {
  background-color: #C0C0C0; /* 银色 */
  color: #000;
  width: 34px;
  height: 34px;
  font-size: 17px;
  box-shadow: 0 2px 5px rgba(192, 192, 192, 0.5);
}

.rank-3 {
  background-color: #CD7F32; /* 铜色 */
  color: #000;
  width: 34px;
  height: 34px;
  font-size: 17px;
  box-shadow: 0 2px 5px rgba(205, 127, 50, 0.5);
}

.bg-primary-subtle {
  background-color: rgba(var(--v-theme-primary), 0.1);
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

/* 确保图标不会被遮挡或压缩 */
.v-list-item-subtitle {
  overflow: visible !important;
  white-space: normal !important;
  display: block;
}
</style>