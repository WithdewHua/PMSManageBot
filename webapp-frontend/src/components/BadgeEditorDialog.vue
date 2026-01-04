<template>
  <v-dialog v-model="dialog" max-width="600px" persistent>
    <v-card>
      <v-card-title class="d-flex align-center">
        <v-icon start color="amber-darken-2">mdi-medal</v-icon>
        <span>{{ isEdit ? '编辑勋章' : '创建勋章' }}</span>
      </v-card-title>

      <v-card-text>
        <v-form ref="form" v-model="valid">
          <v-row>
            <v-col cols="12">
              <v-text-field
                v-model="badgeForm.badge_type"
                label="勋章类型标识"
                placeholder="例如: anniversary_5"
                :rules="[v => !!v || '勋章类型不能为空']"
                :disabled="isEdit"
                density="comfortable"
                variant="outlined"
                hint="唯一标识，创建后不可修改"
                persistent-hint
              ></v-text-field>
            </v-col>

            <v-col cols="12">
              <v-text-field
                v-model="badgeForm.name"
                label="勋章名称"
                placeholder="例如: 五周年纪念勋章"
                :rules="[v => !!v || '勋章名称不能为空']"
                density="comfortable"
                variant="outlined"
              ></v-text-field>
            </v-col>

            <v-col cols="12">
              <v-textarea
                v-model="badgeForm.description"
                label="勋章描述"
                placeholder="描述勋章的用途和特殊意义"
                rows="3"
                density="comfortable"
                variant="outlined"
              ></v-textarea>
            </v-col>

            <v-col cols="12" sm="6">
              <v-text-field
                v-model.number="badgeForm.credits_cost"
                type="number"
                label="兑换积分"
                :rules="[v => v >= 0 || '积分不能为负数']"
                density="comfortable"
                variant="outlined"
                suffix="积分"
              ></v-text-field>
            </v-col>

            <v-col cols="12" sm="6">
              <v-text-field
                v-model.number="bonusPercentageInput"
                type="number"
                label="加成百分比"
                :rules="[v => v >= 0 && v <= 100 || '加成需在0-100之间']"
                density="comfortable"
                variant="outlined"
                suffix="%"
                hint="每日观看积分加成"
                persistent-hint
              ></v-text-field>
            </v-col>

            <v-col cols="12" sm="6">
              <v-text-field
                v-model.number="badgeForm.valid_days"
                type="number"
                label="有效天数"
                :rules="[v => v > 0 || '有效天数必须大于0']"
                density="comfortable"
                variant="outlined"
                suffix="天"
              ></v-text-field>
            </v-col>

            <v-col cols="12" sm="6">
              <v-text-field
                v-model="badgeForm.icon_url"
                label="图标URL"
                placeholder="/badges/anniversary_5.svg"
                :rules="[v => !!v || '图标URL不能为空']"
                density="comfortable"
                variant="outlined"
              ></v-text-field>
            </v-col>

            <v-col cols="12">
              <v-switch
                v-model="badgeForm.is_enabled"
                label="启用此勋章"
                color="success"
                density="comfortable"
                hide-details
              ></v-switch>
            </v-col>
          </v-row>
        </v-form>
      </v-card-text>

      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn
          color="grey"
          variant="text"
          @click="closeDialog"
          :disabled="saving"
        >
          取消
        </v-btn>
        <v-btn
          color="amber-darken-2"
          variant="elevated"
          @click="saveBadge"
          :loading="saving"
          :disabled="!valid"
        >
          {{ isEdit ? '保存' : '创建' }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { adminCreateBadge, adminUpdateBadge } from '@/services/badgeService.js'

export default {
  name: 'BadgeEditorDialog',
  props: {
    modelValue: {
      type: Boolean,
      default: false
    },
    badge: {
      type: Object,
      default: null
    }
  },
  emits: ['update:modelValue', 'badge-saved'],
  data() {
    return {
      valid: false,
      saving: false,
      badgeForm: {
        badge_type: '',
        name: '',
        description: '',
        credits_cost: 1000,
        bonus_percentage: 0.18,
        valid_days: 365,
        icon_url: '',
        is_enabled: true
      },
      bonusPercentageInput: 18 // 百分比输入（0-100）
    }
  },
  computed: {
    dialog: {
      get() {
        return this.modelValue
      },
      set(value) {
        this.$emit('update:modelValue', value)
      }
    },
    isEdit() {
      return !!this.badge
    }
  },
  watch: {
    dialog(val) {
      if (val) {
        this.initForm()
      }
    },
    bonusPercentageInput(val) {
      // 将百分比转换为小数
      this.badgeForm.bonus_percentage = val / 100
    }
  },
  methods: {
    initForm() {
      if (this.badge) {
        // 编辑模式：填充现有数据
        this.badgeForm = {
          badge_type: this.badge.badge_type,
          name: this.badge.name,
          description: this.badge.description || '',
          credits_cost: this.badge.credits_cost,
          bonus_percentage: this.badge.bonus_percentage,
          valid_days: this.badge.valid_days,
          icon_url: this.badge.icon_url,
          is_enabled: this.badge.is_enabled === 1
        }
        this.bonusPercentageInput = this.badge.bonus_percentage * 100
      } else {
        // 创建模式：重置表单
        this.badgeForm = {
          badge_type: '',
          name: '',
          description: '',
          credits_cost: 1000,
          bonus_percentage: 0.18,
          valid_days: 365,
          icon_url: '',
          is_enabled: true
        }
        this.bonusPercentageInput = 18
      }
      this.$nextTick(() => {
        if (this.$refs.form) {
          this.$refs.form.resetValidation()
        }
      })
    },
    async saveBadge() {
      if (!this.valid) return

      try {
        this.saving = true

        const badgeData = {
          ...this.badgeForm,
          is_enabled: this.badgeForm.is_enabled ? 1 : 0
        }

        if (this.isEdit) {
          // 编辑模式
          await adminUpdateBadge(this.badge.id, badgeData)
          this.showMessage('勋章更新成功')
        } else {
          // 创建模式
          await adminCreateBadge(badgeData)
          this.showMessage('勋章创建成功')
        }

        this.$emit('badge-saved')
        this.closeDialog()
      } catch (error) {
        console.error('保存勋章失败:', error)
        const errorMessage = error.response?.data?.detail || '保存勋章失败，请稍后重试'
        this.showMessage(errorMessage)
      } finally {
        this.saving = false
      }
    },
    closeDialog() {
      this.dialog = false
    },
    showMessage(message) {
      // 使用 Telegram WebApp 或浏览器提示
      if (window.Telegram?.WebApp) {
        window.Telegram.WebApp.showAlert(message)
      } else {
        alert(message)
      }
    }
  }
}
</script>

<style scoped>
.v-card-title {
  background: linear-gradient(135deg, rgba(251, 192, 45, 0.1) 0%, rgba(245, 166, 35, 0.1) 100%);
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
}
</style>
