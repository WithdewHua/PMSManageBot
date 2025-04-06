<template>
  <div>
    <!-- 邀请码确认对话框 -->
    <v-dialog v-model="showDialog" max-width="340" persistent>
      <v-card>
        <v-card-title class="headline">
          生成邀请码
        </v-card-title>
        <v-card-text>
          <div v-if="isLoading" class="text-center py-3">
            <v-progress-circular indeterminate color="primary"></v-progress-circular>
            <div class="mt-2">查询积分信息...</div>
          </div>
          <div v-else>
            <p>生成一个新的邀请码需要消耗 <strong>{{ invitePointsRequired }}</strong> 积分</p>
            <p>您当前积分: <strong>{{ userCurrentPoints.toFixed(2) }}</strong></p>
            <div v-if="errorMessage" class="error-message mt-2">
              {{ errorMessage }}
            </div>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="closeDialog">取消</v-btn>
          <v-btn 
            color="primary" 
            :disabled="isLoading || userCurrentPoints < invitePointsRequired || isGenerating"
            @click="generateInviteCodeAction"
          >
            <v-progress-circular
              v-if="isGenerating"
              indeterminate
              color="white"
              size="20"
              width="2"
              class="mr-2"
            ></v-progress-circular>
            {{ isGenerating ? '处理中...' : '确认生成' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    
    <!-- 结果提示对话框 -->
    <v-snackbar v-model="showResultSnackbar" :timeout="3000" :color="snackbarColor">
      {{ snackbarMessage }}
    </v-snackbar>
  </div>
</template>

<script>
import { getInvitePointsInfo, generateInviteCode } from '../services/inviteCodeService';

export default {
  name: 'InviteCodeDialog',
  data() {
    return {
      showDialog: false,
      isLoading: false,
      invitePointsRequired: 0,
      userCurrentPoints: 0,
      errorMessage: '',
      isGenerating: false,
      // 结果提示
      showResultSnackbar: false,
      snackbarMessage: '',
      snackbarColor: 'success'
    }
  },
  methods: {
    // 打开对话框并获取积分信息
    open() {
      this.showDialog = true;
      this.isLoading = true;
      this.errorMessage = '';
      
      // 获取积分信息
      this.fetchInvitePointsInfo();
    },
    
    // 关闭对话框
    closeDialog() {
      this.showDialog = false;
      this.errorMessage = '';
    },
    
    // 获取邀请码积分信息
    fetchInvitePointsInfo() {
      getInvitePointsInfo()
        .then(data => {
          this.handleInviteInfoResponse(data);
        })
        .catch(error => {
          console.error('获取积分信息失败:', error);
          this.handleInviteInfoResponse(null);
        });
    },
    
    // 处理积分信息响应
    handleInviteInfoResponse(data) {
      this.isLoading = false;
      
      if (data) {
        this.invitePointsRequired = data.required_points;
        this.userCurrentPoints = data.current_points;
        
        if (!data.can_generate && data.error_message) {
          this.errorMessage = data.error_message;
        }
      } else {
        this.errorMessage = '获取积分信息失败，请稍后再试';
      }
    },
    
    // 确认生成邀请码
    generateInviteCodeAction() {
      this.isGenerating = true;
      this.errorMessage = '';
      
      // 调用服务生成邀请码
      generateInviteCode()
        .then(response => {
          this.handleGenerateResponse(response);
        })
        .catch(error => {
          console.error('生成邀请码失败:', error);
          this.handleGenerateResponse({
            success: false,
            message: '生成邀请码失败，请稍后再试'
          });
        });
    },
    
    // 处理生成结果
    handleGenerateResponse(response) {
      this.isGenerating = false;
      
      if (response.success) {
        this.showDialog = false;
        this.snackbarColor = 'success';
        this.snackbarMessage = response.message;
      } else {
        this.errorMessage = response.message || '生成邀请码失败，请稍后再试';
        this.snackbarColor = 'error';
        this.snackbarMessage = this.errorMessage;
      }
      
      this.showResultSnackbar = true;
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
