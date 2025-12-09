<template>
  <v-dialog v-model="showDialog" max-width="900" scrollable>
    <v-card class="schedule-dialog">
      <v-card-title class="dialog-title">
        <v-icon start size="28">mdi-calendar-clock</v-icon>
        <span class="title-text">线路调度管理</span>
        <v-spacer></v-spacer>
        <v-chip 
          :color="unlockStatus.is_unlocked ? 'success' : 'warning'" 
          size="small"
          class="status-chip"
        >
          {{ unlockStatus.is_unlocked ? '已解锁' : '未解锁' }}
        </v-chip>
      </v-card-title>

      <v-divider></v-divider>

      <v-card-text class="dialog-content">
        <!-- 未解锁状态 -->
        <v-alert
          v-if="!unlockStatus.is_unlocked"
          type="info"
          variant="tonal"
          prominent
          border="start"
          class="unlock-alert"
        >
          <div class="d-flex align-center justify-space-between flex-wrap">
            <div class="unlock-info">
              <div class="text-h6 mb-2 font-weight-bold">🔓 解锁线路调度功能</div>
              <div class="text-body-2">
                线路调度功能允许您为不同时间段自动切换线路，优化观看体验。
              </div>
              <div class="mt-2">
                解锁需要消耗 
                <v-chip size="small" color="primary" class="mx-1">
                  {{ unlockStatus.unlock_credits }} 积分
                </v-chip>
                <span v-if="unlockStatus.is_premium" class="success--text font-weight-bold">
                  （Premium 用户免费）
                </span>
              </div>
            </div>
            <v-btn
              color="primary"
              variant="elevated"
              size="large"
              class="unlock-btn mt-3 mt-md-0"
              @click="unlockFeature"
              :loading="unlocking"
            >
              <v-icon start>mdi-lock-open-variant</v-icon>
              立即解锁
            </v-btn>
          </div>
        </v-alert>

        <!-- 已解锁状态 - 直接显示高级调度配置 -->
        <div v-else>
          <!-- 当前生效的调度 -->
          <v-card v-if="activeSchedule" variant="tonal" color="success" class="active-schedule-card mb-4">
            <v-card-subtitle class="pb-2 d-flex align-center">
              <v-icon size="small" class="mr-1">mdi-check-circle</v-icon>
              <span class="font-weight-medium">当前生效的调度</span>
            </v-card-subtitle>
            <v-card-text>
              <div class="d-flex align-center flex-wrap gap-2">
                <v-chip color="success" variant="elevated" size="small" class="font-weight-bold">
                  <v-icon start size="x-small">mdi-router-wireless</v-icon>
                  {{ activeSchedule.line }}
                </v-chip>
                <span class="text-body-2">
                  {{ formatDaysOfWeek(activeSchedule.days_of_week) }}
                  <v-icon size="x-small" class="mx-1">mdi-clock-outline</v-icon>
                  {{ activeSchedule.start_time }} - {{ activeSchedule.end_time }}
                </span>
              </div>
            </v-card-text>
          </v-card>

          <!-- 调度列表 -->
          <v-card variant="outlined" class="schedule-list-card">
            <v-card-subtitle class="schedule-header">
              <div class="d-flex justify-space-between align-center">
                <span class="schedule-title">
                  <v-icon size="small" class="mr-1">mdi-format-list-bulleted</v-icon>
                  调度规则列表
                  <v-chip size="x-small" color="purple-lighten-3" class="ml-2">
                    {{ schedules.length }} 条
                  </v-chip>
                </span>
                <v-btn
                  color="purple-darken-1"
                  variant="elevated"
                  size="small"
                  class="add-schedule-btn"
                  @click="openCreateDialog"
                  :disabled="false"
                >
                  <v-icon start size="small">mdi-plus</v-icon>
                  添加调度
                </v-btn>
              </div>
            </v-card-subtitle>
            <v-divider></v-divider>
            <v-card-text class="pa-0">
              <div v-if="schedules.length > 0" class="schedules-container">
                <v-card
                  v-for="schedule in schedules"
                  :key="schedule.id"
                  class="schedule-item"
                  :class="{ 'schedule-disabled': !schedule.is_enabled }"
                  variant="outlined"
                >
                  <!-- 左侧线路标识 -->
                  <div class="schedule-line-indicator" :style="{ backgroundColor: schedule.is_enabled ? '#9333ea' : '#9e9e9e' }"></div>
                  
                  <div class="schedule-content">
                    <!-- 顶部：线路和状态 -->
                    <div class="schedule-top">
                      <div class="d-flex align-center flex-wrap" style="gap: 8px;">
                        <v-chip 
                          :color="schedule.is_enabled ? 'purple-darken-1' : 'grey'" 
                          variant="elevated"
                          size="small"
                          class="schedule-line-chip"
                        >
                          <v-icon start size="x-small">mdi-router-wireless</v-icon>
                          {{ schedule.line }}
                        </v-chip>
                        <v-chip 
                          size="x-small" 
                          :color="schedule.is_enabled ? 'success' : 'grey-lighten-1'"
                          variant="flat"
                        >
                          <v-icon start size="x-small">
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
                      <v-icon size="small" class="mr-2">mdi-calendar-range</v-icon>
                      <span class="schedule-days-text">{{ formatDaysOfWeek(schedule.days_of_week) }}</span>
                    </div>
                    
                    <!-- 底部：时间 -->
                    <div class="schedule-bottom">
                      <div class="schedule-time">
                        <v-icon size="small" class="mr-1">mdi-clock-outline</v-icon>
                        <span>{{ schedule.start_time }} - {{ schedule.end_time }}</span>
                      </div>
                      <!-- 优先级暂时隐藏，因为不允许调度时间重叠 -->
                      <!-- <v-chip 
                        size="x-small" 
                        variant="outlined"
                        color="purple-darken-1"
                      >
                        <v-icon start size="x-small">mdi-priority-high</v-icon>
                        优先级 {{ schedule.priority }}
                      </v-chip> -->
                    </div>
                  </div>
                </v-card>
              </div>
              <div v-else class="empty-state">
                <v-icon size="80" color="grey-lighten-1">mdi-calendar-clock-outline</v-icon>
                <div class="empty-state-text mt-4">暂无调度规则</div>
                <div class="empty-state-hint mt-2">点击"添加调度"创建新的调度规则</div>
              </div>
            </v-card-text>
          </v-card>
        </div>
      </v-card-text>

      <v-divider></v-divider>

      <v-card-actions class="dialog-actions">
        <v-spacer></v-spacer>
        <v-btn variant="text" color="grey" @click="closeDialog">关闭</v-btn>
      </v-card-actions>
    </v-card>

    <!-- 创建/编辑调度对话框 -->
    <v-dialog v-model="showScheduleForm" max-width="600" persistent>
      <v-card class="schedule-form-dialog">
        <v-card-title class="form-dialog-title">
          <v-icon start size="24">{{ editingSchedule ? 'mdi-pencil' : 'mdi-plus-circle' }}</v-icon>
          <span>{{ editingSchedule ? '编辑调度' : '添加调度' }}</span>
        </v-card-title>
        <v-divider></v-divider>
        <v-card-text class="form-content pa-5">
          <v-form ref="scheduleForm" v-model="formValid">
            <!-- 线路选择 -->
            <div class="form-section mb-4">
              <div class="form-label mb-2">
                <v-icon size="small" class="mr-1">mdi-router-wireless</v-icon>
                选择线路
              </div>
              <v-menu v-model="lineMenu" :close-on-content-click="false" @update:model-value="onLineMenuToggle">
                <template v-slot:activator="{ props }">
                  <v-btn
                    v-bind="props"
                    :color="scheduleForm.line ? 'purple-darken-1' : 'grey'"
                    variant="outlined"
                    block
                    class="line-selector-btn"
                    size="large"
                  >
                    <span class="line-selector-text">{{ displayScheduleLine }}</span>
                    <v-icon class="ml-auto" size="small">mdi-chevron-down</v-icon>
                  </v-btn>
                </template>

                <v-card min-width="320" max-width="500" class="line-selector-card">
                  <v-list class="line-selector-list">
                    <v-list-item 
                      @click="selectScheduleLine('AUTO')" 
                      :active="scheduleForm.line === 'auto' || !scheduleForm.line"
                      active-color="purple-darken-1"
                      rounded="lg"
                    >
                      <v-list-item-title>
                        <div class="d-flex align-center justify-space-between">
                          <span>自动选择</span>
                          <v-icon v-if="scheduleForm.line === 'auto' || !scheduleForm.line" color="success" size="small">mdi-check</v-icon>
                        </div>
                      </v-list-item-title>
                    </v-list-item>
                    
                    <v-list-item 
                      v-for="lineInfo in availableScheduleLines" 
                      :key="lineInfo.name" 
                      @click="selectScheduleLine(lineInfo.name)" 
                      :active="scheduleForm.line === lineInfo.name"
                      active-color="purple-darken-1"
                      class="line-item"
                      rounded="lg"
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
                        class="custom-line-input"
                        @keyup.enter="selectCustomScheduleLine"
                      >
                        <template v-slot:append>
                          <v-icon @click="selectCustomScheduleLine" color="purple-darken-1" size="small">mdi-check</v-icon>
                        </template>
                      </v-text-field>
                    </v-list-item>
                  </v-list>
                </v-card>
              </v-menu>
            </div>

            <!-- 星期选择 -->
            <div class="form-section mb-4">
              <div class="form-label mb-2">
                <v-icon size="small" class="mr-1">mdi-calendar-week</v-icon>
                选择星期
              </div>
              <v-chip-group
                v-model="scheduleForm.days_of_week"
                multiple
                column
              >
                <v-chip
                  v-for="day in weekDays"
                  :key="day.value"
                  :value="day.value"
                  filter
                  variant="outlined"
                  color="purple-darken-1"
                  size="small"
                  class="day-chip"
                >
                  {{ day.label }}
                </v-chip>
              </v-chip-group>
              <div v-if="scheduleForm.days_of_week.length === 0" class="error-hint mt-2">
                <v-icon size="small" color="error">mdi-alert-circle</v-icon>
                请至少选择一天
              </div>
            </div>

            <!-- 时间选择 -->
            <div class="form-section mb-4">
              <div class="form-label mb-2">
                <v-icon size="small" class="mr-1">mdi-clock-outline</v-icon>
                时间范围
              </div>
              <v-row dense>
                <v-col cols="6">
                  <v-text-field
                    v-model="scheduleForm.start_time"
                    label="开始时间"
                    type="time"
                    variant="outlined"
                    density="comfortable"
                    :rules="[v => !!v || '请选择开始时间']"
                  ></v-text-field>
                </v-col>
                <v-col cols="6">
                  <v-text-field
                    v-model="scheduleForm.end_time"
                    label="结束时间"
                    type="time"
                    variant="outlined"
                    density="comfortable"
                    :rules="[v => !!v || '请选择结束时间']"
                  ></v-text-field>
                </v-col>
              </v-row>
            </div>

            <!-- 优先级 (暂时隐藏，因为不允许调度时间重叠) -->
            <!-- <div class="form-section">
              <div class="form-label mb-2">
                <v-icon size="small" class="mr-1">mdi-priority-high</v-icon>
                优先级
              </div>
              <v-text-field
                v-model.number="scheduleForm.priority"
                label="数字越小优先级越高"
                type="number"
                variant="outlined"
                density="comfortable"
                hint="数字越小优先级越高"
                persistent-hint
                :rules="[v => v >= 0 || '优先级不能为负数']"
              ></v-text-field>
            </div> -->
          </v-form>
        </v-card-text>
        <v-divider></v-divider>
        <v-card-actions class="pa-4">
          <v-spacer></v-spacer>
          <v-btn variant="text" color="grey" @click="closeScheduleForm">取消</v-btn>
          <v-btn
            color="purple-darken-1"
            variant="elevated"
            @click="saveSchedule"
            :loading="saving"
            :disabled="!formValid || scheduleForm.days_of_week.length === 0"
          >
            <v-icon start>mdi-content-save</v-icon>
            保存
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 消息提示 (非 Telegram 环境降级使用) -->
    <v-snackbar
      v-model="snackbar"
      :color="snackbarColor"
      :timeout="3000"
      location="top"
    >
      {{ snackbarMessage }}
      <template v-slot:actions>
        <v-btn
          variant="text"
          @click="snackbar = false"
        >
          关闭
        </v-btn>
      </template>
    </v-snackbar>
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
      // Snackbar (用于非 Telegram 环境)
      snackbar: false,
      snackbarMessage: '',
      snackbarColor: 'info',
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
        this.showMessage('加载数据失败', 'error');
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
          this.showMessage(result.message || '解锁成功', 'success');
          this.$emit('success', result.message);
          await this.loadData();
        } else {
          this.showMessage(result.message || '解锁失败', 'error');
          this.$emit('error', result.message);
        }
      } catch (error) {
        console.error('解锁失败:', error);
        this.showMessage('解锁失败', 'error');
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
        this.showMessage('获取线路列表失败', 'error');
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
        this.showMessage('请输入线路名称', 'warning');
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
        this.showMessage('请至少选择一天', 'warning');
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

        console.log('调度保存结果:', result);

        if (result && result.success) {
          this.$emit('success', result.message);
          this.closeScheduleForm();
          await this.loadSchedules();
          await this.loadScheduleStatus();
        } else {
          this.showMessage(result?.message || '保存调度失败', 'error');
          this.$emit('error', result?.message || '保存调度失败');
        }
      } catch (error) {
        console.error('保存调度失败:', error);
        this.showMessage('保存调度失败', 'error');
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
          this.showMessage(result.message || '操作成功', 'success');
          this.$emit('success', result.message);
          await this.loadSchedules();
          await this.loadScheduleStatus();
        } else {
          this.showMessage(result.message || '操作失败', 'error');
          this.$emit('error', result.message);
        }
      } catch (error) {
        console.error('切换调度状态失败:', error);
        this.showMessage('切换调度状态失败', 'error');
        this.$emit('error', '切换调度状态失败');
      }
    },
    async deleteSchedule(schedule) {
      // 使用 Telegram 原生确认框
      const doDelete = async () => {
        try {
          const result = await deleteLineSchedule(schedule.id);
          if (result.success) {
            this.showMessage(result.message || '删除成功', 'success');
            this.$emit('success', result.message);
            await this.loadSchedules();
            await this.loadScheduleStatus();
          } else {
            this.showMessage(result.message || '删除失败', 'error');
            this.$emit('error', result.message);
          }
        } catch (error) {
          console.error('删除调度失败:', error);
          this.showMessage('删除调度失败', 'error');
          this.$emit('error', '删除调度失败');
        }
      };

      if (window.Telegram?.WebApp) {
        window.Telegram.WebApp.showConfirm('确定要删除此调度吗？', (confirmed) => {
          if (confirmed) {
            doDelete();
          }
        });
      } else {
        if (confirm('确定要删除此调度吗？')) {
          await doDelete();
        }
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
    showMessage(message, color = 'info') {
      // 优先使用 Telegram 原生弹窗
      if (window.Telegram?.WebApp) {
        const title = color === 'error' ? '❌ 错误' : 
                     color === 'success' ? '✅ 成功' : 
                     color === 'warning' ? '⚠️ 提示' : 'ℹ️ 信息';
        
        window.Telegram.WebApp.showPopup({
          title: title,
          message: message
        });
      } else {
        // 降级处理：使用 Vuetify Snackbar
        this.snackbarMessage = message;
        this.snackbarColor = color;
        this.snackbar = true;
      }
    },
  },
};
</script>

