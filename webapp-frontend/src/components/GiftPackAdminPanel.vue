<template>
  <div class="admin-panel">
    <v-container fluid class="px-2 px-sm-4">
      <v-row>
        <v-col cols="12">
          <h1 class="text-h5 text-sm-h4 mb-4 mb-sm-6">🎁 礼包管理面板</h1>
        </v-col>
      </v-row>

      <!-- 概览统计 -->
      <v-row class="mb-1">
        <v-col cols="6" sm="6" md="3">
          <v-card class="stat-card pa-3 pa-sm-4" flat>
            <div class="text-caption text-medium-emphasis">礼包总数</div>
            <div class="text-h5 text-sm-h4 font-weight-bold">{{ packs.length }}</div>
          </v-card>
        </v-col>
        <v-col cols="6" sm="6" md="3">
          <v-card class="stat-card pa-3 pa-sm-4" flat>
            <div class="text-caption text-medium-emphasis">进行中</div>
            <div class="text-h5 text-sm-h4 font-weight-bold text-success">{{ overview.active }}</div>
          </v-card>
        </v-col>
        <v-col cols="6" sm="6" md="3">
          <v-card class="stat-card pa-3 pa-sm-4" flat>
            <div class="text-caption text-medium-emphasis">未开始</div>
            <div class="text-h5 text-sm-h4 font-weight-bold text-warning">{{ overview.upcoming }}</div>
          </v-card>
        </v-col>
        <v-col cols="6" sm="6" md="3">
          <v-card class="stat-card pa-3 pa-sm-4" flat>
            <div class="text-caption text-medium-emphasis">累计领取</div>
            <div class="text-h5 text-sm-h4 font-weight-bold text-info">{{ overview.claims }}</div>
          </v-card>
        </v-col>
      </v-row>

      <!-- 操作栏 -->
      <v-row>
        <v-col cols="12">
          <v-card class="admin-card" elevation="6" rounded="xl">
            <v-card-title class="d-flex align-center pa-3 pa-sm-4 admin-card-header">
              <v-avatar size="32" class="mr-2" color="rgba(255,255,255,0.2)" variant="flat">
                <v-icon size="18" color="white">mdi-gift</v-icon>
              </v-avatar>
              <span class="text-body-2 text-sm-body-1 font-weight-bold">礼包列表</span>
              <v-spacer></v-spacer>
              <v-btn
                size="small"
                variant="text"
                color="white"
                :loading="loading"
                @click="loadPacks"
              >
                <v-icon size="18" class="mr-1">mdi-refresh</v-icon>
                刷新
              </v-btn>
            </v-card-title>

            <v-card-text class="pa-3 pa-sm-4">
              <v-btn color="primary" block variant="elevated" @click="openCreate">
                <v-icon size="18" class="mr-1">mdi-plus</v-icon>
                新建礼包
              </v-btn>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <!-- 加载 / 空态 -->
      <v-row v-if="loading">
        <v-col cols="12" class="text-center py-10">
          <v-progress-circular indeterminate color="primary" size="48" />
          <div class="mt-3 text-medium-emphasis">加载礼包中...</div>
        </v-col>
      </v-row>

      <v-row v-else-if="!packs.length">
        <v-col cols="12">
          <v-card class="config-card" elevation="4" rounded="xl">
            <v-card-text class="text-center py-10">
              <v-icon size="64" color="grey-lighten-1">mdi-gift-outline</v-icon>
              <div class="text-body-1 mt-4 text-medium-emphasis">还没有创建过礼包</div>
              <div class="text-caption mt-1 text-medium-emphasis">
                点击上方「新建礼包」发布第一个运营福利
              </div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <!-- 礼包卡片 -->
      <v-row v-else>
        <v-col v-for="pack in packs" :key="pack.id" cols="12" md="6">
          <v-card class="config-card" elevation="6" rounded="xl">
            <v-card-title
              class="d-flex align-center pa-3 pa-sm-4 config-card-header"
              :class="`config-card-header--${pack.lifecycle}`"
            >
              <v-avatar size="32" class="mr-2" color="rgba(255,255,255,0.2)" variant="flat">
                <v-icon size="18" color="white">
                  {{ pack.lifecycle === 'ended' ? 'mdi-gift-off-outline' : 'mdi-gift' }}
                </v-icon>
              </v-avatar>
              <span class="text-body-2 text-sm-body-1 font-weight-bold pack-title">
                {{ pack.title }}
              </span>
              <v-spacer></v-spacer>
              <v-chip size="x-small" color="white" variant="flat" class="pack-chip">
                {{ lifecycleText(pack.lifecycle) }}
              </v-chip>
            </v-card-title>

            <v-card-text class="pa-3 pa-sm-4">
              <p v-if="pack.description" class="text-body-2 text-medium-emphasis mb-3">
                {{ pack.description }}
              </p>

              <!-- 奖励内容 -->
              <div class="config-item mb-2">
                <div class="config-label">
                  <v-icon size="16" class="mr-1" color="pink-darken-1">mdi-package-variant</v-icon>
                  礼包内容
                </div>
                <div class="d-flex flex-wrap ga-1 mt-1">
                  <v-chip
                    v-for="(reward, idx) in pack.rewards"
                    :key="idx"
                    size="small"
                    variant="flat"
                    class="config-chip"
                    :color="reward.type === 'credits' ? 'amber-darken-2' : 'deep-purple'"
                  >
                    {{ rewardLabel(reward) }}
                  </v-chip>
                </div>
              </div>

              <!-- 时间窗 -->
              <div class="config-item mb-2">
                <div class="config-label">
                  <v-icon size="16" class="mr-1" color="primary">mdi-clock-outline</v-icon>
                  时间窗
                  <v-chip size="x-small" variant="tonal" color="primary" class="ml-1">
                    {{ TZ_LABEL }}
                  </v-chip>
                </div>
                <div class="config-value">
                  {{ formatServerTime(pack.start_at) }} ~ {{ formatServerTime(pack.end_at) }}
                </div>
              </div>

              <!-- 领取进度 -->
              <div class="config-item mb-2">
                <div class="config-label">
                  <v-icon size="16" class="mr-1" color="info">mdi-account-multiple-check</v-icon>
                  领取进度
                </div>
                <template v-if="pack.total_quantity">
                  <div class="config-value">
                    <span class="config-number">{{ pack.claimed_count }}</span>
                    / {{ pack.total_quantity }} 份，剩余 {{ pack.remaining }}
                  </div>
                  <v-progress-linear
                    class="mt-2"
                    :model-value="claimPercent(pack)"
                    :color="pack.remaining === 0 ? 'error' : 'pink-darken-1'"
                    height="8"
                    rounded
                  />
                </template>
                <div v-else class="config-value">
                  不限量 · 已领 <span class="config-number">{{ pack.claimed_count }}</span> 份
                </div>
              </div>

              <!-- 资格与提醒 -->
              <div class="config-item">
                <div class="config-label">
                  <v-icon size="16" class="mr-1" color="deep-purple">mdi-account-check-outline</v-icon>
                  资格与提醒
                </div>
                <div class="config-value">
                  {{ eligibilitySummary(pack) || '所有人可领' }} · 提醒上限
                  {{ pack.max_prompt_count }} 次/人
                </div>
              </div>

              <v-alert
                v-if="!pack.is_enabled"
                type="warning"
                variant="tonal"
                density="compact"
                class="mt-3"
              >
                已停用，用户不可领取、不再触发提醒
              </v-alert>
            </v-card-text>

            <v-divider />

            <v-card-actions class="pa-2 pa-sm-3 flex-wrap">
              <v-btn size="small" variant="text" class="config-btn" @click="openEdit(pack)">
                <v-icon size="16" class="mr-1">mdi-pencil</v-icon>编辑
              </v-btn>
              <v-btn
                size="small"
                variant="text"
                class="config-btn"
                :color="pack.is_enabled ? 'warning' : 'success'"
                :loading="togglingId === pack.id"
                @click="toggleEnabled(pack)"
              >
                <v-icon size="16" class="mr-1">
                  {{ pack.is_enabled ? 'mdi-pause' : 'mdi-play' }}
                </v-icon>
                {{ pack.is_enabled ? '停用' : '启用' }}
              </v-btn>
              <v-btn size="small" variant="text" class="config-btn" @click="openStats(pack)">
                <v-icon size="16" class="mr-1">mdi-chart-bar</v-icon>统计
              </v-btn>
              <v-btn size="small" variant="text" class="config-btn" @click="openRecords(pack)">
                <v-icon size="16" class="mr-1">mdi-format-list-bulleted</v-icon>记录
              </v-btn>
              <v-spacer></v-spacer>
              <!-- 已有领取记录的礼包不提供删除入口，只能停用 -->
              <v-btn
                v-if="pack.can_delete"
                size="small"
                variant="text"
                color="error"
                class="config-btn"
                :loading="deletingId === pack.id"
                @click="confirmDelete(pack)"
              >
                <v-icon size="16" class="mr-1">mdi-delete-outline</v-icon>删除
              </v-btn>
              <span v-else class="text-caption text-medium-emphasis mr-2">
                已有人领取，只能停用
              </span>
            </v-card-actions>
          </v-card>
        </v-col>
      </v-row>
    </v-container>

    <!-- 创建 / 编辑 -->
    <v-dialog v-model="formDialog" max-width="760" persistent scrollable>
      <v-card class="dialog-card" rounded="xl">
        <v-card-title class="dialog-header pa-4 d-flex align-center">
          <v-avatar size="32" class="mr-2" color="rgba(255,255,255,0.2)" variant="flat">
            <v-icon size="18" color="white">{{ editingId ? 'mdi-pencil' : 'mdi-plus' }}</v-icon>
          </v-avatar>
          <span class="font-weight-bold">{{ editingId ? '编辑礼包' : '新建礼包' }}</span>
        </v-card-title>

        <v-card-text class="pa-4 pa-sm-5">
          <v-card class="setting-card pa-3 pa-sm-4 mb-4" flat>
            <v-text-field
              v-model="form.title"
              label="标题"
              variant="outlined"
              density="comfortable"
              :maxlength="200"
              class="mb-2"
            />
            <v-textarea
              v-model="form.description"
              label="描述（可选）"
              variant="outlined"
              density="comfortable"
              rows="2"
              :maxlength="2000"
              hide-details
            />
          </v-card>

          <!-- 奖励项 -->
          <v-card class="setting-card pa-3 pa-sm-4 mb-4" flat>
            <div class="d-flex align-center mb-3">
              <v-icon class="mr-2" size="18" color="pink-darken-1">mdi-package-variant</v-icon>
              <span class="text-subtitle-2 font-weight-bold">
                礼包内容（{{ form.rewards.length }}/{{ REWARD_TYPES.length }}）
              </span>
              <v-spacer></v-spacer>
              <v-btn
                size="small"
                variant="tonal"
                color="pink-darken-1"
                :disabled="form.rewards.length >= REWARD_TYPES.length"
                @click="addReward"
              >
                <v-icon size="16" class="mr-1">mdi-plus</v-icon>添加
              </v-btn>
            </div>

            <v-alert
              v-if="!form.rewards.length"
              type="warning"
              variant="tonal"
              density="compact"
              class="mb-2"
            >
              至少需要配置一项奖励
            </v-alert>

            <v-card
              v-for="(reward, index) in form.rewards"
              :key="index"
              class="reward-row pa-3 mb-2"
              flat
            >
              <div class="d-flex align-center ga-3">
                <v-avatar size="28" :color="rewardColor(reward.type)" variant="flat">
                  <span class="text-white text-caption font-weight-bold">{{ index + 1 }}</span>
                </v-avatar>
                <v-select
                  v-model="reward.type"
                  :items="availableTypes(index)"
                  item-title="label"
                  item-value="value"
                  label="类型"
                  variant="outlined"
                  density="compact"
                  hide-details
                  style="max-width: 180px"
                  @update:model-value="onRewardTypeChange(reward)"
                />
                <!-- 按类型切换参数字段 -->
                <v-text-field
                  v-if="reward.type === 'credits'"
                  v-model.number="reward.amount"
                  label="积分数量"
                  type="number"
                  variant="outlined"
                  density="compact"
                  hide-details
                  min="1"
                />
                <v-text-field
                  v-else-if="reward.type === 'premium_days'"
                  v-model.number="reward.days"
                  label="Premium 天数"
                  type="number"
                  variant="outlined"
                  density="compact"
                  hide-details
                  min="1"
                />
                <v-btn icon size="small" color="error" variant="text" @click="removeReward(index)">
                  <v-icon>mdi-delete-outline</v-icon>
                </v-btn>
              </div>
            </v-card>

            <v-alert
              v-if="hasPremiumReward"
              type="info"
              variant="tonal"
              density="compact"
              class="mt-2"
            >
              含 Premium 天数奖励：会发放给用户<b>所有已绑定</b>的媒体服务，且系统已自动加上「至少绑定一个媒体账号」的领取资格。
            </v-alert>
          </v-card>

          <!-- 时间窗 -->
          <v-card class="setting-card pa-3 pa-sm-4 mb-4" flat>
            <div class="d-flex align-center mb-1">
              <v-icon class="mr-2" size="18" color="primary">mdi-clock-outline</v-icon>
              <span class="text-subtitle-2 font-weight-bold">时间窗</span>
              <v-chip size="x-small" variant="flat" color="primary" class="ml-2">
                {{ TZ_LABEL }}
              </v-chip>
            </div>
            <div class="text-caption text-medium-emphasis mb-3">
              按服务端时区录入，与 TG 群公告口径一致；用户侧会按各自浏览器时区展示。
            </div>
            <v-row dense>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model="form.startLocal"
                  label="开始时间"
                  type="datetime-local"
                  variant="outlined"
                  density="comfortable"
                  :suffix="TZ_LABEL"
                  hide-details
                />
              </v-col>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model="form.endLocal"
                  label="结束时间"
                  type="datetime-local"
                  variant="outlined"
                  density="comfortable"
                  :suffix="TZ_LABEL"
                  hide-details
                />
              </v-col>
            </v-row>
          </v-card>

          <!-- 限量与提醒 -->
          <v-card class="setting-card pa-3 pa-sm-4 mb-4" flat>
            <div class="d-flex align-center mb-3">
              <v-icon class="mr-2" size="18" color="info">mdi-counter</v-icon>
              <span class="text-subtitle-2 font-weight-bold">限量与提醒</span>
            </div>
            <v-row dense>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model.number="form.total_quantity"
                  label="限量份数（留空 = 不限量）"
                  type="number"
                  variant="outlined"
                  density="comfortable"
                  min="1"
                  clearable
                  hide-details
                />
              </v-col>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model.number="form.max_prompt_count"
                  label="提醒次数上限（每人）"
                  type="number"
                  variant="outlined"
                  density="comfortable"
                  min="1"
                  max="100"
                  hide-details
                />
              </v-col>
            </v-row>
            <v-switch
              v-model="form.is_enabled"
              label="启用礼包"
              color="success"
              density="compact"
              hide-details
              class="mt-2"
            />
          </v-card>

          <!-- 领取资格 -->
          <v-card class="setting-card pa-3 pa-sm-4" flat>
            <div class="d-flex align-center mb-1">
              <v-icon class="mr-2" size="18" color="deep-purple">mdi-account-check-outline</v-icon>
              <span class="text-subtitle-2 font-weight-bold">领取资格</span>
            </div>
            <div class="text-caption text-medium-emphasis mb-3">
              全部留空 = 所有人可领
            </div>
            <v-row dense>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model.number="form.min_credits"
                  label="最低积分"
                  type="number"
                  variant="outlined"
                  density="comfortable"
                  min="0"
                  clearable
                  hide-details
                />
              </v-col>
              <v-col cols="12" md="6">
                <v-select
                  v-model="form.require_binding"
                  :items="BINDING_OPTIONS"
                  item-title="label"
                  item-value="value"
                  label="要求绑定媒体账号"
                  variant="outlined"
                  density="comfortable"
                  :hint="hasPremiumReward && !form.require_binding ? '含 Premium 奖励，将自动按「不限服务」生效' : ''"
                  persistent-hint
                />
              </v-col>
            </v-row>
            <v-switch
              v-model="form.require_premium"
              label="要求 Premium 会员身份"
              color="deep-purple"
              density="compact"
              hide-details
              class="mt-2"
            />
          </v-card>
        </v-card-text>

        <v-divider />
        <v-card-actions class="pa-3 pa-sm-4">
          <v-spacer></v-spacer>
          <v-btn variant="outlined" @click="formDialog = false">取消</v-btn>
          <v-btn color="primary" variant="elevated" :loading="saving" @click="save">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 统计 -->
    <v-dialog v-model="statsDialog" max-width="520">
      <v-card v-if="stats" class="dialog-card" rounded="xl">
        <v-card-title class="result-card-header pa-4 d-flex align-center">
          <v-avatar size="32" class="mr-2" color="rgba(255,255,255,0.2)" variant="flat">
            <v-icon size="18" color="white">mdi-chart-bar</v-icon>
          </v-avatar>
          <span class="font-weight-bold pack-title">{{ stats.title }}</span>
        </v-card-title>

        <v-card-text class="pa-4">
          <v-row dense class="mb-2">
            <v-col cols="4">
              <v-card class="stat-card pa-3 text-center" flat>
                <div class="text-h6 font-weight-bold">{{ stats.claimed_users }}</div>
                <div class="text-caption text-medium-emphasis">领取人数</div>
              </v-card>
            </v-col>
            <v-col cols="4">
              <v-card class="stat-card pa-3 text-center" flat>
                <div class="text-h6 font-weight-bold">{{ stats.prompted_users }}</div>
                <div class="text-caption text-medium-emphasis">被提醒人数</div>
              </v-card>
            </v-col>
            <v-col cols="4">
              <v-card class="stat-card pa-3 text-center" flat>
                <div class="text-h6 font-weight-bold">
                  {{ stats.total_quantity ? stats.remaining : '∞' }}
                </div>
                <div class="text-caption text-medium-emphasis">剩余份数</div>
              </v-card>
            </v-col>
          </v-row>

          <div class="text-subtitle-2 font-weight-bold mt-4 mb-2">奖励发放总量</div>
          <div v-if="!stats.reward_totals.length" class="text-body-2 text-medium-emphasis">
            暂无发放记录
          </div>
          <div
            v-for="(item, idx) in stats.reward_totals"
            :key="idx"
            class="config-item mb-2"
          >
            <div class="d-flex justify-space-between align-center">
              <span class="config-label">{{ item.label }}</span>
              <span class="config-number">{{ item.total }}</span>
            </div>
            <div v-if="item.skipped_lifetime" class="text-caption text-medium-emphasis mt-1">
              {{ item.grants }} 次发放，{{ item.skipped_lifetime }} 次因永久会员跳过
            </div>
          </div>
        </v-card-text>

        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer></v-spacer>
          <v-btn variant="outlined" @click="statsDialog = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 领取记录 -->
    <v-dialog v-model="recordsDialog" max-width="680" scrollable>
      <v-card class="dialog-card" rounded="xl">
        <v-card-title class="preview-card-header pa-4 d-flex align-center">
          <v-avatar size="32" class="mr-2" color="rgba(255,255,255,0.2)" variant="flat">
            <v-icon size="18" color="white">mdi-format-list-bulleted</v-icon>
          </v-avatar>
          <span class="font-weight-bold">领取记录</span>
          <v-spacer></v-spacer>
          <v-chip size="x-small" color="white" variant="flat">共 {{ recordsTotal }} 条</v-chip>
        </v-card-title>

        <v-card-text class="pa-3 pa-sm-4" style="max-height: 60vh">
          <div v-if="recordsLoading" class="text-center py-8">
            <v-progress-circular indeterminate color="primary" size="36" />
          </div>
          <div v-else-if="!records.length" class="text-center py-10">
            <v-icon size="48" color="grey-lighten-1">mdi-inbox-outline</v-icon>
            <div class="text-body-2 mt-3 text-medium-emphasis">暂无领取记录</div>
          </div>
          <v-card
            v-for="(record, idx) in records"
            v-else
            :key="idx"
            class="setting-card pa-3 mb-2"
            flat
          >
            <div class="d-flex align-center justify-space-between">
              <span class="text-body-2 font-weight-medium">
                {{ record.tg_username || record.tg_id }}
              </span>
              <span class="text-caption text-medium-emphasis">
                {{ formatServerTime(record.claimed_at) }}
              </span>
            </div>
            <div class="d-flex flex-wrap ga-1 mt-2">
              <v-chip
                v-for="(item, i) in record.reward_snapshot || []"
                :key="i"
                size="x-small"
                variant="tonal"
                :color="item.skipped ? 'grey' : rewardColor(item.type)"
              >
                {{ snapshotText(item) }}
              </v-chip>
            </div>
          </v-card>
        </v-card-text>

        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer></v-spacer>
          <v-btn variant="outlined" @click="recordsDialog = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar" :color="snackbarColor" timeout="3000">
      {{ snackbarText }}
    </v-snackbar>
  </div>
