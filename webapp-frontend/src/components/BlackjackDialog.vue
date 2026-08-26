<template>
  <v-dialog v-model="dialog" max-width="720" persistent>
    <v-card class="activity-dialog">
      <v-card-title class="blackjack-dialog__titlebar">
        <div class="blackjack-dialog__title">
          <v-icon class="mr-2" color="pink">mdi-cards-playing</v-icon>
          21 点
        </div>
        <div class="d-flex align-center">
          <!-- 规则说明入口：不离开牌桌即可查看 -->
          <v-btn
            class="mr-1"
            icon
            variant="text"
            size="small"
            title="规则说明"
            @click="showRules = true"
          >
            <v-icon>mdi-help-circle-outline</v-icon>
          </v-btn>
          <v-btn icon @click="close">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>
      </v-card-title>

      <v-divider />

      <v-card-text class="pa-6">
        <div v-if="loading" class="text-center py-8">
          <v-progress-circular indeterminate color="pink" size="50" />
          <div class="mt-3">加载中...</div>
        </div>

        <div v-else-if="loadError" class="text-center py-6">
          <v-alert type="error" variant="tonal">{{ loadError }}</v-alert>
          <v-btn class="mt-3" color="primary" @click="load">重试</v-btn>
        </div>

        <div v-else>
          <!-- 当前积分 -->
          <div class="d-flex justify-space-between align-center mb-3">
            <v-chip size="small" variant="outlined" color="primary">
              <v-icon size="small" class="mr-1">mdi-star</v-icon>
              当前积分：{{ currentCredits.toFixed(2) }}
            </v-chip>
            <v-chip v-if="stats" size="small" variant="outlined">
              累计 {{ stats.total_hands }} 手 · 净
              <span :class="stats.net_credits >= 0 ? 'text-success' : 'text-error'">
                {{ stats.net_credits >= 0 ? '+' : '' }}{{ stats.net_credits.toFixed(2) }}
              </span>
            </v-chip>
          </div>

          <!-- 幸运奖池：常驻展示，中奖时整条高亮 -->
          <div
            v-if="config.jackpot_enabled"
            class="jackpot-bar mb-4"
            :class="{ 'jackpot-bar--hit': jackpotHit }"
          >
            <div class="d-flex align-center">
              <v-icon size="small" color="amber-darken-3" class="mr-2">mdi-treasure-chest</v-icon>
              <span class="jackpot-bar__label">幸运奖池</span>
              <span class="jackpot-bar__value ml-2">{{ jackpotBalance.toFixed(2) }}</span>
            </div>
            <span class="jackpot-bar__hint">
              同花天胡派 {{ config.jackpot_suited_bj_pct }}% · 三张 7 派全额
            </span>
          </div>

          <!-- 牌桌：与锦标赛赛内共用同一组件，两侧差异全部由 props 承接 -->
          <BlackjackTable
            ref="table"
            :hand="hand"
            :balance="currentCredits"
            currency-label="积分"
            bet-mode="tiers"
            :bet-options="config.bet_options"
            :deal-disabled="!config.enabled || currentCredits < config.min_credits"
            :deal-disabled-hint="dealDisabledHint"
            :show-rake="true"
            :free-hands-remaining="freeHandsRemaining"
            :free-hands-per-day="config.free_hands_per_day"
            :show-strategy-hint="true"
            :show-jackpot="true"
            :acting="acting"
            :action-error="actionError"
            :hand-decisions="handDecisions"
            :accuracy-stats="stats"
            @deal="deal"
            @hit="act('hit')"
            @stand="act('stand')"
            @double="act('double')"
            @surrender="act('surrender')"
            @new-hand="startNewHand"
            @reveal-change="revealing = $event"
          />
        </div>
      </v-card-text>
    </v-card>

    <!-- 规则说明弹层：数字全部取自后端配置，不硬编码 -->
    <v-dialog v-model="showRules" max-width="560">
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon class="mr-2" color="pink">mdi-help-circle-outline</v-icon>
          21 点规则说明
        </v-card-title>
        <v-divider />
        <v-card-text class="pa-5">
          <div class="rules-section">
            <div class="rules-title">目标</div>
            <p>手中牌点数尽量接近 21 点但不超过，并高于庄家。超过 21 点即爆牌判负。</p>
          </div>

          <div class="rules-section">
            <div class="rules-title">点数</div>
            <p>2 至 10 计面值，J、Q、K 各计 10 点，A 计 11 点或 1 点（自动取不爆的最大点数）。</p>
          </div>

          <div class="rules-section">
            <div class="rules-title">可用动作</div>
            <p>
              <strong>要牌</strong>：再拿一张牌。<br />
              <strong>停牌</strong>：结束你的回合，由庄家补牌。<br />
              <strong>加倍</strong>：追加一份等额注额，只再发一张牌并自动停牌。
              仅在手中恰为最初两张牌时可用，要牌后即不可加倍，且需另有 {{ betRangeText }} 的可用积分。
              <template v-if="config.surrender_enabled">
                <br />
                <strong>投降</strong>：认输并<strong>返还一半基础注额</strong>，本手立即结束，
                不进庄家回合。<strong>仅在手中恰为最初两张牌时可用</strong>，要牌或加倍后即不可投降。
              </template>
            </p>
            <p class="text-caption text-medium-emphasis">
              不设分牌与保险<span v-if="!config.surrender_enabled">、投降</span>。
              <span v-if="config.surrender_enabled">
                投降是几个最差局面（如硬 16 对庄家 10）下唯一能主动减损的选择，
                返还比例固定为一半，不可调整。
              </span>
            </p>
          </div>

          <div class="rules-section">
            <div class="rules-title">庄家规则</div>
            <p>
              你停牌后，庄家先亮出暗牌，再按规则逐张补牌，过程在牌桌上可见。
              庄家点数达到 17 或以上即停牌<span v-if="!config.dealer_hits_soft_17">（含软 17，如 A+6）</span
              ><span v-else>（软 17 时继续要牌）</span>，不足 17 则继续要牌。庄家行为完全由规则决定。
            </p>
          </div>

          <div class="rules-section">
            <div class="rules-title">赔率</div>
            <p>
              <strong>天胡</strong>（最初两张即 21 点）：赔 {{ config.blackjack_payout }} 倍注额。<br />
              <strong>普通取胜</strong>：赔 1 倍注额。<br />
              <strong>加倍取胜</strong>：赔 2 倍注额。<br />
              <strong>平局</strong>：原额退回押注。
              <template v-if="config.surrender_enabled">
                <br />
                <strong>投降</strong>：退回一半基础注额（不计胜负）。
              </template>
            </p>
          </div>

          <div class="rules-section">
            <div class="rules-title">抽水</div>
            <p>
              <strong>仅对赢利部分计取 {{ config.rake_percent_on_profit }}%，输<span
                v-if="config.surrender_enabled">、投降</span>与平局不抽。</strong>
            </p>
            <p v-if="config.free_hands_per_day > 0">
              每个自然日的前 {{ config.free_hands_per_day }} 手<strong>完全免抽水</strong>，
              无需下注解锁，牌桌上会标示当前手牌是否免抽水。免抽水只影响抽水，
              赔率、注额校验与其余结算口径完全不变。
            </p>
          </div>

          <div v-if="config.jackpot_enabled" class="rules-section">
            <div class="rules-title">幸运奖池</div>
            <p>
              奖池由抽水的一部分供养，当前余额 {{ jackpotBalance.toFixed(2) }} 积分，牌桌顶部常驻显示。
              两种牌型触发派彩：<br />
              <strong>同花天胡</strong>（最初两张为同花色的 A 与 10/J/Q/K）：派奖池余额的
              {{ config.jackpot_suited_bj_pct }}%。<br />
              <strong>三张 7</strong>：派<strong>全部</strong>奖池余额。
            </p>
            <p class="text-caption text-medium-emphasis">
              奖池派彩独立于本手胜负，与赔付分开入账，也不计入榜单的单手最大赢利。
            </p>
          </div>

          <div class="rules-section">
            <div class="rules-title">决策反馈</div>
            <p>
              每次要牌、停牌、加倍<span v-if="config.surrender_enabled">、投降</span>都会与<strong>基本策略</strong>（21
              点公认的最优打法）对照，结算后逐次显示「你的决策 / 建议决策」，并统计准确率。
            </p>
            <p class="text-caption text-medium-emphasis">
              这只是事后建议，系统不会阻止或替代你的任何选择。准确率同时用于决策准确率排行榜。
            </p>
          </div>

          <div class="rules-section">
            <div class="rules-title">注额与门槛</div>
            <p>
              可选注额：{{ (config.bet_options || []).join(' / ') }}。<br />
              参与门槛：{{ config.min_credits }} 积分。<br />
              同一时刻只能有一手牌进行中；手牌超过 {{ config.hand_timeout_minutes }} 分钟未完成会自动停牌结算。
            </p>
          </div>
        </v-card-text>
        <v-divider />
        <v-card-actions>
          <v-spacer />
          <v-btn color="primary" variant="text" @click="showRules = false">知道了</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-dialog>
