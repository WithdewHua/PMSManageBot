<template>
  <v-dialog v-model="showDialog" max-width="700" persistent>
    <v-card>
      <v-card-title class="headline d-flex align-center">
        <v-icon class="mr-2" color="primary">mdi-road-variant</v-icon>
        自定义线路
      </v-card-title>
      
      <v-tabs v-model="activeTab" grow>
        <v-tab value="my-lines">我的线路</v-tab>
        <v-tab value="submit">提交新线路</v-tab>
      </v-tabs>

      <v-card-text class="pa-0">
        <v-tabs-window v-model="activeTab">
          <!-- 我的线路列表 -->
          <v-tabs-window-item value="my-lines">
            <div class="pa-4">
              <!-- 加载状态 -->
              <div v-if="loadingLines" class="text-center my-4">
                <v-progress-circular indeterminate color="primary"></v-progress-circular>
                <div class="mt-2">加载中...</div>
              </div>

              <!-- 线路列表 -->
              <div v-else-if="myLines.length > 0">
                <v-list lines="three">
                  <v-list-item
                    v-for="line in myLines"
                    :key="line.id"
                    class="custom-line-item mb-3"
                  >
                    <template v-slot:prepend>
                      <v-avatar :color="getStatusColor(line.status)" size="40">
                        <v-icon color="white" size="20">mdi-road-variant</v-icon>
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
                      </div>
                      <div class="mt-1 text-caption">
                        📡 {{ line.network_info }}
                      </div>
                      <div class="mt-1 text-caption">
                        💰 {{ formatPrice(line) }} | 📊 {{ formatTraffic(line) }}
                      </div>
                      <div class="mt-1 text-caption">
                        ⏰ {{ formatValidity(line) }}
                        <span v-if="line.expires_at && (line.status === 'approved' || line.status === 'expired')">
                          （到期：{{ formatTimestamp(line.expires_at) }}）
                        </span>
                      </div>
                      <div v-if="line.admin_note" class="mt-1 text-caption text-error">
                        💬 备注：{{ line.admin_note }}
                      </div>
                    </v-list-item-subtitle>

                    <template v-slot:append>
                      <div class="d-flex flex-column">
                        <!-- 已上线状态：显示续期和下线按钮 -->
                        <template v-if="line.status === 'approved'">
                          <v-btn
                            v-if="!line.is_permanent"
                            size="small"
                            color="primary"
                            variant="tonal"
                            class="mb-2"
                            @click="showRenewDialog(line)"
                          >
                            续期
                          </v-btn>
                          <v-btn
                            size="small"
                            color="warning"
                            variant="tonal"
                            @click="showOfflineDialog(line)"
                          >
                            下线
                          </v-btn>
                        </template>
                        
                        <!-- 已过期状态：显示续期和删除按钮 -->
                        <template v-else-if="line.status === 'expired'">
                          <v-btn
                            size="small"
                            color="primary"
                            variant="tonal"
                            class="mb-2"
                            @click="showRenewDialog(line)"
                          >
                            续期
                          </v-btn>
                          <v-btn
                            size="small"
                            color="error"
                            variant="tonal"
                            @click="showDeleteDialog(line)"
                          >
                            删除
                          </v-btn>
                        </template>
                        
                        <!-- 已下线状态：显示上线和删除按钮 -->
                        <template v-else-if="line.status === 'offline'">
                          <v-btn
                            size="small"
                            color="success"
                            variant="tonal"
                            class="mb-2"
                            @click="showOnlineDialog(line)"
                          >
                            上线
                          </v-btn>
                          <v-btn
                            size="small"
                            color="error"
                            variant="tonal"
                            @click="showDeleteDialog(line)"
                          >
                            删除
                          </v-btn>
                        </template>
                        
                        <!-- 其他状态：只显示删除按钮 -->
                        <template v-else>
                          <v-btn
                            size="small"
                            color="error"
                            variant="tonal"
                            @click="showDeleteDialog(line)"
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
                您还没有提交过自定义线路，点击"提交新线路"标签页开始提交
              </v-alert>
            </div>
          </v-tabs-window-item>

          <!-- 提交新线路表单 -->
          <v-tabs-window-item value="submit">
            <div class="pa-4">
              <v-alert type="info" variant="tonal" density="compact" class="mb-4">
                <div>1. 请确保域名中包含 <strong>funmedia</strong>，以便匹配分流规则</div>
                <div class="mt-1">2. 提交后需等待管理员审核</div>
              </v-alert>
              <v-form ref="form" v-model="valid" lazy-validation>
          <!-- 域名 -->
          <v-text-field
            v-model="formData.domain"
            label="线路域名 *"
            :rules="domainRules"
            required
            outlined
            dense
            hide-details="auto"
            class="mb-3"
            placeholder="例如：hk.funmedia.example.com"
          ></v-text-field>

          <!-- 三网线路情况 -->
          <v-textarea
            v-model="formData.network_info"
            label="三网线路情况 *"
            :rules="networkInfoRules"
            required
            outlined
            dense
            hide-details="auto"
            class="mb-3"
            rows="3"
            placeholder="请描述电信/联通/移动的线路情况，如：电信CN2 GIA，联通AS9929，移动CMI直连"
          ></v-textarea>

          <!-- 价格信息 -->
          <div class="mb-3">
            <div class="text-subtitle-2 mb-2">价格信息（至少填写一项）</div>
            <v-row>
              <v-col cols="6">
                <v-text-field
                  v-model.number="formData.price_monthly"
                  label="月付价格"
                  type="number"
                  min="0"
                  step="0.01"
                  outlined
                  dense
                  hide-details="auto"
                  prefix="¥"
                  placeholder="0.00"
                ></v-text-field>
              </v-col>
              <v-col cols="6">
                <v-text-field
                  v-model.number="formData.price_yearly"
                  label="年付价格"
                  type="number"
                  min="0"
                  step="0.01"
                  outlined
                  dense
                  hide-details="auto"
                  prefix="¥"
                  placeholder="0.00"
                ></v-text-field>
              </v-col>
            </v-row>
          </div>

          <!-- 流量信息 -->
          <div class="mb-3">
            <div class="text-subtitle-2 mb-2">每月流量</div>
            <v-row>
              <v-col cols="6">
                <v-text-field
                  v-model.number="formData.traffic_limit"
                  label="流量限制 (GB)"
                  type="number"
                  min="0"
                  step="1"
                  outlined
                  dense
                  hide-details="auto"
                  suffix="GB"
                  placeholder="1000"
                ></v-text-field>
              </v-col>
              <v-col cols="6">
                <v-select
                  v-model="formData.traffic_type"
                  label="流量计算方式"
                  :items="trafficTypes"
                  outlined
                  dense
                  hide-details="auto"
                ></v-select>
              </v-col>
            </v-row>
          </div>

          <!-- 可用时间 -->
          <div class="mb-3">
            <div class="d-flex align-center mb-2">
              <div class="text-subtitle-2">可用时间</div>
              <v-checkbox
                v-model="formData.is_permanent"
                label="长期可用"
                dense
                hide-details
                class="ml-4 mt-0"
              ></v-checkbox>
            </div>
            <v-text-field
              v-if="!formData.is_permanent"
              v-model.number="formData.valid_days"
              label="有效天数"
              type="number"
              min="1"
              step="1"
              outlined
              dense
              hide-details="auto"
              suffix="天"
              placeholder="30"
            ></v-text-field>
          </div>

          <!-- 备注 -->
          <v-textarea
            v-model="formData.user_note"
            label="备注（选填）"
            outlined
            dense
            hide-details="auto"
            rows="2"
            class="mb-3"
            placeholder="其他需要说明的信息"
          ></v-textarea>

          <v-alert
            v-if="errorMessage"
            type="error"
            dense
            dismissible
            class="mb-3"
          >
            {{ errorMessage }}
          </v-alert>
        </v-form>
            </div>
          </v-tabs-window-item>
        </v-tabs-window>
      </v-card-text>

      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn
          text
          @click="closeDialog"
          :disabled="submitting"
        >
          取消
        </v-btn>
        <v-btn
          v-if="activeTab === 'submit'"
          color="primary"
          @click="submitCustomLine"
          :loading="submitting"
          :disabled="!valid || submitting"
        >
          提交
        </v-btn>
      </v-card-actions>
    </v-card>

    <!-- 续期对话框 -->
    <v-dialog v-model="showRenewDialogVisible" max-width="400" persistent>
      <v-card>
        <v-card-title class="bg-primary">
          <v-icon class="mr-2">mdi-clock-plus</v-icon>
          续期线路
        </v-card-title>

        <v-card-text class="pt-4">
          <div class="mb-3">
            <strong>线路域名：</strong>{{ currentLine?.domain }}
          </div>
          <div v-if="currentLine?.expires_at" class="mb-3">
            <strong>当前过期时间：</strong>{{ formatTimestamp(currentLine.expires_at) }}
          </div>

          <v-text-field
            v-model.number="renewDays"
            label="续期天数"
            type="number"
            min="1"
            step="1"
            outlined
            dense
            suffix="天"
          ></v-text-field>
        </v-card-text>

        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showRenewDialogVisible = false" :disabled="renewLoading">
            取消
          </v-btn>
          <v-btn
            color="primary"
            @click="submitRenew"
            :loading="renewLoading"
            :disabled="!renewDays || renewDays < 1"
          >
            确认续期
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 下线确认对话框 -->
    <v-dialog v-model="showOfflineDialogVisible" max-width="400" persistent>
      <v-card>
        <v-card-title class="bg-warning">
          <v-icon class="mr-2">mdi-pause-circle</v-icon>
          下线线路
        </v-card-title>

        <v-card-text class="pt-4">
          <v-alert type="warning" variant="tonal" class="mb-3">
            下线后将解除所有用户对该线路的绑定！
          </v-alert>
          
          <div class="mb-3">
            <strong>线路域名：</strong>{{ currentLine?.domain }}
          </div>
          
          <p class="text-body-2">确定要下线此线路吗？下线后您可以随时重新上线。</p>
        </v-card-text>

        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showOfflineDialogVisible = false" :disabled="offlineLoading">
            取消
          </v-btn>
          <v-btn
            color="warning"
            @click="submitOffline"
            :loading="offlineLoading"
          >
            确认下线
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 删除确认对话框 -->
    <v-dialog v-model="showDeleteDialogVisible" max-width="400" persistent>
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
            <strong>当前状态：</strong>{{ getStatusText(currentLine?.status) }}
          </div>
          
          <p class="text-body-2">确定要删除此线路吗？此操作不可撤销！</p>
        </v-card-text>

        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="showDeleteDialogVisible = false" :disabled="deleteLoading">
            取消
          </v-btn>
          <v-btn
            color="error"
            @click="submitDelete"
            :loading="deleteLoading"
          >
            确认删除
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 上线对话框 -->
    <v-dialog v-model="showOnlineDialogVisible" max-width="500" persistent>
      <v-card>
        <v-card-title class="bg-success">
          <v-icon class="mr-2">mdi-play-circle</v-icon>
          上线线路
        </v-card-title>

        <v-card-text class="pt-4">
          <div class="mb-3">
            <strong>线路域名：</strong>{{ currentLine?.domain }}
          </div>
          
          <v-divider class="my-3"></v-divider>
          
          <div class="text-subtitle-2 mb-2">可选：修改线路配置</div>
          
          <v-text-field
            v-model.number="onlineData.traffic_limit"
            label="流量限制 (GB)"
            type="number"
            min="0"
            outlined
            dense
            clearable
            hint="留空表示不限制"
            persistent-hint
            class="mb-3"
          ></v-text-field>

          <v-checkbox
            v-model="onlineData.is_permanent"
            label="长期可用"
            dense
            hide-details
            class="mb-2"
          ></v-checkbox>

          <v-text-field
            v-if="!onlineData.is_permanent"
            v-model.number="onlineData.valid_days"
            label="有效天数"
            type="number"
            min="1"
            outlined
            dense
            suffix="天"
            hint="从上线时间开始计算"
            persistent-hint
          ></v-text-field>
        </v-card-text>

        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="closeOnlineDialog" :disabled="onlineLoading">
            取消
          </v-btn>
          <v-btn
            color="success"
            @click="submitOnline"
            :loading="onlineLoading"
          >
            确认上线
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-dialog>
</template>

