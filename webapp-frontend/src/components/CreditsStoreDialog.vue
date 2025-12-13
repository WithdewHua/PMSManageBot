<template>
  <v-dialog v-model="dialog" max-width="600px" persistent>
    <v-card class="credits-store-dialog">
      <v-card-title class="dialog-title">
        <v-icon start size="28">mdi-store</v-icon>
        <span class="title-text">积分商城</span>
        <v-spacer></v-spacer>
        <v-btn 
          icon 
          variant="text" 
          size="small" 
          @click="close"
          class="close-btn"
        >
          <v-icon size="24">mdi-close</v-icon>
        </v-btn>
      </v-card-title>

      <v-divider></v-divider>

      <v-card-text class="dialog-content">
        <v-list class="store-menu-list">
          <v-list-item
            v-for="item in menuItems"
            :key="item.value"
            @click="handleMenuClick(item)"
            :disabled="item.disabled"
            class="menu-item"
            rounded="lg"
          >
            <template v-slot:prepend>
              <v-avatar :color="item.color" size="40">
                <v-icon :color="item.iconColor || 'white'">{{ item.icon }}</v-icon>
              </v-avatar>
            </template>

            <v-list-item-title class="item-title">
              {{ item.title }}
            </v-list-item-title>

            <v-list-item-subtitle class="item-subtitle">
              {{ item.subtitle }}
            </v-list-item-subtitle>

            <template v-slot:append>
              <v-chip
                v-if="item.badge"
                :color="item.badgeColor || 'primary'"
                size="small"
                class="item-badge"
              >
                {{ item.badge }}
              </v-chip>
              <v-icon v-else color="grey-lighten-1">mdi-chevron-right</v-icon>
            </template>
          </v-list-item>
        </v-list>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<script>
import { getBadgeCenterConfig } from '@/services/badgeService.js'

export default {
  name: 'CreditsStoreDialog',
  data() {
    return {
      dialog: false,
      badgeCenterEnabled: true, // 勋章中心是否启用
      menuItems: [
        {
          value: 'transfer',
          title: '积分转移',
          subtitle: '将积分转移给其他用户',
          icon: 'mdi-bank-transfer',
          color: 'amber-darken-2',
          iconColor: 'white',
          disabled: false
        },
        {
          value: 'vaultwarden',
          title: '兑换 Vaultwarden',
          subtitle: '使用积分兑换密码管理器账户',
          icon: 'mdi-shield-key',
          color: 'blue-darken-2',
          iconColor: 'white',
          disabled: false
        },
        {
          value: 'badges',
          title: '勋章中心',
          subtitle: '兑换周年勋章获得积分加成',
          icon: 'mdi-medal',
          color: 'deep-orange-darken-1',
          iconColor: 'white',
          disabled: false
        },
        // 可以在这里添加更多功能项
        // {
        //   value: 'exchange',
        //   title: '积分兑换',
        //   subtitle: '使用积分兑换商品或服务',
        //   icon: 'mdi-gift',
        //   color: 'purple-darken-1',
        //   iconColor: 'white',
        //   badge: '即将上线',
        //   badgeColor: 'info',
        //   disabled: true
        // },
        // {
        //   value: 'history',
        //   title: '积分历史',
        //   subtitle: '查看积分收支明细',
        //   icon: 'mdi-history',
        //   color: 'blue-darken-1',
        //   iconColor: 'white',
        //   disabled: false
        // }
      ]
    }
  },
  async mounted() {
    // 加载勋章中心配置
    await this.loadBadgeCenterConfig()
  },
  methods: {
    async open() {
      this.dialog = true
      // 每次打开时重新加载配置，确保状态最新
      await this.loadBadgeCenterConfig()
    },
    close() {
      this.dialog = false
    },
    async loadBadgeCenterConfig() {
      try {
        const response = await getBadgeCenterConfig()
        if (response.data) {
          this.badgeCenterEnabled = response.data.enabled
          // 更新勋章中心菜单项的禁用状态
          const badgeMenuItem = this.menuItems.find(item => item.value === 'badges')
          if (badgeMenuItem) {
            badgeMenuItem.disabled = !this.badgeCenterEnabled
            // 如果功能关闭，显示提示badge
            if (!this.badgeCenterEnabled) {
              badgeMenuItem.badge = '暂未开放'
              badgeMenuItem.badgeColor = 'grey'
            } else {
              badgeMenuItem.badge = null
            }
          }
        }
      } catch (error) {
        console.error('加载勋章中心配置失败:', error)
        // 加载失败时默认禁用
        const badgeMenuItem = this.menuItems.find(item => item.value === 'badges')
        if (badgeMenuItem) {
          badgeMenuItem.disabled = true
        }
      }
    },
    handleMenuClick(item) {
      if (item.disabled) {
        return
      }
      
      // 触发相应的功能事件
      this.$emit('menu-selected', item.value)
      
      // 关闭当前对话框
      this.close()
    }
  }
}
</script>

<style scoped>
.credits-store-dialog {
  border-radius: 16px;
}

.dialog-title {
  font-size: 1.25rem;
  font-weight: 600;
  padding: 20px 24px;
  background: linear-gradient(135deg, #FFA726 0%, #FB8C00 100%);
  color: white;
  display: flex;
  align-items: center;
}

.title-text {
  margin-left: 8px;
}

.close-btn {
  color: white !important;
  opacity: 0.9;
  transition: all 0.2s ease;
}

.close-btn:hover {
  opacity: 1;
  background-color: rgba(255, 255, 255, 0.15) !important;
  transform: rotate(90deg);
}

.close-btn:active {
  transform: rotate(90deg) scale(0.95);
}

.dialog-content {
  padding: 16px !important;
}

.store-menu-list {
  background: transparent;
  padding: 0;
}

.menu-item {
  margin-bottom: 12px;
  border: 1px solid rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease;
}

.menu-item:hover:not([disabled]) {
  background-color: rgba(255, 167, 38, 0.08);
  border-color: #FFA726;
  transform: translateX(4px);
  cursor: pointer;
}

.menu-item[disabled] {
  opacity: 0.5;
}

.item-title {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 4px;
}

.item-subtitle {
  font-size: 0.875rem;
  opacity: 0.7;
}

.item-badge {
  font-size: 0.75rem;
  font-weight: 600;
}
</style>
