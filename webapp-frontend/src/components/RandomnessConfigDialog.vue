<template>
  <v-dialog v-model="dialog" max-width="600">
    <template v-slot:activator="{ props }">
      <v-btn
        v-bind="props"
        color="success"
        variant="outlined"
        prepend-icon="mdi-tune"
      >
        随机性配置
      </v-btn>
    </template>
    
    <v-card>
      <v-card-title class="d-flex align-center">
        <v-icon class="mr-2">mdi-tune</v-icon>
        随机性算法配置
      </v-card-title>
      
      <v-card-text>
        <v-form ref="form" v-model="valid">
          <!-- 基础开关配置 -->
          <div class="mb-4">
            <h4 class="mb-3">基础设置</h4>
            
            <v-switch
              v-model="config.use_weighted_protection"
              label="启用低概率奖品保护"
              color="primary"
              hide-details
              class="mb-2"
            >
              <template v-slot:append>
                <v-tooltip location="top">
                  <template v-slot:activator="{ props }">
                    <v-icon v-bind="props" color="grey">mdi-help-circle-outline</v-icon>
                  </template>
                  <span>为概率较低的奖品提供额外的中奖保护机制</span>
                </v-tooltip>
              </template>
            </v-switch>
            
            <v-switch
              v-model="config.use_time_seed_mixing"
              label="启用时间熵混合"
              color="primary"
              hide-details
              class="mb-2"
            >
              <template v-slot:append>
                <v-tooltip location="top">
                  <template v-slot:activator="{ props }">
                    <v-icon v-bind="props" color="grey">mdi-help-circle-outline</v-icon>
                  </template>
                  <span>使用时间戳增强随机数的不可预测性</span>
                </v-tooltip>
              </template>
            </v-switch>
            
            <v-switch
              v-model="config.use_user_seed_mixing"
              label="启用用户ID熵混合"
              color="primary"
              hide-details
            >
              <template v-slot:append>
                <v-tooltip location="top">
                  <template v-slot:activator="{ props }">
                    <v-icon v-bind="props" color="grey">mdi-help-circle-outline</v-icon>
                  </template>
                  <span>使用用户ID增强随机性，确保每个用户的抽奖体验独特</span>
                </v-tooltip>
              </template>
            </v-switch>
          </div>

          <v-divider class="mb-4"></v-divider>

          <!-- 高级参数配置 -->
          <div class="mb-4">
            <h4 class="mb-3">高级参数</h4>
            
            <v-text-field
              v-model.number="config.protection_threshold"
              label="保护阈值 (%)"
              type="number"
              min="0.1"
              max="50"
              step="0.1"
              :rules="thresholdRules"
              density="compact"
              variant="outlined"
              class="mb-3"
              :disabled="!config.use_weighted_protection"
            >
              <template v-slot:append-inner>
                <v-tooltip location="top">
                  <template v-slot:activator="{ props }">
                    <v-icon v-bind="props" color="grey" size="small">mdi-help-circle-outline</v-icon>
                  </template>
                  <span>概率低于此值的奖品将获得保护加成</span>
                </v-tooltip>
              </template>
            </v-text-field>
            
            <v-text-field
              v-model.number="config.protection_factor"
              label="保护系数"
              type="number"
              min="1.0"
              max="3.0"
              step="0.1"
              :rules="factorRules"
              density="compact"
              variant="outlined"
              :disabled="!config.use_weighted_protection"
            >
              <template v-slot:append-inner>
                <v-tooltip location="top">
                  <template v-slot:activator="{ props }">
                    <v-icon v-bind="props" color="grey" size="small">mdi-help-circle-outline</v-icon>
                  </template>
                  <span>低概率奖品的概率乘数，越大保护力度越强</span>
                </v-tooltip>
              </template>
            </v-text-field>
          </div>

          <v-divider class="mb-4"></v-divider>

          <!-- 预设配置 -->
          <div class="mb-4">
            <h4 class="mb-3">快速配置</h4>
            <v-btn-toggle
              v-model="selectedPreset"
              color="primary"
              variant="outlined"
              divided
              @update:model-value="applyPreset"
            >
              <v-btn value="conservative">保守模式</v-btn>
              <v-btn value="balanced">平衡模式</v-btn>
              <v-btn value="aggressive">激进模式</v-btn>
            </v-btn-toggle>
          </div>

          <!-- 配置预览 -->
          <v-alert
            type="info"
            variant="tonal"
            class="mb-4"
          >
            <div class="text-subtitle-2 mb-2">当前配置效果预览：</div>
            <ul class="text-body-2">
              <li v-if="config.use_weighted_protection">
                概率低于 {{ config.protection_threshold }}% 的奖品将获得 {{ ((config.protection_factor - 1) * 100).toFixed(0) }}% 的保护加成
              </li>
              <li v-else>
                所有奖品严格按照设定概率执行
              </li>
              <li v-if="config.use_time_seed_mixing">
                启用时间戳随机增强
              </li>
              <li v-if="config.use_user_seed_mixing">
                启用用户ID随机增强
              </li>
            </ul>
          </v-alert>
        </v-form>
      </v-card-text>
      
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn @click="close">取消</v-btn>
        <v-btn
          color="primary"
          :disabled="!valid"
          :loading="saving"
          @click="save"
        >
          保存配置
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { updateLuckyWheelRandomnessConfig } from '@/services/wheelService'

