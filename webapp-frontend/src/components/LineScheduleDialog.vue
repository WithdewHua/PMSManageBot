<template>
  <v-dialog v-model="showDialog" max-width="900" scrollable>
    <v-card>
      <v-card-title class="headline d-flex justify-space-between align-center">
        <span>线路调度管理</span>
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
                解锁需要消耗 <strong>{{ unlockCredits }}</strong> 积分
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

        <!-- 已解锁状态 -->
        <div v-else>
          <!-- 默认线路设置 -->
          <v-card outlined class="mb-4">
            <v-card-subtitle class="pb-2">
              <v-icon small class="mr-1">mdi-home</v-icon>
              默认线路
            </v-card-subtitle>
            <v-card-text>
              <div class="d-flex align-center">
                <v-select
                  v-model="defaultLine"
                  :items="availableLines"
                  item-text="name"
                  item-value="name"
                  label="选择默认线路"
                  outlined
                  dense
                  clearable
                  hide-details
                  class="flex-grow-1 mr-2"
                >
                  <template v-slot:selection="{ item }">
                    <v-chip small :color="item.is_premium ? 'purple' : 'blue'" dark>
                      {{ item.name }}
                    </v-chip>
                  </template>
                  <template v-slot:item="{ item }">
                    <v-list-item-content>
                      <v-list-item-title>
                        {{ item.name }}
                        <v-chip
                          v-if="item.is_premium"
                          x-small
                          color="purple"
                          dark
                          class="ml-2"
                        >
                          Premium
                        </v-chip>
                      </v-list-item-title>
                      <v-list-item-subtitle v-if="item.tags && item.tags.length">
                        <v-chip
                          v-for="tag in item.tags"
                          :key="tag"
                          x-small
                          outlined
                          class="mr-1"
                        >
                          {{ tag }}
                        </v-chip>
                      </v-list-item-subtitle>
                    </v-list-item-content>
                  </template>
                </v-select>
                <v-btn
                  color="primary"
                  small
                  @click="saveDefaultLine"
                  :loading="savingDefault"
                >
                  保存
                </v-btn>
              </div>
              <div class="text-caption grey--text mt-2">
                当没有生效的调度时，将使用此默认线路。留空则使用 AUTO 自动选择。
              </div>
            </v-card-text>
          </v-card>

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
          <v-card outlined class="mb-4">
            <v-card-subtitle class="pb-2 d-flex justify-space-between align-center">
              <span>
                <v-icon small class="mr-1">mdi-calendar-clock</v-icon>
                调度列表
              </span>
              <v-btn
                color="primary"
                small
                @click="openCreateDialog"
              >
                <v-icon left small>mdi-plus</v-icon>
                添加调度
              </v-btn>
            </v-card-subtitle>
            <v-divider></v-divider>
            <v-card-text class="pa-0">
              <v-list v-if="schedules.length > 0" dense>
                <v-list-item
                  v-for="schedule in schedules"
                  :key="schedule.id"
                  :class="{ 'grey lighten-4': !schedule.is_enabled }"
                >
                  <v-list-item-content>
                    <v-list-item-title>
                      <v-chip small :color="schedule.is_enabled ? 'primary' : 'grey'" dark class="mr-2">
                        {{ schedule.line }}
                      </v-chip>
                      <span class="text-body-2">
                        {{ formatDaysOfWeek(schedule.days_of_week) }}
                      </span>
                    </v-list-item-title>
                    <v-list-item-subtitle>
                      {{ schedule.start_time }} - {{ schedule.end_time }}
                      <v-chip x-small outlined class="ml-2">
                        优先级: {{ schedule.priority }}
                      </v-chip>
                    </v-list-item-subtitle>
                  </v-list-item-content>
                  <v-list-item-action>
                    <div class="d-flex">
                      <v-btn
                        icon
                        small
                        @click="toggleSchedule(schedule)"
                        :title="schedule.is_enabled ? '禁用' : '启用'"
                      >
                        <v-icon small :color="schedule.is_enabled ? 'success' : 'grey'">
                          {{ schedule.is_enabled ? 'mdi-toggle-switch' : 'mdi-toggle-switch-off' }}
                        </v-icon>
                      </v-btn>
                      <v-btn
                        icon
                        small
                        @click="editSchedule(schedule)"
                        title="编辑"
                      >
                        <v-icon small>mdi-pencil</v-icon>
                      </v-btn>
                      <v-btn
                        icon
                        small
                        @click="deleteSchedule(schedule)"
                        title="删除"
                      >
                        <v-icon small color="error">mdi-delete</v-icon>
                      </v-btn>
                    </div>
                  </v-list-item-action>
                </v-list-item>
              </v-list>
              <div v-else class="pa-4 text-center grey--text">
                暂无调度，点击"添加调度"创建新的调度规则
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
            <v-select
              v-model="scheduleForm.line"
              :items="availableLines"
              item-text="name"
              item-value="name"
              label="选择线路"
              outlined
              dense
              :rules="[v => !!v || '请选择线路']"
              class="mb-3"
            >
              <template v-slot:selection="{ item }">
                <v-chip small :color="item.is_premium ? 'purple' : 'blue'" dark>
                  {{ item.name }}
                </v-chip>
              </template>
              <template v-slot:item="{ item }">
                <v-list-item-content>
                  <v-list-item-title>
                    {{ item.name }}
                    <v-chip
                      v-if="item.is_premium"
                      x-small
                      color="purple"
                      dark
                      class="ml-2"
                    >
                      Premium
                    </v-chip>
                  </v-list-item-title>
                  <v-list-item-subtitle v-if="item.tags && item.tags.length">
                    <v-chip
                      v-for="tag in item.tags"
                      :key="tag"
                      x-small
                      outlined
                      class="mr-1"
                    >
                      {{ tag }}
                    </v-chip>
                  </v-list-item-subtitle>
                </v-list-item-content>
              </template>
            </v-select>

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
  setDefaultLine,
  getDefaultLine,
  getLineScheduleStatus,
} from '@/services/lineScheduleService';
import { getAvailableLines } from '@/services/userLineService';

export default {
  name: 'LineScheduleDialog',
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
      },
      unlockCredits: 200, // 从配置获取
      schedules: [],
      availableLines: [],
      defaultLine: null,
      activeSchedule: null,
      unlocking: false,
      savingDefault: false,
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
    };
  },
  watch: {
    show(val) {
      this.showDialog = val;
      if (val) {
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
        // 并行加载所有数据
        await Promise.all([
          this.loadUnlockStatus(),
          this.loadAvailableLines(),
          this.loadSchedules(),
          this.loadDefaultLine(),
          this.loadScheduleStatus(),
        ]);
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
    async loadAvailableLines() {
      try {
        this.availableLines = await getAvailableLines(this.serviceType);
      } catch (error) {
        console.error('加载可用线路失败:', error);
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
    async loadDefaultLine() {
      if (!this.unlockStatus.is_unlocked) return;
      try {
        this.defaultLine = await getDefaultLine(this.serviceType);
      } catch (error) {
        console.error('加载默认线路失败:', error);
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
    async saveDefaultLine() {
      this.savingDefault = true;
      try {
        const result = await setDefaultLine(this.serviceType, this.defaultLine);
        if (result.success) {
          this.$emit('success', result.message);
        } else {
          this.$emit('error', result.message);
        }
      } catch (error) {
        console.error('保存默认线路失败:', error);
        this.$emit('error', '保存默认线路失败');
      } finally {
        this.savingDefault = false;
      }
    },
    openCreateDialog() {
      this.editingSchedule = null;
      this.scheduleForm = {
        line: null,
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
</style>
