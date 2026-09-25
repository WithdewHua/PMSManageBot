<template>
  <v-dialog v-model="dialog" max-width="900" persistent scrollable>
    <v-card class="activity-dialog">
      <v-card-title class="gift-pack-dialog__titlebar">
        <div class="gift-pack-dialog__title">
          <v-icon class="mr-2" color="pink">mdi-gift</v-icon>
          我的礼包
        </div>
        <v-btn class="gift-pack-dialog__close" icon @click="close">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </v-card-title>

      <v-divider />

      <v-card-text class="pa-6">
        <div v-if="loading" class="text-center py-8">
          <v-progress-circular indeterminate color="primary" size="50" />
          <div class="mt-3">加载礼包中...</div>
        </div>

        <div v-else-if="error" class="text-center py-6">
          <v-alert type="error" variant="tonal">{{ error }}</v-alert>
          <v-btn class="mt-3" color="primary" @click="load">重试</v-btn>
        </div>

        <div v-else-if="!packs.length" class="text-center py-10">
          <v-icon size="64" color="grey-lighten-1">mdi-gift-outline</v-icon>
          <div class="text-body-1 mt-4 text-medium-emphasis">暂时没有礼包</div>
          <div class="text-caption mt-1 text-medium-emphasis">有新活动时会在这里出现</div>
        </div>

        <div v-else>
          <!-- 进行中与已领取默认展开 -->
          <div v-if="visiblePacks.length">
            <v-row>
              <v-col v-for="pack in visiblePacks" :key="pack.id" cols="12">
                <v-card variant="outlined" rounded="lg" class="gift-pack-card">
                  <v-card-title class="gift-pack-card__titlebar">
                    <div class="gift-pack-card__title">
                      <v-icon class="mr-2" :color="statusColor(pack.status)">{{ statusIcon(pack.status) }}</v-icon>
                      <span class="text-subtitle-1 gift-pack-card__title-text">{{ pack.title }}</span>
                    </div>
                    <v-chip
                      class="gift-pack-card__status"
                      :color="statusColor(pack.status)"
                      size="small"
                      variant="elevated"
                    >
                      {{ statusText(pack.status) }}
                    </v-chip>
                  </v-card-title>

                  <v-card-text>
                    <div v-if="pack.description" class="text-body-2 text-medium-emphasis mb-3">
                      {{ pack.description }}
                    </div>

                    <div class="mb-3">
                      <div class="text-caption text-medium-emphasis mb-1">礼包内容</div>
                      <div class="d-flex flex-wrap ga-2">
                        <v-chip
                          v-for="(reward, idx) in pack.rewards"
                          :key="idx"
                          size="small"
                          variant="tonal"
                          :color="rewardColor(reward.type)"
                          :prepend-icon="rewardIcon(reward.type)"
                        >
                          {{ reward.label }}
                        </v-chip>
                      </div>
                    </div>

                    <div class="d-flex flex-wrap ga-4 text-body-2">
                      <div>
                        <span class="text-medium-emphasis">剩余：</span>
                        <span v-if="pack.total_quantity === null || pack.total_quantity === undefined">不限量</span>
                        <span v-else :class="{ 'text-error': pack.remaining === 0 }">
                          {{ pack.remaining }}/{{ pack.total_quantity }}
                        </span>
                      </div>
                      <div>
                        <span class="text-medium-emphasis">截止：</span>{{ formatTime(pack.end_at) }}
                      </div>
                    </div>

                    <v-alert v-if="pack.status === 'upcoming'" class="mt-3" type="info" variant="tonal" density="compact">
                      {{ formatTime(pack.start_at) }} 开始，开始前不可领取
                      <div v-if="hasPackWindow(pack.requirements)">“礼包开始后”的任务自礼包开始时才计数，开始前的活动不计入。</div>
                    </v-alert>
                    <v-alert v-else-if="pack.task_closed || (pack.lifecycle === 'claim_only' && pack.status === 'claimable')" class="mt-3" type="warning" variant="tonal" density="compact">
                      任务已截止，带时间记录的活动不再计入进度。{{ pack.status === 'claimable' ? '仍可在礼包结束前领取。' : '仍可查看当前条件与进度。' }}
                    </v-alert>
                    <v-alert v-else-if="pack.status === 'sold_out'" class="mt-3" type="warning" variant="tonal" density="compact">礼包已领完</v-alert>
                    <v-alert v-else-if="pack.status === 'disabled'" class="mt-3" type="info" variant="tonal" density="compact">礼包已下架</v-alert>
                    <v-alert v-else-if="pack.status === 'ended'" class="mt-3" type="info" variant="tonal" density="compact">礼包已结束</v-alert>

                    <div v-if="pack.status === 'in_progress' || (pack.status === 'upcoming' && pack.requirements?.length)" class="mt-3">
                      <div class="text-subtitle-2 mb-2">领取条件与进度</div>
                      <div v-for="(progress, index) in pack.requirements || []" :key="index" class="gift-pack-progress mb-2">
                        <template v-if="progress.type === 'any_of'">
                          <div class="text-body-2 font-weight-medium">任选其一 <v-icon size="small" :color="progress.met ? 'success' : 'warning'">{{ progress.met ? 'mdi-check-circle' : 'mdi-progress-clock' }}</v-icon></div>
                          <div v-for="(item, subIndex) in progress.items" :key="subIndex" class="ml-3 mt-2">
                            <div class="text-body-2">{{ item.met ? '✓' : '○' }} {{ item.label }}<span v-if="item.target != null"> {{ item.current ?? 0 }}/{{ item.target }}</span></div>
                            <v-progress-linear v-if="item.target > 0" :model-value="progressPercent(item)" :color="item.met ? 'success' : 'warning'" rounded height="6" class="mt-1" />
                            <div v-for="(extra, i) in item.sub || []" :key="i" class="text-caption text-medium-emphasis">{{ extra.label }} {{ extra.current }}/{{ extra.target }}{{ extra.met ? ' ✓' : '' }}</div>
                          </div>
                        </template>
                        <template v-else>
                          <div class="text-body-2">{{ progress.met ? '✓' : '○' }} {{ progress.label }}<span v-if="progress.target != null"> {{ progress.current ?? 0 }}/{{ progress.target }}</span></div>
                          <v-progress-linear v-if="progress.target > 0" :model-value="progressPercent(progress)" :color="progress.met ? 'success' : 'warning'" rounded height="6" class="mt-1" />
                          <div v-for="(extra, i) in progress.sub || []" :key="i" class="text-caption text-medium-emphasis">{{ extra.label }} {{ extra.current }}/{{ extra.target }}{{ extra.met ? ' ✓' : '' }}</div>
                        </template>
                      </div>
                    </div>

                    <!-- 已领取：展示本次实际发放内容 -->
                    <div v-if="pack.status === 'claimed'" class="mt-3">
                      <v-divider class="mb-3" />
                      <div class="text-caption text-medium-emphasis mb-2">
                        于 {{ formatTime(pack.claimed_at) }} 领取
                      </div>
                      <GiftPackRewardResult
                        v-for="(item, idx) in pack.reward_snapshot || []"
                        :key="idx"
                        :item="item"
                        @notify="toast"
                      />
                    </div>
                  </v-card-text>

                  <v-card-actions v-if="pack.status === 'claimable'">
                    <v-spacer />
                    <v-btn
                      color="pink"
                      variant="elevated"
                      :loading="claimingId === pack.id"
                      :disabled="claimingId !== null"
                      @click="claim(pack)"
                    >
                      立即领取
                    </v-btn>
                  </v-card-actions>
                </v-card>
              </v-col>
            </v-row>
          </div>

          <div v-else class="text-center py-8">
            <v-icon size="48" color="grey-lighten-1">mdi-gift-outline</v-icon>
            <div class="text-body-2 mt-3 text-medium-emphasis">当前没有进行中的礼包</div>
          </div>

          <!-- 已结束且未领取的折叠收起 -->
          <v-expansion-panels v-if="missedPacks.length" class="mt-4" variant="accordion">
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon class="mr-2" size="small" color="grey">mdi-clock-alert-outline</v-icon>
                已错过的礼包（{{ missedPacks.length }}）
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <v-list density="compact">
                  <v-list-item v-for="pack in missedPacks" :key="pack.id">
                    <v-list-item-title class="text-body-2">{{ pack.title }}</v-list-item-title>
                    <v-list-item-subtitle>
                      {{ rewardSummary(pack) }} · 已于 {{ formatTime(pack.end_at) }} 结束
                    </v-list-item-subtitle>
                  </v-list-item>
                </v-list>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </div>

        <!-- 领取结果 -->
        <v-dialog v-model="resultDialog" max-width="480">
          <v-card v-if="claimResult">
            <v-card-title class="d-flex align-center">
              <v-icon class="mr-2" color="success">mdi-party-popper</v-icon>
              领取成功
            </v-card-title>
            <v-divider />
            <v-card-text class="pa-5">
              <GiftPackRewardResult
                v-for="(item, idx) in claimResult.results"
                :key="idx"
                :item="item"
                @notify="toast"
              />
            </v-card-text>
            <v-card-actions>
              <v-spacer />
              <v-btn color="primary" @click="resultDialog = false">知道了</v-btn>
            </v-card-actions>
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
import { getGiftPacks, claimGiftPack } from '@/services/giftPackService'
import GiftPackRewardResult from '@/components/GiftPackRewardResult.vue'