</template>

<script>
import {
  adminListGiftPacks,
  adminCreateGiftPack,
  adminUpdateGiftPack,
  adminSetGiftPackEnabled,
  adminDeleteGiftPack,
  adminGetGiftPackStats,
  adminGetGiftPackRecords
} from '@/services/giftPackService'

// 服务端时区固定为 UTC+8（见 src/app/config.py 的 settings.TZ）。
// 管理端按此时区录入与展示，保证后台配置与对外公告口径一致。
const SERVER_TZ_OFFSET_MINUTES = 8 * 60

const REWARD_TYPES = [
  { value: 'credits', label: '积分' },
  { value: 'premium_days', label: 'Premium 天数' }
]

const BINDING_OPTIONS = [
  { value: null, label: '不要求' },
  { value: 'any', label: '不限服务（Plex 或 Emby）' },
  { value: 'plex', label: '仅 Plex' },
  { value: 'emby', label: '仅 Emby' }
]

function emptyForm() {
  return {
    title: '',
    description: '',
    rewards: [{ type: 'credits', amount: 100 }],
    startLocal: '',
    endLocal: '',
    total_quantity: null,
    max_prompt_count: 3,
    is_enabled: true,
    min_credits: null,
    require_premium: false,
    require_binding: null
  }
}

export default {
  name: 'GiftPackAdminPanel',
  emits: ['changed'],
  data() {
    return {
      REWARD_TYPES,
      BINDING_OPTIONS,
      TZ_LABEL: 'UTC+8',

      loading: false,
      packs: [],

      formDialog: false,
      editingId: null,
      saving: false,
      form: emptyForm(),

      togglingId: null,
      deletingId: null,

      statsDialog: false,
      stats: null,

      recordsDialog: false,
      recordsLoading: false,
      records: [],
      recordsTotal: 0,

      snackbar: false,
      snackbarText: '',
      snackbarColor: 'success'
    }
  },
  computed: {
    hasPremiumReward() {
      return this.form.rewards.some(r => r.type === 'premium_days')
    },
    overview() {
      return {
        active: this.packs.filter(p => p.lifecycle === 'active' && p.is_enabled).length,
        upcoming: this.packs.filter(p => p.lifecycle === 'upcoming').length,
        claims: this.packs.reduce((sum, p) => sum + (p.claimed_count || 0), 0)
      }
    }
  },
  mounted() {
    this.loadPacks()
  },
  methods: {
    toast(text, color = 'success') {
      const tg = window.Telegram?.WebApp
      const msg = String(text || '')

      // TG 环境优先用原生弹窗，更贴近小程序体验；非 TG 环境退回 snackbar
      if (tg) {
        if (color === 'success' && tg.showPopup) {
          tg.showPopup({ title: '提示', message: msg, buttons: [{ type: 'ok', text: '好的' }] })
          return
        }
        if (tg.showAlert) {
          tg.showAlert(msg)
          return
        }
      }

      this.snackbarText = msg
      this.snackbarColor = color
      this.snackbar = true
    },

    // ===== 时间：epoch 秒 <-> 服务端时区的 datetime-local 字符串 =====
    tsToServerLocal(ts) {
      if (!ts) return ''
      const d = new Date((Number(ts) + SERVER_TZ_OFFSET_MINUTES * 60) * 1000)
      return d.toISOString().slice(0, 16)
    },
    serverLocalToTs(value) {
      if (!value) return null
      // 输入被视为服务端时区的墙上时间，减去偏移得到 UTC 时间戳
      const asUtc = Date.parse(`${value}:00Z`)
      if (Number.isNaN(asUtc)) return null
      return Math.floor(asUtc / 1000) - SERVER_TZ_OFFSET_MINUTES * 60
    },
    formatServerTime(ts) {
      if (!ts) return '-'
      return this.tsToServerLocal(ts).replace('T', ' ')
    },

    rewardLabel(reward) {
      if (reward.type === 'credits') return `${reward.amount} 积分`
      if (reward.type === 'premium_days') return `${reward.days} 天 Premium`
      return reward.type
    },
    rewardColor(type) {
      return type === 'credits' ? 'amber-darken-2' : 'deep-purple'
    },
    snapshotText(item) {
      if (item.type === 'premium_days') {
        const service = (item.service || '').toUpperCase()
        return item.skipped ? `${service} 永久会员跳过` : `${service} +${item.days}天`
      }
      if (item.type === 'credits') return `+${item.amount} 积分`
      return item.label || ''
    },
    claimPercent(pack) {
      if (!pack.total_quantity) return 0
      return Math.min(100, (pack.claimed_count / pack.total_quantity) * 100)
    },
    lifecycleText(lifecycle) {
      return { upcoming: '未开始', active: '进行中', ended: '已结束' }[lifecycle] || '未知'
    },
    eligibilitySummary(pack) {
      const e = pack.eligibility
      if (!e) return ''
      const parts = []
      if (e.min_credits) parts.push(`积分 ≥ ${e.min_credits}`)
      if (e.require_premium) parts.push('Premium 会员')
      if (e.require_binding) {
        const option = BINDING_OPTIONS.find(o => o.value === e.require_binding)
        parts.push(option ? option.label : e.require_binding)
      }
      return parts.join('、')
    },

    // ===== 奖励项动态配置 =====
    // 已被其他奖励项选走的类型从下拉中剔除，作为「同类型不重复」的第一道防线
    availableTypes(index) {
      const taken = this.form.rewards.filter((_, i) => i !== index).map(r => r.type)
      return REWARD_TYPES.filter(t => !taken.includes(t.value))
    },
    addReward() {
      const taken = this.form.rewards.map(r => r.type)
      const next = REWARD_TYPES.find(t => !taken.includes(t.value))
      if (!next) return
      this.form.rewards.push(
        next.value === 'credits'
          ? { type: 'credits', amount: 100 }
          : { type: 'premium_days', days: 7 }
      )
    },
    removeReward(index) {
      this.form.rewards.splice(index, 1)
    },
    onRewardTypeChange(reward) {
      // 切换类型后清掉另一类型的参数字段，避免提交多余键
      if (reward.type === 'credits') {
        delete reward.days
        if (reward.amount === undefined) reward.amount = 100
      } else {
        delete reward.amount
        if (reward.days === undefined) reward.days = 7
      }
    },

    async loadPacks() {
      try {
        this.loading = true
        const res = await adminListGiftPacks({ page: 1, page_size: 100 })
        this.packs = res.data.packs || []
      } catch (e) {
        this.toast(this.extractError(e, '加载礼包列表失败'), 'error')
      } finally {
        this.loading = false
      }
    },

    openCreate() {
      this.editingId = null
      this.form = emptyForm()
      const now = Math.floor(Date.now() / 1000)
      this.form.startLocal = this.tsToServerLocal(now)
      this.form.endLocal = this.tsToServerLocal(now + 7 * 86400)
      this.formDialog = true
    },
    openEdit(pack) {
      this.editingId = pack.id
      const e = pack.eligibility || {}
      this.form = {
        title: pack.title,
        description: pack.description || '',
        rewards: JSON.parse(JSON.stringify(pack.rewards || [])),
        startLocal: this.tsToServerLocal(pack.start_at),
        endLocal: this.tsToServerLocal(pack.end_at),
        total_quantity: pack.total_quantity,
        max_prompt_count: pack.max_prompt_count,
        is_enabled: pack.is_enabled,
        min_credits: e.min_credits ?? null,
        require_premium: !!e.require_premium,
        require_binding: e.require_binding ?? null
      }
      this.formDialog = true
    },

    buildPayload() {
      const startAt = this.serverLocalToTs(this.form.startLocal)
      const endAt = this.serverLocalToTs(this.form.endLocal)
      if (!this.form.title?.trim()) throw new Error('请填写标题')
      if (!this.form.rewards.length) throw new Error('至少需要配置一项奖励')
      if (!startAt || !endAt) throw new Error('请填写完整的时间窗')
      if (endAt <= startAt) throw new Error('结束时间必须晚于开始时间')

      for (const reward of this.form.rewards) {
        if (reward.type === 'credits' && !(reward.amount > 0)) {
          throw new Error('积分数量必须大于 0')
        }
        if (reward.type === 'premium_days' && !(reward.days > 0)) {
          throw new Error('Premium 天数必须大于 0')
        }
      }

      const eligibility = {
        min_credits: this.form.min_credits > 0 ? this.form.min_credits : null,
        require_premium: !!this.form.require_premium,
        require_binding: this.form.require_binding || null
      }
      const hasEligibility =
        eligibility.min_credits !== null ||
        eligibility.require_premium ||
        eligibility.require_binding !== null

      return {
        title: this.form.title.trim(),
        description: this.form.description?.trim() || null,
        rewards: this.form.rewards,
        eligibility: hasEligibility ? eligibility : null,
        total_quantity: this.form.total_quantity > 0 ? this.form.total_quantity : null,
        start_at: startAt,
        end_at: endAt,
        max_prompt_count: this.form.max_prompt_count || 3,
        is_enabled: !!this.form.is_enabled
      }
    },

    async save() {
      let payload
      try {
        payload = this.buildPayload()
      } catch (e) {
        this.toast(e.message, 'error')
        return
      }
      try {
        this.saving = true
        if (this.editingId) {
          await adminUpdateGiftPack(this.editingId, payload)
          this.toast('礼包已更新')
        } else {
          await adminCreateGiftPack(payload)
          this.toast('礼包已创建')
        }
        this.formDialog = false
        await this.loadPacks()
        this.$emit('changed')
      } catch (e) {
        this.toast(this.extractError(e, '保存失败'), 'error')
      } finally {
        this.saving = false
      }
    },

    extractError(e, fallback) {
      const detail = e.response?.data?.detail
      if (typeof detail === 'string') return detail
      // Pydantic 422 返回的是校验错误数组
      if (Array.isArray(detail) && detail.length) {
        return detail[0].msg || fallback
      }
      return fallback
    },

    async toggleEnabled(pack) {
      try {
        this.togglingId = pack.id
        await adminSetGiftPackEnabled(pack.id, !pack.is_enabled)
        this.toast(pack.is_enabled ? '礼包已停用' : '礼包已启用')
        await this.loadPacks()
        this.$emit('changed')
      } catch (e) {
        this.toast(this.extractError(e, '操作失败'), 'error')
      } finally {
        this.togglingId = null
      }
    },

    async confirmDelete(pack) {
      if (!window.confirm(`确定删除礼包「${pack.title}」？此操作不可撤销。`)) return
      try {
        this.deletingId = pack.id
        await adminDeleteGiftPack(pack.id)
        this.toast('礼包已删除')
        await this.loadPacks()
        this.$emit('changed')
      } catch (e) {
        this.toast(this.extractError(e, '删除失败'), 'error')
        await this.loadPacks()
      } finally {
        this.deletingId = null
      }
    },

    async openStats(pack) {
      try {
        const res = await adminGetGiftPackStats(pack.id)
        this.stats = res.data
        this.statsDialog = true
      } catch (e) {
        this.toast(this.extractError(e, '获取统计失败'), 'error')
      }
    },

    async openRecords(pack) {
      this.recordsDialog = true
      this.records = []
      this.recordsTotal = 0
      try {
        this.recordsLoading = true
        const res = await adminGetGiftPackRecords(pack.id, { page: 1, page_size: 100 })
        this.records = res.data.records || []
        this.recordsTotal = res.data.total || 0
      } catch (e) {
        this.toast(this.extractError(e, '获取领取记录失败'), 'error')
      } finally {
        this.recordsLoading = false
      }
    }
  }
}
</script>

