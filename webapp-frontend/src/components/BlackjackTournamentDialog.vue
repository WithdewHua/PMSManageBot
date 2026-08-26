<template>
  <v-dialog v-model="dialog" max-width="760" persistent>
    <v-card class="activity-dialog">
      <v-card-title class="bjt-titlebar">
        <div class="d-flex align-center">
          <v-icon class="mr-2" color="amber-darken-2">mdi-trophy</v-icon>
          21 点锦标赛
        </div>
        <div class="d-flex align-center">
          <v-btn
            v-if="view !== 'lobby'"
            class="mr-1"
            icon
            variant="text"
            size="small"
            title="返回大厅"
            @click="backToLobby"
          >
            <v-icon>mdi-arrow-left</v-icon>
          </v-btn>
          <v-btn
            v-if="view === 'table'"
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

      <v-card-text class="pa-5">
        <div v-if="loading" class="text-center py-8">
          <v-progress-circular indeterminate color="amber-darken-2" size="50" />
          <div class="mt-3">加载中...</div>
        </div>

        <div v-else-if="loadError" class="text-center py-6">
          <v-alert type="error" variant="tonal">{{ loadError }}</v-alert>
          <v-btn class="mt-3" color="primary" @click="loadLobby">重试</v-btn>
        </div>

        <!-- 大厅 -->
        <div v-else-if="view === 'lobby'">
          <div class="d-flex justify-space-between align-center mb-3">
            <v-chip size="small" variant="outlined" color="primary">
              <v-icon size="small" class="mr-1">mdi-star</v-icon>
              当前积分：{{ currentCredits.toFixed(2) }}
            </v-chip>
          </div>

          <v-alert
            v-if="!tournaments.length"
            type="info"
            variant="tonal"
            density="compact"
          >
            当前没有开放中的锦标赛，敬请期待。
          </v-alert>

          <v-card
            v-for="t in tournaments"
            :key="t.id"
            variant="outlined"
            class="mb-3 bjt-card"
            @click="openTournament(t.id)"
          >
            <v-card-text class="pa-4">
              <div class="d-flex justify-space-between align-center mb-2">
                <span class="text-subtitle-1 font-weight-bold">{{ t.title }}</span>
                <v-chip :color="statusColor(t.status)" size="small" variant="flat">
                  {{ statusText(t.status) }}
                </v-chip>
              </div>
              <div class="bjt-meta">
                <span><v-icon size="x-small">mdi-ticket</v-icon> 报名费 {{ t.buy_in_credits }} 积分</span>
                <span><v-icon size="x-small">mdi-poker-chip</v-icon> 起始 {{ t.starting_chips }} 筹码</span>
                <span><v-icon size="x-small">mdi-cards</v-icon> 共 {{ t.total_hands }} 手</span>
                <span><v-icon size="x-small">mdi-cash</v-icon> 注 {{ t.min_bet_chips }}~{{ t.max_bet_chips }}</span>
                <span>
                  <v-icon size="x-small">mdi-account-group</v-icon>
                  {{ t.entrant_count }}/{{ t.max_entrants }} 人（满 {{ t.min_entrants }} 开赛）
                </span>
                <span><v-icon size="x-small">mdi-treasure-chest</v-icon> 奖池 {{ t.prize_pool_net.toFixed(0) }} 积分</span>
              </div>
              <div class="bjt-deadlines mt-2">
                <span>报名截止 {{ fmtTs(t.register_deadline_ms) }}</span>
                <span>完赛截止 {{ fmtTs(t.play_deadline_ms) }}</span>
              </div>
              <div v-if="t.my_entry" class="mt-2">
                <v-chip size="x-small" color="success" variant="flat">
                  已报名 · 筹码 {{ t.my_entry.chips }} · 已打 {{ t.my_entry.hands_played }}/{{ t.total_hands }}
                </v-chip>
              </div>
            </v-card-text>
          </v-card>
        </div>

        <!-- 赛内牌桌 / 报名 / 赛果 -->
        <div v-else-if="view === 'table' && tournament">
          <!-- 状态区 -->
          <div class="bjt-status mb-3">
            <div class="d-flex justify-space-between align-center flex-wrap">
              <span class="text-subtitle-1 font-weight-bold">{{ tournament.title }}</span>
              <v-chip :color="statusColor(tournament.status)" size="small" variant="flat">
                {{ statusText(tournament.status) }}
              </v-chip>
            </div>

            <!-- 已报名：筹码与手数进度 -->
            <div v-if="entry" class="bjt-progress mt-2">
              <v-chip size="small" variant="outlined" color="amber-darken-2">
                <v-icon size="small" class="mr-1">mdi-poker-chip</v-icon>
                筹码 {{ entry.chips }}
              </v-chip>
              <v-chip size="small" variant="outlined">
                已打 {{ entry.hands_played }}/{{ tournament.total_hands }}
              </v-chip>
              <v-chip
                v-if="entry.status === 2"
                size="small"
                color="success"
                variant="flat"
              >
                已打完全部手数
              </v-chip>
              <v-chip
                v-else-if="entry.status === 3"
                size="small"
                color="error"
                variant="flat"
              >
                筹码不足，已淘汰
              </v-chip>
            </div>
          </div>

          <v-alert v-if="actionError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ actionError }}
          </v-alert>

          <!-- 未报名：报名入口 -->
          <div v-if="!entry" class="text-center py-4">
            <p class="mb-3">报名费 <strong>{{ tournament.buy_in_credits }}</strong> 积分，换取 <strong>{{ tournament.starting_chips }}</strong> 起始筹码。</p>
            <v-alert
              v-if="tournament.status !== 1"
              type="warning"
              variant="tonal"
              density="compact"
              class="mb-3"
            >
              该赛事已{{ tournament.status === 2 ? '开赛' : '结束' }}，无法报名。
            </v-alert>
            <v-alert
              v-else-if="currentCredits < tournament.buy_in_credits"
              type="warning"
              variant="tonal"
              density="compact"
              class="mb-3"
            >
              积分不足，报名需 {{ tournament.buy_in_credits }} 积分。
            </v-alert>
            <v-btn
              color="amber-darken-2"
              size="large"
              :loading="registering"
              :disabled="tournament.status !== 1 || currentCredits < tournament.buy_in_credits"
              @click="register"
            >
              <v-icon class="mr-1">mdi-ticket-confirmation</v-icon>
              报名（{{ tournament.buy_in_credits }} 积分）
            </v-btn>
          </div>

          <!-- 已报名且赛事进行中：牌桌。
               条件里的 `|| hand` 不能省：决定性的那一手（打满手数或被淘汰）会把
               entry.status 从 1 改成 2/3，若只看状态，牌桌会在同一个 tick 里被
               卸载——玩家看不到那一手的庄家牌和结果，只看到牌桌凭空消失。
               留着牌桌，由「查看赛果」把 hand 清空后再切到终结面板。 -->
          <BlackjackTable
            v-else-if="tournament.status === 2 && (entry.status === 1 || hand)"
            ref="table"
            :hand="hand"
            :balance="entry.chips"
            currency-label="筹码"
            bet-mode="range"
            :bet-min="tournament.min_bet_chips"
            :bet-max="tournament.max_bet_chips"
            :bet-step="tournament.bet_step_chips"
            :deal-disabled="dealDisabled"
            :deal-disabled-hint="dealDisabledHint"
            :show-rake="false"
            :show-strategy-hint="false"
            :show-jackpot="false"
            :acting="acting"
            :new-hand-label="entryTerminal ? '查看赛果' : `再来一手（剩 ${handsRemaining} 手）`"
            :show-new-hand-button="entryTerminal || handsRemaining > 0"
            :finished-hint="handsRemaining <= 0 ? '你已打满全部手数，等待赛事结算。' : ''"
            @deal="deal"
            @hit="act('hit')"
            @stand="act('stand')"
            @double="act('double')"
            @surrender="act('surrender')"
            @new-hand="startNewHand"
          />

          <!-- 已报名但已终结（打完/淘汰/赛事结束）：看排名 -->
          <div v-else>
            <v-alert
              v-if="entry.status === 2"
              type="success"
              variant="tonal"
              density="compact"
              class="mb-3"
            >
              你已打满全部手数，等待赛事在完赛截止后结算。
            </v-alert>
            <v-alert
              v-else-if="entry.status === 3"
              type="info"
              variant="tonal"
              density="compact"
              class="mb-3"
            >
              你的筹码已不足最小注，被淘汰出局，仍保留派奖资格。
            </v-alert>
          </div>

          <!-- 排名 -->
          <div class="mt-4">
            <div class="d-flex align-center mb-2">
              <v-icon size="small" class="mr-1">mdi-format-list-numbered</v-icon>
              <span class="text-subtitle-2">{{ tournament.status === 3 ? '最终名次' : '实时排名' }}</span>
              <v-spacer />
              <v-btn size="x-small" variant="text" :loading="standingsLoading" @click="loadStandings">
                刷新
              </v-btn>
            </div>
            <v-table density="compact" class="bjt-standings">
              <thead>
                <tr>
                  <th>名次</th>
                  <th>玩家</th>
                  <th class="text-right">筹码</th>
                  <th class="text-right">派奖</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in standings"
                  :key="row.tg_id"
                  :class="{ 'bjt-me': entry && row.tg_id === entry.tg_id }"
                >
                  <td>{{ row.final_rank || row.provisional_rank || '-' }}</td>
                  <td>
                    {{ row.display_name || row.tg_id }}
                    <v-icon v-if="!row.eligible" size="x-small" color="grey" title="未完赛，无派奖资格">mdi-alert-circle-outline</v-icon>
                  </td>
                  <td class="text-right">{{ row.chips }}</td>
                  <td class="text-right">
                    <span v-if="row.prize_credits">+{{ row.prize_credits.toFixed(2) }}</span>
                    <span v-else>-</span>
                  </td>
                </tr>
              </tbody>
            </v-table>
          </div>
        </div>
      </v-card-text>
    </v-card>

    <!-- 赛内规则说明 -->
    <v-dialog v-model="showRules" max-width="560">
      <v-card v-if="tournament">
        <v-card-title class="d-flex align-center">
          <v-icon class="mr-2" color="amber-darken-2">mdi-help-circle-outline</v-icon>
          锦标赛规则
        </v-card-title>
        <v-divider />
        <v-card-text class="pa-5">
          <div class="rules-section">
            <div class="rules-title">目标</div>
            <p>用起始筹码打满 <strong>{{ tournament.total_hands }}</strong> 手，最终筹码越多名次越高，按名次分取奖池。</p>
          </div>
          <div class="rules-section">
            <div class="rules-title">下注</div>
            <p>
              每手可在 <strong>{{ tournament.min_bet_chips }} ~ {{ tournament.max_bet_chips }}</strong> 筹码之间自由选择，
              须为 <strong>{{ tournament.bet_step_chips }}</strong> 的整数倍。
              <strong>下注多少本身就是锦标赛的核心技巧</strong>——落后时可加注追赶，领先时可收缩保成。
            </p>
          </div>
          <div class="rules-section">
            <div class="rules-title">淘汰与完赛</div>
            <p>
              打满全部手数即完赛；筹码低于最小注（{{ tournament.min_bet_chips }}）即被淘汰。
              <strong>两者都保留派奖资格。</strong>
            </p>
          </div>
          <div class="rules-section">
            <div class="rules-title">派奖资格</div>
            <p>
              <strong>只有打满全部手数或被淘汰者才参与派奖。</strong>
              未打满且未被淘汰者失去派奖资格，报名费留在奖池中——所以报名后一定要打完。
            </p>
          </div>
          <div class="rules-section">
            <div class="rules-title">排名与并列</div>
            <p>按最终筹码降序排名，筹码相同则报名较早者列前。奖池按档位派发，具备资格者少于档位数时截断并重新归一，奖池不残留。</p>
          </div>
          <div class="rules-section">
            <div class="rules-title">与现金局的不同</div>
            <p>
              赛内<strong>不抽水、不触发幸运奖池</strong>，赛内手牌也<strong>不提供基本策略提示、不计入决策准确率</strong>
              ——以名次为目标时的正解与单手最优打法并不一致。
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
  dealTournamentHand,
  doubleTournamentHand,
  getBlackjackTournament,
  getBlackjackTournamentStandings,
  getCurrentTournamentHand,
  hitTournamentHand,
  listBlackjackTournaments,
  registerBlackjackTournament,
  standTournamentHand,
  surrenderTournamentHand
} from '../services/blackjackTournamentService'
import { getUserInfo } from '../api'

