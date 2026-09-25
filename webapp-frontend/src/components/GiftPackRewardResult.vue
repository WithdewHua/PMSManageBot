<template>
  <div class="d-flex align-start mb-2">
    <v-icon class="mr-2 mt-1" size="small" :color="item.skipped ? 'grey' : 'success'">
      {{ item.skipped ? 'mdi-minus-circle-outline' : 'mdi-check-circle' }}
    </v-icon>
    <div class="gift-reward-result__content text-body-2">
      <div>{{ summary }}</div>
      <div v-if="item.new_expiry" class="text-caption text-medium-emphasis">
        新到期时间：{{ formatTime(item.new_expiry) }}
      </div>
      <div v-if="item.type === 'wheel_free_spins' && item.expires_at" class="text-caption text-medium-emphasis">
        到期时间：{{ formatTime(Number(item.expires_at) * 1000) }}
      </div>
      <template v-if="item.type === 'invite_codes'">
        <div v-for="code in item.codes || []" :key="code" class="d-flex align-center ga-1 mt-1">
          <span class="gift-reward-result__code">{{ code }}</span>
          <v-btn size="x-small" variant="text" color="primary" :aria-label="`复制邀请码 ${code}`" @click="copyCode(code)">
            复制
          </v-btn>
        </div>
        <div class="text-caption text-medium-emphasis mt-1">可在「我的邀请码」再次查看</div>
      </template>
    </div>
  </div>
</template>

<script>
export default {
  name: 'GiftPackRewardResult',
  props: {
    item: { type: Object, required: true }
  },
  emits: ['notify'],
  computed: {
    summary() {
      const item = this.item
      const service = (item.service || '').toUpperCase()
      if (item.type === 'premium_days') {
        if (item.skipped === 'lifetime') return `${service}：永久会员，${item.days} 天 Premium 未生效`
        return `${service}：Premium 延长 ${item.days} 天`
      }
      if (item.type === 'credits') return `获得 ${item.amount} 积分`
      if (item.type === 'wheel_free_spins') return `获得 ${item.count} 次大转盘免费机会`
      if (item.type === 'tournament_wallet') {
        return `获得 ${item.amount} 争霸赛余额，到账后余额 ${item.balance_after}`
      }
      if (item.type === 'invite_codes') return `获得 ${item.count} 枚${item.privileged ? '特权' : ''}邀请码`
      if (item.type === 'line_schedule_unlock' || item.type === 'download_unlock') {
        return item.message || `${service}：${item.skipped ? '已解锁，本次未变更' : '已永久解锁'}`
      }
      return item.message || item.label || ''
    }
  },
  methods: {
    formatTime(value) {
      const date = new Date(value)
      return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString()
    },
    async copyCode(code) {
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(code)
        } else {
          const input = document.createElement('textarea')
          input.value = code
          input.style.position = 'fixed'
          input.style.opacity = '0'
          document.body.appendChild(input)
          try {
            input.select()
            if (!document.execCommand('copy')) throw new Error('复制失败')
          } finally {
            document.body.removeChild(input)
          }
        }
        this.$emit('notify', '邀请码已复制', 'success')
      } catch (error) {
        this.$emit('notify', '复制失败，请手动选择邀请码', 'error')
      }
    }
  }
}
</script>

<style scoped>
.gift-reward-result__content {
  min-width: 0;
}

.gift-reward-result__code {
  font-family: monospace;
  overflow-wrap: anywhere;
}
</style>
