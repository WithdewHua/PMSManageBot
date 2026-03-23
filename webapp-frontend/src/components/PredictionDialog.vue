<template>
  <v-dialog v-model="dialog" max-width="960" persistent>
    <v-card>
      <v-card-title class="d-flex align-center justify-space-between">
        <div class="d-flex align-center">
          <v-icon class="mr-2" color="indigo">mdi-chart-line</v-icon>
          预测游戏
        </div>
        <v-btn icon @click="close"><v-icon>mdi-close</v-icon></v-btn>
      </v-card-title>
      <v-divider />

      <v-card-text class="pa-6">
        <div v-if="loading" class="text-center py-8">
          <v-progress-circular indeterminate color="primary" size="42" />
          <div class="mt-2">加载预测题目中...</div>
        </div>

        <div v-else-if="error" class="text-center py-8">
          <v-alert type="error" variant="tonal">{{ error }}</v-alert>
          <v-btn class="mt-3" color="primary" @click="load">重试</v-btn>
        </div>

        <div v-else>
          <v-row>
            <v-col v-for="m in markets" :key="m.id" cols="12" md="6">
              <v-card variant="outlined" rounded="lg" class="market-card" @click="openDetail(m)">
                <v-card-title class="text-subtitle-1 d-flex align-center justify-space-between">
                  <span class="text-truncate">#{{ m.id }} {{ m.title }}</span>
                  <v-chip size="small" :color="statusColor(m.status)">{{ statusText(m.status) }}</v-chip>
                </v-card-title>
                <v-card-text>
                  <div class="text-body-2 text-medium-emphasis mb-2">{{ m.description || '暂无描述' }}</div>
                  <div class="d-flex justify-space-between">
                    <div>YES 池：<b>{{ m.real_yes_pool }}</b></div>
                    <div>NO 池：<b>{{ m.real_no_pool }}</b></div>
                  </div>
                  <div class="d-flex justify-space-between mt-1">
                    <div>YES 赔率：{{ m.yes_odds.toFixed(2) }}</div>
                    <div>NO 赔率：{{ m.no_odds.toFixed(2) }}</div>
                  </div>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
        </div>
      </v-card-text>
    </v-card>
  </v-dialog>

  <v-dialog v-model="detailDialog" max-width="860" persistent>
    <v-card v-if="detail">
      <v-card-title class="d-flex align-center justify-space-between">
        <span>#{{ detail.market.id }} {{ detail.market.title }}</span>
        <v-btn icon @click="detailDialog = false"><v-icon>mdi-close</v-icon></v-btn>
      </v-card-title>
      <v-divider />
      <v-card-text class="pa-6">
        <div class="betting-panel mb-4">
          <div class="d-flex align-center justify-space-between mb-3">
            <v-chip size="small" :color="statusColor(detail.market.status)" variant="flat">
              {{ statusText(detail.market.status) }}
            </v-chip>
            <div class="text-caption text-medium-emphasis" v-if="detail.market.betting_deadline">
              截止 {{ formatDeadline(detail.market.betting_deadline) }}
            </div>
          </div>

          <div class="text-subtitle-1 font-weight-bold mb-3">{{ detail.market.title }}</div>

          <div class="text-body-2 text-medium-emphasis mb-2">当前押注分布</div>
          <div class="bet-distribution mb-2">
            <div class="yes-bar" :style="{ width: `${getYesPercent()}%` }"></div>
            <div class="no-bar" :style="{ width: `${getNoPercent()}%` }"></div>
          </div>
          <div class="d-flex justify-space-between text-body-2 mb-4">
            <div>YES {{ getYesPercent().toFixed(0) }}%</div>
            <div>NO {{ getNoPercent().toFixed(0) }}%</div>
          </div>

          <div class="option-buttons mb-4">
            <v-btn
              block
              class="option-btn"
              :class="{ 'option-btn--active': Number(betOption) === 1 }"
              variant="outlined"
              @click="betOption = 1"
            >
              YES 赔率 ×{{ Number(detail.market.yes_odds || 0).toFixed(2) }}
            </v-btn>
            <v-btn
              block
              class="option-btn"
              :class="{ 'option-btn--active': Number(betOption) === 0 }"
              variant="outlined"
              @click="betOption = 0"
            >
              NO 赔率 ×{{ Number(detail.market.no_odds || 0).toFixed(2) }}
            </v-btn>
          </div>

          <div class="text-body-2 text-medium-emphasis mb-2">押注积分</div>
          <v-text-field
            v-model.number="betAmount"
            label="输入押注数量"
            type="number"
            :min="10"
            :max="500"
            density="comfortable"
            variant="outlined"
            class="mb-3"
          />

          <v-btn
            block
            color="indigo"
            :loading="betting"
            @click="submitBet"
            :disabled="detail.market.status !== 1 || Number(betAmount || 0) < 10 || Number(betAmount || 0) > 500"
          >
            立即押注
          </v-btn>
        </div>

        <div class="d-flex justify-space-between mb-4">
          <div>我的 YES：{{ detail.my_yes_amount }}</div>
          <div>我的 NO：{{ detail.my_no_amount }}</div>
        </div>

        <v-divider class="my-4" />

        <div class="stats-grid mb-4">
          <div class="stat-box">
            <div class="text-caption text-medium-emphasis">总奖池</div>
            <div class="text-h6 font-weight-bold">{{ totalPool() }}</div>
          </div>
          <div class="stat-box">
            <div class="text-caption text-medium-emphasis">参与人数</div>
            <div class="text-h6 font-weight-bold">{{ participantCount() }}</div>
          </div>
          <div class="stat-box">
            <div class="text-caption text-medium-emphasis">冷门赔率</div>
            <div class="text-h6 font-weight-bold">×{{ coldOdds().toFixed(2) }}</div>
          </div>
        </div>

        <div class="d-flex align-center justify-space-between mb-2">
          <div class="text-subtitle-2">最近押注</div>
          <v-btn size="small" variant="text" @click="loadBets">刷新</v-btn>
        </div>
        <v-list density="compact" v-if="bets.length > 0">
          <v-list-item v-for="b in bets" :key="b.id">
            <v-list-item-title>
              {{ b.tg_username || b.tg_id }} · {{ b.option === 1 ? 'YES' : 'NO' }} · {{ b.amount }}
            </v-list-item-title>
          </v-list-item>
        </v-list>
        <div v-else class="text-body-2 text-medium-emphasis">暂无押注记录</div>
      </v-card-text>
    </v-card>
  </v-dialog>

  <v-snackbar v-model="snackbar" :color="snackbarColor" timeout="3000">{{ snackbarText }}</v-snackbar>
