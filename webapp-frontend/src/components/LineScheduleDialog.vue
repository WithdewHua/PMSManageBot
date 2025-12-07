<template>
  <v-dialog v-model="showDialog" max-width="900" scrollable>
    <v-card>
      <v-card-title class="headline d-flex justify-space-between align-center">
        <div class="d-flex align-center">
          <v-icon left color="purple">mdi-calendar-clock</v-icon>
          <span>线路调度管理</span>
        </div>
        <v-chip :color="unlockStatus.is_unlocked ? 'success' : 'warning'" small>
          {{ unlockStatus.is_unlocked ? '已解锁' : '未解锁' }}
        </v-chip>
      </v-card-title>

      <v-divider></v-divider>

      <v-card-text class="pa-4">
        <!-- 未解锁状态 -->
        <v-alert
          v-if="!unlockStatus.is_unlocked"
          type="info"
          prominent
          border="left"
          class="mb-4"
        >
          <div class="d-flex align-center justify-space-between">
            <div>
              <div class="text-h6 mb-2">解锁线路调度功能</div>
              <div>
                线路调度功能允许您为不同时间段自动切换线路，优化观看体验。
                <br />
                解锁需要消耗 <strong>{{ unlockStatus.unlock_credits }}</strong> 积分
                <span v-if="unlockStatus.is_premium" class="ml-2 success--text">
                  （Premium 用户免费）
                </span>
              </div>
            </div>
            <v-btn
              color="primary"
              @click="unlockFeature"
              :loading="unlocking"
            >
              <v-icon left>mdi-lock-open</v-icon>
              解锁功能
            </v-btn>
          </div>
        </v-alert>

        <!-- 已解锁状态 - 直接显示高级调度配置 -->
        <div v-else>
          <!-- 当前生效的调度 -->
          <v-card v-if="activeSchedule" outlined color="success" class="mb-4">
            <v-card-subtitle class="pb-2 white--text">
              <v-icon small class="mr-1" color="white">mdi-check-circle</v-icon>
              当前生效的调度
            </v-card-subtitle>
            <v-card-text class="white--text">
              <div class="d-flex align-center">
                <v-chip color="white" small class="mr-2">
                  {{ activeSchedule.line }}
                </v-chip>
                <span>
                  {{ formatDaysOfWeek(activeSchedule.days_of_week) }}
                  {{ activeSchedule.start_time }} - {{ activeSchedule.end_time }}
                </span>
              </div>
            </v-card-text>
          </v-card>

          <!-- 调度列表 -->
          <v-card outlined class="mb-4 schedule-list-card">
            <v-card-subtitle class="pb-2 d-flex justify-space-between align-center schedule-header">
              <span class="schedule-title">
                <v-icon small class="mr-1">mdi-format-list-bulleted</v-icon>
                调度规则列表
              </span>
              <v-btn
                color="primary"
                small
                @click="openCreateDialog"
                :disabled="false"
                elevation="2"
              >
                <v-icon left small>mdi-plus</v-icon>
                添加调度
              </v-btn>
            </v-card-subtitle>
            <v-divider></v-divider>
            <v-card-text class="pa-0">
              <div v-if="schedules.length > 0" class="schedules-container">
                <v-card
                  v-for="schedule in schedules"
                  :key="schedule.id"
                  class="schedule-item"
                  :class="{ 'schedule-disabled': !schedule.is_enabled }"
                  elevation="0"
                  outlined
                >
                  <!-- 左侧线路标识 -->
                  <div class="schedule-line-indicator" :style="{ backgroundColor: schedule.is_enabled ? '#9333ea' : '#9e9e9e' }"></div>
                  
                  <div class="schedule-content">
                    <!-- 顶部：线路和状态 -->
                    <div class="schedule-top">
                      <div class="d-flex align-center flex-wrap gap-2">
                        <v-chip 
                          :color="schedule.is_enabled ? 'purple' : 'grey'" 
                          dark 
                          size="small"
                          class="schedule-line-chip"
                        >
                          <v-icon left size="x-small">mdi-router-wireless</v-icon>
                          {{ schedule.line }}
                        </v-chip>
                        <v-chip 
                          size="x-small" 
                          :color="schedule.is_enabled ? 'success' : 'grey lighten-1'"
                          variant="flat"
                        >
                          <v-icon left size="x-small">
                            {{ schedule.is_enabled ? 'mdi-check-circle' : 'mdi-pause-circle' }}
                          </v-icon>
                          {{ schedule.is_enabled ? '已启用' : '已禁用' }}
                        </v-chip>
                      </div>
                      
                      <!-- 操作按钮 -->
                      <div class="schedule-actions">
                        <v-tooltip location="top">
                          <template v-slot:activator="{ props }">
                            <v-btn
                              v-bind="props"
                              icon
                              size="small"
                              variant="text"
                              @click="toggleSchedule(schedule)"
                            >
                              <v-icon 
                                size="small" 
                                :color="schedule.is_enabled ? 'success' : 'grey'"
                              >
                                {{ schedule.is_enabled ? 'mdi-toggle-switch' : 'mdi-toggle-switch-off' }}
                              </v-icon>
                            </v-btn>
                          </template>
                          <span>{{ schedule.is_enabled ? '禁用' : '启用' }}</span>
                        </v-tooltip>
                        
                        <v-tooltip location="top">
                          <template v-slot:activator="{ props }">
                            <v-btn
                              v-bind="props"
                              icon
                              size="small"
                              variant="text"
                              @click="editSchedule(schedule)"
                            >
                              <v-icon size="small" color="primary">mdi-pencil</v-icon>
                            </v-btn>
                          </template>
                          <span>编辑</span>
                        </v-tooltip>
                        
                        <v-tooltip location="top">
                          <template v-slot:activator="{ props }">
                            <v-btn
                              v-bind="props"
                              icon
                              size="small"
                              variant="text"
                              @click="deleteSchedule(schedule)"
                            >
                              <v-icon size="small" color="error">mdi-delete</v-icon>
                            </v-btn>
                          </template>
                          <span>删除</span>
                        </v-tooltip>
                      </div>
                    </div>
                    
                    <!-- 中间：日期信息 -->
                    <div class="schedule-days">
                      <v-icon size="small" class="mr-2" color="grey-darken-1">mdi-calendar-range</v-icon>
                      <span class="schedule-days-text">{{ formatDaysOfWeek(schedule.days_of_week) }}</span>
                    </div>
                    
                    <!-- 底部：时间和优先级 -->
                    <div class="schedule-bottom">
                      <div class="schedule-time">
                        <v-icon size="small" class="mr-1" color="grey-darken-1">mdi-clock-outline</v-icon>
                        <span>{{ schedule.start_time }} - {{ schedule.end_time }}</span>
                      </div>
                      <v-chip 
                        size="x-small" 
                        variant="outlined"
                        color="grey-darken-1"
                      >
                        <v-icon left size="x-small">mdi-priority-high</v-icon>
                        优先级: {{ schedule.priority }}
                      </v-chip>
                    </div>
                  </div>
                </v-card>
              </div>
              <div v-else class="empty-state">
                <v-icon size="64" color="grey lighten-1">mdi-calendar-clock-outline</v-icon>
                <div class="empty-state-text mt-3">暂无调度规则</div>
                <div class="empty-state-hint">点击"添加调度"创建新的调度规则</div>
              </div>
            </v-card-text>
          </v-card>
        </div>
      </v-card-text>

      <v-divider></v-divider>

      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn text @click="closeDialog">关闭</v-btn>
      </v-card-actions>
    </v-card>

    <!-- 创建/编辑调度对话框 -->
    <v-dialog v-model="showScheduleForm" max-width="600" persistent>
      <v-card>
        <v-card-title>{{ editingSchedule ? '编辑调度' : '添加调度' }}</v-card-title>
        <v-divider></v-divider>
        <v-card-text class="pa-4">
          <v-form ref="scheduleForm" v-model="formValid">
            <!-- 线路选择 -->
            <div class="mb-3">
              <div class="text-subtitle-2 mb-2">选择线路</div>
              <v-menu v-model="lineMenu" :close-on-content-click="false" @update:model-value="onLineMenuToggle">
                <template v-slot:activator="{ props }">
                  <v-btn
                    v-bind="props"
                    :color="scheduleForm.line ? 'primary' : 'grey'"
                    variant="outlined"
                    block
                    class="line-selector-btn text-none"
                  >
                    <span class="line-selector-text">{{ displayScheduleLine }}</span>
                    <v-icon class="ml-auto" size="small">mdi-chevron-down</v-icon>
                  </v-btn>
                </template>

                <v-card min-width="320" max-width="500">
                  <v-list class="line-selector-list">
                    <v-list-item 
                      @click="selectScheduleLine('AUTO')" 
                      :active="scheduleForm.line === 'auto' || !scheduleForm.line"
                      :color="(scheduleForm.line === 'auto' || !scheduleForm.line) ? '#9333ea' : undefined"
                    >
                      <v-list-item-title>
                        自动选择
                        <v-icon v-if="scheduleForm.line === 'auto' || !scheduleForm.line" color="success" size="small" end>mdi-check</v-icon>
                      </v-list-item-title>
                    </v-list-item>
                    
                    <v-list-item 
                      v-for="lineInfo in availableScheduleLines" 
                      :key="lineInfo.name" 
                      @click="selectScheduleLine(lineInfo.name)" 
                      :active="scheduleForm.line === lineInfo.name"
                      :color="scheduleForm.line === lineInfo.name ? '#9333ea' : undefined"
                      class="line-item"
                    >
                      <v-list-item-title class="d-flex align-center justify-space-between">
                        <div class="line-name-container">
                          <span class="line-name">{{ lineInfo.name }}</span>
                          <div v-if="lineInfo.tags && lineInfo.tags.length > 0" class="tags-container mt-1">
                            <v-chip
                              v-for="tag in lineInfo.tags"
                              :key="tag"
                              size="x-small"
                              :color="getTagColor(tag)"
                              variant="flat"
                              class="mr-1 mb-1 tag-chip"
                            >
                              {{ tag }}
                            </v-chip>
                          </div>
                        </div>
                        <v-icon v-if="scheduleForm.line === lineInfo.name" color="success" size="small">mdi-check</v-icon>
                      </v-list-item-title>
                    </v-list-item>
                    
                    <v-divider></v-divider>
                    
                    <v-list-item>
                      <v-text-field
                        v-model="customScheduleLine"
                        label="自定义线路"
                        variant="underlined"
                        density="compact"
                        hide-details
                        class="mx-2"
                        @keyup.enter="selectCustomScheduleLine"
                      >
                        <template v-slot:append>
                          <v-icon @click="selectCustomScheduleLine" color="primary" size="small">mdi-check</v-icon>
                        </template>
                      </v-text-field>
                    </v-list-item>
                  </v-list>
                </v-card>
              </v-menu>
            </div>

            <!-- 星期选择 -->
            <div class="mb-3">
              <div class="text-subtitle-2 mb-2">选择星期</div>
              <v-chip-group
                v-model="scheduleForm.days_of_week"
                multiple
                active-class="primary--text"
              >
                <v-chip
                  v-for="day in weekDays"
                  :key="day.value"
                  :value="day.value"
                  filter
                  outlined
                  small
                >
                  {{ day.label }}
                </v-chip>
              </v-chip-group>
              <div v-if="scheduleForm.days_of_week.length === 0" class="error--text text-caption">
                请至少选择一天
              </div>
            </div>

            <!-- 时间选择 -->
            <v-row>
              <v-col cols="6">
                <v-text-field
                  v-model="scheduleForm.start_time"
                  label="开始时间"
                  type="time"
                  outlined
                  dense
                  :rules="[v => !!v || '请选择开始时间']"
                ></v-text-field>
              </v-col>
              <v-col cols="6">
                <v-text-field
                  v-model="scheduleForm.end_time"
                  label="结束时间"
                  type="time"
                  outlined
                  dense
                  :rules="[v => !!v || '请选择结束时间']"
                ></v-text-field>
              </v-col>
            </v-row>

            <!-- 优先级 -->
            <v-text-field
              v-model.number="scheduleForm.priority"
              label="优先级"
              type="number"
              outlined
              dense
              hint="数字越小优先级越高"
              persistent-hint
              :rules="[v => v >= 0 || '优先级不能为负数']"
              class="mb-3"
            ></v-text-field>
          </v-form>
        </v-card-text>
        <v-divider></v-divider>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="closeScheduleForm">取消</v-btn>
          <v-btn
            color="primary"
            @click="saveSchedule"
            :loading="saving"
            :disabled="!formValid || scheduleForm.days_of_week.length === 0"
          >
            保存
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-dialog>
</template>

