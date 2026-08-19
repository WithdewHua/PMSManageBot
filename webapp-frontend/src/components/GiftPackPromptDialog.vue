<template>
  <v-dialog v-model="dialog" max-width="440" persistent>
    <v-card class="gift-prompt">
      <div class="gift-prompt__hero">
        <v-icon size="52" color="white">mdi-gift</v-icon>
        <div class="text-h6 mt-2">你有礼包待领取</div>
        <div class="text-caption mt-1">
          {{ packs.length > 1 ? `共 ${packs.length} 个礼包` : '快去领取吧' }}
        </div>
      </div>

      <v-card-text class="pa-5">
        <div v-for="pack in displayPacks" :key="pack.id" class="gift-prompt__item">
          <div class="d-flex align-center justify-space-between mb-1">
            <span class="text-subtitle-2 gift-prompt__item-title">{{ pack.title }}</span>
            <v-chip
              v-if="pack.total_quantity"
              size="x-small"
              variant="tonal"
              :color="pack.remaining <= 3 ? 'error' : 'grey'"
            >
              剩 {{ pack.remaining }}/{{ pack.total_quantity }}
            </v-chip>
            <v-chip v-else size="x-small" variant="tonal" color="grey">不限量</v-chip>
          </div>
          <div class="d-flex flex-wrap ga-1">
            <v-chip
              v-for="(reward, idx) in pack.rewards"
              :key="idx"
              size="x-small"
              variant="tonal"
              :color="reward.type === 'credits' ? 'amber-darken-2' : 'deep-purple'"
            >
              {{ reward.label }}
            </v-chip>
          </div>
        </div>

        <!-- 超过 3 个不逐条铺开，避免弹窗过长 -->
        <div v-if="truncatedCount > 0" class="text-caption text-medium-emphasis text-center mt-2">
          …等 {{ packs.length }} 个礼包
        </div>
      </v-card-text>

      <v-card-actions class="px-5 pb-4">
        <v-btn variant="text" color="grey" @click="dismiss">稍后再说</v-btn>
        <v-spacer />
        <v-btn color="pink" variant="elevated" @click="goClaim">前往领取</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'GiftPackPromptDialog',
  emits: ['go-claim', 'dismiss'],
  data() {
    return {
      dialog: false,
      packs: []
    }
  },
  computed: {
    displayPacks() {
      return this.packs.slice(0, 3)
    },
    truncatedCount() {
      return Math.max(0, this.packs.length - 3)
    }
  },
  methods: {
    /**
     * 由外部在 prompt-check 返回非空时调用。
     * 提醒次数已在后端返回时记账，本弹窗只负责展示。
     */
    open(packs) {
      if (!packs || !packs.length) return
      this.packs = packs
      this.dialog = true
    },
    close() {
      this.dialog = false
    },
    dismiss() {
      this.close()
      this.$emit('dismiss')
    },
    goClaim() {
      this.close()
      this.$emit('go-claim')
    }
  }
}
</script>

<style scoped>
.gift-prompt {
  overflow: hidden;
}

.gift-prompt__hero {
  background: linear-gradient(135deg, #ec407a 0%, #7e57c2 100%);
  color: #fff;
  text-align: center;
  padding: 24px 16px 20px;
}

.gift-prompt__item {
  padding: 10px 0;
}

.gift-prompt__item + .gift-prompt__item {
  border-top: 1px solid rgba(128, 128, 128, 0.18);
}

.gift-prompt__item-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