<style scoped>
/* 主对话框样式 */
.schedule-dialog {
  border-radius: 16px;
}

.dialog-title {
  font-size: 1.25rem;
  font-weight: 600;
  padding: 20px 24px;
  background: linear-gradient(135deg, #9333ea 0%, #7e22ce 100%);
  color: white;
  display: flex;
  align-items: center;
}

.title-text {
  margin-left: 8px;
}

.status-chip {
  color: white !important;
}

.dialog-content {
  padding: 20px !important;
}

.dialog-actions {
  padding: 16px 24px;
}

/* 解锁提示卡片 */
.unlock-alert {
  border-radius: 12px !important;
  margin-bottom: 20px;
}

.unlock-info {
  flex: 1;
  min-width: 0;
}

.unlock-btn {
  flex-shrink: 0;
  font-weight: 600;
  letter-spacing: 0.5px;
}

/* 当前生效的调度卡片 */
.active-schedule-card {
  border-radius: 12px !important;
  border-left: 4px solid #4caf50 !important;
}

/* 调度列表卡片 */
.schedule-list-card {
  border-radius: 12px !important;
  overflow: hidden;
  margin-bottom: 20px;
}

.schedule-header {
  background: linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%);
  padding: 16px 20px !important;
}

.schedule-title {
  font-weight: 600;
  font-size: 15px;
  color: #2d3748;
  display: flex;
  align-items: center;
}

