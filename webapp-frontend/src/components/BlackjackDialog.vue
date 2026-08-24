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

          <v-alert v-if="actionError" type="error" variant="tonal" density="compact" class="mb-4">
            {{ actionError }}
          </v-alert>

          <!-- 下注界面：无进行中手牌时 -->
          <div v-if="!hand">
            <v-alert v-if="!config.enabled" type="warning" variant="tonal" density="compact" class="mb-4">
              21 点活动当前未开放
            </v-alert>
            <v-alert
              v-else-if="currentCredits < config.min_credits"
              type="warning"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              参与需至少 {{ config.min_credits }} 积分，还需 {{ (config.min_credits - currentCredits).toFixed(2) }} 积分
            </v-alert>

            <div class="d-flex align-center mb-2">
              <span class="text-subtitle-2">选择注额</span>
              <!-- 免抽水标示：剩余手数取自 /current，发牌后本地递减 -->
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
              <span
                v-else-if="config.free_hands_per_day > 0"
                class="text-caption text-medium-emphasis ml-2"
              >
                今日免抽水手数已用完
              </span>
            </div>
            <div class="bet-options mb-4">
              <v-btn
                v-for="bet in config.bet_options"
                :key="bet"
                :variant="selectedBet === bet ? 'elevated' : 'outlined'"
                :color="selectedBet === bet ? 'pink' : undefined"
                :disabled="bet > currentCredits"
                class="mr-2 mb-2"
                @click="selectedBet = bet"
              >
                {{ bet }}
              </v-btn>
            </div>

            <v-btn
              block
              color="pink"
              size="large"
              :loading="acting"
              :disabled="!canDeal"
              @click="deal"
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
                <v-chip v-if="hand.rake_waived" size="x-small" variant="outlined" color="teal" class="ml-2">
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
                本手押注 {{ totalStake }}，返还 {{ (hand.payout_credits || 0).toFixed(2) }} · 不计抽水
              </div>
              <div v-else class="text-caption mt-1">
                本手押注 {{ totalStake }}，入账 {{ (hand.payout_credits || 0).toFixed(2) }}
                <span v-if="hand.rake_credits"> （含抽水 {{ hand.rake_credits.toFixed(2) }}）</span>
                <span v-else-if="hand.rake_waived"> （本手免抽水）</span>
                · 净
                <span :class="handNet >= 0 ? 'text-success' : 'text-error'">
                  {{ handNet >= 0 ? '+' : '' }}{{ handNet.toFixed(2) }}
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

            <!-- 决策反馈：仅事后评判，不干预玩家的选择 -->
            <v-card
              v-if="hand.outcome && !revealing && hand.decisions_total > 0"
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

              <div v-if="stats && stats.decisions_total" class="text-caption text-medium-emphasis mt-2">
                累计准确率 {{ stats.accuracy.toFixed(1) }}%（{{ stats.decisions_total }} 次决策）
              </div>
            </v-card>

            <!-- 动作按钮 -->
            <div v-if="!hand.outcome" class="d-flex flex-wrap">
              <v-btn
                class="mr-2 mb-2"
                color="pink"
                :loading="acting === 'hit'"
                :disabled="!hand.can_hit || !!acting"
                @click="act('hit')"
              >
                要牌
              </v-btn>
              <v-btn
                class="mr-2 mb-2"
                color="grey-darken-1"
                :loading="acting === 'stand'"
                :disabled="!hand.can_stand || !!acting"
                @click="act('stand')"
              >
                停牌
              </v-btn>
              <v-btn
                class="mr-2 mb-2"
                color="amber-darken-2"
                :loading="acting === 'double'"
                :disabled="!canDouble || !!acting"
                @click="act('double')"
              >
                加倍
                <span v-if="hand.can_double && currentCredits < hand.bet_credits" class="text-caption ml-1">
                  （需 {{ hand.bet_credits }} 积分）
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
            <v-btn
              v-else-if="revealing"
              block
              variant="outlined"
              size="large"
              @click="skipReveal"
            >
              跳过
            </v-btn>

            <!-- 结算后可再来一手 -->
            <v-btn
              v-else
              block
              color="pink"
              size="large"
              @click="startNewHand"
            >
              再来一手
            </v-btn>
          </div>
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
            <strong v-if="hand">{{ (hand.bet_credits / 2).toFixed(2) }}</strong>
            积分，不再发牌、不进庄家回合。
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
  </v-dialog>
</template>

<script>
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

export default {
  name: 'BlackjackDialog',
  emits: ['credits-changed'],
  data() {
    return {
      dialog: false,
      loading: false,
      loadError: null,
      actionError: null,
      acting: null,
      showRules: false,
      // 投降的二次确认弹层
      confirmSurrender: false,
      hand: null,
      stats: null,
      currentCredits: 0,
      selectedBet: 0,
      // 幸运奖池余额：随每次操作的响应刷新，牌桌顶部常驻显示
      jackpotBalance: 0,
      // 今日剩余免抽水手数：进入活动时由 /current 给出，发牌后本地递减
      freeHandsRemaining: 0,
      // 本手的逐次决策评判，用于结算后逐条回放。刷新或换设备后会为空，
      // 届时只展示手牌上的累计计数，不伪造缺失的条目。
      handDecisions: [],
      // 庄家补牌演示：null 表示不在演示中（直接展示后端给的全部牌面），
      // 数字表示当前已揭示到第几张
      dealerRevealCount: null,
      revealing: false,
      // 演示批次号，用于让被跳过或被打断的旧演示自行退出
      revealToken: 0,
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
    canDeal() {
      return (
        this.config.enabled &&
        !this.acting &&
        this.selectedBet > 0 &&
        this.currentCredits >= this.config.min_credits &&
        this.currentCredits >= this.selectedBet
      )
    },
    canDouble() {
      // 服务端会强校验余额；此处禁用只是避免用户白点一次
      return !!this.hand && this.hand.can_double && this.currentCredits >= this.hand.bet_credits
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
      // 演示未结束时不提前透露，与结算结果同步出现
      return !!(this.hand && !this.revealing && this.hand.jackpot_won > 0)
    },
    jackpotTriggerText() {
      // 牌型由服务端判定并随响应给出，前端只做文案映射，不从牌面反推
      const trigger = this.hand && this.hand.jackpot_trigger
      return JACKPOT_TRIGGER_TEXT[trigger] || '幸运牌型'
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
        const options = this.config.bet_options || []
        this.selectedBet = options.length ? options[0] : 0

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

    async deal() {
      this.acting = 'deal'
      this.actionError = null
      // 新的一手从零开始记录决策，不与上一手混在一起
      this.handDecisions = []
      try {
        const response = await dealBlackjackHand(this.selectedBet)
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

    // 二次确认后才真正发出投降请求
    doSurrender() {
      this.confirmSurrender = false
      this.act('surrender')
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
        // 本手已结束：回放庄家的补牌过程，而非直接甩出最终牌面
        this.revealDealerPlay()
      } else {
        this.cancelReveal()
      }
    },

    sleep(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms))
    },

    // 按真实牌桌的顺序回放庄家这一轮：亮暗牌 → 逐张补牌 → 出结果。
    // 后端返回的是补完后的最终牌面，其中下标 0、1 为初始两张，2 及以后是补的牌。
    async revealDealerPlay() {
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
    skipReveal() {
      this.cancelReveal()
    },

    cancelReveal() {
      this.revealToken += 1
      this.revealing = false
      this.dealerRevealCount = null
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
.blackjack-dialog__titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.blackjack-dialog__title {
  display: flex;
  align-items: center;
}

.blackjack-table {
  min-height: 260px;
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
