<template>
  <v-card class="quota-card my-4" elevation="8" rounded="xl">
    <v-card-title class="d-flex align-center flex-wrap pa-4 pa-sm-6 quota-card-header">
      <v-avatar size="36" class="mr-3" color="rgba(255,255,255,0.2)" variant="flat">
        <v-icon size="20" color="white">mdi-ticket-confirmation</v-icon>
      </v-avatar>
      <span class="text-body-1 text-sm-h6 font-weight-bold">邀请码周限额</span>
      <v-spacer class="d-none d-sm-flex" />
      <v-btn
        color="white"
        variant="outlined"
        size="small"
        prepend-icon="mdi-refresh"
        :loading="loading"
        :disabled="saving"
        class="quota-btn mt-2 mt-sm-0"
        @click="load"
      >
        刷新数据
      </v-btn>
    </v-card-title>
    <v-card-text class="pa-4 pa-sm-6">
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
        <div class="text-caption quota-period">{{ formatTime(stats.week_start_ms) }} 至 {{ formatTime(stats.week_end_ms) }}</div>
        <v-row class="mt-1">
          <v-col cols="12" sm="4">
            <div class="quota-stat">
              <div class="quota-stat-label">本周已发</div>
              <div class="quota-stat-value">{{ stats.global_used }} <span>/ {{ stats.global_limit }} 枚</span></div>
            </div>
          </v-col>
          <v-col cols="12" sm="4">
            <div class="quota-stat">
              <div class="quota-stat-label">历史初始化</div>
              <div class="quota-stat-value">{{ stats.historical_issued }} <span>枚</span></div>
            </div>
          </v-col>
          <v-col cols="12" sm="4">
            <div class="quota-stat">
              <div class="quota-stat-label">上线后新增</div>
              <div class="quota-stat-value">{{ stats.new_issued }} <span>枚</span></div>
            </div>
          </v-col>
        </v-row>
        <div class="quota-summary mt-2">
          全服触顶 {{ stats.global_blocked_count }} 次，个人触顶 {{ stats.personal_blocked_count }} 次，同时触顶 {{ stats.both_blocked_count }} 次
        </div>
        <div class="text-caption">全服与个人命中可重叠，不应将三项直接相加。</div>
        <div class="text-caption mt-2">可证实的首次耗尽时间：{{ formatTime(stats.first_exhausted_at_ms) }}</div>
        <v-expansion-panels class="mt-3" variant="accordion">
          <v-expansion-panel title="获码用户与来源">
            <v-expansion-panel-text>
              <v-table density="comfortable" class="quota-table">
                <thead><tr><th>Telegram 用户名</th><th class="text-right">本周已发</th></tr></thead>
                <tbody>
                  <tr v-for="(user, index) in stats.users" :key="`${user.username || 'unknown'}-${index}`">
                    <td class="font-weight-medium">{{ formatUsername(user.username) }}</td>
                    <td class="text-right">{{ user.issued }} 枚</td>
                  </tr>
                </tbody>
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
    formatUsername(username) {
      if (!username) return '未设置用户名'
      return username.startsWith('@') ? username : `@${username}`
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

<style scoped>
.quota-card {
  border: 1px solid rgba(0, 0, 0, 0.08);
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
}

.quota-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12) !important;
}

.quota-card-header {
  background: linear-gradient(135deg, #00897b 0%, #43a047 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
}

.quota-card .v-card-text {
  background: rgba(255, 255, 255, 0.96);
}

.quota-btn {
  border-width: 2px;
  font-weight: 600;
}

.quota-period {
  color: rgba(0, 0, 0, 0.58);
}

.quota-stat {
  height: 100%;
  padding: 12px;
  text-align: center;
  border-radius: 12px;
  background: rgba(0, 150, 136, 0.06);
  border: 1px solid rgba(0, 150, 136, 0.12);
}

.quota-stat-label {
  margin-bottom: 4px;
  color: rgba(0, 0, 0, 0.58);
  font-size: 0.75rem;
  font-weight: 500;
}

.quota-stat-value {
  color: #00796b;
  font-size: 1.2rem;
  font-weight: 700;
}

.quota-stat-value span {
  color: rgba(0, 0, 0, 0.55);
  font-size: 0.8rem;
  font-weight: 500;
}

.quota-summary {
  font-weight: 600;
}

.quota-table :deep(th) {
  color: rgba(0, 0, 0, 0.6);
  font-size: 0.75rem;
  font-weight: 600;
}

.quota-table :deep(td) {
  color: rgba(0, 0, 0, 0.78);
}
</style>
