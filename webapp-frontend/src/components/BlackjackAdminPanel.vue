<template>
  <div class="pa-4">
    <div v-if="loading" class="text-center py-8">
      <v-progress-circular indeterminate color="pink" size="50" />
      <div class="mt-3">加载配置中...</div>
    </div>

    <div v-else-if="loadError" class="text-center py-6">
      <v-alert type="error" variant="tonal">{{ loadError }}</v-alert>
      <v-btn class="mt-3" color="primary" @click="load">重试</v-btn>
    </div>

    <div v-else>
      <!-- 服务端停用开关 -->
      <v-card variant="outlined" rounded="lg" class="mb-4">
        <v-card-title class="text-subtitle-1">
          <v-icon class="mr-2" :color="form.enabled ? 'success' : 'grey'">
            {{ form.enabled ? 'mdi-play-circle' : 'mdi-pause-circle' }}
          </v-icon>
          活动开关
        </v-card-title>
        <v-card-text>
          <v-switch
            v-model="form.enabled"
            :label="form.enabled ? '已开放：接受新的发牌' : '已停用：拒绝新的发牌'"
            color="success"
            hide-details
            density="compact"
          />
          <div class="text-caption text-medium-emphasis mt-2">
            停用只拦截新发牌，已在进行中的手牌仍可正常操作与结算，不会作废或没收押注。
          </div>
        </v-card-text>
      </v-card>

      <!-- 注额与门槛 -->
      <v-card variant="outlined" rounded="lg" class="mb-4">
        <v-card-title class="text-subtitle-1">
          <v-icon class="mr-2" color="pink">mdi-cash-multiple</v-icon>
          注额与门槛
        </v-card-title>
        <v-card-text>
          <div class="text-subtitle-2 mb-2">注额档位</div>
          <div class="d-flex flex-wrap align-center mb-2">
            <v-chip
              v-for="(bet, i) in form.bet_options"
              :key="`${bet}-${i}`"
              class="mr-2 mb-2"
              closable
              color="pink"
              variant="outlined"
              @click:close="removeBetOption(i)"
            >
              {{ bet }}
            </v-chip>
          </div>
          <div class="d-flex align-center mb-4" style="max-width: 320px;">
            <v-text-field
              v-model.number="newBetOption"
              label="新增档位"
              type="number"
              density="compact"
              variant="outlined"
              hide-details
              min="1"
              @keyup.enter="addBetOption"
            />
            <v-btn class="ml-2" color="pink" variant="outlined" @click="addBetOption">添加</v-btn>
          </div>

          <v-text-field
            v-model.number="form.min_credits"
            label="参与门槛（积分）"
            type="number"
            density="compact"
            variant="outlined"
            min="1"
            hint="积分低于该值无法发牌"
            persistent-hint
            style="max-width: 320px;"
          />
        </v-card-text>
      </v-card>

      <!-- 抽水 -->
      <v-card variant="outlined" rounded="lg" class="mb-4">
        <v-card-title class="text-subtitle-1">
          <v-icon class="mr-2" color="amber-darken-2">mdi-water-percent</v-icon>
          抽水
        </v-card-title>
        <v-card-text>
          <v-row dense>
            <v-col cols="12" md="4">
              <v-text-field
                v-model.number="form.rake_bp_on_profit"
                label="抽水比率（基点）"
                type="number"
                density="compact"
                variant="outlined"
                min="0"
                max="10000"
                :hint="`= ${(form.rake_bp_on_profit / 100).toFixed(2)}%，仅对净赢利计取`"
                persistent-hint
              />
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field
                v-model.number="form.rake_burn_bp"
                label="销毁部分（基点）"
                type="number"
                density="compact"
                variant="outlined"
                min="0"
                max="10000"
                :hint="burnShareHint"
                persistent-hint
              />
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field
                v-model.number="form.rake_jackpot_bp"
                label="注入幸运奖池（基点）"
                type="number"
                density="compact"
                variant="outlined"
                min="0"
                max="10000"
                :hint="jackpotShareHint"
                persistent-hint
              />
            </v-col>
          </v-row>

          <v-alert
            v-if="!rakeSplitValid"
            type="error"
            variant="tonal"
            density="compact"
            class="mt-4"
          >
            销毁 + 幸运奖池（{{ form.rake_burn_bp + form.rake_jackpot_bp }}）必须等于抽水比率（{{
              form.rake_bp_on_profit
            }}）
          </v-alert>
          <v-alert v-else type="info" variant="tonal" density="compact" class="mt-4">
            幸运奖池是 21 点专属的独立奖池，与大预言家的荣耀奖池互不影响。
          </v-alert>

          <v-text-field
            v-model.number="form.free_hands_per_day"
            class="mt-4"
            label="每日免抽水手数"
            type="number"
            density="compact"
            variant="outlined"
            min="0"
            hint="每个自然日的前 N 手不计取抽水；填 0 关闭"
            persistent-hint
            style="max-width: 320px;"
          />
        </v-card-text>
      </v-card>

      <!-- 幸运奖池 -->
      <v-card variant="outlined" rounded="lg" class="mb-4">
        <v-card-title class="text-subtitle-1">
          <v-icon class="mr-2" color="amber-darken-3">mdi-treasure-chest</v-icon>
          幸运奖池
        </v-card-title>
        <v-card-text>
          <v-switch
            v-model="form.jackpot_enabled"
            :label="form.jackpot_enabled ? '已启用：抽水注入奖池，触发牌型可中奖' : '已停用：抽水全额销毁，不派奖池'"
            color="amber-darken-3"
            hide-details
            density="compact"
            class="mb-4"
          />

          <v-text-field
            v-model.number="form.jackpot_suited_bj_pct"
            label="同花天胡派彩比例（%）"
            type="number"
            step="1"
            density="compact"
            variant="outlined"
            min="0"
            max="100"
            hint="三张 7 固定派发全额，不可配置"
            persistent-hint
            style="max-width: 320px;"
          />

          <v-switch
            v-model="form.jackpot_notify_enabled"
            label="中奖时向群组播报"
            color="amber-darken-3"
            hide-details
            density="compact"
            class="mt-4"
          />
          <div class="text-caption text-medium-emphasis">
            需已配置 <code>TG_GROUP_ID</code>。同花天胡约每 83 手一次、三张 7 约每 5500 手一次，
            播报频率随社区活跃度增长；若觉得刷屏可在此关闭。
          </div>

          <v-divider class="my-4" />

          <div class="d-flex align-center flex-wrap mb-2">
            <span class="text-subtitle-2 mr-2">当前余额</span>
            <span class="text-h6 text-amber-darken-3">{{ jackpotBalance.toFixed(2) }}</span>
            <v-btn
              class="ml-2"
              icon
              size="x-small"
              variant="text"
              title="刷新余额"
              :loading="refreshingBalance"
              @click="refreshJackpotBalance"
            >
              <v-icon size="small">mdi-refresh</v-icon>
            </v-btn>
          </div>
          <div class="text-caption text-medium-emphasis mb-3">
            奖池平时只由抽水供养。注入种子是<strong>唯一会增发积分</strong>的路径，
            用途是上线冷启动时让奖池有个初值，否则前期余额几乎为零、毫无观感。
          </div>
          <div class="d-flex align-center" style="max-width: 320px;">
            <v-text-field
              v-model.number="seedAmount"
              label="注入金额（积分）"
              type="number"
              step="1"
              density="compact"
              variant="outlined"
              hide-details
              min="0"
              @keyup.enter="seedJackpot"
            />
            <v-btn
              class="ml-2"
              color="amber-darken-3"
              variant="outlined"
              :loading="seeding"
              @click="seedJackpot"
            >
              注入
            </v-btn>
          </div>
        </v-card-text>
      </v-card>

      <!-- 玩法规则 -->
      <v-card variant="outlined" rounded="lg" class="mb-4">
        <v-card-title class="text-subtitle-1">
          <v-icon class="mr-2" color="indigo">mdi-cards-playing-outline</v-icon>
          玩法规则
        </v-card-title>
        <v-card-text>
          <v-switch
            v-model="form.dealer_hits_soft_17"
            label="庄家软 17 继续要牌（关闭则软 17 停牌，对玩家更有利）"
            color="indigo"
            hide-details
            density="compact"
            class="mb-4"
          />
          <v-switch
            v-model="form.surrender_enabled"
            label="开放投降（初始两张牌时可认输，返还一半注额）"
            color="indigo"
            hint="关闭后仅影响此后发出的手牌，进行中的手牌仍可投降。返还比例固定为一半，不可配置"
            persistent-hint
            density="compact"
            class="mb-4"
          />
          <v-row dense>
            <v-col cols="12" md="4">
              <v-text-field
                v-model.number="form.blackjack_payout"
                label="天胡赔率"
                type="number"
                step="0.1"
                density="compact"
                variant="outlined"
                min="0.1"
                hint="1.5 即 3:2"
                persistent-hint
              />
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field
                v-model.number="form.hand_timeout_minutes"
                label="手牌超时（分钟）"
                type="number"
                density="compact"
                variant="outlined"
                min="1"
                hint="超时按停牌自动结算"
                persistent-hint
              />
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field
                v-model.number="form.min_deal_interval_seconds"
                label="发牌最小间隔（秒）"
                type="number"
                step="0.5"
                density="compact"
                variant="outlined"
                min="0"
                hint="压制脚本刷牌，不限制正常玩家"
                persistent-hint
              />
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>

      <!-- 榜单与勋章 -->
      <v-card variant="outlined" rounded="lg" class="mb-4">
        <v-card-title class="text-subtitle-1">
          <v-icon class="mr-2" color="deep-purple">mdi-trophy-variant</v-icon>
          榜单与勋章
        </v-card-title>
        <v-card-text>
          <v-row dense>
            <v-col cols="12" md="4">
              <v-text-field
                v-model.number="form.rank_min_hands"
                label="入榜最低手数"
                type="number"
                density="compact"
                variant="outlined"
                min="1"
                hint="仅约束准确率榜与胜率榜；单手最大赢利榜不设门槛"
                persistent-hint
              />
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field
                v-model.number="form.badge_min_hands"
                label="游戏王勋章：手数阈值"
                type="number"
                density="compact"
                variant="outlined"
                min="1"
                hint="与准确率阈值同时满足才授予"
                persistent-hint
              />
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field
                v-model.number="form.badge_min_accuracy"
                label="游戏王勋章：准确率阈值（%）"
                type="number"
                step="1"
                density="compact"
                variant="outlined"
                min="0"
                max="100"
                hint="决策准确率不低于该值"
                persistent-hint
              />
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>

      <v-alert type="info" variant="tonal" density="compact" class="mb-4">
        配置变更只对此后的新手牌生效；进行中与已结算的手牌按其发牌时快照的参数结算。
      </v-alert>

      <div class="d-flex">
        <v-btn
          color="pink"
          size="large"
          :loading="saving"
          :disabled="!rakeSplitValid || !form.bet_options.length"
          @click="save"
        >
          <v-icon class="mr-1">mdi-content-save</v-icon>
          保存配置
        </v-btn>
        <v-btn class="ml-2" variant="outlined" size="large" :disabled="saving" @click="load">
          放弃修改
        </v-btn>
      </div>
    </div>
  </div>
