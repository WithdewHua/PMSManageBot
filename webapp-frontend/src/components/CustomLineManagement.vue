<template>
  <div class="custom-line-management">
    <v-card class="admin-card-enhanced mb-4">
      <v-card-title class="text-center">
        <v-icon start color="primary">mdi-road-variant</v-icon> 自定义线路管理
      </v-card-title>
      
      <v-card-text>
        <!-- 状态筛选 -->
        <v-chip-group v-model="selectedStatus" mandatory class="mb-4">
          <v-chip value="all" filter>全部</v-chip>
          <v-chip value="pending" filter color="orange">待审核</v-chip>
          <v-chip value="approved" filter color="success">已批准</v-chip>
          <v-chip value="rejected" filter color="error">已拒绝</v-chip>
          <v-chip value="offline" filter color="grey-darken-1">已下线</v-chip>
          <v-chip value="expired" filter color="grey">已过期</v-chip>
        </v-chip-group>

        <!-- 加载状态 -->
        <div v-if="loading" class="text-center my-4">
          <v-progress-circular indeterminate color="primary"></v-progress-circular>
          <div class="mt-2">加载中...</div>
        </div>

        <!-- 错误提示 -->
        <v-alert v-else-if="error" type="error" class="mb-4">
          {{ error }}
        </v-alert>

        <!-- 线路列表 -->
        <div v-else-if="filteredLines.length > 0">
          <v-list lines="three">
            <v-list-item
              v-for="line in filteredLines"
              :key="line.id"
              class="custom-line-item mb-3"
              @click="viewLineDetail(line)"
            >
              <template v-slot:prepend>
                <v-avatar :color="getStatusColor(line.status)">
                  <v-icon color="white">mdi-road-variant</v-icon>
                </v-avatar>
              </template>

              <v-list-item-title class="font-weight-bold">
                {{ line.domain }}
              </v-list-item-title>
              
              <v-list-item-subtitle>
                <div class="mt-1">
                  <v-chip size="x-small" :color="getStatusColor(line.status)" class="mr-2">
                    {{ getStatusText(line.status) }}
                  </v-chip>
                  <span class="text-caption">提交者ID: {{ line.tg_id }}</span>
                </div>
                <div class="mt-1 text-caption">
                  📡 {{ line.network_info }}
                </div>
                <div class="mt-1 text-caption">
                  💰 {{ formatPrice(line) }} | 📊 {{ formatTraffic(line) }} | 
                  ⏰ {{ formatValidity(line) }}
                </div>
              </v-list-item-subtitle>

              <template v-slot:append>
                <div class="d-flex flex-column">
                  <!-- 待审核状态 -->
                  <template v-if="line.status === 'pending'">
                    <v-btn
                      size="small"
                      color="success"
                      variant="tonal"
                      class="mb-2"
                      @click.stop="approveDialog(line)"
                    >
                      批准
                    </v-btn>
                    <v-btn
                      size="small"
                      color="error"
                      variant="tonal"
                      @click.stop="rejectDialog(line)"
                    >
                      拒绝
                    </v-btn>
                  </template>
                  <!-- 已批准状态 -->
                  <template v-else-if="line.status === 'approved'">
                    <v-btn
                      size="small"
                      color="warning"
                      variant="tonal"
                      class="mb-2"
                      @click.stop="offlineDialog(line)"
                    >
                      下线
                    </v-btn>
                    <v-btn
                      size="small"
                      color="primary"
                      variant="tonal"
                      @click.stop="viewLineDetail(line)"
                    >
                      详情
                    </v-btn>
                  </template>
                  <!-- 其他状态 -->
                  <template v-else>
                    <v-btn
                      size="small"
                      color="primary"
                      variant="tonal"
                      class="mb-2"
                      @click.stop="viewLineDetail(line)"
                    >
                      详情
                    </v-btn>
                    <v-btn
                      v-if="line.status !== 'offline'"
                      size="small"
                      color="error"
                      variant="tonal"
                      @click.stop="deleteDialog(line)"
                    >
                      删除
                    </v-btn>
                  </template>
                </div>
              </template>
            </v-list-item>
          </v-list>
        </div>

        <!-- 空状态 -->
        <v-alert v-else type="info" variant="tonal">
          暂无{{ selectedStatus === 'all' ? '' : getStatusText(selectedStatus) }}线路
        </v-alert>
      </v-card-text>
    </v-card>

    <!-- 审批对话框 -->
    <v-dialog v-model="showApprovalDialog" max-width="500" persistent>
      <v-card>
        <v-card-title :class="approvalAction === 'approve' ? 'bg-success' : 'bg-error'">
          <v-icon class="mr-2">
            {{ approvalAction === 'approve' ? 'mdi-check-circle' : 'mdi-close-circle' }}
          </v-icon>
          {{ approvalAction === 'approve' ? '批准' : '拒绝' }}线路
        </v-card-title>

        <v-card-text class="pt-4">
          <div class="mb-3">
            <strong>域名：</strong>{{ currentLine?.domain }}
          </div>
          <div class="mb-3">
            <strong>网络情况：</strong>{{ currentLine?.network_info }}
          </div>

          <v-textarea
            v-model="approvalNote"
            :label="approvalAction === 'approve' ? '批准备注（选填）' : '拒绝原因'"
            outlined
            dense
            rows="3"
            class="mb-3"
          ></v-textarea>

          <div v-if="approvalAction === 'approve'">
            <v-checkbox
              v-model="customValidity"
              label="自定义有效期"
              dense
              hide-details
              class="mb-2"
            ></v-checkbox>

            <div v-if="customValidity" class="ml-6">
              <v-checkbox
                v-model="isPermanent"
                label="长期可用"
                dense
                hide-details
                class="mb-2"
              ></v-checkbox>

              <v-text-field
                v-if="!isPermanent"
                v-model.number="validDays"
                label="有效天数"
                type="number"
                min="1"
                outlined
                dense
                hide-details
                suffix="天"
              ></v-text-field>
            </div>
          </div>
        </v-card-text>

        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showApprovalDialog = false" :disabled="submitting">
            取消
          </v-btn>
          <v-btn
            :color="approvalAction === 'approve' ? 'success' : 'error'"
            @click="submitApproval"
            :loading="submitting"
          >
            确认{{ approvalAction === 'approve' ? '批准' : '拒绝' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 详情对话框 -->
    <v-dialog v-model="showDetailDialog" max-width="600">
      <v-card v-if="currentLine">
        <v-card-title class="bg-primary">
          <v-icon class="mr-2">mdi-information</v-icon>
          线路详情
        </v-card-title>

        <v-card-text class="pt-4">
          <v-list dense>
            <v-list-item>
              <v-list-item-title>域名</v-list-item-title>
              <v-list-item-subtitle>{{ currentLine.domain }}</v-list-item-subtitle>
            </v-list-item>
            
            <v-list-item>
              <v-list-item-title>状态</v-list-item-title>
              <v-list-item-subtitle>
                <v-chip size="small" :color="getStatusColor(currentLine.status)">
                  {{ getStatusText(currentLine.status) }}
                </v-chip>
              </v-list-item-subtitle>
            </v-list-item>

            <v-list-item>
              <v-list-item-title>提交用户ID</v-list-item-title>
              <v-list-item-subtitle>{{ currentLine.tg_id }}</v-list-item-subtitle>
            </v-list-item>

            <v-list-item>
              <v-list-item-title>网络情况</v-list-item-title>
              <v-list-item-subtitle>{{ currentLine.network_info }}</v-list-item-subtitle>
            </v-list-item>

            <v-list-item>
              <v-list-item-title>价格</v-list-item-title>
              <v-list-item-subtitle>{{ formatPrice(currentLine) }}</v-list-item-subtitle>
            </v-list-item>

            <v-list-item>
              <v-list-item-title>流量</v-list-item-title>
              <v-list-item-subtitle>{{ formatTraffic(currentLine) }}</v-list-item-subtitle>
            </v-list-item>

            <v-list-item>
              <v-list-item-title>有效期</v-list-item-title>
              <v-list-item-subtitle>{{ formatValidity(currentLine) }}</v-list-item-subtitle>
            </v-list-item>

            <v-list-item v-if="currentLine.user_note">
              <v-list-item-title>用户备注</v-list-item-title>
              <v-list-item-subtitle>{{ currentLine.user_note }}</v-list-item-subtitle>
            </v-list-item>

            <v-list-item v-if="currentLine.admin_note">
              <v-list-item-title>管理员备注</v-list-item-title>
              <v-list-item-subtitle>{{ currentLine.admin_note }}</v-list-item-subtitle>
            </v-list-item>

            <v-list-item>
              <v-list-item-title>标签</v-list-item-title>
              <v-list-item-subtitle>
                <v-chip
                  v-for="tag in (currentLine.tags || [])"
                  :key="tag"
                  size="small"
                  color="primary"
                  class="mr-1"
                >
                  {{ tag }}
                </v-chip>
                <span v-if="!currentLine.tags || currentLine.tags.length === 0" class="text-grey">无标签</span>
              </v-list-item-subtitle>
            </v-list-item>

            <v-list-item>
              <v-list-item-title>创建时间</v-list-item-title>
              <v-list-item-subtitle>{{ formatTimestamp(currentLine.created_at) }}</v-list-item-subtitle>
            </v-list-item>

            <v-list-item v-if="currentLine.approved_at">
              <v-list-item-title>批准时间</v-list-item-title>
              <v-list-item-subtitle>{{ formatTimestamp(currentLine.approved_at) }}</v-list-item-subtitle>
            </v-list-item>
          </v-list>
        </v-card-text>

        <v-card-actions>
          <!-- 已批准状态：显示下线按钮 -->
          <v-btn
            v-if="currentLine.status === 'approved'"
            size="small"
            color="warning"
            variant="tonal"
            @click="offlineDialog(currentLine)"
          >
            <v-icon start size="small">mdi-pause-circle</v-icon>
            下线
          </v-btn>
          <!-- 其他状态（除了 offline）：显示删除按钮 -->
          <v-btn
            v-if="currentLine.status !== 'approved' && currentLine.status !== 'offline'"
            size="small"
            color="error"
            variant="tonal"
            @click="deleteDialog(currentLine)"
          >
            <v-icon start size="small">mdi-delete</v-icon>
            删除
          </v-btn>
          <!-- 所有状态都可以管理标签 -->
          <v-btn
            size="small"
            color="primary"
            variant="tonal"
            @click="editTagsDialog(currentLine)"
          >
            <v-icon start size="small">mdi-tag-multiple</v-icon>
            管理标签
          </v-btn>
          <v-spacer></v-spacer>
          <v-btn text @click="showDetailDialog = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 标签编辑对话框 -->
    <v-dialog v-model="showTagsDialog" max-width="500" persistent>
      <v-card>
        <v-card-title class="bg-primary">
          <v-icon class="mr-2">mdi-tag-multiple</v-icon>
          管理标签
        </v-card-title>

        <v-card-text class="pt-4">
          <div class="mb-3">
            <strong>线路域名：</strong>{{ currentLine?.domain }}
          </div>

          <v-combobox
            v-model="editingTags"
            label="标签"
            multiple
            chips
            closable-chips
            outlined
            dense
            hint="输入后按回车添加标签"
            persistent-hint
          >
            <template v-slot:selection="{ item, index }">
              <v-chip
                size="small"
                closable
                @click:close="removeTag(index)"
              >
                {{ item.title || item }}
              </v-chip>
            </template>
          </v-combobox>
        </v-card-text>

        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showTagsDialog = false" :disabled="submittingTags">
            取消
          </v-btn>
          <v-btn
            color="primary"
            @click="submitTags"
            :loading="submittingTags"
          >
            保存
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 下线确认对话框 -->
    <v-dialog v-model="showOfflineDialog" max-width="500" persistent>
      <v-card>
        <v-card-title class="bg-warning">
          <v-icon class="mr-2">mdi-pause-circle</v-icon>
          下线线路
        </v-card-title>

        <v-card-text class="pt-4">
          <v-alert type="warning" variant="tonal" class="mb-3">
            下线后将自动解除所有用户对该线路的绑定！
          </v-alert>
          
          <div class="mb-3">
            <strong>线路域名：</strong>{{ currentLine?.domain }}
          </div>
          <div class="mb-3">
            <strong>网络情况：</strong>{{ currentLine?.network_info }}
          </div>
          
          <p class="text-body-2">确定要下线此线路吗？下线后线路所有者可以重新上线。</p>
        </v-card-text>

        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showOfflineDialog = false" :disabled="submittingOffline">
            取消
          </v-btn>
          <v-btn
            color="warning"
            @click="submitOffline"
            :loading="submittingOffline"
          >
            确认下线
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 删除确认对话框 -->
    <v-dialog v-model="showDeleteDialog" max-width="500" persistent>
      <v-card>
        <v-card-title class="bg-error">
          <v-icon class="mr-2">mdi-delete</v-icon>
          删除线路
        </v-card-title>

        <v-card-text class="pt-4">
          <v-alert type="error" variant="tonal" class="mb-3">
            删除操作不可撤销！
          </v-alert>
          
          <div class="mb-3">
            <strong>线路域名：</strong>{{ currentLine?.domain }}
          </div>
          <div class="mb-3">
            <strong>网络情况：</strong>{{ currentLine?.network_info }}
          </div>
          
          <p class="text-body-2">确定要从数据库中删除此线路吗？此操作不可撤销！</p>
        </v-card-text>

        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showDeleteDialog = false" :disabled="submittingDelete">
            取消
          </v-btn>
          <v-btn
            color="error"
            @click="submitDelete"
            :loading="submittingDelete"
          >
            确认删除
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script>
import { adminGetAllCustomLines, adminApproveCustomLine, adminOfflineCustomLine, adminDeleteCustomLine, adminSetCustomLineTags } from '../services/customLineService'

export default {
  name: 'CustomLineManagement',
  data() {
    return {
      loading: false,
      error: '',
      lines: [],
      selectedStatus: 'all',
      showApprovalDialog: false,
      showDetailDialog: false,
      showTagsDialog: false,
      showOfflineDialog: false,
      showDeleteDialog: false,
      currentLine: null,
      approvalAction: 'approve',
      approvalNote: '',
      customValidity: false,
      isPermanent: false,
      validDays: null,
      submitting: false,
      editingTags: [],
      submittingTags: false,
      submittingOffline: false,
      submittingDelete: false
    }
  },
  computed: {
    filteredLines() {
      if (this.selectedStatus === 'all') {
        return this.lines
      }
      return this.lines.filter(line => line.status === this.selectedStatus)
    }
  },
  mounted() {
    this.loadLines()
  },
  methods: {
    async loadLines() {
      this.loading = true
      this.error = ''
      
      try {
        const response = await adminGetAllCustomLines()
        if (response.success) {
          this.lines = response.lines || []
        } else {
          this.error = response.message || '加载失败'
        }
      } catch (error) {
        console.error('加载自定义线路失败:', error)
        this.error = error.response?.data?.detail || error.response?.data?.message || '加载失败'
      } finally {
        this.loading = false
      }
    },
    
    approveDialog(line) {
      this.currentLine = line
      this.approvalAction = 'approve'
      this.approvalNote = ''
      this.customValidity = false
      this.isPermanent = false
      this.validDays = null
      this.showApprovalDialog = true
    },
    
    rejectDialog(line) {
      this.currentLine = line
      this.approvalAction = 'reject'
      this.approvalNote = ''
      this.showApprovalDialog = true
    },
    
    async submitApproval() {
      this.submitting = true
      
      try {
        const data = {
          action: this.approvalAction,
          admin_note: this.approvalNote || undefined
        }
        
        if (this.approvalAction === 'approve' && this.customValidity) {
          data.is_permanent = this.isPermanent
          if (!this.isPermanent && this.validDays) {
            data.valid_days = this.validDays
          }
        }
        
        const response = await adminApproveCustomLine(this.currentLine.id, data)
        
        if (response.success) {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '操作成功')
          }
          
          this.showApprovalDialog = false
          await this.loadLines()
        } else {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '操作失败')
          }
        }
      } catch (error) {
        console.error('审批失败:', error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.message || '操作失败'
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.showAlert(errorMsg)
        }
      } finally {
        this.submitting = false
      }
    },
    
    viewLineDetail(line) {
      this.currentLine = line
      this.showDetailDialog = true
    },
    
    editTagsDialog(line) {
      this.currentLine = line
      this.editingTags = [...(line.tags || [])]
      this.showTagsDialog = true
    },
    
    removeTag(index) {
      this.editingTags.splice(index, 1)
    },
    
    async submitTags() {
      this.submittingTags = true
      
      try {
        const response = await adminSetCustomLineTags(this.currentLine.id, this.editingTags)
        
        if (response.success) {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert('标签更新成功')
          }
          
          this.showTagsDialog = false
          await this.loadLines()
        } else {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '标签更新失败')
          }
        }
      } catch (error) {
        console.error('更新标签失败:', error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.message || '标签更新失败'
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.showAlert(errorMsg)
        }
      } finally {
        this.submittingTags = false
      }
    },
    
    offlineDialog(line) {
      this.currentLine = line
      this.showOfflineDialog = true
    },
    
    deleteDialog(line) {
      this.currentLine = line
      this.showDeleteDialog = true
    },
    
    async submitOffline() {
      this.submittingOffline = true
      
      try {
        const response = await adminOfflineCustomLine(this.currentLine.id)
        
        if (response.success) {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '线路已下线')
          }
          
          this.showOfflineDialog = false
          this.showDetailDialog = false
          await this.loadLines()
        } else {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '下线失败')
          }
        }
      } catch (error) {
        console.error('下线失败:', error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.message || '下线失败'
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.showAlert(errorMsg)
        }
      } finally {
        this.submittingOffline = false
      }
    },
    
    async submitDelete() {
      this.submittingDelete = true
      
      try {
        const response = await adminDeleteCustomLine(this.currentLine.id)
        
        if (response.success) {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '线路已删除')
          }
          
          this.showDeleteDialog = false
          this.showDetailDialog = false
          await this.loadLines()
        } else {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '删除失败')
          }
        }
      } catch (error) {
        console.error('删除失败:', error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.message || '删除失败'
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.showAlert(errorMsg)
        }
      } finally {
        this.submittingDelete = false
      }
    },
    
    getStatusColor(status) {
      const colors = {
        pending: 'orange',
        approved: 'success',
        rejected: 'error',
        expired: 'grey',
        offline: 'grey-darken-1'
      }
      return colors[status] || 'grey'
    },
    
    getStatusText(status) {
      const texts = {
        pending: '待审核',
        approved: '已批准',
        rejected: '已拒绝',
        expired: '已过期',
        offline: '已下线'
      }
      return texts[status] || status
    },
    
    formatPrice(line) {
      const prices = []
      if (line.price_monthly) {
        prices.push(`月付 ¥${line.price_monthly}`)
      }
      if (line.price_yearly) {
        prices.push(`年付 ¥${line.price_yearly}`)
      }
      return prices.length > 0 ? prices.join(' / ') : '未提供'
    },
    
    formatTraffic(line) {
      const parts = []
      const type = line.traffic_type === 'one_way' ? '单向' : '双向'
      
      if (line.traffic_limit) {
        parts.push(`月限 ${line.traffic_limit}GB`)
      }
      if (line.total_traffic) {
        parts.push(`总量 ${line.total_traffic}GB`)
      }
      
      if (parts.length === 0) return '未提供'
      return `${parts.join(' | ')} (${type})`
    },
    
    formatValidity(line) {
      if (line.is_permanent) return '长期可用'
      if (line.valid_days) return `${line.valid_days}天`
      return '未设置'
    },
    
    formatTimestamp(timestamp) {
      if (!timestamp) return '-'
      const date = new Date(timestamp * 1000)
      return date.toLocaleString('zh-CN')
    }
  }
}
</script>

<style scoped>
.custom-line-management {
  width: 100%;
}

.custom-line-item {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  background: #fafafa;
  transition: all 0.3s;
}

.custom-line-item:hover {
  background: #f5f5f5;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

/* 美化后的管理卡片样式 - 与 Management.vue 一致 */
.admin-card-enhanced {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  padding: 30px 24px;
  text-align: center;
  box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(15px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  transition: all 0.3s ease;
}

.admin-card-enhanced:hover {
  transform: translateY(-8px);
  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2);
  background: rgba(255, 255, 255, 0.98);
}

/* 卡片标题样式 */
.admin-card-enhanced :deep(.v-card-title) {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
  backdrop-filter: blur(10px);
  border-radius: 16px 16px 0 0;
  border-bottom: 1px solid rgba(102, 126, 234, 0.2);
  font-weight: 600;
  color: #333;
  padding: 16px 24px;
  margin: -30px -24px 20px;
}
</style>