<script>
import {
  checkLineScheduleUnlockStatus,
  unlockLineSchedule,
  getLineSchedules,
  createLineSchedule,
  updateLineSchedule,
  deleteLineSchedule,
  getLineScheduleStatus,
} from '@/services/lineScheduleService';
import { getAvailableLines } from '@/services/userLineService';

export default {
  name: 'LineScheduleDialog',
  components: {},
  props: {
    show: {
      type: Boolean,
      default: false,
    },
    initialService: {
      type: String,
      default: 'plex',
    },
  },
  data() {
    return {
      showDialog: false,
      serviceType: this.initialService,
      unlockStatus: {
        is_unlocked: false,
        is_premium: false,
        unlock_time: null,
        unlock_credits: 264,
      },
      schedules: [],
      activeSchedule: null,
      unlocking: false,
      showScheduleForm: false,
      formValid: false,
      saving: false,
      editingSchedule: null,
      scheduleForm: {
        line: null,
        days_of_week: [],
        start_time: '00:00',
        end_time: '23:59',
        priority: 0,
      },
      weekDays: [
        { label: '周一', value: 0 },
        { label: '周二', value: 1 },
        { label: '周三', value: 2 },
        { label: '周四', value: 3 },
        { label: '周五', value: 4 },
        { label: '周六', value: 5 },
        { label: '周日', value: 6 },
      ],
      // 线路选择器相关
      lineMenu: false,
      availableScheduleLines: [],
      loadingScheduleLines: false,
      customScheduleLine: '',
    };
  },
  computed: {
    displayScheduleLine() {
      return (this.scheduleForm.line && this.scheduleForm.line !== 'auto') ? this.scheduleForm.line : 'AUTO (自动选择)';
    }
  },
  watch: {
    show(val) {
      this.showDialog = val;
      if (val) {
        console.log('LineScheduleDialog 打开, serviceType:', this.serviceType);
        this.loadData();
      }
    },
    showDialog(val) {
      if (!val) {
        this.$emit('update:show', false);
      }
    },
  },
  methods: {
    async loadData() {
      try {
        // 先加载解锁状态
        await this.loadUnlockStatus();
        
        // 如果已解锁，再加载其他数据
        if (this.unlockStatus.is_unlocked) {
          await Promise.all([
            this.loadSchedules(),
            this.loadScheduleStatus(),
          ]);
        }
      } catch (error) {
        console.error('加载数据失败:', error);
        this.$emit('error', '加载数据失败');
      }
    },
    async loadUnlockStatus() {
      try {
        const result = await checkLineScheduleUnlockStatus(this.serviceType);
        this.unlockStatus = result;
      } catch (error) {
        console.error('检查解锁状态失败:', error);
      }
    },
    async loadSchedules() {
      if (!this.unlockStatus.is_unlocked) return;
      try {
        this.schedules = await getLineSchedules(this.serviceType);
      } catch (error) {
        console.error('加载调度列表失败:', error);
      }
    },
    async loadScheduleStatus() {
      if (!this.unlockStatus.is_unlocked) return;
      try {
        const result = await getLineScheduleStatus(this.serviceType);
        this.activeSchedule = result.active_schedule;
      } catch (error) {
        console.error('加载调度状态失败:', error);
      }
    },
    async unlockFeature() {
      this.unlocking = true;
      try {
        const result = await unlockLineSchedule(this.serviceType);
        if (result.success) {
          this.$emit('success', result.message);
          await this.loadData();
        } else {
          this.$emit('error', result.message);
        }
      } catch (error) {
        console.error('解锁失败:', error);
        this.$emit('error', '解锁失败');
      } finally {
        this.unlocking = false;
      }
    },
    openCreateDialog() {
      this.editingSchedule = null;
      this.scheduleForm = {
        line: 'auto',  // 默认设置为 auto
        days_of_week: [],
        start_time: '00:00',
        end_time: '23:59',
        priority: 0,
      };
      this.showScheduleForm = true;
    },
    editSchedule(schedule) {
      this.editingSchedule = schedule;
      this.scheduleForm = {
        line: schedule.line,
        days_of_week: [...schedule.days_of_week],
        start_time: schedule.start_time,
        end_time: schedule.end_time,
        priority: schedule.priority,
      };
      this.showScheduleForm = true;
    },
    async onLineMenuToggle(isOpen) {
      if (isOpen && !this.loadingScheduleLines && this.availableScheduleLines.length === 0) {
        await this.loadAvailableScheduleLines();
      }
    },
    async loadAvailableScheduleLines() {
      this.loadingScheduleLines = true;
      try {
        this.availableScheduleLines = await getAvailableLines(this.serviceType);
      } catch (error) {
        console.error('获取线路列表失败:', error);
        this.$emit('error', '获取线路列表失败');
      } finally {
        this.loadingScheduleLines = false;
      }
    },
    selectScheduleLine(line) {
      // AUTO 时保存为 'auto'，让后端自动选择
      this.scheduleForm.line = line === 'AUTO' ? 'auto' : line;
      this.lineMenu = false;
      this.customScheduleLine = '';
    },
    selectCustomScheduleLine() {
      if (!this.customScheduleLine.trim()) {
        this.$emit('error', '请输入线路名称');
        return;
      }
      this.selectScheduleLine(this.customScheduleLine.trim());
    },
    getTagColor(tag) {
      // 使用更深色的背景色，确保在白色背景下有良好对比度
      const contrastColors = [
        'red-darken-1',
        'pink-darken-1', 
        'purple-darken-1',
        'deep-purple-darken-1',
        'indigo-darken-1',
        'blue-darken-1',
        'light-blue-darken-1',
        'cyan-darken-1',
        'teal-darken-1',
        'green-darken-1',
        'light-green-darken-1',
        'lime-darken-1',
        'amber-darken-1',
        'orange-darken-1',
        'deep-orange-darken-1',
        'brown-darken-1',
        'blue-grey-darken-1',
        'red-darken-2',
        'pink-darken-2',
        'purple-darken-2',
        'deep-purple-darken-2',
        'indigo-darken-2',
        'blue-darken-2',
        'teal-darken-2',
        'green-darken-2'
      ];
      
      // 使用标签内容作为种子生成稳定的随机索引
      let hash = 0;
      for (let i = 0; i < tag.length; i++) {
        const char = tag.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // 转换为32位整数
      }
      
      const colorIndex = Math.abs(hash) % contrastColors.length;
      return contrastColors[colorIndex];
    },
    onScheduleLineChanged(newLine) {
      this.scheduleForm.line = newLine;
    },
    async saveSchedule() {
      if (!this.$refs.scheduleForm.validate()) return;
      if (this.scheduleForm.days_of_week.length === 0) {
        this.$emit('error', '请至少选择一天');
        return;
      }

      this.saving = true;
      try {
        const data = {
          service: this.serviceType,
          line: this.scheduleForm.line,
          days_of_week: this.scheduleForm.days_of_week,
          start_time: this.scheduleForm.start_time,
          end_time: this.scheduleForm.end_time,
          priority: this.scheduleForm.priority,
        };

        let result;
        if (this.editingSchedule) {
          result = await updateLineSchedule(this.editingSchedule.id, data);
        } else {
          result = await createLineSchedule(data);
        }

        if (result.success) {
          this.$emit('success', result.message);
          this.closeScheduleForm();
          await this.loadSchedules();
          await this.loadScheduleStatus();
        } else {
          this.$emit('error', result.message);
        }
      } catch (error) {
        console.error('保存调度失败:', error);
        this.$emit('error', '保存调度失败');
      } finally {
        this.saving = false;
      }
    },
    async toggleSchedule(schedule) {
      try {
        const result = await updateLineSchedule(schedule.id, {
          is_enabled: !schedule.is_enabled,
        });
        if (result.success) {
          this.$emit('success', result.message);
          await this.loadSchedules();
          await this.loadScheduleStatus();
        } else {
          this.$emit('error', result.message);
        }
      } catch (error) {
        console.error('切换调度状态失败:', error);
        this.$emit('error', '切换调度状态失败');
      }
    },
    async deleteSchedule(schedule) {
      if (!confirm(`确定要删除此调度吗？`)) return;

      try {
        const result = await deleteLineSchedule(schedule.id);
        if (result.success) {
          this.$emit('success', result.message);
          await this.loadSchedules();
          await this.loadScheduleStatus();
        } else {
          this.$emit('error', result.message);
        }
      } catch (error) {
        console.error('删除调度失败:', error);
        this.$emit('error', '删除调度失败');
      }
    },
    closeScheduleForm() {
      this.showScheduleForm = false;
      this.editingSchedule = null;
    },
    closeDialog() {
      this.showDialog = false;
    },
    formatDaysOfWeek(days) {
      if (!days || days.length === 0) return '';
      if (days.length === 7) return '每天';
      
      const labels = days
        .map(d => this.weekDays.find(wd => wd.value === d)?.label || '')
        .filter(l => l);
      
      return labels.join(', ');
    },
  },
};
</script>

