<template>
  <div>
    <v-alert v-if="actionError" type="error" variant="tonal" density="compact" class="mb-4">
      {{ actionError }}
    </v-alert>

    <!-- 下注界面：无进行中手牌时 -->
    <div v-if="!hand">
      <v-alert
        v-if="dealDisabledHint"
        type="warning"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ dealDisabledHint }}
      </v-alert>

      <div class="d-flex align-center mb-2">
        <span class="text-subtitle-2">选择注额</span>
        <!-- 免抽水标示：仅现金局有抽水，赛内根本不产生抽水故整块隐藏 -->
        <template v-if="showRake">
          <v-chip
            v-if="freeHandsRemaining > 0"
            size="x-small"
            color="teal"
            variant="flat"
            class="ml-2"
          >
            <v-icon start size="x-small">mdi-water-off</v-icon>
            本手免抽水{{ freeHandsRemaining > 1 ? `（今日还剩 ${freeHandsRemaining} 手）` : '' }}
          </v-chip>
          <span v-else-if="freeHandsPerDay > 0" class="text-caption text-medium-emphasis ml-2">
            今日免抽水手数已用完
          </span>
        </template>
      </div>

      <!-- 档位模式：现金局的固定注额 -->
      <div v-if="betMode === 'tiers'" class="bet-options mb-4">
        <v-btn
          v-for="bet in betOptions"
          :key="bet"
          :variant="selectedBet === bet ? 'elevated' : 'outlined'"
          :color="selectedBet === bet ? 'pink' : undefined"
          :disabled="bet > balance"
          class="mr-2 mb-2"
          @click="selectedBet = bet"
        >
          {{ bet }}
        </v-btn>
      </div>

      <!-- 区间模式：锦标赛的自由下注。下注额本身即为锦标赛的主要技巧，
           固定档位会让这项技巧无从施展 -->
      <div v-else class="mb-4">
        <div class="d-flex align-center justify-space-between mb-1">
          <span class="text-h6 font-weight-bold">{{ selectedBet }}</span>
          <span class="text-caption text-medium-emphasis">
            可下注 {{ betMin }} ~ {{ effectiveBetMax }}（{{ betStep }} 的整数倍）
          </span>
        </div>
        <v-slider
          v-model="selectedBet"
          :min="betMin"
          :max="effectiveBetMax"
          :step="betStep"
          :disabled="effectiveBetMax < betMin"
          color="pink"
          thumb-label
          hide-details
          class="mb-2"
        />
        <div class="bet-options">
          <v-btn
            v-for="quick in quickBets"
            :key="quick.label"
            size="small"
            variant="outlined"
            class="mr-2 mb-2"
            :disabled="quick.value < betMin"
            @click="selectedBet = quick.value"
          >
            {{ quick.label }}
          </v-btn>
        </div>
      </div>

      <v-btn
        block
        color="pink"
        size="large"
        :loading="acting === 'deal'"
        :disabled="!canDeal"
        @click="$emit('deal', selectedBet)"
      >
        <v-icon class="mr-1">mdi-cards-playing-outline</v-icon>
        发牌（注 {{ selectedBet }}）
      </v-btn>
    </div>

    <!-- 牌桌：有手牌时 -->
    <div v-else class="blackjack-table">
      <!-- 庄家 -->
      <div class="mb-5">
        <div class="d-flex align-center mb-2">
          <span class="text-subtitle-2 mr-2">庄家</span>
          <v-chip
            v-if="displayedDealerTotal !== null"
            size="x-small"
            variant="flat"
            :color="dealerTotalColor"
          >
            {{ displayedDealerTotal }} 点
          </v-chip>
          <!-- 补牌过程中的状态提示，让玩家看清庄家在做什么 -->
          <span v-if="dealerStatusText" class="text-caption text-medium-emphasis ml-2">
            {{ dealerStatusText }}
          </span>
        </div>
        <div class="card-row">
          <div
            v-for="(card, i) in displayedDealerCards"
            :key="`d-${i}-${card}`"
            class="playing-card"
            :class="{ 'playing-card--dealt': revealing && i >= 1 }"
          >
            <span :class="suitClass(card)">{{ cardLabel(card) }}</span>
          </div>
          <!-- 尚未亮出的暗牌占位 -->
          <div v-if="dealerHoleHidden" class="playing-card playing-card--back">
            <v-icon size="small" color="white">mdi-help</v-icon>
          </div>
        </div>
      </div>

      <!-- 玩家 -->
      <div class="mb-5">
        <div class="d-flex align-center mb-2">
          <span class="text-subtitle-2 mr-2">你</span>
          <v-chip size="x-small" variant="flat" color="pink">{{ hand.player_total }} 点</v-chip>
          <v-chip v-if="hand.doubled" size="x-small" variant="outlined" color="amber" class="ml-2">
            已加倍
          </v-chip>
          <v-chip
            v-if="showRake && hand.rake_waived"
            size="x-small"
            variant="outlined"
            color="teal"
            class="ml-2"
          >
            <v-icon start size="x-small">mdi-water-off</v-icon>
            本手免抽水
          </v-chip>
        </div>
        <div class="card-row">
          <div v-for="(card, i) in hand.player_cards" :key="`p-${i}-${card}`" class="playing-card">
            <span :class="suitClass(card)">{{ cardLabel(card) }}</span>
          </div>
        </div>
      </div>

      <!-- 结算结果：等庄家补牌演示完再出，避免提前剧透 -->
      <v-alert
        v-if="hand.outcome && !revealing"
        :type="outcomeAlertType(hand.outcome)"
        variant="tonal"
        class="mb-4"
      >
        <div class="font-weight-bold">{{ outcomeText(hand.outcome) }}</div>
        <!-- 投降没有胜负，故不套用「入账/净额」那套胜负口径的展示 -->
        <div v-if="isSurrender" class="text-caption mt-1">
          本手押注 {{ totalStake }}，返还 {{ formatAmount(hand.payout_credits || 0) }}
          <span v-if="showRake"> · 不计抽水</span>
        </div>
        <div v-else class="text-caption mt-1">
          本手押注 {{ totalStake }}，入账 {{ formatAmount(hand.payout_credits || 0) }}
          <template v-if="showRake">
            <span v-if="hand.rake_credits"> （含抽水 {{ hand.rake_credits.toFixed(2) }}）</span>
            <span v-else-if="hand.rake_waived"> （本手免抽水）</span>
          </template>
          · 净
          <span :class="handNet >= 0 ? 'text-success' : 'text-error'">
            {{ handNet >= 0 ? '+' : '' }}{{ formatAmount(handNet) }}
          </span>
        </div>
        <!-- 奖池派彩与本手赔付分别记账，故也分开呈现，不混入上面的净额 -->
        <div v-if="jackpotHit" class="jackpot-hit mt-2">
          <v-icon size="small" color="amber-darken-3" class="mr-1">mdi-treasure-chest</v-icon>
          幸运奖池 <strong>+{{ hand.jackpot_won.toFixed(2) }}</strong>
          <span class="text-caption ml-1">
            （{{ jackpotTriggerText }}，独立于胜负，与本手赔付分开入账）
          </span>
        </div>
      </v-alert>

      <!-- 决策反馈：仅事后评判，不干预玩家的选择。
           赛内整块不展示——以名次而非单手期望为目标时，锦标赛的正解与基本策略
           并不一致，按后者反馈会误导玩家 -->
      <v-card
        v-if="showStrategyHint && hand.outcome && !revealing && hand.decisions_total > 0"
        variant="tonal"
        color="indigo"
        class="mb-4 pa-3"
      >
        <div class="d-flex align-center flex-wrap mb-2">
          <v-icon size="small" color="indigo" class="mr-1">mdi-school-outline</v-icon>
          <span class="text-subtitle-2">决策反馈</span>
          <v-spacer />
          <span class="text-caption">
            本手 {{ hand.decisions_correct }}/{{ hand.decisions_total }} 与基本策略一致
          </span>
        </div>

        <!-- 刷新或换设备后本地不再持有更早的逐次记录，如实说明而非假装完整 -->
        <div
          v-if="handDecisions.length < hand.decisions_total"
          class="text-caption text-medium-emphasis mb-1"
        >
          本手另有 {{ hand.decisions_total - handDecisions.length }} 次决策不在本次会话中，未逐条列出
        </div>

        <div v-for="(d, i) in handDecisions" :key="`dec-${i}`" class="decision-row">
          <span class="decision-row__index">第 {{ i + 1 }} 次</span>
          <v-icon size="x-small" :color="d.correct ? 'success' : 'warning'" class="mr-1">
            {{ d.correct ? 'mdi-check-circle' : 'mdi-alert-circle-outline' }}
          </v-icon>
          <span>你选择 <strong>{{ actionText(d.action) }}</strong></span>
          <span v-if="!d.correct" class="text-medium-emphasis ml-1">
            · 建议 <strong>{{ actionText(d.recommended) }}</strong>
          </span>
        </div>

        <div
          v-if="accuracyStats && accuracyStats.decisions_total"
          class="text-caption text-medium-emphasis mt-2"
        >
          累计准确率 {{ accuracyStats.accuracy.toFixed(1) }}%（{{ accuracyStats.decisions_total }} 次决策）
        </div>
      </v-card>

      <!-- 动作按钮 -->
      <div v-if="!hand.outcome" class="d-flex flex-wrap">
        <v-btn
          class="mr-2 mb-2"
          color="pink"
          :loading="acting === 'hit'"
          :disabled="!hand.can_hit || !!acting"
          @click="$emit('hit')"
        >
          要牌
        </v-btn>
        <v-btn
          class="mr-2 mb-2"
          color="grey-darken-1"
          :loading="acting === 'stand'"
          :disabled="!hand.can_stand || !!acting"
          @click="$emit('stand')"
        >
          停牌
        </v-btn>
        <v-btn
          class="mr-2 mb-2"
          color="amber-darken-2"
          :loading="acting === 'double'"
          :disabled="!canDouble || !!acting"
          @click="$emit('double')"
        >
          加倍
          <span v-if="hand.can_double && balance < hand.bet_credits" class="text-caption ml-1">
            （需 {{ hand.bet_credits }} {{ currencyLabel }}）
          </span>
        </v-btn>
        <!-- 与前三个动作同等形态。颜色避开停牌的 grey-darken-1，否则两个
             灰按钮相邻难以分辨 -->
        <v-btn
          v-if="hand.can_surrender"
          class="mb-2"
          color="blue-grey-darken-1"
          :loading="acting === 'surrender'"
          :disabled="!!acting"
          @click="confirmSurrender = true"
        >
          投降
        </v-btn>
      </div>

      <!-- 庄家补牌演示中：给一个跳过入口，不强迫等待 -->
      <v-btn v-else-if="revealing" block variant="outlined" size="large" @click="cancelReveal">
        跳过
      </v-btn>

      <!-- 结算后可再来一手。赛内打满手数或被淘汰时由父组件收起该按钮 -->
      <v-btn
        v-else-if="showNewHandButton"
        block
        color="pink"
        size="large"
        @click="$emit('new-hand')"
      >
        {{ newHandLabel }}
      </v-btn>

      <!-- 不能再来一手时说明原因，而非只留一个空白的牌桌 -->
      <v-alert v-else-if="finishedHint" type="info" variant="tonal" density="compact">
        {{ finishedHint }}
      </v-alert>
    </div>

    <!-- 投降二次确认：本活动唯一「点下去即无任何后续操作」的动作，
         加倍至少还会发一张牌，故只有这里需要拦一道 -->
    <v-dialog v-model="confirmSurrender" max-width="420">
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon class="mr-2" color="grey-darken-1">mdi-flag-outline</v-icon>
          确认投降？
        </v-card-title>
        <v-divider />
        <v-card-text class="pa-5">
          <p class="text-body-2">
            本手立即结束，返还一半基础注额
            <strong v-if="hand">{{ formatAmount(hand.bet_credits / 2) }}</strong>
            {{ currencyLabel }}，不再发牌、不进庄家回合。
          </p>
          <p class="text-caption text-medium-emphasis mb-0">投降后无法撤回。</p>
        </v-card-text>
        <v-divider />
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="confirmSurrender = false">取消</v-btn>
          <v-btn color="grey-darken-2" variant="flat" @click="doSurrender">确认投降</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script>