const STATUS_TEXT = { 1: '报名中', 2: '进行中', 3: '已结算', 4: '已取消' }
const STATUS_COLOR = { 1: 'primary', 2: 'success', 3: 'grey', 4: 'error' }

export default {
  name: 'BlackjackTournamentDialog',
  components: { BlackjackTable },
  emits: ['credits-changed'],
  data() {
    return {
      dialog: false,
      loading: false,
      loadError: null,
      actionError: null,
      showRules: false,
      view: 'lobby', // lobby | table
      acting: null,
      registering: false,
      standingsLoading: false,
      currentCredits: 0,
      tournaments: [],
      tournament: null,
      entry: null,
      hand: null,
      standings: []
    }
  },
  computed: {
    handsRemaining() {
      if (!this.tournament || !this.entry) {
        return 0
      }
      return Math.max(0, this.tournament.total_hands - this.entry.hands_played)
    },
    // 报名已进入终态（已打完 / 已淘汰）。终态下牌桌只用来展示最后一手的结果
    entryTerminal() {
      return !!this.entry && this.entry.status !== 1
    },
    dealDisabled() {
      return (
        !this.tournament ||
        this.tournament.status !== 2 ||
        !this.entry ||
        this.entry.status !== 1 ||
        this.handsRemaining <= 0
      )
    },
    dealDisabledHint() {
      if (this.entry && this.entry.status === 3) {
        return '你的筹码已不足最小注，被淘汰出局，仍保留派奖资格。'
      }
      if (this.handsRemaining <= 0) {
        return '你已打满全部手数，等待赛事结算。'
      }
      return ''
    }
  },
  methods: {
    open() {
      this.dialog = true
      this.view = 'lobby'
      this.loadLobby()
    },

    close() {
      this.cancelReveal()
      this.dialog = false
      this.actionError = null
      this.$emit('credits-changed')
    },

    backToLobby() {
      this.cancelReveal()
      this.view = 'lobby'
      this.tournament = null
      this.entry = null
      this.hand = null
      this.standings = []
      this.loadLobby()
    },

    cancelReveal() {
      this.$refs.table?.cancelReveal()
    },

    statusText(s) {
      return STATUS_TEXT[s] || '未知'
    },
    statusColor(s) {
      return STATUS_COLOR[s] || 'grey'
    },
    fmtTs(ms) {
      const d = new Date(Number(ms))
      const p = (n) => String(n).padStart(2, '0')
      return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
    },

    async refreshCredits() {
      try {
        const res = await getUserInfo()
        this.currentCredits = Number(res.data?.credits ?? this.currentCredits)
      } catch (err) {
        console.error('刷新积分失败:', err)
      }
    },

    async loadLobby() {
      this.loading = true
      this.loadError = null
      try {
        const [listRes] = await Promise.all([listBlackjackTournaments(), this.refreshCredits()])
        this.tournaments = listRes.data?.tournaments || []
      } catch (err) {
        console.error('加载锦标赛大厅失败:', err)
        this.loadError = err.response?.data?.detail || '加载失败'
      } finally {
        this.loading = false
      }
    },

    async openTournament(tournamentId) {
      this.loading = true
      this.loadError = null
      this.actionError = null
      this.view = 'table'
      try {
        const res = await getBlackjackTournament(tournamentId)
        this.tournament = res.data
        this.entry = res.data.my_entry || null
        this.hand = null
        // 已报名则拉当前手牌与筹码
        if (this.entry) {
          await this.loadCurrentHand()
        }
        await this.loadStandings()
      } catch (err) {
        console.error('加载赛事失败:', err)
        this.loadError = err.response?.data?.detail || '加载失败'
      } finally {
        this.loading = false
      }
    },

    async loadCurrentHand() {
      try {
        const res = await getCurrentTournamentHand(this.tournament.id)
        this.tournament = res.data.tournament
        this.entry = res.data.entry
        this.hand = res.data.hand || null
      } catch (err) {
        // 未报名等情况下 /current 会 400，静默即可（报名入口由 entry 控制）
        if (err.response?.status !== 400) {
          console.error('加载赛内手牌失败:', err)
        }
      }
    },

    async loadStandings() {
      if (!this.tournament) {
        return
      }
      this.standingsLoading = true
      try {
        const res = await getBlackjackTournamentStandings(this.tournament.id)
        this.standings = res.data?.standings || []
      } catch (err) {
        console.error('加载排名失败:', err)
      } finally {
        this.standingsLoading = false
      }
    },

    async register() {
      this.registering = true
      this.actionError = null
      try {
        const res = await registerBlackjackTournament(this.tournament.id)
        this.tournament = res.data.tournament
        this.entry = res.data.entry
        this.currentCredits = Number(res.data.current_credits)
        this.$emit('credits-changed')
        await this.loadStandings()
      } catch (err) {
        this.actionError = err.response?.data?.detail || '报名失败'
      } finally {
        this.registering = false
      }
    },

    async deal(bet) {
      this.acting = 'deal'
      this.actionError = null
      try {
        const res = await dealTournamentHand(this.tournament.id, bet)
        this.applyActionResult(res.data)
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
        hit: hitTournamentHand,
        stand: standTournamentHand,
        double: doubleTournamentHand,
        surrender: surrenderTournamentHand
      }
      this.acting = action
      this.actionError = null
      try {
        const res = await handlers[action](this.tournament.id, this.hand.id)
        this.applyActionResult(res.data)
      } catch (err) {
        this.handleActionError(err)
      } finally {
        this.acting = null
      }
    },

    applyActionResult(data) {
      this.hand = data.hand
      // 筹码与手数进度落在 entry 上，动作响应直接带回，无需再查。
      // **只在字段非空时覆盖**：结算被兜底扫描抢先时这三个字段会是 null，
      // 无条件赋值会把玩家的筹码栈显示成 0、进度回退到 0/N
      if (this.entry) {
        if (data.chips != null) {
          this.entry.chips = data.chips
        }
        if (data.hands_played != null) {
          this.entry.hands_played = data.hands_played
        }
        if (data.entry_status != null) {
          this.entry.status = data.entry_status
        }
      }
      if (data.settled) {
        this.$nextTick(() => this.$refs.table?.startReveal())
        this.loadStandings()
      } else {
        this.cancelReveal()
      }
    },

    startNewHand() {
      this.cancelReveal()
      this.hand = null
      // 终态下这个按钮的语义是「查看赛果」：清掉手牌即切到终结面板，顺手刷名次
      if (this.entryTerminal) {
        this.loadStandings()
      }
    },

    handleActionError(err) {
      console.error('赛内操作失败:', err)
      this.actionError = err.response?.data?.detail || '操作失败'
      const status = err.response?.status
      if (status === 400 || status === 404 || status >= 500 || !status) {
        this.loadCurrentHand()
      }
    }
  }
}
</script>

<style scoped>
.bjt-titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.bjt-card {
  cursor: pointer;
  transition: box-shadow 0.2s ease;
}
.bjt-card:hover {
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
}

.bjt-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  font-size: 0.82rem;
  opacity: 0.85;
}

.bjt-deadlines {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  font-size: 0.75rem;
  opacity: 0.65;
}

.bjt-status {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 143, 0, 0.35);
  background: linear-gradient(90deg, rgba(255, 193, 7, 0.1), rgba(255, 143, 0, 0.04));
}

.bjt-progress {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.bjt-standings :deep(th),
.bjt-standings :deep(td) {
  font-size: 0.82rem;
}

.bjt-me {
  background: rgba(255, 193, 7, 0.14);
  font-weight: 600;
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
