<template>
  <div class="gift-pack-condition-editor">
    <v-alert
      class="mb-3"
      density="compact"
      type="info"
      variant="tonal"
    >
      {{ mode === 'audience'
        ? '受众决定哪些用户能看到礼包；所有顶层条件都需要同时满足。'
        : '领取条件决定用户需要完成什么；所有顶层条件都需要同时满足。' }}
      可添加“满足其一”组，但组内只允许放叶子条件。
    </v-alert>

    <v-alert
      v-if="validationErrors.length"
      class="mb-3"
      density="compact"
      type="warning"
      variant="tonal"
    >
      <div class="font-weight-medium mb-1">保存前请处理以下条件：</div>
      <ul class="condition-errors">
        <li v-for="error in validationErrors" :key="error">{{ error }}</li>
      </ul>
    </v-alert>

    <div v-if="!conditionRows.length" class="empty-conditions mb-3">
      未配置条件：{{ mode === 'audience' ? '所有用户可见' : '无需额外完成任务' }}。
    </div>

    <template v-for="row in conditionRows" :key="row.key">
      <v-card
        v-if="row.kind === 'group'"
        class="condition-group-header mb-2"
        variant="tonal"
        color="primary"
      >
        <v-card-text class="d-flex align-center py-2">
          <v-icon class="mr-2">mdi-set-center</v-icon>
          <span class="font-weight-medium">满足其一</span>
          <span class="text-caption ml-2">组内至少满足一个条件</span>
          <v-spacer></v-spacer>
          <v-btn
            :disabled="isEditorDisabled()"
            size="small"
            variant="text"
            @click="addGroupItem(row)"
          >
            <v-icon start>mdi-plus</v-icon>
            添加组内条件
          </v-btn>
          <v-btn
            :disabled="isEditorDisabled()"
            icon="mdi-delete-outline"
            size="small"
            variant="text"
            @click="removeGroup(row)"
          ></v-btn>
        </v-card-text>
      </v-card>

      <v-card
        v-else
        class="condition-card mb-2"
        :class="{ 'condition-card--nested': row.group }"
        variant="outlined"
      >
        <v-card-text>
          <div class="d-flex align-center mb-2">
            <span class="condition-index text-caption text-medium-emphasis">
              {{ row.group ? `组内条件 ${row.itemIndex + 1}` : `条件 ${row.topIndex + 1}` }}
            </span>
            <v-spacer></v-spacer>
            <v-btn
              :disabled="isEditorDisabled() || (row.group && row.group.items.length <= 2)"
              icon="mdi-delete-outline"
              size="small"
              variant="text"
              @click="removeCondition(row)"
            ></v-btn>
          </div>

          <v-select
            :disabled="isEditorDisabled()"
            density="comfortable"
            item-title="label"
            item-value="value"
            :items="conditionTypeItems(row)"
            label="条件类型"
            :model-value="row.condition.type"
            variant="outlined"
            @update:model-value="replaceConditionType(row, $event)"
          ></v-select>

          <!-- 指定名单 -->
          <template v-if="row.condition.type === 'user_list'">
            <v-select
              :disabled="isEditorDisabled()"
              density="comfortable"
              item-title="label"
              item-value="value"
              :items="userListModeItems"
              label="名单模式"
              :model-value="row.condition.mode"
              variant="outlined"
              @update:model-value="setConditionValue(row.condition, 'mode', $event)"
            ></v-select>

            <v-textarea
              :disabled="isEditorDisabled()"
              auto-grow
              density="comfortable"
              hint="支持 Telegram ID、Plex 用户名/邮箱、Emby 用户名；可用空格、逗号或换行分隔。"
              label="粘贴用户标识"
              :model-value="row.condition._userListText"
              persistent-hint
              rows="3"
              variant="outlined"
              @update:model-value="updateUserListText(row.condition, $event)"
            ></v-textarea>

            <div class="d-flex align-center flex-wrap mt-2">
              <v-btn
                color="primary"
                :disabled="isEditorDisabled() || row.condition._resolutionState === 'loading'"
                :loading="row.condition._resolutionState === 'loading'"
                size="small"
                variant="tonal"
                @click="resolveUserList(row)"
              >
                <v-icon start>mdi-account-search</v-icon>
                解析名单
              </v-btn>
              <span
                v-if="row.condition._resolutionState === 'resolved'"
                class="text-caption text-success ml-3"
              >
                已解析 {{ row.condition.tg_ids.length }} 个用户
              </span>
              <span
                v-else-if="row.condition._resolutionState === 'partial'"
                class="text-caption text-warning ml-3"
              >
                已解析 {{ row.condition.tg_ids.length }} 个用户，仍有标识无法解析
              </span>
              <span
                v-else-if="row.condition._resolutionState === 'dirty'"
                class="text-caption text-warning ml-3"
              >
                名单已修改，请重新解析后保存
              </span>
              <span
                v-else-if="row.condition._resolutionState === 'empty'"
                class="text-caption text-medium-emphasis ml-3"
              >
                当前名单为空
              </span>
            </div>

            <v-alert
              v-if="row.condition._resolutionError"
              class="mt-3"
              density="compact"
              type="error"
              variant="tonal"
            >
              名单解析失败：{{ row.condition._resolutionError }}
            </v-alert>

            <v-alert
              v-if="row.condition._unresolved.length"
              class="mt-3"
              density="compact"
              type="warning"
              variant="tonal"
            >
              <div class="font-weight-medium mb-1">以下标识无法解析，不能被保存为名单：</div>
              <ul class="unresolved-users">
                <li v-for="item in row.condition._unresolved" :key="`${row.condition._key}-${item.token}`">
                  <code>{{ item.token }}</code><span v-if="item.reason">：{{ item.reason }}</span>
                </li>
              </ul>
            </v-alert>

            <div v-if="row.condition._resolved.length" class="resolved-users mt-3">
              <div class="text-caption text-medium-emphasis mb-1">本次解析结果</div>
              <v-chip
                v-for="item in row.condition._resolved"
                :key="`${row.condition._key}-${item.tg_id}`"
                class="mr-1 mb-1"
                size="small"
                variant="outlined"
              >
                {{ item.display_name || item.token }} → {{ item.tg_id }}
                <span class="ml-1 text-medium-emphasis">({{ matchedByLabel(item.matched_by) }})</span>
              </v-chip>
            </div>
          </template>

          <!-- 状态型条件 -->
          <template v-else-if="row.condition.type === 'premium'">
            <v-select
              :disabled="isEditorDisabled()"
              density="comfortable"
              item-title="label"
              item-value="value"
              :items="premiumStateItems"
              label="Premium 状态"
              :model-value="row.condition.state"
              variant="outlined"
              @update:model-value="setConditionValue(row.condition, 'state', $event)"
            ></v-select>
          </template>

          <template v-else-if="row.condition.type === 'bound'">
            <v-select
              :disabled="isEditorDisabled()"
              density="comfortable"
              item-title="label"
              item-value="value"
              :items="boundServiceItems"
              label="绑定服务"
              :model-value="row.condition.service"
              variant="outlined"
              @update:model-value="setConditionValue(row.condition, 'service', $event)"
            ></v-select>
          </template>

          <template v-else-if="row.condition.type === 'credits'">
            <v-row dense>
              <v-col cols="12" sm="6">
                <v-text-field
                  :disabled="isEditorDisabled()"
                  density="comfortable"
                  label="最低积分（可选）"
                  min="0"
                  :model-value="row.condition.min"
                  type="number"
                  variant="outlined"
                  @update:model-value="setConditionValue(row.condition, 'min', $event)"
                ></v-text-field>
              </v-col>
              <v-col cols="12" sm="6">
                <v-text-field
                  :disabled="isEditorDisabled()"
                  density="comfortable"
                  label="最高积分（可选）"
                  min="0"
                  :model-value="row.condition.max"
                  type="number"
                  variant="outlined"
                  @update:model-value="setConditionValue(row.condition, 'max', $event)"
                ></v-text-field>
              </v-col>
            </v-row>
          </template>

          <template v-else-if="row.condition.type === 'badge'">
            <v-text-field
              :disabled="isEditorDisabled()"
              density="comfortable"
              label="勋章 ID"
              min="1"
              :model-value="row.condition.badge_id"
              type="number"
              variant="outlined"
              @update:model-value="setConditionValue(row.condition, 'badge_id', $event)"
            ></v-text-field>
          </template>

          <template v-else-if="row.condition.type === 'claimed_pack'">
            <v-text-field
              :disabled="isEditorDisabled()"
              density="comfortable"
              label="已领取的礼包 ID"
              min="1"
              :model-value="row.condition.pack_id"
              type="number"
              variant="outlined"
              @update:model-value="setConditionValue(row.condition, 'pack_id', $event)"
            ></v-text-field>
          </template>

          <!-- 计数型条件 -->
          <template v-else>
            <v-row dense>
              <v-col cols="12" :sm="row.condition.type === 'blackjack_hands' ? 6 : 12">
                <v-text-field
                  :disabled="isEditorDisabled()"
                  density="comfortable"
                  :label="row.condition.type === 'watched_hours' ? '目标时长' : '目标数量'"
                  min="0"
                  :model-value="row.condition.min"
                  type="number"
                  :suffix="row.condition.type === 'watched_hours' ? '小时' : ''"
                  variant="outlined"
                  @update:model-value="setConditionValue(row.condition, 'min', $event)"
                ></v-text-field>
              </v-col>
              <v-col v-if="row.condition.type === 'blackjack_hands'" cols="12" sm="6">
                <v-text-field
                  :disabled="isEditorDisabled()"
                  density="comfortable"
                  label="每手最低注额（可选）"
                  min="0"
                  :model-value="row.condition.min_bet"
                  type="number"
                  variant="outlined"
                  @update:model-value="setConditionValue(row.condition, 'min_bet', $event)"
                ></v-text-field>
              </v-col>
            </v-row>

            <v-row v-if="row.condition.type === 'blackjack_hands'" dense>
              <v-col cols="12" sm="6">
                <v-text-field
                  :disabled="isEditorDisabled()"
                  density="comfortable"
                  hint="0–100"
                  label="最低决策准确率（可选）"
                  max="100"
                  min="0"
                  :model-value="row.condition.min_accuracy"
                  persistent-hint
                  suffix="%"
                  type="number"
                  variant="outlined"
                  @update:model-value="setConditionValue(row.condition, 'min_accuracy', $event)"
                ></v-text-field>
              </v-col>
              <v-col cols="12" sm="6" class="d-flex align-center">
                <v-switch
                  color="primary"
                  :disabled="isEditorDisabled()"
                  hide-details
                  label="仅统计已结束的现金局"
                  :model-value="true"
                  readonly
                ></v-switch>
              </v-col>
            </v-row>

            <v-switch
              v-if="row.condition.type === 'wheel_spins'"
              color="primary"
              :disabled="isEditorDisabled()"
              hide-details
              label="仅统计付费参与（关闭后也计入免费参与）"
              :model-value="row.condition.paid_only"
              @update:model-value="setConditionValue(row.condition, 'paid_only', $event)"
            ></v-switch>

            <template v-if="supportsWindow(row.condition)">
              <v-select
                class="mt-3"
                :disabled="isEditorDisabled()"
                density="comfortable"
                item-title="label"
                item-value="value"
                :items="windowItems"
                label="时间范围"
                :model-value="windowKind(row.condition)"
                variant="outlined"
                @update:model-value="updateWindowKind(row.condition, $event)"
              ></v-select>
              <v-alert
                v-if="windowKind(row.condition) === 'pack'"
                class="mb-2"
                density="compact"
                type="info"
                variant="text"
              >
                “礼包开始后”只统计开始时间之后的活动，任务类礼包推荐使用此项。
              </v-alert>
              <v-text-field
                v-if="windowKind(row.condition) === 'days'"
                :disabled="isEditorDisabled()"
                density="comfortable"
                hint="只能填写 1–365 天"
                label="最近多少天"
                max="365"
                min="1"
                :model-value="row.condition.window.days"
                persistent-hint
                type="number"
                variant="outlined"
                @update:model-value="updateWindowDays(row.condition, $event)"
              ></v-text-field>
            </template>
            <v-alert
              v-else
              class="mt-3"
              density="compact"
              type="info"
              variant="text"
            >
              {{ row.condition.type === 'invitees' ? '邀请人数只支持历史累计。' : '累计观看时长只支持历史累计。' }}
            </v-alert>
          </template>
        </v-card-text>
      </v-card>
    </template>

    <div class="d-flex flex-wrap ga-2 mt-3">
      <v-btn
        color="primary"
        :disabled="isEditorDisabled()"
        prepend-icon="mdi-plus"
        variant="tonal"
        @click="addCondition"
      >
        添加条件
      </v-btn>
      <v-btn
        color="primary"
        :disabled="isEditorDisabled()"
        prepend-icon="mdi-set-center"
        variant="tonal"
        @click="addAnyOf"
      >
        添加“满足其一”组
      </v-btn>
    </div>
  </div>
