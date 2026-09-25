<template>
  <v-dialog v-model="dialog" max-width="440" persistent>
    <v-card class="gift-prompt">
      <div class="gift-prompt__hero">
        <v-icon size="52" color="white">mdi-gift</v-icon>
        <div class="text-h6 mt-2">{{ packs.length ? '你有礼包可以领取' : '你有礼包任务待完成' }}</div>
        <div class="text-caption mt-1">共 {{ packs.length + taskPacks.length }} 个礼包</div>
      </div>

      <v-card-text class="pa-5 gift-prompt__body">
        <div v-if="packs.length" class="text-subtitle-2 font-weight-bold mb-2">可以领了（{{ packs.length }}）</div>
        <div v-for="pack in displayPacks" :key="pack.id" class="gift-prompt__item">
          <div class="d-flex align-center justify-space-between mb-1">
            <span class="text-subtitle-2 gift-prompt__item-title">{{ pack.title }}</span>
            <v-chip
              v-if="pack.total_quantity"
              size="x-small"
              variant="tonal"
              :color="pack.remaining <= 3 ? 'error' : 'grey'"
            >
              剩 {{ pack.remaining }}/{{ pack.total_quantity }}
            </v-chip>
            <v-chip v-else size="x-small" variant="tonal" color="grey">不限量</v-chip>
          </div>
          <div class="d-flex flex-wrap ga-1">
            <v-chip
              v-for="(reward, idx) in pack.rewards"
              :key="idx"
              size="x-small"
              variant="tonal"
              :color="rewardColor(reward.type)"
              :prepend-icon="rewardIcon(reward.type)"
            >
              {{ rewardLabel(reward) }}
            </v-chip>
          </div>
        </div>

        <!-- 超过 3 个不逐条铺开，避免弹窗过长 -->
        <div v-if="truncatedCount > 0" class="text-caption text-medium-emphasis mt-2">可领取礼包还有 {{ truncatedCount }} 个，请前往礼包中心查看</div>

        <div v-if="taskPacks.length" class="text-subtitle-2 font-weight-bold mb-2 mt-4">待完成（{{ taskPacks.length }}）</div>
        <div v-for="pack in displayTaskPacks" :key="pack.id" class="gift-prompt__item">
          <div class="d-flex justify-space-between align-center">
            <span class="text-subtitle-2 gift-prompt__item-title">{{ pack.title }}</span>
            <v-chip v-if="pack.total_quantity" size="x-small" variant="tonal" :color="pack.remaining <= 3 ? 'error' : 'grey'">剩 {{ pack.remaining }}/{{ pack.total_quantity }}</v-chip>
            <v-chip v-else size="x-small" variant="tonal" color="grey">不限量</v-chip>
          </div>
          <div v-for="(progress, index) in pack.requirements || []" :key="index" class="text-caption mt-2">
            <template v-if="progress.type === 'any_of'">
              <div class="font-weight-medium">任选其一{{ progress.met ? ' ✓' : '' }}</div>
              <div v-for="(item, i) in progress.items" :key="i" class="ml-3">
                {{ item.met ? '✓' : '○' }} {{ item.label }}<span v-if="item.target != null"> {{ item.current ?? 0 }}/{{ item.target }}</span>
                <v-progress-linear v-if="item.target > 0" :model-value="progressPercent(item)" :color="item.met ? 'success' : 'warning'" rounded height="5" />
                <div v-for="(extra, j) in item.sub || []" :key="j" class="ml-2">{{ extra.label }} {{ extra.current }}/{{ extra.target }}</div>
              </div>
            </template>
            <template v-else>
              {{ progress.met ? '✓' : '○' }} {{ progress.label }}<span v-if="progress.target != null"> {{ progress.current ?? 0 }}/{{ progress.target }}</span>
              <v-progress-linear v-if="progress.target > 0" :model-value="progressPercent(progress)" :color="progress.met ? 'success' : 'warning'" rounded height="5" />
              <div v-for="(extra, i) in progress.sub || []" :key="i" class="ml-2">{{ extra.label }} {{ extra.current }}/{{ extra.target }}</div>
            </template>
          </div>
        </div>
        <div v-if="taskPacks.length > 3" class="text-caption text-medium-emphasis mt-2">待完成礼包还有 {{ taskPacks.length - 3 }} 个，请前往礼包中心查看</div>
      </v-card-text>

      <v-card-actions class="px-5 pb-4">
        <v-btn variant="text" color="grey" @click="dismiss">稍后再说</v-btn>
        <v-spacer />
        <v-btn color="pink" variant="elevated" @click="goClaim">{{ packs.length ? '前往领取' : '查看礼包' }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'GiftPackPromptDialog',
  emits: ['go-claim', 'dismiss'],
  data() {
    return {
      dialog: false,
      packs: [],
      taskPacks: []
    }
  },
  computed: {
    displayPacks() {
      return this.packs.slice(0, 3)
    },
    displayTaskPacks() {
      return this.taskPacks.slice(0, 3)
    },
    truncatedCount() {
      return Math.max(0, this.packs.length - 3)
    }
  },
  methods: {
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
    rewardLabel(reward) {
      if (reward.label) return reward.label
      if (reward.type === 'wheel_free_spins') return `${reward.count} 次大转盘免费机会（${reward.expiry_days} 天有效）`
      if (reward.type === 'tournament_wallet') return `${reward.amount} 争霸赛余额`
      if (reward.type === 'invite_codes') return `${reward.count} 枚${reward.privileged ? '特权' : ''}邀请码`
      return { line_schedule_unlock: '线路调度解锁', download_unlock: '下载权限解锁' }[reward.type] || reward.type
    },
    /**
     * 由外部在 prompt-check 返回非空时调用。
     * 提醒次数已在后端返回时记账，本弹窗只负责展示。
     */
    progressPercent(item) {
      return item.target > 0 ? Math.min(100, Math.max(0, Number(item.current || 0) / item.target * 100)) : 0
    },
    open(packs, taskPacks = []) {
      if (!packs?.length && !taskPacks?.length) return
      this.packs = packs || []
      this.taskPacks = taskPacks || []
      this.dialog = true
    },
    close() {
      this.dialog = false
    },
    dismiss() {
      this.close()
      this.$emit('dismiss')
    },
    goClaim() {
      this.close()
      this.$emit('go-claim')
    }
  }
}
</script>

<style scoped>
.gift-prompt {
  overflow: hidden;
}

 .gift-prompt__hero {
  background: linear-gradient(135deg, #ec407a 0%, #7e57c2 100%);
  color: #fff;
  text-align: center;
  padding: 24px 16px 20px;
}

.gift-prompt__item {
  padding: 10px 0;
}

.gift-prompt__item + .gift-prompt__item {
  border-top: 1px solid rgba(128, 128, 128, 0.18);
}

.gift-prompt__item-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