</template>

<script>
import BlackjackTable from './BlackjackTable.vue'
import {
  dealBlackjackHand,
  doubleBlackjackHand,
  getBlackjackConfig,
  getCurrentBlackjackHand,
  getUserBlackjackStats,
  hitBlackjackHand,
  standBlackjackHand,
  surrenderBlackjackHand
} from '../services/blackjackService'

export default {
  name: 'BlackjackDialog',
  components: { BlackjackTable },
  emits: ['credits-changed'],
  data() {
    return {
      dialog: false,
      loading: false,
      loadError: null,
      actionError: null,
      acting: null,
      showRules: false,
      hand: null,
      stats: null,
      currentCredits: 0,
      // 庄家回放是否进行中。由牌桌子组件通过 reveal-change 推上来，用于让奖池
      // 高亮与回放同步——不能在 computed 里读 $refs，那不是响应式的。
      revealing: false,
      // 幸运奖池余额：随每次操作的响应刷新，牌桌顶部常驻显示
      jackpotBalance: 0,
      // 今日剩余免抽水手数：进入活动时由 /current 给出，发牌后本地递减
      freeHandsRemaining: 0,
      // 本手的逐次决策评判，用于结算后逐条回放。刷新或换设备后会为空，
      // 届时只展示手牌上的累计计数，不伪造缺失的条目。
      handDecisions: [],
      config: {
        enabled: false,
        bet_options: [],
        min_credits: 30,
        blackjack_payout: 1.5,
        rake_percent_on_profit: 3,
        dealer_hits_soft_17: false,
        surrender_enabled: false,
        hand_timeout_minutes: 15,
        free_hands_per_day: 0,
        jackpot_enabled: false,
        jackpot_balance: 0,
        jackpot_suited_bj_pct: 10
      }
    }
  },
  computed: {
    dealDisabledHint() {
      if (!this.config.enabled) {
        return '21 点活动当前未开放'
      }
      if (this.currentCredits < this.config.min_credits) {
        const gap = (this.config.min_credits - this.currentCredits).toFixed(2)
        return `参与需至少 ${this.config.min_credits} 积分，还需 ${gap} 积分`
      }
      return ''
    },
    betRangeText() {
      const options = this.config.bet_options || []
      if (!options.length) {
        return '一份注额'
      }
      const min = Math.min(...options)
      const max = Math.max(...options)
      return min === max ? `${min} 积分` : `${min} ~ ${max} 积分`
    },
    jackpotHit() {
      // 中奖高亮与牌桌内的结算展示同步：回放未结束时不提前透露
      return !!(this.hand && this.hand.jackpot_won > 0 && !this.revealing)
    }
  },
  methods: {
    open() {
      this.dialog = true
      this.load()
    },

    close() {
      this.cancelReveal()
      this.dialog = false
      this.actionError = null
      this.$emit('credits-changed')
    },

    cancelReveal() {
      const table = this.$refs.table
      if (table) {
        table.cancelReveal()
      }
      // 子组件在 loading 期间是被卸载的，届时它无法再推 reveal-change 上来，
      // 故本地这份状态要自己收尾，否则奖池高亮会卡在回放中的样子
      this.revealing = false
    },

    async load() {
      this.loading = true
      this.loadError = null
      this.actionError = null
      this.cancelReveal()
      this.handDecisions = []
      try {
        const [configRes, currentRes, statsRes] = await Promise.all([
          getBlackjackConfig(),
          getCurrentBlackjackHand(),
          getUserBlackjackStats()
        ])

        this.config = configRes.data

        this.currentCredits = currentRes.data.current_credits
        // 有进行中手牌则直接恢复牌桌，而非展示下注界面
        this.hand = currentRes.data.hand || null
        this.jackpotBalance = currentRes.data.jackpot_balance || 0
        this.freeHandsRemaining = currentRes.data.free_hands_remaining || 0

        this.stats = statsRes.data
      } catch (err) {
        console.error('加载 21 点数据失败:', err)
        this.loadError = err.response?.data?.detail || '加载失败'
      } finally {
        this.loading = false
      }
    },

    async deal(bet) {
      this.acting = 'deal'
      this.actionError = null
      // 新的一手从零开始记录决策，不与上一手混在一起
      this.handDecisions = []
      try {
        const response = await dealBlackjackHand(bet)
        this.applyActionResult(response.data)
        // 每次发牌都占用当日一个手数名额，剩余免抽水手数随之减一
        this.freeHandsRemaining = Math.max(0, this.freeHandsRemaining - 1)
      } catch (err) {
        this.handleActionError(err)
      } finally {
        this.acting = null
      }
    },

    async act(action) {
      if (!this.hand) {
        return
      }
      const handlers = {
        hit: hitBlackjackHand,
        stand: standBlackjackHand,
        double: doubleBlackjackHand,
        surrender: surrenderBlackjackHand
      }
      this.acting = action
      this.actionError = null
      try {
        const response = await handlers[action](this.hand.id)
        this.applyActionResult(response.data)
      } catch (err) {
        this.handleActionError(err)
      } finally {
        this.acting = null
      }
    },

    applyActionResult(data) {
      this.hand = data.hand
      this.currentCredits = data.current_credits
      if (typeof data.jackpot_balance === 'number') {
        this.jackpotBalance = data.jackpot_balance
      }
      // 发牌无决策，故 decision 为 null；要牌/停牌/加倍各贡献一条
      if (data.decision) {
        this.handDecisions.push(data.decision)
      }
      this.$emit('credits-changed')
      if (data.settled) {
        this.refreshStats()
        // 本手已结束：回放庄家的补牌过程，而非直接甩出最终牌面。
        // 等牌面 props 落到子组件之后再启动，否则回放读到的还是上一手的牌。
        this.$nextTick(() => {
          const table = this.$refs.table
          if (table) {
            table.startReveal()
          }
        })
      } else {
        this.cancelReveal()
      }
    },

    startNewHand() {
      this.cancelReveal()
      this.handDecisions = []
      this.hand = null
    },

    async refreshStats() {
      try {
        const response = await getUserBlackjackStats()
        this.stats = response.data
      } catch (err) {
        console.error('刷新 21 点统计失败:', err)
      }
    },

    handleActionError(err) {
      console.error('21 点操作失败:', err)
      this.actionError = err.response?.data?.detail || '操作失败'
      // 前端状态可能已过期，重新拉取服务端的权威状态。
      //
      // 500 也必须重新同步：发牌的事务先提交、随后构造响应时才出错的话，押注
      // 已经扣掉、手牌已经开局，而前端仍停在下注界面显示旧余额——用户会以为
      // 积分凭空少了，再点一次发牌只会得到「你还有一手牌未结束」。
      const status = err.response?.status
      if (status === 400 || status === 404 || status >= 500 || !status) {
        this.syncHand()
      }
    },

    async syncHand() {
      try {
        const response = await getCurrentBlackjackHand()
        this.currentCredits = response.data.current_credits
        this.jackpotBalance = response.data.jackpot_balance || 0
        this.freeHandsRemaining = response.data.free_hands_remaining || 0
        this.cancelReveal()
        // 服务端才是权威：本地记录的决策未必属于这手牌，一并丢弃
        this.handDecisions = []
        this.hand = response.data.hand || null
      } catch (err) {
        console.error('同步手牌状态失败:', err)
      }
    }
  }
}
</script>