const SUIT_SYMBOLS = { S: '♠', H: '♥', D: '♦', C: '♣' }
const RED_SUITS = ['H', 'D']

// 庄家补牌的演示节奏（毫秒）。后端一次性返回补完的最终牌面，前端按真实牌桌的
// 顺序回放：亮暗牌 → 逐张补牌 → 出结果，否则庄家会从一张牌瞬间跳到最终结果，
// 玩家看不到他是怎么打的。
//
// 回放期间的中间点数取自后端的 dealer_step_totals，本文件不再自行实现点数规则
// ——A 的降级口径在前后端各写一遍就必须靠人工保持同步。
const REVEAL_HOLE_DELAY = 650
const REVEAL_DRAW_DELAY = 700
const REVEAL_END_DELAY = 450

const JACKPOT_TRIGGER_TEXT = {
  triple_seven: '三张 7',
  suited_blackjack: '同花天胡'
}

/**
 * 21 点牌桌。现金局与锦标赛赛内共用同一套牌面、动作与庄家回放，
 * 两侧差异全部由 props 承接，组件内部**不判断自己身处哪一侧**——
 * 「赛内不显示基本策略提示」这类规则由调用点显式传入，一眼可见。
 *
 * 本组件不发起任何请求：动作以 emit 上抛，由父组件调用接口并把新的手牌
 * 回传到 `hand`。庄家回放的时机由父组件通过 ref 调用 `startReveal()` /
 * `cancelReveal()` 控制——回放是否播放取决于「这一手是刚刚结算的，还是
 * 打开页面时就已结算的」，只有父组件知道。
 */
