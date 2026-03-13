<template>
  <v-dialog v-model="dialog" max-width="900" persistent>
    <v-card class="activity-dialog">
      <v-card-title class="treasure-dialog__titlebar">
        <div class="treasure-dialog__title">
          <v-icon class="mr-2" color="deep-purple">mdi-treasure-chest</v-icon>
          夺宝奇兵
        </div>
        <v-btn class="treasure-dialog__close" icon @click="close">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </v-card-title>

      <v-divider />

      <v-card-text class="pa-6">
        <div v-if="loading" class="text-center py-8">
          <v-progress-circular indeterminate color="primary" size="50" />
          <div class="mt-3">加载期数中...</div>
        </div>

        <div v-else-if="error" class="text-center py-6">
          <v-alert type="error" variant="tonal">{{ error }}</v-alert>
          <v-btn class="mt-3" color="primary" @click="load">重试</v-btn>
        </div>

        <div v-else>
          <v-row>
            <v-col v-for="issue in issues" :key="issue.id" cols="12" md="6">
              <v-card variant="outlined" rounded="lg" class="issue-card" @click="openIssue(issue)">
                <v-card-title class="treasure-issue__titlebar">
                  <div class="treasure-issue__title">
                    <v-icon class="mr-2" color="deep-purple">mdi-treasure-chest</v-icon>
                    <span class="text-subtitle-1 treasure-issue__title-text">{{ issue.title }}</span>
                  </div>
                  <v-chip class="treasure-issue__status" :color="statusColor(issue.status)" size="small" variant="elevated">
                    {{ statusText(issue.status) }}
                  </v-chip>
                </v-card-title>

                <v-card-text>
                  <div class="d-flex justify-space-between">
                    <div>
                      <div class="text-caption text-medium-emphasis">奖池</div>
                      <div class="text-h6 text-primary">{{ issue.prize_credits }}</div>
                    </div>
                    <div>
                      <div class="text-caption text-medium-emphasis">每份</div>
                      <div class="text-h6">{{ issue.credits_per_share }}</div>
                    </div>
                    <div>
                      <div class="text-caption text-medium-emphasis">进度</div>
                      <div class="text-h6">{{ issue.shares_sold }}/{{ issue.total_shares }}</div>
                    </div>
                  </div>

                  <v-progress-linear
                    class="mt-3"
                    :model-value="Math.min(100, (issue.shares_sold / issue.total_shares) * 100)"
                    color="deep-purple"
                    height="8"
                    rounded
                  />

                  <div v-if="issue.winner_number" class="mt-2 text-body-2">
                    中奖号码：<span class="font-weight-bold">{{ issue.winner_number }}</span>
                  </div>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
        </div>

        <!-- 期数详情弹窗 -->
        <v-dialog v-model="detailDialog" max-width="800" persistent>
          <v-card v-if="selectedIssue">
            <v-card-title class="treasure-dialog__titlebar">
              <div class="treasure-dialog__title">
                <v-icon class="mr-2" color="deep-purple">mdi-treasure-chest</v-icon>
                {{ selectedIssue.title }}
              </div>
              <v-btn class="treasure-dialog__close" icon @click="detailDialog=false"><v-icon>mdi-close</v-icon></v-btn>
            </v-card-title>
            <v-divider />

            <v-card-text class="pa-6">
              <v-alert type="info" variant="tonal" density="compact" class="mb-4">
                每份 {{ selectedIssue.credits_per_share }} 积分，满 {{ selectedIssue.total_shares }} 份立即开奖。
              </v-alert>

              <div class="d-flex justify-space-between mb-2">
                <div class="text-body-2">进度：{{ selectedIssue.shares_sold }}/{{ selectedIssue.total_shares }}</div>
                <div class="text-body-2">状态：{{ statusText(selectedIssue.status) }}</div>
              </div>

              <v-progress-linear
                :model-value="Math.min(100, (selectedIssue.shares_sold / selectedIssue.total_shares) * 100)"
                color="deep-purple"
                height="10"
                rounded
                class="mb-4"
              />

              <div v-if="selectedIssue.winner_number" class="mb-4">
                <v-alert type="success" variant="tonal">
                  已开奖：中奖号码 {{ selectedIssue.winner_number }}
                </v-alert>
              </div>

              <div class="treasure-join-row mb-4">
                <v-text-field
                  v-model.number="quantity"
                  class="treasure-qty"
                  label="购买份数"
                  type="number"
                  variant="outlined"
                  density="compact"
                  hide-details
                  :min="1"
                  :max="100"
                />
                <v-btn
                  class="treasure-join-btn"
                  color="deep-purple"
                  :loading="joining"
                  :disabled="selectedIssue.status !== 1"
                  @click="joinSelected"
                >
                  立即参与
                </v-btn>
              </div>

              <v-divider class="my-4" />

              <div class="d-flex align-center justify-space-between">
                <div class="text-subtitle-2">最近参与记录</div>
                <v-btn size="small" variant="text" @click="loadParticipations">刷新</v-btn>
              </div>

              <div v-if="pLoading" class="text-center py-6">
                <v-progress-circular indeterminate color="primary" size="32" />
              </div>
              <div v-else>
                <v-list density="compact">
                  <v-list-item v-for="p in participations" :key="p.id">
                    <v-list-item-title>
                      #{{ p.issue_seq || p.id }} · 号码 {{ p.lucky_number }}
                    </v-list-item-title>
                    <v-list-item-subtitle>
                      用户 {{ p.tg_username || p.tg_id }} · {{ formatMs(p.created_at_ms) }}
                    </v-list-item-subtitle>
                  </v-list-item>
                </v-list>
              </div>
            </v-card-text>
          </v-card>
        </v-dialog>

        <v-snackbar v-model="snackbar" :color="snackbarColor" timeout="3000">
          {{ snackbarText }}
        </v-snackbar>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>