.add-schedule-btn {
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: none;
}

/* 调度容器 */
.schedules-container {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 500px;
  overflow-y: auto;
}

/* 自定义滚动条 */
.schedules-container::-webkit-scrollbar {
  width: 8px;
}

.schedules-container::-webkit-scrollbar-track {
  background: #f1f5f9;
  border-radius: 4px;
}

.schedules-container::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}

.schedules-container::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

/* 单个调度项卡片 */
.schedule-item {
  position: relative;
  border-radius: 12px !important;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  background: white;
  border: 2px solid #e2e8f0 !important;
}

.schedule-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 16px rgba(147, 51, 234, 0.15) !important;
  border-color: #9333ea !important;
}

.schedule-item.schedule-disabled {
  background: #f8fafc;
  opacity: 0.75;
}

.schedule-item.schedule-disabled:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
  border-color: #cbd5e1 !important;
}

/* 左侧线路指示条 */
.schedule-line-indicator {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 5px;
  transition: width 0.3s ease;
}

.schedule-item:hover .schedule-line-indicator {
  width: 8px;
}

/* 调度内容区域 */
.schedule-content {
  padding: 16px 18px 16px 24px;
  display: flex;
  flex-direction: column;
  gap: 12px;
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
  letter-spacing: 0.3px;
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
  padding: 10px 14px;
  background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%);
  border-radius: 8px;
  border-left: 4px solid #9333ea;
}