export default {
  name: 'BlackjackTable',
  props: {
    // 当前手牌；null 表示展示下注界面
    hand: { type: Object, default: null },
    // 可用余额：现金局为积分，赛内为筹码
    balance: { type: Number, default: 0 },
    currencyLabel: { type: String, default: '积分' },
    // 'tiers' = 固定档位（现金局）；'range' = 区间自由下注（锦标赛）
    betMode: { type: String, default: 'tiers' },
    betOptions: { type: Array, default: () => [] },
    betMin: { type: Number, default: 0 },
    betMax: { type: Number, default: 0 },
    betStep: { type: Number, default: 10 },
    // 发牌按钮的禁用与原因说明（活动未开放、积分不足门槛、赛事已结束等）
    dealDisabled: { type: Boolean, default: false },
    dealDisabledHint: { type: String, default: '' },
    // 抽水相关展示（抽水文案与免抽水标示）。赛内不产生抽水故整块隐藏
    showRake: { type: Boolean, default: true },
    freeHandsRemaining: { type: Number, default: 0 },
    freeHandsPerDay: { type: Number, default: 0 },
    // 基本策略的决策反馈。赛内为 false
    showStrategyHint: { type: Boolean, default: true },
    // 幸运奖池派彩展示。赛内不触发奖池故为 false
    showJackpot: { type: Boolean, default: true },
    // 父组件持有的动作进行中标记：'deal' / 'hit' / 'stand' / 'double' / 'surrender'
    acting: { type: String, default: null },
    actionError: { type: String, default: null },
    handDecisions: { type: Array, default: () => [] },
    accuracyStats: { type: Object, default: null },
    // 结算后是否提供「再来一手」，以及不提供时的说明
    showNewHandButton: { type: Boolean, default: true },
    newHandLabel: { type: String, default: '再来一手' },
    finishedHint: { type: String, default: '' }
  },
  emits: ['deal', 'hit', 'stand', 'double', 'surrender', 'new-hand', 'reveal-change'],
  data() {
    return {
      selectedBet: 0,
      confirmSurrender: false,
      // 庄家补牌演示：null 表示不在演示中（直接展示后端给的全部牌面），
      // 数字表示当前已揭示到第几张
      dealerRevealCount: null,
      revealing: false,
      // 演示批次号，用于让被跳过或被打断的旧演示自行退出
      revealToken: 0
    }
  },
  computed: {
    // 区间模式下的实际上限：不得超过当前筹码，且须落在步进上
    effectiveBetMax() {
      const cap = Math.min(this.betMax, this.balance)
      if (cap < this.betMin) {
        return this.betMin
      }
      return Math.floor(cap / this.betStep) * this.betStep
    },
    quickBets() {
      const max = this.effectiveBetMax
      const round = (v) => Math.floor(v / this.betStep) * this.betStep
      return [
        { label: '最小', value: this.betMin },
        { label: '1/4', value: round(max / 4) },
        { label: '1/2', value: round(max / 2) },
        { label: '全下', value: max }
      ]
    },
    canDeal() {
      return (
        !this.dealDisabled &&
        !this.acting &&
        this.selectedBet > 0 &&
        this.selectedBet <= this.balance
      )
    },
    canDouble() {
      // 服务端会强校验余额；此处禁用只是避免用户白点一次
      return !!this.hand && this.hand.can_double && this.balance >= this.hand.bet_credits
    },
    isSurrender() {
      return !!(this.hand && this.hand.outcome === 'surrender')
    },
    dealerCards() {
      return (this.hand && this.hand.dealer_cards) || []
    },
    // 庄家每揭开一张牌后的累计点数，由后端给出，与 dealerCards 一一对应
    dealerStepTotals() {
      return (this.hand && this.hand.dealer_step_totals) || []
    },
    displayedDealerCards() {
      if (!this.revealing || this.dealerRevealCount === null) {
        return this.dealerCards
      }
      return this.dealerCards.slice(0, this.dealerRevealCount)
    },
    dealerHoleHidden() {
      // 占位牌只代表「暗牌尚未亮出」，不代表「还没补的牌」
      if (this.revealing) {
        return this.dealerRevealCount < 2
      }
      return !!(this.hand && this.hand.dealer_hidden)
    },
    displayedDealerTotal() {
      if (!this.hand) {
        return null
      }
      if (this.revealing) {
        // 暗牌未亮出前不显示点数，否则等于泄露暗牌
        if (this.dealerRevealCount < 2) {
          return null
        }
        const total = this.dealerStepTotals[this.dealerRevealCount - 1]
        return total === undefined ? null : total
      }
      return this.hand.dealer_total
    },
    dealerTotalColor() {
      const total = this.displayedDealerTotal
      if (total === null) {
        return 'grey-darken-2'
      }
      return total > 21 ? 'error' : 'grey-darken-2'
    },
    dealerStatusText() {
      if (!this.hand) {
        return ''
      }
      // 投降的手牌庄家从未行动过：暗牌照常公开（便于复盘这次投降是对是错），
      // 但绝不能标「停牌」——庄家手上可能只有 16 点，那与「不足 17 必须要牌」
      // 的规则直接矛盾，玩家会以为庄家违规。
      if (this.isSurrender) {
        return this.revealing && this.dealerRevealCount < 2 ? '亮出暗牌…' : '未行动'
      }
      if (this.revealing) {
        if (this.dealerRevealCount < 2) {
          return '亮出暗牌…'
        }
        const total = this.dealerStepTotals[this.dealerRevealCount - 1]
        if (total === undefined) {
          return ''
        }
        if (this.dealerRevealCount < this.dealerCards.length) {
          return `${total} 点，继续要牌`
        }
        return total > 21 ? '爆牌' : '停牌'
      }
      // 结算后静态说明庄家为何停手，这正是玩家需要看到的信息
      if (this.hand.outcome && this.hand.dealer_total !== null) {
        return this.hand.dealer_total > 21 ? '爆牌' : '停牌'
      }
      return ''
    },
    totalStake() {
      if (!this.hand) {
        return 0
      }
      return this.hand.doubled ? this.hand.bet_credits * 2 : this.hand.bet_credits
    },
    handNet() {
      if (!this.hand) {
        return 0
      }
      return Number(((this.hand.payout_credits || 0) - this.totalStake).toFixed(2))
    },
    jackpotHit() {
      // 演示未结束时不提前透露，与结算结果同步出现
      return !!(this.showJackpot && this.hand && !this.revealing && this.hand.jackpot_won > 0)
    },
    jackpotTriggerText() {
      // 牌型由服务端判定并随响应给出，前端只做文案映射，不从牌面反推
      const trigger = this.hand && this.hand.jackpot_trigger
      return JACKPOT_TRIGGER_TEXT[trigger] || '幸运牌型'
    }
  },
  watch: {
    betOptions: {
      immediate: true,
      handler() {
        this.resetSelectedBet()
      }
    },
    betMin: {
      immediate: true,
      handler() {
        this.resetSelectedBet()
      }
    },
    // 筹码变化会改变可下注上限，须把已选注额收回到合法范围内
    balance() {
      if (this.betMode === 'range') {
        this.clampSelectedBet()
      }
    },
    // 回放状态上抛给父组件。父组件的奖池高亮等展示要与回放同步，而 `$refs`
    // 不是响应式的——在父组件的 computed 里读子组件的 `revealing` 不会触发
    // 重新求值，必须靠事件把状态推出去。
    revealing(value) {
      this.$emit('reveal-change', value)
    }
  },
  methods: {
    resetSelectedBet() {
      if (this.betMode === 'tiers') {
        const options = this.betOptions || []
        this.selectedBet = options.length ? options[0] : 0
      } else {
        this.selectedBet = this.betMin
        this.clampSelectedBet()
      }
    },

    clampSelectedBet() {
      const max = this.effectiveBetMax
      if (this.selectedBet > max) {
        this.selectedBet = max
      }
      if (this.selectedBet < this.betMin) {
        this.selectedBet = this.betMin
      }
    },

    // 二次确认后才真正上抛投降
    doSurrender() {
      this.confirmSurrender = false
      this.$emit('surrender')
    },

    // 金额展示：现金局的积分带两位小数，赛内筹码为整数
    formatAmount(value) {
      const num = Number(value || 0)
      return Number.isInteger(num) ? String(num) : num.toFixed(2)
    },

    sleep(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms))
    },

    // 按真实牌桌的顺序回放庄家这一轮：亮暗牌 → 逐张补牌 → 出结果。
    // 后端返回的是补完后的最终牌面，其中下标 0、1 为初始两张，2 及以后是补的牌。
    async startReveal() {
      const cards = this.dealerCards
      if (cards.length < 2) {
        this.cancelReveal()
        return
      }

      this.revealToken += 1
      const token = this.revealToken
      this.revealing = true
      // 起点是玩家回合时就已经可见的那张明牌
      this.dealerRevealCount = 1

      await this.sleep(REVEAL_HOLE_DELAY)
      if (token !== this.revealToken) {
        return
      }
      this.dealerRevealCount = 2

      for (let i = 3; i <= cards.length; i += 1) {
        await this.sleep(REVEAL_DRAW_DELAY)
        if (token !== this.revealToken) {
          return
        }
        this.dealerRevealCount = i
      }

      await this.sleep(REVEAL_END_DELAY)
      if (token !== this.revealToken) {
        return
      }
      this.cancelReveal()
    },

    // 跳过与取消是同一件事：让进行中的回放退出，并直接展示完整牌面
    cancelReveal() {
      this.revealToken += 1
      this.revealing = false
      this.dealerRevealCount = null
    },

    cardLabel(card) {
      const rank = card.slice(0, -1)
      const suit = card.slice(-1)
      return `${rank}${SUIT_SYMBOLS[suit] || suit}`
    },

    suitClass(card) {
      return RED_SUITS.includes(card.slice(-1)) ? 'card-red' : 'card-black'
    },

    outcomeText(outcome) {
      return (
        {
          blackjack: '天胡！21 点',
          win: '你赢了',
          push: '平局',
          lose: '你输了',
          bust: '爆牌，你输了',
          surrender: '已投降，返还一半注额'
        }[outcome] || outcome
      )
    },

    outcomeAlertType(outcome) {
      if (outcome === 'blackjack' || outcome === 'win') {
        return 'success'
      }
      // 投降既非胜也非负，用中性色，不打胜负标识
      if (outcome === 'push' || outcome === 'surrender') {
        return 'info'
      }
      return 'error'
    },

    actionText(action) {
      return { hit: '要牌', stand: '停牌', double: '加倍', surrender: '投降' }[action] || action
    }
  }
}
</script>

<style scoped>
.blackjack-table {
  min-height: 260px;
}

.jackpot-hit {
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(255, 143, 0, 0.14);
  color: #e65100;
  font-size: 0.875rem;
}

.decision-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  font-size: 0.8125rem;
  line-height: 1.9;
}

.decision-row__index {
  min-width: 48px;
  opacity: 0.6;
  font-size: 0.75rem;
}

.card-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.playing-card {
  width: 48px;
  height: 66px;
  border: 1px solid rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
}

.playing-card--back {
  background: repeating-linear-gradient(45deg, #7b1fa2, #7b1fa2 6px, #6a1b9a 6px, #6a1b9a 12px);
  border-color: rgba(0, 0, 0, 0.3);
}

/* 庄家回放时新出现的牌：轻微入场动画，使逐张补牌的过程看得出来 */
.playing-card--dealt {
  animation: card-deal 0.28s ease-out;
}

@keyframes card-deal {
  from {
    opacity: 0;
    transform: translateY(-10px) scale(0.92);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.card-red {
  color: #d32f2f;
}

.card-black {
  color: #212121;
}

.bet-options {
  display: flex;
  flex-wrap: wrap;
}
</style>
