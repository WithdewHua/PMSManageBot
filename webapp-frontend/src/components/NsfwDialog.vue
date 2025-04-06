<template>
  <v-dialog v-model="showDialog" max-width="400">
    <v-card>
      <v-card-title>{{ title }}</v-card-title>
      <v-card-text>
        <div v-if="loading" class="text-center py-2">
          <v-progress-circular indeterminate color="primary" size="24"></v-progress-circular>
          <div class="mt-2">加载中...</div>
        </div>
        <div v-else>
          <p v-if="isUnlock">解锁 NSFW 内容需要消耗 <strong>{{ cost }}</strong> 积分</p>
          <p v-else>锁定 NSFW 内容将返还 <strong>{{ refund }}</strong> 积分</p>
          <p class="mt-2">您当前积分: <strong>{{ currentCredits.toFixed(2) }}</strong></p>
          <div v-if="error" class="error-message mt-2 red--text">
            {{ error }}
          </div>
        </div>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn text @click="closeDialog">取消</v-btn>
        <v-btn 
          color="primary" 
          @click="executeOperation"
          :loading="processing"
          :disabled="loading || processing || (isUnlock && currentCredits < cost)"
        >
          确认{{ isUnlock ? '解锁' : '锁定' }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { getNsfwOperationInfo, executeNsfwOperation } from '@/services/nsfwService'

export default {
  name: 'NsfwDialog',
  props: {
    currentCredits: {
      type: Number,
      required: true
    }
  },
  data() {
    return {
      showDialog: false,
      title: '',
      isUnlock: false,
      service: '',
      loading: false,
      processing: false,
      error: '',
      cost: 100, // 默认值，实际会从API获取
      refund: 0 // 默认值，实际会从API获取
    }
  },
  methods: {
    // 打开对话框
    async open(service, isAllLib) {
      // 判断是解锁还是锁定操作
      this.isUnlock = !isAllLib;
      this.service = service;
      this.title = this.isUnlock ? '解锁 NSFW 内容' : '锁定 NSFW 内容';
      this.showDialog = true;
      this.loading = true;
      this.error = '';
      
      try {
        // 获取NSFW操作所需积分或返还积分信息
        const operation = this.isUnlock ? 'unlock' : 'lock';
        const infoData = await getNsfwOperationInfo(service, operation);
        
        if (this.isUnlock) {
          this.cost = infoData.cost;
        } else {
          this.refund = infoData.refund;
        }
      } catch (error) {
        this.error = '获取积分信息失败';
        console.error('获取 NSFW 积分信息失败:', error);
      } finally {
        this.loading = false;
      }
    },
    
    // 关闭对话框
    closeDialog() {
      this.showDialog = false;
    },
    
    // 执行 NSFW 权限操作
    async executeOperation() {
      this.processing = true;
      this.error = '';
      
      try {
        const operation = this.isUnlock ? 'unlock' : 'lock';
        
        // 调用NSFW服务执行操作
        const result = await executeNsfwOperation(operation, this.service);
        
        if (result.success) {
          // 关闭对话框
          this.showDialog = false;
          
          // 显示操作成功提示
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showPopup({
              title: '操作成功',
              message: this.isUnlock ? 'NSFW 内容已解锁' : 'NSFW 内容已锁定'
            });
          }
          
          // 通知父组件更新状态
          this.$emit('operation-completed', {
            service: this.service, 
            isUnlock: this.isUnlock,
            cost: this.isUnlock ? this.cost : -this.refund
          });
        } else {
          this.error = result.message || '操作失败';
        }
      } catch (error) {
        this.error = error.response?.data?.message || '请求失败，请稍后再试';
        console.error('NSFW 操作失败:', error);
      } finally {
        this.processing = false;
      }
    }
  }
}
</script>

<style scoped>
.error-message {
  color: #ff5252;
  font-size: 14px;
}
</style>