<style scoped>
/* 主面板样式 —— 与 WheelAdminPanel 保持同一套视觉语言 */
.admin-panel {
  min-height: 100vh;
  background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
  padding: 16px 0;
}

@media (min-width: 600px) {
  .admin-panel {
    padding: 24px 0;
  }
}

/* 统一的卡片样式 */
.admin-card {
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  border: 1px solid rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.admin-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12) !important;
}

.admin-card-header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
  min-height: 64px;
}

.admin-card .v-card-text {
  background: rgba(255, 255, 255, 0.95);
}

/* 礼包卡片 */
.config-card {
  height: 100%;
  border: 1px solid rgba(0, 0, 0, 0.08);
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  background: rgba(255, 255, 255, 0.95);
}

.config-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12) !important;
}

.config-card-header {
  color: white;
  border-radius: 16px 16px 0 0 !important;
  min-height: 64px;
}

/* 卡头按生命周期换色：进行中粉紫、未开始蓝、已结束灰 */
.config-card-header--active {
  background: linear-gradient(135deg, #ec407a 0%, #7e57c2 100%);
}

.config-card-header--upcoming {
  background: linear-gradient(135deg, #2196f3 0%, #21cbf3 100%);
}

.config-card-header--ended {
  background: linear-gradient(135deg, #9e9e9e 0%, #757575 100%);
}

/*
  flex 子项默认 min-width:auto，长标题会把右侧状态 chip 挤出视野。
  显式 min-width:0 + ellipsis，让标题可截断、chip 永远可见。
*/
.pack-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pack-chip {
  flex: 0 0 auto;
  font-weight: 700;
  color: rgba(0, 0, 0, 0.75) !important;
}

/* 配置条目 */
.config-item {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.05) 0%, rgba(118, 75, 162, 0.05) 100%);
  border: 1px solid rgba(102, 126, 234, 0.1);
  border-radius: 12px;
  padding: 10px 12px;
  transition: all 0.2s ease;
}

.config-item:hover {
  border-color: rgba(102, 126, 234, 0.25);
}

.config-label {
  display: flex;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  color: #666;
  letter-spacing: 0.3px;
}

.config-value {
  font-size: 13px;
  color: #333;
  margin-top: 4px;
}

.config-number {
  font-size: 16px;
  font-weight: 700;
  color: #333;
}

.config-chip {
  font-weight: 600;
}

.config-btn {
  min-width: 0;
}

/* 统计卡片样式 */
.stat-card {
  border: 2px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px !important;
  transition: all 0.2s ease;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.9) 100%);
}

.stat-card:hover {
  border-color: rgba(236, 64, 122, 0.3);
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

/* 对话框样式 */
.dialog-card {
  border: 1px solid rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.dialog-header {
  background: linear-gradient(135deg, #ec407a 0%, #7e57c2 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
  position: sticky;
  top: 0;
  z-index: 2;
}

.result-card-header {
  background: linear-gradient(135deg, #673ab7 0%, #3f51b5 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
}

.preview-card-header {
  background: linear-gradient(135deg, #9c27b0 0%, #673ab7 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
}

/* 表单分组卡片 */
.setting-card {
  border: 2px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px !important;
  transition: all 0.2s ease;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.9) 100%);
}

.setting-card:hover {
  border-color: rgba(236, 64, 122, 0.2);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

/* 奖励项行 */
.reward-row {
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 12px !important;
  background: rgba(255, 255, 255, 0.95);
}

/* 小屏适配 */
@media (max-width: 600px) {
  .config-card-header,
  .admin-card-header {
    min-height: 56px;
  }

  .config-value {
    font-size: 12px;
  }

  .reward-row .d-flex {
    flex-wrap: wrap;
  }
}
</style>
