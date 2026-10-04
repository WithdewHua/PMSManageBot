<template>
  <v-card class="my-4" rounded="xl" variant="outlined">
    <v-card-title class="d-flex align-center flex-wrap">
      邀请码周限额
      <v-spacer />
      <v-btn variant="text" :loading="loading" :disabled="saving" @click="load">刷新</v-btn>
    </v-card-title>
    <v-card-text>
      <p class="text-caption mb-4">北京时间每周一 00:00 划周；免费、付费和十连抽共用额度。0 表示禁止发码，不是无限制。</p>
      <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
      <v-alert v-if="notice" type="success" variant="tonal" class="mb-4">{{ notice }}</v-alert>
      <v-alert v-if="stats && !stats.initialized" type="warning" variant="tonal" class="mb-4">
        尚未完成本周所需的历史初始化。请在维护窗口核对历史并运行初始化脚本，不要按零用量开放抽奖。
      </v-alert>
      <v-row>
        <v-col cols="12" sm="6">
          <v-text-field v-model.number="limits.global_weekly_limit" label="全服每周上限" type="number" min="0" max="2147483647" step="1"
            :rules="limitRules" :disabled="!loaded || loading || saving" />
        </v-col>
        <v-col cols="12" sm="6">
          <v-text-field v-model.number="limits.personal_weekly_limit" label="个人每周上限" type="number" min="0" max="2147483647" step="1"
            :rules="limitRules" :disabled="!loaded || loading || saving" />
        </v-col>
      </v-row>
      <v-btn color="primary" :loading="saving" :disabled="!canSave" @click="save">保存限额</v-btn>
      <p class="text-caption mt-2">修改不清零已用量，调低上限不会撤销已发出的码。</p>
      <template v-if="stats">
        <v-divider class="my-4" />
        <div class="text-caption mb-2">{{ formatTime(stats.week_start_ms) }} 至 {{ formatTime(stats.week_end_ms) }}</div>
        <div class="text-body-1 mb-2">本周已发 {{ stats.global_used }} / {{ stats.global_limit }} 枚</div>
        <div>历史初始化 {{ stats.historical_issued }} 枚，上线后新增 {{ stats.new_issued }} 枚</div>
        <div class="mt-2">全服触顶 {{ stats.global_blocked_count }} 次，个人触顶 {{ stats.personal_blocked_count }} 次，同时触顶 {{ stats.both_blocked_count }} 次</div>
        <div class="text-caption">全服与个人命中可重叠，不应将三项直接相加。</div>
        <div class="text-caption mt-2">可证实的首次耗尽时间：{{ formatTime(stats.first_exhausted_at_ms) }}</div>
        <v-expansion-panels class="mt-3" variant="accordion">
          <v-expansion-panel title="获码用户与来源">
            <v-expansion-panel-text>
              <v-table density="compact">
                <thead><tr><th>Telegram ID</th><th>本周已发</th></tr></thead>
                <tbody><tr v-for="user in stats.users" :key="user.tg_id"><td>{{ user.tg_id }}</td><td>{{ user.issued }}</td></tr></tbody>
              </v-table>
              <div v-for="source in stats.sources" :key="source.source || 'legacy-unknown'" class="text-caption mt-2">
                {{ source.source || '未知（历史）' }}：{{ source.issued }} 枚
              </div>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
      </template>
    </v-card-text>
  </v-card>
</template>

<script>
import { getLuckyWheelInviteQuotas, updateLuckyWheelInviteQuotas, getLuckyWheelInviteQuotaStats } from '../services/wheelService'

export default {
  name: 'WheelInviteQuotaPanel',
  data() {
    return {
      // Values arrive only from the authenticated administrator endpoint.
      limits: { global_weekly_limit: null, personal_weekly_limit: null },
      stats: null,
      loaded: false,
      loading: false,
      saving: false,
      error: '',
      notice: '',
      limitRules: [value => (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= 2147483647) || '请输入 0 至 2147483647 的整数'],
    }
  },
  computed: {
    canSave() {
      return this.loaded && !this.loading && !this.saving &&
        this.validLimit(this.limits.global_weekly_limit) && this.validLimit(this.limits.personal_weekly_limit)
    },
  },
  mounted() {
    this.load()
  },
  methods: {
    validLimit(value) {
      return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= 2147483647
    },
    formatTime(value) {
      if (value === null || value === undefined) return '未知'
      return new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hour12: false,
      }).format(new Date(value))
    },
    errorText(error) {
      const detail = error.response?.data?.detail
      return typeof detail === 'string' ? detail : '请求失败，请稍后重试'
    },
    validateLimits(limits) {
      if (!limits || !this.validLimit(limits.global_weekly_limit) || !this.validLimit(limits.personal_weekly_limit)) {
        throw new Error('Invalid quota response')
      }
      return { global_weekly_limit: limits.global_weekly_limit, personal_weekly_limit: limits.personal_weekly_limit }
    },
    validateStats(stats) {
      if (!stats || typeof stats.initialized !== 'boolean' || !this.validLimit(stats.global_used) ||
          !Array.isArray(stats.users) || !Array.isArray(stats.sources)) {
        throw new Error('Invalid quota statistics response')
      }
      return stats
    },
    async load() {
      if (this.loading || this.saving) return
      this.loading = true
      this.error = ''
      this.notice = ''
      try {
        const [configResponse, statsResponse] = await Promise.all([
          getLuckyWheelInviteQuotas(), getLuckyWheelInviteQuotaStats(),
        ])
        const limits = this.validateLimits(configResponse.data)
        const stats = this.validateStats(statsResponse.data)
        this.limits = limits
        this.stats = stats
        this.loaded = true
      } catch (error) {
        this.error = this.errorText(error) + (this.loaded ? '；当前保留上次加载的数据，可能不是最新状态。' : '')
      } finally {
        this.loading = false
      }
    },
    async save() {
      if (!this.canSave) return
      this.saving = true
      this.error = ''
      this.notice = ''
      try {
        const response = await updateLuckyWheelInviteQuotas(this.validateLimits(this.limits))
        this.limits = this.validateLimits(response.data)
        this.notice = '限额已保存，已用数量不会清零。'
        try {
          this.stats = this.validateStats((await getLuckyWheelInviteQuotaStats()).data)
        } catch (error) {
          this.error = '限额已保存，但统计刷新失败；当前统计可能不是最新状态。' + this.errorText(error)
        }
      } catch (error) {
        this.error = '保存失败：' + this.errorText(error)
      } finally {
        this.saving = false
      }
    },
  },
}
</script>