<style scoped>
.v-chip-group {
  flex-wrap: wrap;
}

.gap-2 {
  gap: 8px;
}

/* 调度列表卡片样式 */
.schedule-list-card {
  border-radius: 8px !important;
  overflow: hidden;
}

.schedule-header {
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  padding: 12px 16px !important;
}

.schedule-title {
  font-weight: 600;
  font-size: 15px;
  color: #2d3748;
}

/* 调度容器 */
.schedules-container {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 500px;
  overflow-y: auto;
}

/* 自定义滚动条 */
.schedules-container::-webkit-scrollbar {
  width: 6px;
}

.schedules-container::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.schedules-container::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.schedules-container::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

/* 单个调度项卡片 */
.schedule-item {
  position: relative;
  border-radius: 8px !important;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  background: white;
  border: 1px solid #e2e8f0 !important;
}

.schedule-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1) !important;
  border-color: #9333ea !important;
}

.schedule-item.schedule-disabled {
  background: #f8f9fa;
  opacity: 0.7;
}

/* 左侧线路指示条 */
.schedule-line-indicator {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  transition: width 0.3s ease;
}

.schedule-item:hover .schedule-line-indicator {
  width: 6px;
}

/* 调度内容区域 */
.schedule-content {
  padding: 14px 16px 14px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 顶部区域 */
.schedule-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.schedule-line-chip {
  font-weight: 600 !important;
  letter-spacing: 0.5px;
}

/* 操作按钮组 */
.schedule-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

/* 日期区域 */
.schedule-days {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 6px;
  border-left: 3px solid #9333ea;
}

.schedule-days-text {
  font-size: 13px;
  font-weight: 500;
  color: #475569;
}

.schedule-item.schedule-disabled .schedule-days {
  background: #f1f5f9;
  border-left-color: #9e9e9e;
}

/* 底部区域 */
.schedule-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.schedule-time {
  display: flex;
  align-items: center;
  font-size: 13px;
  font-weight: 500;
  color: #64748b;
}

/* 空状态 */
.empty-state {
  padding: 60px 20px;
  text-align: center;
  color: #94a3b8;
}

.empty-state-text {
  font-size: 16px;
  font-weight: 500;
  color: #64748b;
}

.empty-state-hint {
  font-size: 13px;
  color: #94a3b8;
  margin-top: 8px;
}

/* 线路选择按钮样式 */
.line-selector-btn {
  justify-content: space-between !important;
  text-align: left !important;
  height: 40px !important;
  padding: 0 12px !important;
}

.line-selector-btn .line-selector-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
  display: block;
}

/* 线路选择器样式 */
.line-selector-list {
  max-height: 60vh;
  overflow-y: auto;
}

/* 自定义滚动条样式 */
.line-selector-list::-webkit-scrollbar {
  width: 6px;
}

.line-selector-list::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.line-selector-list::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.line-selector-list::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

/* 对于Firefox浏览器 */
.line-selector-list {
  scrollbar-width: thin;
  scrollbar-color: #c1c1c1 #f1f1f1;
}

.line-item {
  min-height: 56px;
}

.line-name-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 0;
}

.line-name {
  font-weight: 500;
  font-size: 14px;
  word-break: break-all;
  overflow-wrap: break-word;
  line-height: 1.3;
}

.tags-container {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px;
  max-width: 320px;
  line-height: 1.2;
}

.tags-container .v-chip {
  height: 18px !important;
  font-size: 10px !important;
  padding: 0 6px !important;
}

.tag-chip {
  color: white !important;
  font-weight: 500 !important;
}
</style>