</template>

<script>
import { resolveGiftPackUsers } from '../services/giftPackService'

const LEAF_CONDITION_TYPES = [
  { value: 'premium', label: 'Premium 状态' },
  { value: 'bound', label: '账号绑定' },
  { value: 'credits', label: '积分范围' },
  { value: 'badge', label: '持有勋章' },
  { value: 'claimed_pack', label: '已领取某礼包' },
  { value: 'wheel_spins', label: '大转盘局数' },
  { value: 'blackjack_hands', label: '21 点手数' },
  { value: 'treasure_issues', label: '夺宝参与期数' },
  { value: 'prediction_bets', label: '大预言家下注次数' },
  { value: 'auction_participations', label: '竞拍参与场数' },
  { value: 'tournament_entries', label: '锦标赛参赛次数' },
  { value: 'invitees', label: '邀请人数' },
  { value: 'watched_hours', label: '累计观看时长' }
]

const ALL_CONDITION_TYPES = [
  { value: 'user_list', label: '指定名单' },
  ...LEAF_CONDITION_TYPES
]

const WINDOWED_TYPES = [
  'wheel_spins',
  'blackjack_hands',
  'treasure_issues',
  'prediction_bets',
  'auction_participations',
  'tournament_entries'
]

const ALL_WINDOW_TYPES = ['invitees', 'watched_hours']