export default {
  name: 'RandomnessConfigDialog',
  props: {
    initialConfig: {
      type: Object,
      default: () => ({})
    }
  },
  emits: ['config-updated'],
  data() {
    return {
      dialog: false,
      valid: false,
      saving: false,
      selectedPreset: null,
      config: {
        use_weighted_protection: true,
        protection_threshold: 2.0,
        protection_factor: 1.2,
        use_time_seed_mixing: true,
        use_user_seed_mixing: true
      },
      thresholdRules: [
        v => !!v || '保护阈值不能为空',
        v => (v >= 0.1 && v <= 50) || '保护阈值必须在 0.1% 到 50% 之间'
      ],
      factorRules: [
        v => !!v || '保护系数不能为空',
        v => (v >= 1.0 && v <= 3.0) || '保护系数必须在 1.0 到 3.0 之间'
      ],
      presets: {
        conservative: {
          use_weighted_protection: true,
          protection_threshold: 5.0,
          protection_factor: 1.5,
          use_time_seed_mixing: true,
          use_user_seed_mixing: true
        },
        balanced: {
          use_weighted_protection: true,
          protection_threshold: 2.0,
          protection_factor: 1.2,
          use_time_seed_mixing: true,
          use_user_seed_mixing: true
        },
        aggressive: {
          use_weighted_protection: false,
          protection_threshold: 1.0,
          protection_factor: 1.0,
          use_time_seed_mixing: true,
          use_user_seed_mixing: false
        }
      }
    }
  },
  watch: {
    initialConfig: {
      handler(newConfig) {
        if (newConfig && Object.keys(newConfig).length > 0) {
          this.config = { ...this.config, ...newConfig }
        }
      },
      immediate: true,
      deep: true
    }
  },
  methods: {
    applyPreset(presetName) {
      if (presetName && this.presets[presetName]) {
        this.config = { ...this.presets[presetName] }
      }
    },
    
    async save() {
      if (!this.valid) return
      
      this.saving = true
      try {
        await updateLuckyWheelRandomnessConfig(this.config)
        
        this.$emit('config-updated', this.config)
        
        // 显示成功消息
        this.$nextTick(() => {
          // 这里可以使用 Vuetify 的 snackbar 或其他通知方式
          console.log('随机性配置更新成功')
        })
        
        this.close()
      } catch (error) {
        console.error('保存随机性配置失败:', error)
        // 这里可以显示错误消息
        alert('保存配置失败，请稍后重试')
      } finally {
        this.saving = false
      }
    },
    
    close() {
      this.dialog = false
      this.selectedPreset = null
    }
  }
}
</script>

<style scoped>
.v-btn-toggle {
  width: 100%;
}

.v-btn-toggle .v-btn {
  flex: 1;
}
</style>