</template>

<script>
import {
  getPredictionMarketDetail,
  listPredictionBets,
  listPredictionMarkets,
  placePredictionBet
} from '@/services/predictionService'

export default {
  name: 'PredictionDialog',
  data() {
    return {
      dialog: false,
      detailDialog: false,
      loading: false,
      error: null,
      markets: [],
      detail: null,
      bets: [],
      betOption: 1,
      betAmount: 50,
      betting: false,
      snackbar: false,
      snackbarText: '',
      snackbarColor: 'success',
      betOptions: [
        { label: 'YES', value: 1 },
        { label: 'NO', value: 0 }
      ]
    }
  },
  methods: {
    open() {
      this.dialog = true
      this.load()
    },
    close() {
      this.dialog = false
      this.detailDialog = false
      this.detail = null
      this.bets = []
    },
    toast(text, color = 'success') {
      this.snackbarText = String(text || '')
      this.snackbarColor = color
      this.snackbar = true
    },
    statusText(status) {
      if (status === 1) return '押注中'
      if (status === 2) return '已截止'
      if (status === 3) return '已结算'
      if (status === 4) return '已取消'
      return '未知'
    },
    statusColor(status) {
      if (status === 1) return 'indigo'
      if (status === 2) return 'orange'
      if (status === 3) return 'success'
      return 'grey'
    },
    getYesPercent() {
      const yes = Number(this.detail?.market?.real_yes_pool || 0)
      const no = Number(this.detail?.market?.real_no_pool || 0)
      const total = yes + no
      if (total <= 0) return 50
      return (yes / total) * 100
    },
    getNoPercent() {
      return 100 - this.getYesPercent()
    },
    totalPool() {
      const yes = Number(this.detail?.market?.real_yes_pool || 0)
      const no = Number(this.detail?.market?.real_no_pool || 0)
      return (yes + no).toLocaleString('zh-CN')
    },
    participantCount() {
      if (!Array.isArray(this.bets) || this.bets.length === 0) return 0
      return new Set(this.bets.map((b) => Number(b.tg_id))).size
    },
    coldOdds() {
      const yesOdds = Number(this.detail?.market?.yes_odds || 0)
      const noOdds = Number(this.detail?.market?.no_odds || 0)
      return Math.max(yesOdds, noOdds)
    },
    formatDeadline(ts) {
      if (!ts) return '未设置'
      try {
        return new Date(Number(ts) * 1000).toLocaleString('zh-CN', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit'
        })
      } catch (err) {
        return String(ts)
      }
    },
    async load() {
      try {
        this.loading = true
        this.error = null
        const res = await listPredictionMarkets({ include_closed: true, limit: 50 })
        this.markets = res.data.markets || []
      } catch (e) {
        this.error = e.response?.data?.detail || '加载失败'
      } finally {
        this.loading = false
      }
    },
    async openDetail(market) {
      try {
        const res = await getPredictionMarketDetail(market.id)
        this.detail = res.data
        this.betOption = 1
        this.betAmount = 50
        this.detailDialog = true
        await this.loadBets()
      } catch (e) {
        this.toast(e.response?.data?.detail || '加载题目详情失败', 'error')
      }
    },
    async loadBets() {
      if (!this.detail?.market?.id) return
      try {
        const res = await listPredictionBets(this.detail.market.id, 100)
        this.bets = res.data.bets || []
      } catch (e) {
        this.toast(e.response?.data?.detail || '加载押注记录失败', 'error')
      }
    },
    async submitBet() {
      if (!this.detail?.market?.id) return
      const amount = Number(this.betAmount || 0)
      if (amount < 10 || amount > 500) {
        this.toast('押注积分需在 10~500 之间', 'warning')
        return
      }
      const nowSec = Math.floor(Date.now() / 1000)
      if (this.detail.market.betting_deadline && nowSec >= Number(this.detail.market.betting_deadline)) {
        this.toast('已过截止时间，无法继续押注', 'warning')
        return
      }
      try {
        this.betting = true
        const res = await placePredictionBet(this.detail.market.id, Number(this.betOption), amount)
        const market = res?.data?.market || {}
        this.detail.market = {
          ...(this.detail.market || {}),
          ...market
        }

        if (Object.prototype.hasOwnProperty.call(market, 'my_yes_amount')) {
          this.detail.my_yes_amount = Number(market.my_yes_amount) || 0
        } else if (Number(this.betOption) === 1) {
          this.detail.my_yes_amount = Number(this.detail.my_yes_amount || 0) + amount
        }

        if (Object.prototype.hasOwnProperty.call(market, 'my_no_amount')) {
          this.detail.my_no_amount = Number(market.my_no_amount) || 0
        } else if (Number(this.betOption) === 0) {
          this.detail.my_no_amount = Number(this.detail.my_no_amount || 0) + amount
        }

        await this.loadBets()
        await this.load()
        this.toast('押注成功')
      } catch (e) {
        this.toast(e.response?.data?.detail || '押注失败', 'error')
      } finally {
        this.betting = false
      }
    }
  }
}
</script>

<style scoped>
.market-card {
  cursor: pointer;
}

.betting-panel {
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 14px;
  padding: 16px;
  background: #fafafa;
}

.bet-distribution {
  display: flex;
  width: 100%;
  height: 10px;
  border-radius: 999px;
  overflow: hidden;
  background: #ececec;
}

.yes-bar {
  background: #2eaf6f;
}

.no-bar {
  background: #d9534f;
}

.option-buttons {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.option-btn {
  height: 44px;
  min-width: 0;
}

.option-btn :deep(.v-btn__content) {
  white-space: normal;
  text-align: center;
  line-height: 1.2;
}

.option-btn--active {
  border-width: 2px;
  background: rgba(63, 81, 181, 0.06);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.stat-box {
  background: #f3f3f3;
  border-radius: 10px;
  padding: 12px;
  text-align: center;
}

@media (max-width: 640px) {
  .option-buttons {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
