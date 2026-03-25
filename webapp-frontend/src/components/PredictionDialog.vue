<template>
  <v-dialog v-model="dialog" max-width="960" persistent>
    <v-card>
      <v-card-title class="prediction-header">
        <div class="prediction-header__top">
          <div class="prediction-header__title d-flex align-center">
            <v-icon class="mr-2" color="indigo">mdi-chart-line</v-icon>
            大预言家
          </div>
          <v-btn icon @click="close"><v-icon>mdi-close</v-icon></v-btn>
        </div>
        <div class="prediction-header__actions">
          <v-btn size="small" variant="tonal" color="indigo" @click="submissionDialog = true">
            提交题目
          </v-btn>
          <v-btn
            v-if="isAdmin"
            size="small"
            variant="tonal"
            color="deep-purple"
            @click="openReviewDialog"
          >
            审核投稿
          </v-btn>
        </div>
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
      <v-card-title class="d-flex align-center justify-space-between prediction-detail-title">
        <span class="prediction-detail-title__text">#{{ detail.market.id }} {{ detail.market.title }}</span>
        <v-btn icon class="prediction-detail-title__close" @click="detailDialog = false"><v-icon>mdi-close</v-icon></v-btn>
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

  <v-dialog v-model="submissionDialog" max-width="620" persistent>
    <v-card>
      <v-card-title class="d-flex align-center justify-space-between">
        <span>提交预测题目</span>
        <v-btn icon @click="submissionDialog = false"><v-icon>mdi-close</v-icon></v-btn>
      </v-card-title>
      <v-divider />
      <v-card-text>
        <v-text-field
          v-model="submitForm.title"
          label="预测题目"
          variant="outlined"
          density="comfortable"
          maxlength="200"
          counter
          class="mb-3"
        />
        <v-textarea
          v-model="submitForm.description"
          label="描述（可选）"
          variant="outlined"
          density="comfortable"
          maxlength="2000"
          counter
          rows="3"
          class="mb-3"
        />
        <v-text-field
          v-model="submitForm.deadlineLocal"
          label="截止时间"
          type="datetime-local"
          variant="outlined"
          density="comfortable"
        />
        <v-alert type="info" variant="tonal" class="mt-2">
          提交后将通知管理员审核，管理员可修改题目后发布。
        </v-alert>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="submissionDialog = false">取消</v-btn>
        <v-btn color="indigo" :loading="submittingTopic" @click="submitTopic">提交</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-dialog v-model="reviewDialog" max-width="960" persistent>
    <v-card>
      <v-card-title class="d-flex align-center justify-space-between">
        <span>投稿审核</span>
        <v-btn icon @click="reviewDialog = false"><v-icon>mdi-close</v-icon></v-btn>
      </v-card-title>
      <v-divider />
      <v-card-text>
        <div class="d-flex align-center ga-2 mb-3">
          <v-select
            v-model="reviewFilterStatus"
            :items="reviewStatusOptions"
            item-title="label"
            item-value="value"
            label="状态筛选"
            density="comfortable"
            variant="outlined"
            hide-details
            class="review-filter"
          />
          <v-btn color="primary" variant="text" :loading="reviewLoading" @click="loadSubmissions">
            刷新
          </v-btn>
        </div>

        <v-list v-if="submissions.length > 0" lines="three">
          <v-list-item v-for="item in submissions" :key="item.id" class="submission-item">
            <template #title>
              <div class="d-flex align-center justify-space-between ga-2">
                <span class="text-truncate">#{{ item.id }} {{ item.title }}</span>
                <v-chip size="small" :color="submissionStatusColor(item.status)">
                  {{ submissionStatusText(item.status) }}
                </v-chip>
              </div>
            </template>
            <template #subtitle>
              <div class="mt-1">
                <div>提交人：{{ item.submitter_tg_id }} ｜ 截止：{{ formatDeadline(item.betting_deadline) }}</div>
                <div class="text-medium-emphasis">{{ item.description || '暂无描述' }}</div>
              </div>
            </template>
            <template #append>
              <v-btn
                v-if="item.status === 0"
                size="small"
                color="deep-purple"
                variant="tonal"
                @click="openReviewForm(item)"
              >
                审核
              </v-btn>
            </template>
          </v-list-item>
        </v-list>
        <div v-else class="text-body-2 text-medium-emphasis py-4">暂无投稿数据</div>

        <v-divider class="my-4" />

        <div v-if="reviewForm.id">
          <div class="text-subtitle-1 mb-2">审核投稿 #{{ reviewForm.id }}</div>
          <v-text-field
            v-model="reviewForm.title"
            label="题目（可修改）"
            variant="outlined"
            density="comfortable"
            maxlength="200"
            counter
            class="mb-2"
          />
          <v-textarea
            v-model="reviewForm.description"
            label="描述（可修改）"
            variant="outlined"
            density="comfortable"
            maxlength="2000"
            counter
            rows="3"
            class="mb-2"
          />
          <v-text-field
            v-model="reviewForm.deadlineLocal"
            label="截止时间（可修改）"
            type="datetime-local"
            variant="outlined"
            density="comfortable"
            class="mb-2"
          />
          <v-textarea
            v-model="reviewForm.note"
            label="审核备注（可选）"
            variant="outlined"
            density="comfortable"
            rows="2"
          />
          <div class="d-flex ga-2 mt-3">
            <v-btn color="success" :loading="reviewSubmitting" @click="submitReview(true)">通过并发布</v-btn>
            <v-btn color="error" variant="tonal" :loading="reviewSubmitting" @click="submitReview(false)">拒绝</v-btn>
          </div>
        </div>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>