<script>
import { getMyCustomLines, deleteCustomLine, offlineCustomLine, onlineCustomLine, renewCustomLine, submitCustomLine } from '../services/customLineService'

export default {
  name: 'SubmitCustomLineDialog',
  data() {
    return {
      showDialog: false,
      activeTab: 'my-lines',
      valid: false,
      submitting: false,
      errorMessage: '',
      // 我的线路相关
      loadingLines: false,
      myLines: [],
      // 续期相关
      showRenewDialogVisible: false,
      renewDays: 30,
      renewLoading: false,
      currentLine: null,
      // 下线相关
      showOfflineDialogVisible: false,
      offlineLoading: false,
      // 删除相关
      showDeleteDialogVisible: false,
      deleteLoading: false,
      // 上线相关
      showOnlineDialogVisible: false,
      onlineLoading: false,
      onlineData: {
        traffic_limit: null,
        valid_days: null,
        is_permanent: false
      },
      // 表单数据
      formData: {
        domain: '',
        network_info: '',
        price_monthly: null,
        price_yearly: null,
        traffic_limit: null,
        traffic_type: 'one_way',
        valid_days: null,
        is_permanent: false,
        user_note: ''
      },
      trafficTypes: [
        { title: '单向流量', value: 'one_way' },
        { title: '双向流量', value: 'two_way' }
      ],
      domainRules: [
        v => !!v || '请输入线路域名',
        v => (v && v.length >= 1 && v.length <= 255) || '域名长度应在1-255字符之间'
      ],
      networkInfoRules: [
        v => !!v || '请描述三网线路情况',
        v => (v && v.length >= 1 && v.length <= 500) || '描述长度应在1-500字符之间'
      ]
    }
  },
  methods: {
    open() {
      this.showDialog = true
      this.activeTab = 'my-lines'
      this.resetForm()
      this.loadMyLines()
    },
    closeDialog() {
      this.showDialog = false
      this.resetForm()
    },
    resetForm() {
      this.errorMessage = ''
      this.formData = {
        domain: '',
        network_info: '',
        price_monthly: null,
        price_yearly: null,
        traffic_limit: null,
        traffic_type: 'one_way',
        valid_days: null,
        is_permanent: false,
        user_note: ''
      }
      if (this.$refs.form) {
        this.$refs.form.resetValidation()
      }
    },
    async loadMyLines() {
      this.loadingLines = true
      try {
        const response = await getMyCustomLines()
        if (response.success) {
          this.myLines = response.lines || []
        } else {
          this.myLines = []
        }
      } catch (error) {
        console.error('加载我的线路失败:', error)
        this.myLines = []
      } finally {
        this.loadingLines = false
      }
    },
    // 续期相关
    showRenewDialog(line) {
      this.currentLine = line
      this.renewDays = 30
      this.showRenewDialogVisible = true
    },
    async submitRenew() {
      if (!this.renewDays || this.renewDays < 1) return
      
      this.renewLoading = true
      try {
        const response = await renewCustomLine(this.currentLine.id, this.renewDays)
        
        if (response.success) {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '续期成功')
          } else {
            alert(response.message || '续期成功')
          }
          this.showRenewDialogVisible = false
          await this.loadMyLines()
        } else {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '续期失败')
          } else {
            alert(response.message || '续期失败')
          }
        }
      } catch (error) {
        console.error('续期失败:', error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.message || '续期失败'
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.showAlert(errorMsg)
        } else {
          alert(errorMsg)
        }
      } finally {
        this.renewLoading = false
      }
    },
    // 下线相关
    showOfflineDialog(line) {
      this.currentLine = line
      this.showOfflineDialogVisible = true
    },
    async submitOffline() {
      this.offlineLoading = true
      try {
        const response = await offlineCustomLine(this.currentLine.id)
        
        if (response.success) {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '下线成功')
          } else {
            alert(response.message || '下线成功')
          }
          this.showOfflineDialogVisible = false
          this.$emit('submitted')
          await this.loadMyLines()
        } else {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '下线失败')
          } else {
            alert(response.message || '下线失败')
          }
        }
      } catch (error) {
        console.error('下线失败:', error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.message || '下线失败'
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.showAlert(errorMsg)
        } else {
          alert(errorMsg)
        }
      } finally {
        this.offlineLoading = false
      }
    },
    // 删除相关
    showDeleteDialog(line) {
      this.currentLine = line
      this.showDeleteDialogVisible = true
    },
    async submitDelete() {
      this.deleteLoading = true
      try {
        const response = await deleteCustomLine(this.currentLine.id)
        
        if (response.success) {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '删除成功')
          } else {
            alert(response.message || '删除成功')
          }
          this.showDeleteDialogVisible = false
          this.$emit('submitted')
          await this.loadMyLines()
        } else {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '删除失败')
          } else {
            alert(response.message || '删除失败')
          }
        }
      } catch (error) {
        console.error('删除失败:', error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.message || '删除失败'
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.showAlert(errorMsg)
        } else {
          alert(errorMsg)
        }
      } finally {
        this.deleteLoading = false
      }
    },
    // 上线相关
    showOnlineDialog(line) {
      this.currentLine = line
      // 预填充当前线路的配置
      this.onlineData = {
        traffic_limit: line.traffic_limit,
        valid_days: line.valid_days,
        is_permanent: line.is_permanent
      }
      this.showOnlineDialogVisible = true
    },
    closeOnlineDialog() {
      this.showOnlineDialogVisible = false
      this.onlineData = {
        traffic_limit: null,
        valid_days: null,
        is_permanent: false
      }
    },
    async submitOnline() {
      this.onlineLoading = true
      try {
        // 构造上线数据，只发送用户修改的字段
        const payload = {}
        if (this.onlineData.traffic_limit !== null && this.onlineData.traffic_limit !== undefined) {
          payload.traffic_limit = this.onlineData.traffic_limit
        }
        if (this.onlineData.is_permanent) {
          payload.is_permanent = true
        } else if (this.onlineData.valid_days) {
          payload.valid_days = this.onlineData.valid_days
        }
        
        const response = await onlineCustomLine(this.currentLine.id, payload)
        
        if (response.success) {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '上线成功')
          } else {
            alert(response.message || '上线成功')
          }
          this.closeOnlineDialog()
          this.$emit('submitted')
          await this.loadMyLines()
        } else {
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '上线失败')
          } else {
            alert(response.message || '上线失败')
          }
        }
      } catch (error) {
        console.error('上线失败:', error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.message || '上线失败'
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.showAlert(errorMsg)
        } else {
          alert(errorMsg)
        }
      } finally {
        this.onlineLoading = false
      }
    },
    // 辅助方法
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
      if (!line.traffic_limit) return '未提供'
      const type = line.traffic_type === 'one_way' ? '单向' : '双向'
      return `${line.traffic_limit}GB (${type})`
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
    },
    async submitCustomLine() {
      if (!this.$refs.form.validate()) {
        return
      }

      // 验证价格信息：至少填写一项
      if (!this.formData.price_monthly && !this.formData.price_yearly) {
        this.errorMessage = '请至少填写月付价格或年付价格'
        return
      }

      // 验证有效期：如果不是长期可用，必须填写天数
      if (!this.formData.is_permanent && !this.formData.valid_days) {
        this.errorMessage = '请填写有效天数或勾选长期可用'
        return
      }

      this.submitting = true
      this.errorMessage = ''

      try {
        // 构造提交数据，确保类型正确
        const submitData = {
          ...this.formData,
          // 如果是长期可用，valid_days 设为 null
          valid_days: this.formData.is_permanent ? null : this.formData.valid_days
        }
        const response = await submitCustomLine(submitData)
        
        if (response.success) {
          // 显示成功消息
          if (window.Telegram?.WebApp) {
            window.Telegram.WebApp.showAlert(response.message || '提交成功！请等待管理员审核')
          } else {
            alert(response.message || '提交成功！请等待管理员审核')
          }
          
          // 触发提交成功事件
          this.$emit('submitted')
          this.resetForm()
          this.activeTab = 'my-lines'
          await this.loadMyLines()
        } else {
          this.errorMessage = response.message || '提交失败'
        }
      } catch (error) {
        console.error('提交自定义线路失败:', error)
        this.errorMessage = error.response?.data?.detail || error.response?.data?.message || '提交失败，请稍后重试'
      } finally {
        this.submitting = false
      }
    }
  }
}
</script>

<style scoped>
.headline {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.text-subtitle-2 {
  font-weight: 600;
  color: rgba(0, 0, 0, 0.87);
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

.bg-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.bg-error {
  background: linear-gradient(135deg, #f44336 0%, #e91e63 100%);
  color: white;
}
</style>