export default {
  name: 'GiftPackDialog',
  components: { GiftPackRewardResult },
  data() {
    return {
      dialog: false,
      loading: false,
      error: null,
      packs: [],

      claimingId: null,
      claimResult: null,
      resultDialog: false,

      snackbar: false,
      snackbarText: '',
      snackbarColor: 'success'
    }
  },
  computed: {
    // 进行中（含不可领取但仍在窗口内的）与已领取默认展开
    visiblePacks() {
      return this.packs.filter(p => p.status === 'claimed' || p.lifecycle !== 'ended')
    },
    // 已结束且该用户未领取的收进折叠区
    missedPacks() {
      return this.packs.filter(p => p.lifecycle === 'ended' && p.status !== 'claimed')
    }
  },
  methods: {
    open() {
      this.dialog = true
      this.load()
    },
    close() {
      this.dialog = false
      this.resultDialog = false
      this.claimResult = null
    },
    toast(text, color = 'success') {
      const tg = window.Telegram?.WebApp
      const msg = String(text || '')

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

      this.snackbarText = msg
      this.snackbarColor = color
      this.snackbar = true
    },
    statusText(status) {
      const map = {
        claimable: '可领取',
        claimed: '已领取',
        in_progress: '未达成',
        sold_out: '已领完',
        ended: '已结束',
        upcoming: '未开始',
        disabled: '已下架'
      }
      return map[status] || '未知'
    },
    statusColor(status) {
      const map = {
        claimable: 'pink',
        claimed: 'success',
        in_progress: 'warning',
        sold_out: 'grey',
        ended: 'grey',
        upcoming: 'info',
        disabled: 'grey'
      }
      return map[status] || 'grey'
    },
    statusIcon(status) {
      if (status === 'claimed') return 'mdi-gift-open'
      if (status === 'claimable') return 'mdi-gift'
      return 'mdi-gift-outline'
    },
    // 后端存的是 epoch 秒的绝对时间点，这里按浏览器时区展示
    formatTime(timestamp) {
      if (!timestamp) return '-'
      return new Date(Number(timestamp) * 1000).toLocaleString(undefined, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      })
    },
    rewardColor(type) {
      return { credits: 'amber-darken-2', wheel_free_spins: 'pink', tournament_wallet: 'teal', invite_codes: 'indigo' }[type] || 'deep-purple'
    },
    rewardIcon(type) {
      return {
        credits: 'mdi-circle-multiple', premium_days: 'mdi-crown',
        wheel_free_spins: 'mdi-ticket-confirmation', tournament_wallet: 'mdi-wallet',
        invite_codes: 'mdi-ticket-account', line_schedule_unlock: 'mdi-calendar-clock',
        download_unlock: 'mdi-download'
      }[type] || 'mdi-gift'
    },
    rewardSummary(pack) {
      return (pack.rewards || []).map(r => r.label).join('、')
    },
    progressPercent(item) {
      return item.target > 0 ? Math.min(100, Math.max(0, Number(item.current || 0) / item.target * 100)) : 0
    },
    hasPackWindow(requirements) {
      return (requirements || []).some(item => item.type === 'any_of'
        ? (item.items || []).some(child => child.window?.kind === 'pack')
        : item.window?.kind === 'pack')
    },
    async load() {
      try {
        this.loading = true
        this.error = null
        const res = await getGiftPacks()
        this.packs = res.data.packs || []
      } catch (e) {
        this.error = e.response?.data?.detail || '加载失败，请稍后重试'
      } finally {
        this.loading = false
      }
    },
    async claim(pack) {
      try {
        this.claimingId = pack.id
        const res = await claimGiftPack(pack.id)
        this.claimResult = res.data
        this.resultDialog = true
        await this.load()
        // 积分、Premium、余额及免费机会可能变化，通知外部刷新用户信息
        this.$emit('claimed', res.data)
      } catch (e) {
        const detail = e.response?.data?.detail
        if (detail && typeof detail === 'object' && Array.isArray(detail.requirements)) {
          // 领取时滑动时间窗可能刚好回落；先展示持锁复核得出的进度。
          pack.requirements = detail.requirements
          pack.status = 'in_progress'
          this.toast(detail.message || '领取条件尚未达成', 'error')
        } else {
          this.toast(typeof detail === 'string' ? detail : '领取失败，请稍后重试', 'error')
        }
        // 失败原因可能是余量或资格变化，刷新列表让用户看到最新状态
        await this.load()
      } finally {
        this.claimingId = null
      }
    }
  }
}
</script>

<style scoped>
.gift-pack-dialog__titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

/*
  flex 子项默认 min-width:auto，长标题会把右侧按钮挤出视野。
  显式 min-width:0 + ellipsis，让标题可截断、按钮永远可见。
*/
.gift-pack-dialog__title {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gift-pack-dialog__close {
  flex: 0 0 auto;
}

.gift-pack-card__titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.gift-pack-card__title {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
}

.gift-pack-card__title-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gift-pack-card__status {
  flex: 0 0 auto;
  white-space: nowrap;
}
.gift-pack-progress {
  border-left: 3px solid rgba(128, 128, 128, 0.25);
  padding-left: 10px;
}
</style>