import {
  listPredictionSubmissions,
  getPredictionMarketDetail,
  reviewPredictionSubmission,
  listPredictionBets,
  listPredictionMarkets,
  placePredictionBet,
  submitPredictionMarket
} from '@/services/predictionService'
import { getUserInfo } from '@/api'

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
      isAdmin: false,
      submissionDialog: false,
      submittingTopic: false,
      submitForm: {
        title: '',
        description: '',
        deadlineLocal: ''
      },
      reviewDialog: false,
      reviewLoading: false,
      reviewSubmitting: false,
      reviewFilterStatus: 0,
      reviewStatusOptions: [
        { label: '待审核', value: 0 },
        { label: '已通过', value: 1 },
        { label: '已拒绝', value: 2 },
        { label: '全部', value: -1 }
      ],
      submissions: [],
      reviewForm: {
        id: null,
        title: '',
        description: '',
        deadlineLocal: '',
        note: ''
      },
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
      this.loadCurrentUser()
      this.load()
    },
    close() {
      this.dialog = false
      this.detailDialog = false
      this.detail = null
      this.bets = []
      this.reviewForm = {
        id: null,
        title: '',
        description: '',
        deadlineLocal: '',
        note: ''
      }
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
    toLocalInput(ts) {
      if (!ts) return ''
      const date = new Date(Number(ts) * 1000)
      if (Number.isNaN(date.getTime())) return ''
      const p = (v) => String(v).padStart(2, '0')
      return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}T${p(date.getHours())}:${p(date.getMinutes())}`
    },
    parseLocalInputToTs(value) {
      if (!value) return null
      const d = new Date(value)
      if (Number.isNaN(d.getTime())) return null
      return Math.floor(d.getTime() / 1000)
    },
    submissionStatusText(status) {
      if (status === 0) return '待审核'
      if (status === 1) return '已通过'
      if (status === 2) return '已拒绝'
      return '未知'
    },
    submissionStatusColor(status) {
      if (status === 0) return 'orange'
      if (status === 1) return 'success'
      if (status === 2) return 'error'
      return 'grey'
    },
    async loadCurrentUser() {
      try {
        const res = await getUserInfo()
        this.isAdmin = !!res?.data?.is_admin
      } catch (e) {
        this.isAdmin = false
      }
    },
    async submitTopic() {
      const title = String(this.submitForm.title || '').trim()
      const deadline = this.parseLocalInputToTs(this.submitForm.deadlineLocal)
      if (!title) {
        this.toast('请填写预测题目', 'warning')
        return
      }
      if (!deadline) {
        this.toast('请填写有效截止时间', 'warning')
        return
      }
      if (deadline <= Math.floor(Date.now() / 1000)) {
        this.toast('截止时间必须晚于当前时间', 'warning')
        return
      }
      try {
        this.submittingTopic = true
        await submitPredictionMarket({
          title,
          description: this.submitForm.description || null,
          betting_deadline: deadline
        })
        this.toast('提交成功，已通知管理员审核')
        this.submitForm = {
          title: '',
          description: '',
          deadlineLocal: ''
        }
        this.submissionDialog = false
      } catch (e) {
        this.toast(e.response?.data?.detail || '提交失败', 'error')
      } finally {
        this.submittingTopic = false
      }
    },
    async openReviewDialog() {
      this.reviewDialog = true
      await this.loadSubmissions()
    },
    async loadSubmissions() {
      try {
        this.reviewLoading = true
        const params = { limit: 50 }
        if (Number(this.reviewFilterStatus) >= 0) {
          params.status = Number(this.reviewFilterStatus)
        }
        const res = await listPredictionSubmissions(params)
        this.submissions = res?.data?.submissions || []
      } catch (e) {
        this.toast(e.response?.data?.detail || '加载投稿失败', 'error')
      } finally {
        this.reviewLoading = false
      }
    },
    openReviewForm(item) {
      this.reviewForm = {
        id: Number(item.id),
        title: String(item.title || ''),
        description: String(item.description || ''),
        deadlineLocal: this.toLocalInput(item.betting_deadline),
        note: ''
      }
    },
    async submitReview(approved) {
      if (!this.reviewForm.id) {
        this.toast('请先选择一个投稿', 'warning')
        return
      }
      const title = String(this.reviewForm.title || '').trim()
      const deadline = this.parseLocalInputToTs(this.reviewForm.deadlineLocal)
      if (!title) {
        this.toast('题目不能为空', 'warning')
        return
      }
      if (!deadline || deadline <= Math.floor(Date.now() / 1000)) {
        this.toast('请设置晚于当前时间的截止时间', 'warning')
        return
      }

      try {
        this.reviewSubmitting = true
        await reviewPredictionSubmission(this.reviewForm.id, {
          approved: !!approved,
          review_note: this.reviewForm.note || null,
          title,
          description: this.reviewForm.description || null,
          betting_deadline: deadline
        })
        this.toast(approved ? '审核通过并发布成功' : '已拒绝该投稿')
        this.reviewForm = {
          id: null,
          title: '',
          description: '',
          deadlineLocal: '',
          note: ''
        }
        await this.loadSubmissions()
        await this.load()
      } catch (e) {
        this.toast(e.response?.data?.detail || '审核操作失败', 'error')
      } finally {
        this.reviewSubmitting = false
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

.prediction-detail-title {
  min-width: 0;
}

.prediction-detail-title__text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prediction-detail-title__close {
  flex-shrink: 0;
  margin-left: 8px;
}

.prediction-header {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.prediction-header__top {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.prediction-header__title {
  min-width: 0;
  font-weight: 600;
}

.prediction-header__actions {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.review-filter {
  max-width: 200px;
}

.submission-item {
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 10px;
  margin-bottom: 8px;
}

@media (max-width: 640px) {
  .prediction-header {
    gap: 8px;
  }

  .option-buttons {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