const INTEGER_COUNT_TYPES = [
  'wheel_spins',
  'blackjack_hands',
  'treasure_issues',
  'prediction_bets',
  'auction_participations',
  'tournament_entries',
  'invitees'
]

export default {
  name: 'GiftPackConditionEditor',
  props: {
    modelValue: {
      type: Array,
      default: () => []
    },
    mode: {
      type: String,
      default: 'requirements',
      validator: value => ['audience', 'requirements'].includes(value)
    },
    disabled: {
      type: Boolean,
      default: false
    },
    readonly: {
      type: Boolean,
      default: false
    }
  },
  emits: ['update:modelValue', 'validity-change', 'users-resolved'],
  data() {
    return {
      localConditions: [],
      keySeed: 0,
      windowItems: [
        { value: 'all', label: '历史累计' },
        { value: 'pack', label: '礼包开始后' },
        { value: 'days', label: '最近 N 天' }
      ],
      userListModeItems: [
        { value: 'include', label: '包含名单中的用户' },
        { value: 'exclude', label: '排除名单中的用户' }
      ],
      premiumStateItems: [
        { value: 'active', label: 'Premium 用户' },
        { value: 'none', label: '非 Premium 用户' }
      ],
      boundServiceItems: [
        { value: 'any', label: '任一媒体服务' },
        { value: 'plex', label: 'Plex' },
        { value: 'emby', label: 'Emby' }
      ]
    }
  },
  computed: {
    conditionRows() {
      const rows = []
      this.localConditions.forEach((condition, topIndex) => {
        if (condition.type === 'any_of') {
          rows.push({
            kind: 'group',
            condition,
            topIndex,
            key: condition._key
          })
          condition.items.forEach((item, itemIndex) => {
            rows.push({
              kind: 'leaf',
              condition: item,
              group: condition,
              topIndex,
              itemIndex,
              key: item._key
            })
          })
          return
        }
        rows.push({
          kind: 'leaf',
          condition,
          topIndex,
          group: null,
          key: condition._key
        })
      })
      return rows
    },
    validationErrors() {
      const errors = []
      this.localConditions.forEach((condition, index) => {
        this.validateCondition(condition, `条件 ${index + 1}`, errors, false)
      })
      return [...new Set(errors)]
    }
  },
  watch: {
    modelValue: {
      deep: true,
      immediate: true,
      handler(value) {
        this.syncFromModel(value)
      }
    },
    validationErrors: {
      deep: true,
      handler() {
        this.emitValidity()
      }
    }
  },
  methods: {
    isEditorDisabled() {
      return this.disabled || this.readonly
    },
    nextKey() {
      this.keySeed += 1
      return `gift-condition-${this.keySeed}`
    },
    createCondition(type) {
      const condition = { type, _key: this.nextKey() }
      switch (type) {
        case 'user_list':
          return Object.assign(condition, {
            mode: 'include',
            tg_ids: [],
            _userListText: '',
            _resolved: [],
            _unresolved: [],
            _resolutionState: 'empty',
            _resolutionError: ''
          })
        case 'premium':
          return Object.assign(condition, { state: 'active' })
        case 'bound':
          return Object.assign(condition, { service: 'any' })
        case 'credits':
          return Object.assign(condition, { min: null, max: null })
        case 'badge':
          return Object.assign(condition, { badge_id: null })
        case 'claimed_pack':
          return Object.assign(condition, { pack_id: null })
        case 'wheel_spins':
          return Object.assign(condition, {
            min: 1,
            window: { kind: 'all' },
            paid_only: true
          })
        case 'blackjack_hands':
          return Object.assign(condition, {
            min: 1,
            window: { kind: 'all' },
            min_bet: null,
            min_accuracy: null
          })
        case 'watched_hours':
          return Object.assign(condition, {
            min: 1,
            window: { kind: 'all' }
          })
        case 'invitees':
          return Object.assign(condition, {
            min: 1,
            window: { kind: 'all' }
          })
        default:
          return Object.assign(condition, {
            min: 1,
            window: { kind: 'all' }
          })
      }
    },
    hydrateCondition(raw) {
      const source = raw && typeof raw === 'object' ? raw : {}
      const condition = Object.assign(this.createCondition(source.type || 'premium'), source)
      condition._key = this.nextKey()

      if (condition.type === 'any_of') {
        condition.items = Array.isArray(source.items)
          ? source.items.map(item => this.hydrateCondition(item))
          : []
        return condition
      }

      if (condition.type === 'user_list') {
        const ids = Array.isArray(source.tg_ids) ? source.tg_ids : []
        condition.tg_ids = ids
        condition._userListText = ids.join('\n')
        condition._resolved = ids.map(id => ({
          token: String(id),
          tg_id: id,
          matched_by: 'tg_id',
          display_name: String(id)
        }))
        condition._unresolved = []
        condition._resolutionState = ids.length ? 'resolved' : 'empty'
        condition._resolutionError = ''
      }

      if (WINDOWED_TYPES.includes(condition.type) && !condition.window) {
        condition.window = { kind: 'all' }
      }
      if (ALL_WINDOW_TYPES.includes(condition.type)) {
        condition.window = { kind: 'all' }
      }
      return condition
    },
    hydrateConditions(value) {
      return (Array.isArray(value) ? value : []).map(condition => this.hydrateCondition(condition))
    },
    serializeCondition(condition) {
      if (!condition || typeof condition !== 'object') return {}
      if (condition.type === 'any_of') {
        return {
          type: 'any_of',
          items: (condition.items || []).map(item => this.serializeCondition(item))
        }
      }

      const payload = {}
      Object.keys(condition).forEach(key => {
        if (key.startsWith('_')) return
        const value = condition[key]
        if (value === undefined || value === null || value === '') return
        if (key === 'window' && value && typeof value === 'object') {
          payload.window = value.kind === 'days'
            ? { kind: 'days', days: Number(value.days) }
            : { kind: value.kind || 'all' }
          return
        }
        if (key === 'tg_ids') {
          payload.tg_ids = Array.isArray(value)
            ? [...new Set(value.map(Number).filter(Number.isFinite))]
            : []
          return
        }
        payload[key] = value
      })
      return payload
    },
    serializeConditions(conditions) {
      return (Array.isArray(conditions) ? conditions : []).map(condition => this.serializeCondition(condition))
    },
    syncFromModel(value) {
      const incoming = Array.isArray(value) ? value : []
      const current = this.serializeConditions(this.localConditions)
      if (JSON.stringify(current) === JSON.stringify(incoming)) return
      this.localConditions = this.hydrateConditions(incoming)
      this.emitValidity()
    },
    emitUpdate() {
      this.$emit('update:modelValue', this.serializeConditions(this.localConditions))
      this.emitValidity()
    },
    emitValidity() {
      this.$emit('validity-change', {
        valid: this.validationErrors.length === 0,
        errors: this.validationErrors
      })
    },
    conditionTypeItems(row) {
      if (row.group) return LEAF_CONDITION_TYPES
      return this.mode === 'audience' ? ALL_CONDITION_TYPES : LEAF_CONDITION_TYPES
    },
    addCondition() {
      this.localConditions.push(this.createCondition(this.mode === 'audience' ? 'premium' : 'premium'))
      this.emitUpdate()
    },
    addAnyOf() {
      const group = this.createCondition('any_of')
      group.items = [
        this.createCondition('wheel_spins'),
        this.createCondition('blackjack_hands')
      ]
      this.localConditions.push(group)
      this.emitUpdate()
    },
    removeGroup(row) {
      this.localConditions.splice(row.topIndex, 1)
      this.emitUpdate()
    },
    addGroupItem(row) {
      row.group.items.push(this.createCondition('wheel_spins'))
      this.emitUpdate()
    },
    removeCondition(row) {
      if (row.group) {
        if (row.group.items.length <= 2) return
        row.group.items.splice(row.itemIndex, 1)
      } else {
        this.localConditions.splice(row.topIndex, 1)
      }
      this.emitUpdate()
    },
    replaceConditionType(row, type) {
      if (!type || type === row.condition.type) return
      const replacement = this.createCondition(type)
      if (row.group) {
        row.group.items.splice(row.itemIndex, 1, replacement)
      } else {
        this.localConditions.splice(row.topIndex, 1, replacement)
      }
      this.emitUpdate()
    },
    setConditionValue(condition, field, value) {
      const numericFields = [
        'min',
        'max',
        'badge_id',
        'pack_id',
        'min_bet',
        'min_accuracy'
      ]
      if (numericFields.includes(field)) {
        if (value === '' || value === null || value === undefined) {
          condition[field] = null
        } else {
          const number = Number(value)
          condition[field] = Number.isFinite(number) ? number : null
        }
      } else {
        condition[field] = value
      }
      this.emitUpdate()
    },
    updateWindowKind(condition, kind) {
      condition.window = kind === 'days'
        ? { kind: 'days', days: 7 }
        : { kind }
      this.emitUpdate()
    },
    updateWindowDays(condition, value) {
      const days = Number(value)
      condition.window = {
        kind: 'days',
        days: Number.isFinite(days) ? days : null
      }
      this.emitUpdate()
    },
    windowKind(condition) {
      return condition.window?.kind || 'all'
    },
    supportsWindow(condition) {
      return WINDOWED_TYPES.includes(condition.type)
    },
    updateUserListText(condition, value) {
      condition._userListText = value || ''
      // Invalidate any in-flight resolution of the previous textarea contents.
      condition._resolveRequestId = (condition._resolveRequestId || 0) + 1
      condition._resolutionError = ''
      condition._unresolved = []
      if (!condition._userListText.trim()) {
        condition.tg_ids = []
        condition._resolved = []
        condition._resolutionState = 'empty'
      } else {
        // Clear previous IDs so stale users cannot be saved for newly pasted text.
        condition.tg_ids = []
        condition._resolved = []
        condition._resolutionState = 'dirty'
      }
      this.emitUpdate()
    },
    async resolveUserList(row) {
      const condition = row.condition
      const text = (condition._userListText || '').trim()
      if (!text) {
        condition.tg_ids = []
        condition._resolved = []
        condition._unresolved = []
        condition._resolutionError = ''
        condition._resolutionState = 'empty'
        this.emitUpdate()
        return
      }

      const requestId = (condition._resolveRequestId || 0) + 1
      condition._resolveRequestId = requestId
      condition._resolutionState = 'loading'
      condition._resolutionError = ''
      condition._unresolved = []
      this.emitUpdate()

      try {
        const response = await resolveGiftPackUsers(text)
        if (condition._resolveRequestId !== requestId || (condition._userListText || '').trim() !== text) return
        const result = response?.data || response || {}
        const resolved = Array.isArray(result.resolved) ? result.resolved : []
        const unresolved = Array.isArray(result.unresolved) ? result.unresolved : []
        const ids = [...new Set(
          resolved
            .map(item => Number(item.tg_id))
            .filter(id => Number.isFinite(id))
        )]

        condition.tg_ids = ids
        condition._resolved = resolved
        condition._unresolved = unresolved
        condition._resolutionState = unresolved.length ? 'partial' : 'resolved'
        this.$emit('users-resolved', { resolved, unresolved, condition })
        this.emitUpdate()
      } catch (error) {
        if (condition._resolveRequestId !== requestId || (condition._userListText || '').trim() !== text) return
        condition.tg_ids = []
        condition._resolved = []
        condition._unresolved = []
        condition._resolutionState = 'failed'
        condition._resolutionError = this.resolveErrorMessage(error)
        this.emitUpdate()
      }
    },
    resolveErrorMessage(error) {
      return error?.response?.data?.detail || error?.message || '服务端未返回解析结果'
    },
    matchedByLabel(value) {
      const labels = {
        tg_id: 'Telegram ID',
        plex: 'Plex',
        emby: 'Emby',
        telegram: 'Telegram 用户缓存'
      }
      return labels[value] || value || '用户记录'
    },
    validateCondition(condition, path, errors, insideGroup) {
      if (!condition || !condition.type) {
        errors.push(`${path}：缺少条件类型`)
        return
      }

      if (condition.type === 'any_of') {
        if (insideGroup) errors.push(`${path}：不允许嵌套“满足其一”组`)
        if (!Array.isArray(condition.items) || condition.items.length < 2) {
          errors.push(`${path}：至少需要两个组内条件`)
        }
        const items = condition.items || []
        items.forEach((item, index) => {
          this.validateCondition(item, `${path}第 ${index + 1} 项`, errors, true)
        })
        return
      }

      if (condition.type === 'user_list') {
        if (this.mode !== 'audience' || insideGroup) {
          errors.push(`${path}：指定名单只能放在受众顶层`)
        }
        if (!['include', 'exclude'].includes(condition.mode)) {
          errors.push(`${path}：名单模式无效`)
        }
        if (!Array.isArray(condition.tg_ids) || condition.tg_ids.length > 5000) {
          errors.push(`${path}：名单最多保存 5000 个 Telegram ID`)
        } else if (condition.tg_ids.some(id => !this.isPositiveInteger(id))) {
          errors.push(`${path}：名单只能包含正整数 Telegram ID`)
        }
        if (condition._resolutionState === 'dirty' || condition._resolutionState === 'loading') {
          errors.push(`${path}：名单尚未完成解析`)
        }
        if (condition._resolutionState === 'failed') {
          errors.push(`${path}：名单解析失败，请重试`)
        }
        if (condition._unresolved.length) {
          errors.push(`${path}：仍有 ${condition._unresolved.length} 个标识无法解析`)
        }
        return
      }

      if (condition.type === 'premium') {
        if (!['active', 'none'].includes(condition.state)) {
          errors.push(`${path}：Premium 状态无效`)
        }
        return
      }

      if (condition.type === 'bound') {
        if (!['any', 'plex', 'emby'].includes(condition.service)) {
          errors.push(`${path}：绑定服务无效`)
        }
        return
      }

      if (condition.type === 'credits') {
        const min = this.numberOrNull(condition.min)
        const max = this.numberOrNull(condition.max)
        if (min === null && max === null) errors.push(`${path}：至少填写最低或最高积分`)
        if (min !== null && min < 0) errors.push(`${path}：最低积分不能为负数`)
        if (max !== null && max < 0) errors.push(`${path}：最高积分不能为负数`)
        if (min !== null && max !== null && min > max) errors.push(`${path}：最低积分不能超过最高积分`)
        return
      }

      if (condition.type === 'badge' && !this.isPositiveInteger(condition.badge_id)) {
        errors.push(`${path}：勋章 ID 必须是正整数`)
      }
      if (condition.type === 'claimed_pack' && !this.isPositiveInteger(condition.pack_id)) {
        errors.push(`${path}：礼包 ID 必须是正整数`)
      }

      if (['badge', 'claimed_pack'].includes(condition.type)) return

      if (INTEGER_COUNT_TYPES.includes(condition.type)) {
        if (!this.isPositiveInteger(condition.min)) {
          errors.push(`${path}：目标值必须是大于 0 的整数`)
        }
      } else if (!this.isPositiveNumber(condition.min)) {
        errors.push(`${path}：目标值必须大于 0`)
      }
      if (condition.type === 'blackjack_hands') {
        if (condition.min_bet !== null && condition.min_bet !== undefined && !this.isPositiveNumber(condition.min_bet)) {
          errors.push(`${path}：最低注额必须大于 0`)
        }
        const accuracy = this.numberOrNull(condition.min_accuracy)
        if (accuracy !== null && (accuracy < 0 || accuracy > 100)) {
          errors.push(`${path}：准确率必须在 0–100 之间`)
        }
      }

      if (ALL_WINDOW_TYPES.includes(condition.type)) {
        if (this.windowKind(condition) !== 'all') {
          errors.push(`${path}：该条件只支持历史累计`)
        }
      } else if (WINDOWED_TYPES.includes(condition.type)) {
        const kind = this.windowKind(condition)
        if (!['all', 'pack', 'days'].includes(kind)) {
          errors.push(`${path}：时间范围无效`)
        }
        if (kind === 'days') {
          const days = Number(condition.window?.days)
          if (!Number.isInteger(days) || days < 1 || days > 365) {
            errors.push(`${path}：最近 N 天必须是 1–365 的整数`)
          }
        }
      }
    },
    numberOrNull(value) {
      if (value === null || value === undefined || value === '') return null
      const number = Number(value)
      return Number.isFinite(number) ? number : null
    },
    isPositiveNumber(value) {
      const number = this.numberOrNull(value)
      return number !== null && number > 0
    },
    isPositiveInteger(value) {
      const number = this.numberOrNull(value)
      return number !== null && Number.isInteger(number) && number > 0
    }
  }
}
</script>

<style scoped>
.gift-pack-condition-editor {
  width: 100%;
}

.empty-conditions {
  border: 1px dashed rgba(var(--v-theme-on-surface), 0.28);
  border-radius: 8px;
  color: rgba(var(--v-theme-on-surface), 0.68);
  padding: 12px 16px;
}

.condition-card--nested {
  margin-left: 20px;
  border-left: 3px solid rgb(var(--v-theme-primary));
}

.condition-index {
  letter-spacing: 0.02em;
}

.condition-errors,
.unresolved-users {
  margin: 0;
  padding-left: 20px;
}

.resolved-users {
  border-top: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  padding-top: 10px;
}

@media (max-width: 600px) {
  .condition-card--nested {
    margin-left: 8px;
  }

  .condition-group-header .v-btn {
    min-width: 0;
    padding: 0 8px;
  }
}
</style>