.schedule-days-text {
  font-size: 13px;
  font-weight: 500;
  color: #6b21a8;
}

.schedule-item.schedule-disabled .schedule-days {
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-left-color: #9e9e9e;
}

.schedule-item.schedule-disabled .schedule-days-text {
  color: #64748b;
}

/* 底部区域 */
.schedule-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.schedule-time {
  display: flex;
  align-items: center;
  font-size: 13px;
  font-weight: 500;
  color: #475569;
}

/* 空状态 */
.empty-state {
  padding: 80px 20px;
  text-align: center;
}

.empty-state-text {
  font-size: 18px;
  font-weight: 600;
  color: #64748b;
}

.empty-state-hint {
  font-size: 14px;
  color: #94a3b8;
}

/* 表单对话框样式 */
.schedule-form-dialog {
  border-radius: 16px;
}

.form-dialog-title {
  font-size: 1.2rem;
  font-weight: 600;
  padding: 20px 24px;
  background: linear-gradient(135deg, #9333ea 0%, #7e22ce 100%);
  color: white;
}

.form-content {
  max-height: 70vh;
  overflow-y: auto;
}

.form-section {
  position: relative;
}

.form-label {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  display: flex;
  align-items: center;
}

/* 线路选择按钮 */
.line-selector-btn {
  justify-content: space-between !important;
  text-align: left !important;
  padding: 0 16px !important;
  text-transform: none;
  font-weight: 500;
}

.line-selector-btn .line-selector-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

/* 线路选择器卡片 */
.line-selector-card {
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12) !important;
}

