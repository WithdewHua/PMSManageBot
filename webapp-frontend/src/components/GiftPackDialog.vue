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
                          :color="reward.type === 'credits' ? 'amber-darken-2' : 'deep-purple'"
                          :prepend-icon="reward.type === 'credits' ? 'mdi-circle-multiple' : 'mdi-crown'"
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

                    <v-alert
                      v-if="pack.status === 'ineligible' && pack.ineligible_reasons.length"
                      class="mt-3"
                      type="warning"
                      variant="tonal"
                      density="compact"
                    >
                      <div v-for="(reason, idx) in pack.ineligible_reasons" :key="idx">{{ reason }}</div>
                    </v-alert>

                    <v-alert
                      v-else-if="pack.status === 'upcoming'"
                      class="mt-3"
                      type="info"
                      variant="tonal"
                      density="compact"
                    >
                      {{ formatTime(pack.start_at) }} 开始
                    </v-alert>

                    <!-- 已领取：展示本次实际发放内容 -->
                    <div v-if="pack.status === 'claimed'" class="mt-3">
                      <v-divider class="mb-3" />
                      <div class="text-caption text-medium-emphasis mb-2">
                        于 {{ formatTime(pack.claimed_at) }} 领取
                      </div>
                      <div v-for="(item, idx) in pack.reward_snapshot || []" :key="idx" class="text-body-2 mb-1">
                        <v-icon
                          size="small"
                          class="mr-1"
                          :color="item.skipped ? 'grey' : 'success'"
                        >
                          {{ item.skipped ? 'mdi-minus-circle-outline' : 'mdi-check-circle' }}
                        </v-icon>
                        {{ snapshotText(item) }}
                      </div>
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
              <div
                v-for="(item, idx) in claimResult.results"
                :key="idx"
                class="d-flex align-start mb-3"
              >
                <v-icon
                  class="mr-2 mt-1"
                  size="small"
                  :color="item.skipped ? 'grey' : 'success'"
                >
                  {{ item.skipped ? 'mdi-minus-circle-outline' : 'mdi-check-circle' }}
                </v-icon>
                <div>
                  <div class="text-body-2">{{ snapshotText(item) }}</div>
                  <div v-if="item.new_expiry" class="text-caption text-medium-emphasis">
                    新到期时间：{{ formatIso(item.new_expiry) }}
                  </div>
                </div>
              </div>
              <v-alert
                v-if="hasSkipped"
                type="info"
                variant="tonal"
                density="compact"
                class="mt-2"
              >
                永久会员无需延长 Premium，该部分未生效。
              </v-alert>
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

export default {
  name: 'GiftPackDialog',
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
    },
    hasSkipped() {
      return (this.claimResult?.results || []).some(item => item.skipped)
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
        ineligible: '条件未满足',
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
        ineligible: 'warning',
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
    formatIso(iso) {
      if (!iso) return '-'
      const d = new Date(iso)
      if (Number.isNaN(d.getTime())) return iso
      return d.toLocaleString(undefined, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      })
    },
    rewardSummary(pack) {
      return (pack.rewards || []).map(r => r.label).join('、')
    },
    snapshotText(item) {
      if (item.type === 'premium_days') {
        const service = (item.service || '').toUpperCase()
        if (item.skipped === 'lifetime') {
          return `${service}：永久会员，${item.days} 天 Premium 未生效`
        }
        return `${service}：Premium 延长 ${item.days} 天`
      }
      if (item.type === 'credits') {
        return `获得 ${item.amount} 积分`
      }
      return item.label || ''
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
        // 积分/Premium 已变化，通知外部刷新用户信息
        this.$emit('claimed', res.data)
      } catch (e) {
        this.toast(e.response?.data?.detail || '领取失败，请稍后重试', 'error')
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
</style>
