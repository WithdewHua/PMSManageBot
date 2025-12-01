<template>
  <v-dialog v-model="dialog" max-width="600px" persistent>
    <v-card class="credits-store-dialog">
      <v-card-title class="dialog-title">
        <v-icon start color="amber-darken-2">mdi-store</v-icon>
        积分商城
        <v-spacer></v-spacer>
        <v-btn icon size="small" @click="close">
          <v-icon>mdi-close</v-icon>
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

      <v-divider></v-divider>

      <v-card-actions class="dialog-actions">
        <v-spacer></v-spacer>
        <v-btn color="grey-darken-1" variant="text" @click="close">
          关闭
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
export default {
  name: 'CreditsStoreDialog',
  data() {
    return {
      dialog: false,
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
  methods: {
    open() {
      this.dialog = true
    },
    close() {
      this.dialog = false
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

.dialog-actions {
  padding: 16px 24px;
}
</style>