.line-selector-list {
  max-height: 60vh;
  overflow-y: auto;
}

/* 自定义滚动条 */
.line-selector-list::-webkit-scrollbar {
  width: 8px;
}

.line-selector-list::-webkit-scrollbar-track {
  background: #f1f5f9;
  border-radius: 4px;
}

.line-selector-list::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}

.line-selector-list::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

.line-item {
  min-height: 56px;
  margin: 4px 8px;
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
  line-height: 1.4;
}

.tags-container {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  max-width: 320px;
  line-height: 1.2;
}

.tag-chip {
  color: white !important;
  font-weight: 500 !important;
  height: 20px !important;
  font-size: 11px !important;
  padding: 0 8px !important;
}

.custom-line-input {
  padding: 0 8px;
}

/* 星期选择 */
.day-chip {
  font-weight: 500;
  transition: all 0.2s ease;
}

.error-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #dc2626;
}

/* 响应式调整 */
@media (max-width: 600px) {
  .schedule-top {
    flex-direction: column;
    align-items: flex-start;
  }
  
  .schedule-actions {
    width: 100%;
    justify-content: flex-end;
  }
  
  .unlock-alert .d-flex {
    flex-direction: column;
    align-items: flex-start !important;
  }
  
  .unlock-btn {
    width: 100%;
  }
}
</style>