</template>

<script>
import {
  getBlackjackAdminConfig,
  getBlackjackConfig,
  seedBlackjackJackpot,
  updateBlackjackConfig
} from '../services/blackjackService'

export default {
  name: 'BlackjackAdminPanel',
  emits: ['show-message'],
  data() {
    return {
      loading: false,
      loadError: null,
      saving: false,
      newBetOption: null,
      // 奖池余额不在管理配置里（它是运行时状态不是配置），取自公开配置接口
      jackpotBalance: 0,
      refreshingBalance: false,
      seedAmount: null,
      seeding: false,
      form: {
        enabled: false,
        bet_options: [],
        min_credits: 30,
        rake_bp_on_profit: 300,
        rake_burn_bp: 180,
        rake_jackpot_bp: 120,
        dealer_hits_soft_17: false,
        surrender_enabled: true,
        blackjack_payout: 1.5,
        hand_timeout_minutes: 15,
        min_deal_interval_seconds: 1,
        jackpot_enabled: true,
        jackpot_suited_bj_pct: 10,
        jackpot_notify_enabled: true,
        free_hands_per_day: 1,
        rank_min_hands: 100,
        badge_min_hands: 2000,
        badge_min_accuracy: 80
      }
    }
  },
  computed: {
    rakeSplitValid() {
      return (
        Number(this.form.rake_burn_bp) + Number(this.form.rake_jackpot_bp) ===
        Number(this.form.rake_bp_on_profit)
      )
    },
    burnShareHint() {
      const total = Number(this.form.rake_bp_on_profit)
      if (!total) {
        return '占抽水的比例'
      }
      return `占抽水的 ${((this.form.rake_burn_bp / total) * 100).toFixed(0)}%`
    },
    jackpotShareHint() {
      const total = Number(this.form.rake_bp_on_profit)
      if (!total) {
        return '占抽水的比例'
      }
      return `占抽水的 ${((this.form.rake_jackpot_bp / total) * 100).toFixed(0)}%`
    }
  },
  mounted() {
    this.load()
  },
  methods: {
    async load() {
      this.loading = true
      this.loadError = null
      try {
        const [adminRes, publicRes] = await Promise.all([
          getBlackjackAdminConfig(),
          getBlackjackConfig()
        ])
        this.form = { ...this.form, ...adminRes.data }
        this.jackpotBalance = publicRes.data.jackpot_balance || 0
      } catch (err) {
        console.error('加载 21 点配置失败:', err)
        this.loadError = err.response?.data?.detail || '加载配置失败'
      } finally {
        this.loading = false
      }
    },

    async refreshJackpotBalance() {
      this.refreshingBalance = true
      try {
        const response = await getBlackjackConfig()
        this.jackpotBalance = response.data.jackpot_balance || 0
      } catch (err) {
        console.error('刷新奖池余额失败:', err)
        this.$emit('show-message', '刷新奖池余额失败', 'error')
      } finally {
        this.refreshingBalance = false
      }
    },

    async seedJackpot() {
      const amount = Number(this.seedAmount)
      if (!amount || amount <= 0) {
        this.$emit('show-message', '注入金额必须为正数', 'warning')
        return
      }
      this.seeding = true
      try {
        const response = await seedBlackjackJackpot(amount)
        this.jackpotBalance = response.data.jackpot_balance || 0
        this.seedAmount = null
        this.$emit('show-message', response.data.message || '已注入奖池', 'success')
      } catch (err) {
        console.error('注入奖池种子失败:', err)
        this.$emit('show-message', err.response?.data?.detail || '注入奖池失败', 'error')
      } finally {
        this.seeding = false
      }
    },

    addBetOption() {
      const value = Number(this.newBetOption)
      if (!value || value <= 0 || !Number.isInteger(value)) {
        this.$emit('show-message', '注额档位必须为正整数', 'warning')
        return
      }
      if (this.form.bet_options.includes(value)) {
        this.$emit('show-message', '该档位已存在', 'warning')
        return
      }
      this.form.bet_options = [...this.form.bet_options, value].sort((a, b) => a - b)
      this.newBetOption = null
    },

    removeBetOption(index) {
      if (this.form.bet_options.length <= 1) {
        this.$emit('show-message', '至少需要保留一个注额档位', 'warning')
        return
      }
      this.form.bet_options = this.form.bet_options.filter((_, i) => i !== index)
    },

    async save() {
      this.saving = true
      try {
        const response = await updateBlackjackConfig(this.form)
        this.form = { ...this.form, ...response.data }
        this.$emit('show-message', '21 点配置已保存', 'success')
      } catch (err) {
        console.error('保存 21 点配置失败:', err)
        this.$emit('show-message', err.response?.data?.detail || '保存配置失败', 'error')
      } finally {
        this.saving = false
      }
    }
  }
}
</script>
