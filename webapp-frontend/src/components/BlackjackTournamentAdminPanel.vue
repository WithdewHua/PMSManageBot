<template>
  <div class="pa-4">
    <v-alert type="info" variant="tonal" density="compact" class="mb-4">
      锦标赛是<strong>事件而非常规回收器</strong>。赛内 30 手的庄家优势全作用在虚拟筹码上，
      真实成本只有报名费上的抽水，故<strong>频次建议按周赛</strong>：单人单周把 30 手现金局换成
      一场赛事，站点少回收约 8 积分，20 人全换约 156 积分/周，与大转盘 21 次回收量相当，周赛频次下可忽略；
      做成日赛则会实质蚕食现金局这个温和但持续的沉淀器。
    </v-alert>

    <!-- 创建 / 编辑表单 -->
    <v-card variant="outlined" class="mb-4">
      <v-card-title class="text-subtitle-1">
        {{ editingId ? `编辑赛事 #${editingId}` : '创建新赛事' }}
      </v-card-title>
      <v-card-text>
        <v-row dense>
          <v-col cols="12">
            <v-text-field
              v-model="form.title"
              label="赛事名称"
              density="compact"
              hide-details="auto"
              :placeholder="editingId ? '' : '留空自动生成'"
              :hint="editingId ? '' : '留空将自动命名为「21 点锦标赛 · 第 N 期」'"
              :persistent-hint="!editingId"
            />
          </v-col>
          <v-col cols="12">
            <v-text-field v-model="form.description" label="赛事说明（可选）" density="compact" hide-details="auto" />
          </v-col>
          <v-col cols="6" sm="4">
            <v-text-field v-model.number="form.buy_in_credits" type="number" label="报名费（积分）" density="compact" hide-details="auto" />
          </v-col>
          <v-col cols="6" sm="4">
            <v-text-field v-model.number="form.starting_chips" type="number" label="起始筹码" density="compact" hide-details="auto" />
          </v-col>
          <v-col cols="6" sm="4">
            <v-text-field v-model.number="form.total_hands" type="number" label="总手数" density="compact" hide-details="auto" />
          </v-col>
          <v-col cols="6" sm="3">
            <v-text-field v-model.number="form.min_bet_chips" type="number" label="最小注" density="compact" hide-details="auto" />
          </v-col>
          <v-col cols="6" sm="3">
            <v-text-field v-model.number="form.max_bet_chips" type="number" label="最大注" density="compact" hide-details="auto" />
          </v-col>
          <v-col cols="6" sm="3">
            <v-text-field v-model.number="form.bet_step_chips" type="number" label="下注步进" density="compact" hide-details="auto" />
          </v-col>
          <v-col cols="6" sm="3">
            <v-text-field v-model.number="form.rake_bp" type="number" label="抽水（基点）" density="compact" hide-details="auto" hint="1000 = 10%" />
          </v-col>
          <v-col cols="6" sm="4">
            <v-text-field v-model.number="form.min_entrants" type="number" label="最低开赛人数" density="compact" hide-details="auto" hint="建议 ≥ 6" persistent-hint />
          </v-col>
          <v-col cols="6" sm="4">
            <v-text-field v-model.number="form.max_entrants" type="number" label="人数上限（满员即开）" density="compact" hide-details="auto" />
          </v-col>
          <v-col cols="12" sm="4">
            <v-text-field v-model.number="form.seeded_prize_credits" type="number" label="奖池补贴（积分）" density="compact" hide-details="auto" hint="唯一增发路径，谨慎" persistent-hint />
          </v-col>
          <v-col cols="12">
            <v-text-field v-model="form.payout_structure" label="派奖档位（逗号分隔，须和为 100）" density="compact" hide-details="auto" placeholder="50, 30, 20" />
          </v-col>
          <v-col cols="12" sm="6">
            <v-text-field v-model="form.register_deadline" type="datetime-local" label="报名截止" density="compact" hide-details="auto" />
          </v-col>
          <v-col cols="12" sm="6">
            <v-text-field v-model="form.play_deadline" type="datetime-local" label="完赛截止" density="compact" hide-details="auto" />
          </v-col>
        </v-row>

        <div class="d-flex mt-4">
          <v-btn color="primary" :loading="submitting" @click="submit">
            {{ editingId ? '保存修改' : '创建赛事' }}
          </v-btn>
          <v-btn v-if="editingId" variant="text" class="ml-2" @click="resetForm">取消编辑</v-btn>
        </div>
      </v-card-text>
    </v-card>

    <!-- 赛事列表 -->
    <div class="d-flex align-center mb-2">
      <span class="text-subtitle-1">赛事列表</span>
      <v-spacer />
      <v-btn size="small" variant="text" :loading="loading" @click="load">刷新</v-btn>
    </div>

    <v-alert v-if="!tournaments.length" type="info" variant="tonal" density="compact">
      当前没有报名中或进行中的赛事。
    </v-alert>

    <v-card v-for="t in tournaments" :key="t.id" variant="outlined" class="mb-2">
      <v-card-text class="pa-3">
        <div class="d-flex justify-space-between align-center mb-1">
          <span class="font-weight-bold">#{{ t.id }} {{ t.title }}</span>
          <v-chip :color="statusColor(t.status)" size="x-small" variant="flat">{{ statusText(t.status) }}</v-chip>
        </div>
        <div class="text-caption" style="opacity: 0.8">
          报名费 {{ t.buy_in_credits }} · 起始 {{ t.starting_chips }} · {{ t.total_hands }} 手 ·
          注 {{ t.min_bet_chips }}~{{ t.max_bet_chips }} · {{ t.entrant_count }}/{{ t.max_entrants }} 人 ·
          奖池 {{ t.prize_pool_net.toFixed(0) }}
        </div>
        <div class="d-flex mt-2">
          <v-btn v-if="t.status === 1" size="x-small" variant="tonal" color="primary" @click="edit(t)">编辑</v-btn>
          <v-btn v-if="t.status === 1" size="x-small" variant="tonal" color="error" class="ml-2" @click="cancel(t)">取消退款</v-btn>
          <v-btn size="x-small" variant="text" class="ml-2" @click="checkConsistency(t)">一致性校验</v-btn>
        </div>
        <div v-if="consistency[t.id]" class="text-caption mt-1" :class="consistency[t.id].consistent ? 'text-success' : 'text-error'">
          entrant_count={{ consistency[t.id].entrant_count }} · entry 行数={{ consistency[t.id].entry_rows }} ·
          {{ consistency[t.id].consistent ? '一致' : '不一致！' }}
        </div>
      </v-card-text>
    </v-card>
  </div>