<style scoped>
.blackjack-dialog__titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.blackjack-dialog__title {
  display: flex;
  align-items: center;
}

/* 幸运奖池常驻条 */
.jackpot-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 143, 0, 0.35);
  background: linear-gradient(90deg, rgba(255, 193, 7, 0.12), rgba(255, 143, 0, 0.06));
  transition: box-shadow 0.3s ease;
}

.jackpot-bar__label {
  font-size: 0.8rem;
  font-weight: 600;
}

.jackpot-bar__value {
  font-size: 1.05rem;
  font-weight: 700;
  color: #ef6c00;
}

.jackpot-bar__hint {
  font-size: 0.72rem;
  opacity: 0.7;
}

/* 中奖时整条高亮，与常态明显区分 */
.jackpot-bar--hit {
  border-color: rgba(255, 143, 0, 0.9);
  box-shadow: 0 0 0 2px rgba(255, 143, 0, 0.25);
  animation: jackpot-pulse 1.1s ease-in-out 3;
}

@keyframes jackpot-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 2px rgba(255, 143, 0, 0.25);
  }
  50% {
    box-shadow: 0 0 0 7px rgba(255, 143, 0, 0.05);
  }
}

.rules-section {
  margin-bottom: 16px;
}

.rules-section:last-child {
  margin-bottom: 0;
}

.rules-title {
  font-weight: 700;
  font-size: 0.9rem;
  margin-bottom: 4px;
}

.rules-section p {
  font-size: 0.875rem;
  line-height: 1.6;
  margin-bottom: 4px;
}
</style>
