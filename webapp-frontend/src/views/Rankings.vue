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
          <v-tab value="watched">观看时长</v-tab>
        </v-tabs>

        <v-window v-model="activeTab">
          <!-- 积分榜 -->
          <v-window-item value="credits">
            <v-list lines="two">
              <v-list-subheader>积分榜</v-list-subheader>
              <v-list-item
                v-for="(item, index) in rankings.credits_rank"
                :key="`credits-${index}`"
                :class="{ 'bg-primary-subtle': item.is_self }"
              >
                <template v-slot:prepend>
                  <div class="rank-number">{{ index + 1 }}</div>
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
              <v-list-subheader>捐赠榜</v-list-subheader>
              <v-list-item
                v-for="(item, index) in rankings.donation_rank"
                :key="`donation-${index}`"
                :class="{ 'bg-primary-subtle': item.is_self }"
              >
                <template v-slot:prepend>
                  <div class="rank-number">{{ index + 1 }}</div>
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
            <v-list lines="two">
              <v-list-subheader>Plex 观看时长榜</v-list-subheader>
              <v-list-item
                v-for="(item, index) in rankings.watched_time_rank_plex"
                :key="`plex-watched-${index}`"
                :class="{ 'bg-primary-subtle': item.is_self }"
              >
                <template v-slot:prepend>
                  <div class="rank-number">{{ index + 1 }}</div>
                </template>
                <v-list-item-title>{{ item.name }}</v-list-item-title>
                <v-list-item-subtitle>
                  {{ item.watched_time.toFixed(2) }} 小时
                </v-list-item-subtitle>
              </v-list-item>
              <v-divider class="my-3"></v-divider>
              
              <v-list-subheader>Emby 观看时长榜</v-list-subheader>
              <v-list-item
                v-for="(item, index) in rankings.watched_time_rank_emby"
                :key="`emby-watched-${index}`"
                :class="{ 'bg-primary-subtle': item.is_self }"
              >
                <template v-slot:prepend>
                  <div class="rank-number">{{ index + 1 }}</div>
                </template>
                <v-list-item-title>{{ item.name }}</v-list-item-title>
                <v-list-item-subtitle>
                  {{ item.watched_time.toFixed(2) }} 小时
                </v-list-item-subtitle>
              </v-list-item>
              <v-list-item v-if="rankings.watched_time_rank_plex.length === 0 && rankings.watched_time_rank_emby.length === 0" class="text-center">
                <v-list-item-title>暂无数据</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-window-item>
        </v-window>
      </div>
    </v-container>
  </div>
</template>

<script>
import { getRankings } from '@/api'

export default {
  name: 'Rankings',
  data() {
    return {
      activeTab: 'credits',
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
    }
  }
}
</script>

<style scoped>
.rankings-container {
  padding-bottom: 56px; /* 为底部导航栏留出空间 */
}

.rank-number {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--v-primary-base);
  color: white;
  font-weight: bold;
}

.bg-primary-subtle {
  background-color: rgba(var(--v-theme-primary), 0.1);
}
</style>