</template>

<script>
import {
  cancelBlackjackTournament,
  checkBlackjackTournamentConsistency,
  createBlackjackTournament,
  listBlackjackTournaments,
  updateBlackjackTournament
} from '../services/blackjackTournamentService'

const STATUS_TEXT = { 1: '报名中', 2: '进行中', 3: '已结算', 4: '已取消' }
const STATUS_COLOR = { 1: 'primary', 2: 'success', 3: 'grey', 4: 'error' }

// 默认表单：与后端 DEFAULT_BLACKJACK_CONFIG.tournament_defaults 保持一致
function defaultForm() {
  return {
    title: '',
    description: '',
    buy_in_credits: 30,
    starting_chips: 1000,
    total_hands: 30,
    min_bet_chips: 10,
    max_bet_chips: 500,
    bet_step_chips: 10,
    rake_bp: 1000,
    min_entrants: 6,
    max_entrants: 20,
    seeded_prize_credits: 0,
    payout_structure: '50, 30, 20',
    register_deadline: '',
    play_deadline: ''
  }
}

export default {
  name: 'BlackjackTournamentAdminPanel',
  emits: ['show-message'],
  data() {
    return {
      loading: false,
      submitting: false,
      tournaments: [],
      editingId: null,
      form: defaultForm(),
      consistency: {}
    }
  },
  mounted() {
    this.load()
  },
  methods: {
    statusText(s) {
      return STATUS_TEXT[s] || '未知'
    },
    statusColor(s) {
      return STATUS_COLOR[s] || 'grey'
    },

    async load() {
      this.loading = true
      try {
        // 报名中、进行中、已结算、已取消都列出，便于管理员回看
        const res = await listBlackjackTournaments({ includeFinished: true })
        this.tournaments = res.data?.tournaments || []
      } catch (err) {
        this.$emit('show-message', err.response?.data?.detail || '加载赛事失败', 'error')
      } finally {
        this.loading = false
      }
    },

    resetForm() {
      this.editingId = null
      this.form = defaultForm()
    },

    // datetime-local 字符串 -> 毫秒时间戳
    toMs(local) {
      if (!local) {
        return null
      }
      return new Date(local).getTime()
    },

    // 毫秒时间戳 -> datetime-local 字符串
    toLocal(ms) {
      const d = new Date(Number(ms))
      const p = (n) => String(n).padStart(2, '0')
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
    },

    buildPayload() {
      const structure = String(this.form.payout_structure)
        .split(',')
        .map((x) => Number(x.trim()))
        .filter((x) => !Number.isNaN(x))
      return {
        title: this.form.title,
        description: this.form.description || null,
        buy_in_credits: this.form.buy_in_credits,
        starting_chips: this.form.starting_chips,
        total_hands: this.form.total_hands,
        min_bet_chips: this.form.min_bet_chips,
        max_bet_chips: this.form.max_bet_chips,
        bet_step_chips: this.form.bet_step_chips,
        rake_bp: this.form.rake_bp,
        min_entrants: this.form.min_entrants,
        max_entrants: this.form.max_entrants,
        seeded_prize_credits: this.form.seeded_prize_credits,
        payout_structure: structure,
        register_deadline_ms: this.toMs(this.form.register_deadline),
        play_deadline_ms: this.toMs(this.form.play_deadline)
      }
    },

    async submit() {
      // 编辑时留空的含义是「清空名字」而非「自动生成」，在此就地拒绝，
      // 省掉一次注定失败的请求
      if (this.editingId && !String(this.form.title || '').trim()) {
        this.$emit('show-message', '赛事名称不能为空', 'error')
        return
      }
      this.submitting = true
      try {
        const payload = this.buildPayload()
        if (this.editingId) {
          await updateBlackjackTournament(this.editingId, payload)
          this.$emit('show-message', '赛事已更新', 'success')
        } else {
          const res = await createBlackjackTournament(payload)
          // 回显最终名称：留空创建时，管理员否则要翻列表才知道系统取了什么名字
          const name = res?.data?.tournament?.title
          this.$emit(
            'show-message',
            name ? `「${name}」已创建并已群播报` : '赛事已创建并已群播报',
            'success'
          )
        }
        this.resetForm()
        await this.load()
      } catch (err) {
        this.$emit('show-message', err.response?.data?.detail || '提交失败', 'error')
      } finally {
        this.submitting = false
      }
    },

    edit(t) {
      this.editingId = t.id
      this.form = {
        title: t.title,
        description: t.description || '',
        buy_in_credits: t.buy_in_credits,
        starting_chips: t.starting_chips,
        total_hands: t.total_hands,
        min_bet_chips: t.min_bet_chips,
        max_bet_chips: t.max_bet_chips,
        bet_step_chips: t.bet_step_chips,
        rake_bp: t.rake_bp,
        min_entrants: t.min_entrants,
        max_entrants: t.max_entrants,
        seeded_prize_credits: t.seeded_prize_credits,
        payout_structure: (t.payout_structure || []).join(', '),
        register_deadline: this.toLocal(t.register_deadline_ms),
        play_deadline: this.toLocal(t.play_deadline_ms)
      }
    },

    async cancel(t) {
      if (!window.confirm(`取消赛事「${t.title}」并全额退还 ${t.entrant_count} 人的报名费？`)) {
        return
      }
      try {
        await cancelBlackjackTournament(t.id)
        this.$emit('show-message', '赛事已取消，报名费已全额退还', 'success')
        await this.load()
      } catch (err) {
        this.$emit('show-message', err.response?.data?.detail || '取消失败', 'error')
      }
    },

    async checkConsistency(t) {
      try {
        const res = await checkBlackjackTournamentConsistency(t.id)
        this.consistency = { ...this.consistency, [t.id]: res.data }
      } catch (err) {
        this.$emit('show-message', err.response?.data?.detail || '校验失败', 'error')
      }
    }
  }
}
</script>