import { listTreasureIssues, joinTreasureIssue, listTreasureParticipations } from '@/services/treasureService'

export default {
  name: 'TreasureDialog',
  data() {
    return {
      dialog: false,
      loading: false,
      error: null,
      issues: [],

      detailDialog: false,
      selectedIssue: null,
    quantity: 1,
      joining: false,

      participations: [],
      pLoading: false,

      snackbar: false,
      snackbarText: '',
      snackbarColor: 'success'
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
      this.selectedIssue = null
      this.participations = []
    },
    toast(text, color = 'success') {
      const tg = window.Telegram?.WebApp
      const msg = String(text || '')

      // TG 环境：成功用 popup（更像“操作完成”），失败用 alert（更醒目）
      if (tg) {
        if (color === 'success' && tg.showPopup) {
          tg.showPopup({
            title: '提示',
            message: msg,
            buttons: [{ type: 'ok', text: '好的' }]
          })
          return
        }
        if (tg.showAlert) {
          tg.showAlert(msg)
          return
        }
      }

      // 非 TG 环境兜底（本地浏览器等）
      this.snackbarText = msg
      this.snackbarColor = color
      this.snackbar = true
    },
    statusText(status) {
      if (status === 1) return '进行中'
      if (status === 2) return '已开奖'
      if (status === 3) return '已取消'
      return '未知'
    },
    statusColor(status) {
      if (status === 1) return 'deep-purple'
      if (status === 2) return 'success'
      if (status === 3) return 'grey'
      return 'grey'
    },
    formatMs(ms) {
      const d = new Date(Number(ms))
      const pad = (n, len = 2) => String(n).padStart(len, '0')
      return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
    },
    async load() {
      try {
        this.loading = true
        this.error = null
        const res = await listTreasureIssues({ include_closed: true, limit: 50 })
        this.issues = res.data.issues || []
      } catch (e) {
        this.error = e.response?.data?.detail || '加载失败，请稍后重试'
        this.toast(this.error, 'error')
      } finally {
        this.loading = false
      }
    },
    async openIssue(issue) {
      this.selectedIssue = issue
      this.quantity = 1
      this.detailDialog = true
      await this.loadParticipations()
    },
    async loadParticipations() {
      if (!this.selectedIssue) return
      try {
        this.pLoading = true
        const res = await listTreasureParticipations(this.selectedIssue.id, 50)
        this.participations = res.data.participations || []
      } catch (e) {
        this.toast(e.response?.data?.detail || '加载参与记录失败，请稍后重试', 'error')
      } finally {
        this.pLoading = false
      }
    },
    async joinSelected() {
      if (!this.selectedIssue) return
      try {
        this.joining = true
        const qty = Math.max(1, Math.min(100, Number(this.quantity || 1)))
        const res = await joinTreasureIssue(this.selectedIssue.id, qty)
        const data = res.data
        if (data.settled) {
          this.toast(`已满员开奖！中奖号码：${data.winner_number}`, 'success')
        } else {
          const nums = (data.participations || [])
            .map(p => p.lucky_number)
            .filter(n => n !== undefined && n !== null)
          if (nums.length > 1) {
            this.toast(`参与成功，获得号码 ${nums.join('、')}`, 'success')
          } else {
            this.toast(`参与成功，获得号码 ${data.participation?.lucky_number}`, 'success')
          }
        }
        await this.load()
        const updated = this.issues.find(i => i.id === this.selectedIssue.id)
        if (updated) this.selectedIssue = updated
        await this.loadParticipations()
      } catch (e) {
        this.toast(e.response?.data?.detail || '参与失败，请稍后重试', 'error')
      } finally {
        this.joining = false
      }
    }
  }
}
</script>

<style scoped>
.treasure-dialog__titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

/*
  关键点：flex 子项默认 min-width:auto，会导致长标题把右侧按钮“挤出/遮住”。
  这里显式设置 min-width:0 + ellipsis，让标题可截断，按钮永远可见。
*/
.treasure-dialog__title {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.treasure-dialog__close {
  flex: 0 0 auto;
}

.treasure-issue__titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.treasure-issue__title {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
}

.treasure-issue__title-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.treasure-issue__status {
  flex: 0 0 auto;
  white-space: nowrap;
}

.issue-card {
  cursor: pointer;
}

.treasure-join-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 让输入框在宽屏下“吃掉”空白，按钮保持合适宽度 */
.treasure-qty {
  flex: 1 1 220px;
  min-width: 140px;
}

.treasure-join-btn {
  flex: 0 0 auto;
  min-width: 120px;
}

/* 小屏更舒服：允许换行，按钮占满一行 */
@media (max-width: 420px) {
  .treasure-join-row {
    flex-wrap: wrap;
  }

  .treasure-qty {
    flex-basis: 100%;
  }

  .treasure-join-btn {
    width: 100%;
  }
}
</style>
