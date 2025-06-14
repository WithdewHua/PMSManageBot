<template>
  <div class="admin-panel">
    <v-container fluid class="px-2 px-sm-4">
      <v-row>
        <v-col cols="12">
          <h1 class="text-h5 text-sm-h4 mb-4 mb-sm-6">🎰 转盘管理面板</h1>
        </v-col>
      </v-row>

      <!-- 快速操作卡片 -->
      <v-row>
        <v-col cols="6" sm="6" md="6" lg="3">
          <v-card class="admin-card" elevation="6" rounded="xl">
            <v-card-title class="d-flex align-center pa-3 pa-sm-4 admin-card-header">
              <v-avatar size="32" class="mr-2" color="rgba(255,255,255,0.2)" variant="flat">
                <v-icon size="18" color="white">mdi-cog</v-icon>
              </v-avatar>
              <span class="text-body-2 text-sm-body-1 font-weight-bold">转盘配置</span>
            </v-card-title>
            <v-card-text class="pa-3 pa-sm-4">
              <div class="text-caption text-sm-body-2 text-medium-emphasis">管理奖品设置、概率分配和参与条件</div>
            </v-card-text>
            <v-card-actions class="pa-3 pa-sm-4 pt-0">
              <v-btn color="primary" block size="small" variant="elevated" @click="openWheelConfig">
                <v-icon size="16" class="mr-1">mdi-cog</v-icon>
                配置转盘
              </v-btn>
            </v-card-actions>
          </v-card>
        </v-col>

        <v-col cols="6" sm="6" md="6" lg="3">
          <v-card class="admin-card" elevation="6" rounded="xl">
            <v-card-title class="d-flex align-center pa-3 pa-sm-4 admin-card-header">
              <v-avatar size="32" class="mr-2" color="rgba(255,255,255,0.2)" variant="flat">
                <v-icon size="18" color="white">mdi-chart-line</v-icon>
              </v-avatar>
              <span class="text-body-2 text-sm-body-1 font-weight-bold">随机性测试</span>
            </v-card-title>
            <v-card-text class="pa-3 pa-sm-4">
              <div class="text-caption text-sm-body-2 text-medium-emphasis">验证抽奖算法的公平性和随机性分布</div>
            </v-card-text>
            <v-card-actions class="pa-3 pa-sm-4 pt-0">
              <v-btn color="success" block size="small" variant="elevated" @click="openRandomnessTest">
                <v-icon size="16" class="mr-1">mdi-play</v-icon>
                运行测试
              </v-btn>
            </v-card-actions>
          </v-card>
        </v-col>

        <v-col cols="6" sm="6" md="6" lg="3">
          <v-card class="admin-card" elevation="6" rounded="xl">
            <v-card-title class="d-flex align-center pa-3 pa-sm-4 admin-card-header">
              <v-avatar size="32" class="mr-2" color="rgba(255,255,255,0.2)" variant="flat">
                <v-icon size="18" color="white">mdi-tune</v-icon>
              </v-avatar>
              <span class="text-body-2 text-sm-body-1 font-weight-bold">算法配置</span>
            </v-card-title>
            <v-card-text class="pa-3 pa-sm-4">
              <div class="text-caption text-sm-body-2 text-medium-emphasis">调整随机性参数和保护机制设置</div>
            </v-card-text>
            <v-card-actions class="pa-3 pa-sm-4 pt-0">
              <v-btn color="warning" block size="small" variant="elevated" @click="openRandomnessConfig">
                <v-icon size="16" class="mr-1">mdi-tune</v-icon>
                算法配置
              </v-btn>
            </v-card-actions>
          </v-card>
        </v-col>

        <v-col cols="6" sm="6" md="6" lg="3">
          <v-card class="admin-card" elevation="6" rounded="xl">
            <v-card-title class="d-flex align-center pa-3 pa-sm-4 admin-card-header">
              <v-avatar size="32" class="mr-2" color="rgba(255,255,255,0.2)" variant="flat">
                <v-icon size="18" color="white">mdi-chart-bar</v-icon>
              </v-avatar>
              <span class="text-body-2 text-sm-body-1 font-weight-bold">使用统计</span>
            </v-card-title>
            <v-card-text class="pa-3 pa-sm-4">
              <div class="text-caption text-sm-body-2 text-medium-emphasis">查看转盘使用情况和用户参与数据</div>
            </v-card-text>
            <v-card-actions class="pa-3 pa-sm-4 pt-0">
              <v-btn color="info" block size="small" variant="elevated" @click="viewStats">
                <v-icon size="16" class="mr-1">mdi-chart-bar</v-icon>
                查看统计
              </v-btn>
            </v-card-actions>
          </v-card>
        </v-col>
      </v-row>

      <!-- 转盘预览 -->
      <v-row class="mt-4 mt-sm-6">
        <v-col cols="12">
          <v-card elevation="10" rounded="xl" class="preview-card">
            <v-card-title class="d-flex align-center pa-4 pa-sm-6 preview-card-header">
              <v-avatar size="40" class="mr-3" color="rgba(255,255,255,0.2)" variant="flat">
                <v-icon size="24" color="white">mdi-ferris-wheel</v-icon>
              </v-avatar>
              <span class="text-body-1 text-sm-h6 font-weight-bold">转盘预览</span>
            </v-card-title>
            
            <v-card-text class="pa-4 pa-sm-6">
              <div class="wheel-preview-container">
                <div class="wheel-wrapper">
                  <LuckyWheel 
                    ref="luckyWheel"
                    :disabled="true"
                    @spin-complete="onSpinComplete" 
                    @result-closed="onResultClosed"
                  />
                </div>
              </div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <!-- 当前随机性配置 -->
      <v-row class="mt-4 mt-sm-6">
        <v-col cols="12">
          <v-card elevation="8" rounded="xl" class="config-card">
            <v-card-title class="d-flex align-center flex-wrap pa-4 pa-sm-6 config-card-header">
              <v-avatar size="36" class="mr-3" color="rgba(255,255,255,0.2)" variant="flat">
                <v-icon size="20" color="white">mdi-tune</v-icon>
              </v-avatar>
              <span class="text-body-1 text-sm-h6 mr-2 font-weight-bold">当前随机性配置</span>
              <v-spacer class="d-none d-sm-flex"></v-spacer>
              <v-btn
                color="white"
                variant="outlined"
                size="small"
                prepend-icon="mdi-cog"
                @click="openRandomnessConfig"
                class="mt-2 mt-sm-0 config-btn"
              >
                修改配置
              </v-btn>
            </v-card-title>
            
            <v-card-text class="pa-4 pa-sm-6">
              <v-row>
                <v-col cols="12" sm="6" md="3">
                  <div class="config-item">
                    <div class="config-label">低概率保护</div>
                    <div class="config-value">
                      <v-chip 
                        :color="randomnessConfig.use_weighted_protection ? 'success' : 'default'"
                        variant="flat"
                        size="small"
                        rounded="lg"
                        class="config-chip"
                      >
                        {{ randomnessConfig.use_weighted_protection ? '启用' : '禁用' }}
                      </v-chip>
                    </div>
                  </div>
                </v-col>
                <v-col cols="12" sm="6" md="3" v-if="randomnessConfig.use_weighted_protection">
                  <div class="config-item">
                    <div class="config-label">保护阈值</div>
                    <div class="config-value config-number">{{ randomnessConfig.protection_threshold || 0 }}%</div>
                  </div>
                </v-col>
                <v-col cols="12" sm="6" md="3" v-if="randomnessConfig.use_weighted_protection">
                  <div class="config-item">
                    <div class="config-label">保护系数</div>
                    <div class="config-value config-number">{{ randomnessConfig.protection_factor || 1.0 }}</div>
                  </div>
                </v-col>
                <v-col cols="12" sm="6" md="3">
                  <div class="config-item">
                    <div class="config-label">时间熵混合</div>
                    <div class="config-value">
                      <v-chip 
                        :color="randomnessConfig.use_time_seed_mixing ? 'success' : 'default'"
                        variant="flat"
                        size="small"
                        rounded="lg"
                        class="config-chip"
                      >
                        {{ randomnessConfig.use_time_seed_mixing ? '启用' : '禁用' }}
                      </v-chip>
                    </div>
                  </div>
                </v-col>
                <v-col cols="12" sm="6" md="3">
                  <div class="config-item">
                    <div class="config-label">用户ID熵混合</div>
                    <div class="config-value">
                      <v-chip 
                        :color="randomnessConfig.use_user_seed_mixing ? 'success' : 'default'"
                        variant="flat"
                        size="small"
                        rounded="lg"
                        class="config-chip"
                      >
                        {{ randomnessConfig.use_user_seed_mixing ? '启用' : '禁用' }}
                      </v-chip>
                    </div>
                  </div>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>

      <!-- 最近测试结果 -->
      <v-row class="mt-4 mt-sm-6" v-if="lastTestResult">
        <v-col cols="12">
          <v-card elevation="8" rounded="xl" class="result-card">
            <v-card-title class="d-flex align-center flex-wrap pa-4 pa-sm-6 result-card-header">
              <v-avatar size="36" class="mr-3" color="rgba(255,255,255,0.2)" variant="flat">
                <v-icon size="20" color="white">mdi-history</v-icon>
              </v-avatar>
              <span class="text-body-1 text-sm-h6 mr-2 font-weight-bold">最近测试结果</span>
              <v-spacer class="d-none d-sm-flex"></v-spacer>
              <v-chip 
                :color="lastTestResult.overall_fairness ? 'success' : 'error'"
                variant="flat"
                size="small"
                class="mt-2 mt-sm-0 result-chip"
              >
                {{ lastTestResult.overall_fairness ? '公平' : '需要调整' }}
              </v-chip>
            </v-card-title>
            
            <v-card-text class="pa-4 pa-sm-6">
              <v-row class="test-result-row">
                <v-col cols="6" sm="3">
                  <v-card variant="outlined" class="text-center stat-card" elevation="3">
                    <v-card-text class="pa-3">
                      <div class="text-body-1 text-sm-h6 font-weight-bold text-primary">{{ lastTestResult.iterations?.toLocaleString() }}</div>
                      <div class="text-caption text-medium-emphasis">测试次数</div>
                    </v-card-text>
                  </v-card>
                </v-col>
                <v-col cols="6" sm="3">
                  <v-card variant="outlined" class="text-center stat-card" elevation="3">
                    <v-card-text class="pa-3">
                      <div class="text-body-1 text-sm-h6 font-weight-bold text-success">{{ lastTestResult.valid_items }}</div>
                      <div class="text-caption text-medium-emphasis">有效奖品</div>
                    </v-card-text>
                  </v-card>
                </v-col>
                <v-col cols="6" sm="3">
                  <v-card variant="outlined" class="text-center stat-card" elevation="3">
                    <v-card-text class="pa-3">
                      <div class="text-body-1 text-sm-h6 font-weight-bold text-warning">{{ lastTestResult.average_deviation }}%</div>
                      <div class="text-caption text-medium-emphasis">平均偏差</div>
                    </v-card-text>
                  </v-card>
                </v-col>
                <v-col cols="6" sm="3">
                  <v-card variant="outlined" class="text-center stat-card" elevation="3">
                    <v-card-text class="pa-3">
                      <div class="text-body-1 text-sm-h6 font-weight-bold text-info">{{ formatDate(lastTestResult.timestamp) }}</div>
                      <div class="text-caption text-medium-emphasis">测试时间</div>
                    </v-card-text>
                  </v-card>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </v-container>

    <!-- 随机性测试弹窗 -->
    <v-dialog 
      v-model="showTestDialog" 
      :max-width="$vuetify.display.xs ? '95vw' : '800'"
      :fullscreen="$vuetify.display.xs"
    >
      <v-card rounded="xl" elevation="12" class="dialog-card">
        <v-card-title class="text-body-1 text-sm-h6 pa-4 pa-sm-6 dialog-header">
          <v-avatar size="32" class="mr-3" color="success" variant="flat">
            <v-icon size="18" color="white">mdi-chart-line</v-icon>
          </v-avatar>
          <span class="font-weight-bold">快速随机性测试</span>
        </v-card-title>
        <v-card-text class="pa-4 pa-sm-6">
          <!-- 测试配置 -->
          <v-row class="mb-4">
            <v-col cols="12" sm="6">
              <v-text-field
                v-model.number="testIterations"
                label="测试次数"
                type="number"
                min="1000"
                max="100000"
                step="1000"
                density="compact"
                variant="outlined"
                rounded="lg"
                hint="建议 10000-50000 次"
              ></v-text-field>
            </v-col>
            <v-col cols="12" sm="6" class="d-flex align-center">
              <v-btn
                @click="runRandomnessTest"
                color="primary"
                :loading="testRunning"
                :disabled="testRunning"
                block
                size="small"
                variant="elevated"
              >
                <v-icon class="mr-2">mdi-play</v-icon>
                开始测试
              </v-btn>
            </v-col>
          </v-row>

          <!-- 加载状态 -->
          <div v-if="testRunning" class="text-center py-8">
            <v-progress-circular indeterminate color="primary" size="64"></v-progress-circular>
            <div class="mt-4 text-body-1">正在运行随机性测试...</div>
          </div>

          <!-- 测试结果 -->
          <div v-if="currentTestResult">
            <v-divider class="mb-6"></v-divider>
            
            <!-- 测试概览 -->
            <div class="mb-6">
              <h4 class="mb-4 text-body-1 text-sm-h6 font-weight-bold">测试概览</h4>
              <v-row>
                <v-col cols="6" sm="3">
                  <v-card variant="outlined" class="text-center stat-card" elevation="3">
                    <v-card-text class="pa-3">
                      <div class="text-body-1 text-sm-h6 font-weight-bold text-primary">{{ currentTestResult.iterations?.toLocaleString() }}</div>
                      <div class="text-caption text-medium-emphasis">测试次数</div>
                    </v-card-text>
                  </v-card>
                </v-col>
                <v-col cols="6" sm="3">
                  <v-card variant="outlined" class="text-center stat-card" elevation="3">
                    <v-card-text class="pa-3">
                      <div class="text-body-1 text-sm-h6 font-weight-bold text-success">{{ currentTestResult.valid_items }}</div>
                      <div class="text-caption text-medium-emphasis">有效奖品</div>
                    </v-card-text>
                  </v-card>
                </v-col>
                <v-col cols="6" sm="3">
                  <v-card variant="outlined" class="text-center stat-card" elevation="3">
                    <v-card-text class="pa-3">
                      <div class="text-body-1 text-sm-h6 font-weight-bold" :class="currentTestResult.overall_fairness ? 'text-success' : 'text-error'">
                        {{ currentTestResult.overall_fairness ? '公平' : '异常' }}
                      </div>
                      <div class="text-caption text-medium-emphasis">整体评估</div>
                    </v-card-text>
                  </v-card>
                </v-col>
                <v-col cols="6" sm="3">
                  <v-card variant="outlined" class="text-center stat-card" elevation="3">
                    <v-card-text class="pa-3">
                      <div class="text-body-1 text-sm-h6 font-weight-bold text-warning">{{ currentTestResult.average_deviation }}%</div>
                      <div class="text-caption text-medium-emphasis">平均偏差</div>
                    </v-card-text>
                  </v-card>
                </v-col>
              </v-row>
            </div>

            <!-- 详细测试结果 -->
            <div v-if="currentTestResult.stats && currentTestResult.stats.length > 0" class="mb-4">
              <h4 class="mb-4 text-body-1 text-sm-h6 font-weight-bold d-flex align-center">
                <v-icon class="mr-2" color="primary">mdi-chart-bar</v-icon>
                各奖品测试详情
              </h4>
              
              <v-row>
                <v-col 
                  v-for="(stat, index) in currentTestResult.stats" 
                  :key="index"
                  cols="12" 
                  sm="6" 
                  md="4"
                  lg="3"
                >
                  <v-card 
                    variant="outlined" 
                    class="item-stat-card"
                    elevation="4"
                    rounded="lg"
                    :class="getStatCardClass(stat)"
                  >
                    <v-card-text class="pa-4">
                      <!-- 奖品标题 -->
                      <div class="d-flex align-center mb-3">
                        <v-avatar 
                          size="24" 
                          :color="getItemColor(index)"
                          variant="flat"
                          class="mr-2"
                        >
                          <span class="text-white text-caption font-weight-bold">{{ index + 1 }}</span>
                        </v-avatar>
                        <div class="flex-grow-1">
                          <div class="text-subtitle-2 font-weight-bold text-truncate">
                            {{ stat.name || `奖品 ${index + 1}` }}
                          </div>
                        </div>
                        <v-chip 
                          :color="getDeviationColor(stat.deviation)"
                          variant="flat"
                          size="x-small"
                          rounded="lg"
                        >
                          {{ stat.deviation > 0 ? '+' : '' }}{{ stat.deviation }}%
                        </v-chip>
                      </div>
                      
                      <!-- 概率对比 -->
                      <div class="mb-3">
                        <div class="d-flex justify-space-between text-caption text-medium-emphasis mb-1">
                          <span>期望概率</span>
                          <span>{{ stat.expected_probability }}%</span>
                        </div>
                        <div class="d-flex justify-space-between text-caption mb-2">
                          <span class="font-weight-bold">实际概率</span>
                          <span class="font-weight-bold">{{ stat.actual_probability }}%</span>
                        </div>
                        
                        <!-- 概率可视化条 -->
                        <div class="probability-comparison">
                          <!-- 期望概率条 -->
                          <div class="mb-1">
                            <v-progress-linear
                              :model-value="stat.expected_probability"
                              height="4"
                              rounded
                              color="grey-lighten-1"
                              bg-color="grey-lighten-4"
                            ></v-progress-linear>
                            <div class="text-caption text-grey text-center mt-1">期望</div>
                          </div>
                          
                          <!-- 实际概率条 -->
                          <div>
                            <v-progress-linear
                              :model-value="stat.actual_probability"
                              height="6"
                              rounded
                              :color="getDeviationColor(stat.deviation)"
                              :bg-color="getDeviationColor(stat.deviation) + '-lighten-4'"
                            ></v-progress-linear>
                            <div class="text-caption text-center mt-1" :class="'text-' + getDeviationColor(stat.deviation)">
                              实际
                            </div>
                          </div>
                        </div>
                      </div>
                      
                      <!-- 统计数据 -->
                      <v-divider class="mb-2"></v-divider>
                      <div class="d-flex justify-space-between">
                        <div class="text-center">
                          <div class="text-body-2 font-weight-bold text-primary">{{ stat.count?.toLocaleString() }}</div>
                          <div class="text-caption text-medium-emphasis">中奖次数</div>
                        </div>
                        <div class="text-center">
                          <div class="text-body-2 font-weight-bold" :class="'text-' + getDeviationColor(stat.deviation)">
                            {{ Math.abs(stat.deviation) }}%
                          </div>
                          <div class="text-caption text-medium-emphasis">偏差幅度</div>
                        </div>
                        <div class="text-center">
                          <v-icon 
                            :color="getFairnessColor(stat.is_fair)"
                            size="16"
                          >
                            {{ stat.is_fair ? 'mdi-check-circle' : 'mdi-alert-circle' }}
                          </v-icon>
                          <div class="text-caption text-medium-emphasis">
                            {{ stat.is_fair ? '正常' : '异常' }}
                          </div>
                        </div>
                      </div>
                    </v-card-text>
                  </v-card>
                </v-col>
              </v-row>
            </div>

            <!-- 测试分析建议 -->
            <div v-if="testAnalysis" class="mb-4">
              <v-alert
                :type="testAnalysis.type"
                variant="tonal"
                rounded="lg"
                class="test-analysis-alert"
              >
                <template v-slot:prepend>
                  <v-icon size="large">{{ testAnalysis.icon }}</v-icon>
                </template>
                <div class="text-subtitle-1 font-weight-bold mb-1">{{ testAnalysis.title }}</div>
                <div class="text-body-2">{{ testAnalysis.message }}</div>
                <div v-if="testAnalysis.suggestions && testAnalysis.suggestions.length > 0" class="mt-2">
                  <div class="text-subtitle-2 font-weight-bold mb-1">建议：</div>
                  <ul class="text-body-2">
                    <li v-for="(suggestion, index) in testAnalysis.suggestions" :key="index">
                      {{ suggestion }}
                    </li>
                  </ul>
                </div>
              </v-alert>
            </div>
          </div>
        </v-card-text>
        <v-card-actions class="pa-4 pa-sm-6">
          <v-spacer></v-spacer>
          <v-btn size="small" variant="text" @click="showTestDialog = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 随机性配置弹窗 -->
    <v-dialog 
      v-model="showConfigDialog" 
      :max-width="$vuetify.display.xs ? '95vw' : '600'"
      :fullscreen="$vuetify.display.xs"
    >
      <v-card rounded="xl" elevation="12" class="dialog-card">
        <v-card-title class="d-flex align-center pa-4 pa-sm-6 dialog-header">
          <v-avatar size="32" class="mr-3" color="teal" variant="flat">
            <v-icon size="18" color="white">mdi-tune</v-icon>
          </v-avatar>
          <span class="text-body-1 text-sm-h6 font-weight-bold">随机性算法配置</span>
        </v-card-title>
        
        <v-card-text class="pa-4 pa-sm-6">
          <v-form ref="configForm" v-model="configValid">
            <!-- 基础开关配置 -->
            <div class="mb-6">
              <h4 class="mb-4 text-body-1 text-sm-h6 font-weight-bold">基础设置</h4>
              
              <v-card variant="outlined" rounded="lg" class="mb-3 setting-card">
                <v-card-text class="pa-4">
                  <v-switch
                    v-model="randomnessConfig.use_weighted_protection"
                    label="启用低概率奖品保护"
                    color="primary"
                    hide-details
                    class="mb-0"
                  >
                    <template v-slot:append>
                      <v-tooltip location="top">
                        <template v-slot:activator="{ props }">
                          <v-icon v-bind="props" color="grey" size="small">mdi-help-circle-outline</v-icon>
                        </template>
                        <span>为概率较低的奖品提供额外的中奖保护机制</span>
                      </v-tooltip>
                    </template>
                  </v-switch>
                </v-card-text>
              </v-card>
              
              <v-card variant="outlined" rounded="lg" class="mb-3 setting-card">
                <v-card-text class="pa-4">
                  <v-switch
                    v-model="randomnessConfig.use_time_seed_mixing"
                    label="启用时间熵混合"
                    color="primary"
                    hide-details
                    class="mb-0"
                  >
                    <template v-slot:append>
                      <v-tooltip location="top">
                        <template v-slot:activator="{ props }">
                          <v-icon v-bind="props" color="grey" size="small">mdi-help-circle-outline</v-icon>
                        </template>
                        <span>使用时间戳增强随机数的不可预测性</span>
                      </v-tooltip>
                    </template>
                  </v-switch>
                </v-card-text>
              </v-card>
              
              <v-card variant="outlined" rounded="lg" class="setting-card">
                <v-card-text class="pa-4">
                  <v-switch
                    v-model="randomnessConfig.use_user_seed_mixing"
                    label="启用用户ID熵混合"
                    color="primary"
                    hide-details
                    class="mb-0"
                  >
                    <template v-slot:append>
                      <v-tooltip location="top">
                        <template v-slot:activator="{ props }">
                          <v-icon v-bind="props" color="grey" size="small">mdi-help-circle-outline</v-icon>
                        </template>
                        <span>使用用户ID增强随机性，确保每个用户的抽奖体验独特</span>
                      </v-tooltip>
                    </template>
                  </v-switch>
                </v-card-text>
              </v-card>
            </div>

            <v-divider class="mb-6"></v-divider>

            <!-- 高级参数配置 -->
            <div class="mb-6" v-if="randomnessConfig.use_weighted_protection">
              <h4 class="mb-4 text-body-1 text-sm-h6 font-weight-bold">保护参数</h4>
              
              <v-text-field
                v-model.number="randomnessConfig.protection_threshold"
                label="保护阈值 (%)"
                type="number"
                min="0.1"
                max="50"
                step="0.1"
                :rules="thresholdRules"
                density="compact"
                variant="outlined"
                rounded="lg"
                class="mb-4"
              >
                <template v-slot:append-inner>
                  <v-tooltip location="top">
                    <template v-slot:activator="{ props }">
                      <v-icon v-bind="props" color="grey" size="small">mdi-help-circle-outline</v-icon>
                    </template>
                    <span>概率低于此值的奖品将获得保护加成</span>
                  </v-tooltip>
                </template>
              </v-text-field>
              
              <v-text-field
                v-model.number="randomnessConfig.protection_factor"
                label="保护系数"
                type="number"
                min="1.0"
                max="3.0"
                step="0.1"
                :rules="factorRules"
                density="compact"
                variant="outlined"
                rounded="lg"
              >
                <template v-slot:append-inner>
                  <v-tooltip location="top">
                    <template v-slot:activator="{ props }">
                      <v-icon v-bind="props" color="grey" size="small">mdi-help-circle-outline</v-icon>
                    </template>
                    <span>低概率奖品的概率乘数，越大保护力度越强</span>
                  </v-tooltip>
                </template>
              </v-text-field>
            </div>

            <v-divider class="mb-6"></v-divider>

            <!-- 快速配置 -->
            <div class="mb-6">
              <h4 class="mb-4 text-body-1 text-sm-h6 font-weight-bold">快速配置</h4>
              <v-btn-toggle
                v-model="selectedPreset"
                color="primary"
                variant="outlined"
                divided
                @update:model-value="applyPreset"
                class="preset-toggle"
              >
                <v-btn value="conservative" size="small">保守模式</v-btn>
                <v-btn value="balanced" size="small">平衡模式</v-btn>
                <v-btn value="aggressive" size="small">激进模式</v-btn>
              </v-btn-toggle>
            </div>

            <!-- 配置预览 -->
            <v-alert
              type="info"
              variant="tonal"
              class="mb-4"
            >
              <div class="text-subtitle-2 mb-2 font-weight-bold">当前配置效果预览：</div>
              <ul class="text-body-2">
                <li v-if="randomnessConfig.use_weighted_protection">
                  概率低于 {{ randomnessConfig.protection_threshold }}% 的奖品将获得 {{ ((randomnessConfig.protection_factor - 1) * 100).toFixed(0) }}% 的保护加成
                </li>
                <li v-else>
                  所有奖品严格按照设定概率执行
                </li>
                <li v-if="randomnessConfig.use_time_seed_mixing">
                  启用时间戳随机增强
                </li>
                <li v-if="randomnessConfig.use_user_seed_mixing">
                  启用用户ID随机增强
                </li>
              </ul>
            </v-alert>
          </v-form>
        </v-card-text>
        
        <v-card-actions class="pa-4 pa-sm-6">
          <v-spacer></v-spacer>
          <v-btn size="small" variant="text" @click="showConfigDialog = false">取消</v-btn>
          <v-btn
            color="primary"
            :disabled="!configValid"
            :loading="configSaving"
            size="small"
            variant="elevated"
            @click="saveRandomnessConfig"
          >
            保存配置
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 转盘配置弹窗 -->
    <v-dialog 
      v-model="showWheelConfigDialog" 
      :max-width="$vuetify.display.xs ? '95vw' : '800'"
      :fullscreen="$vuetify.display.xs"
      persistent
      scrollable
    >
      <v-card rounded="xl" elevation="16" class="wheel-config-dialog">
        <v-card-title class="wheel-config-header pa-4 pa-sm-6">
          <v-avatar size="40" class="mr-3" color="rgba(255,255,255,0.2)" variant="flat">
            <v-icon size="22" color="white">mdi-wheel-spin-outline</v-icon>
          </v-avatar>
          <div class="flex-grow-1">
            <div class="text-h6 font-weight-bold">转盘配置管理</div>
            <div class="text-body-2 opacity-90">配置奖品及其中奖概率</div>
          </div>
          <v-btn 
            icon="mdi-close" 
            variant="text" 
            color="white"
            @click="showWheelConfigDialog = false"
          ></v-btn>
        </v-card-title>
        
        <v-card-text class="pa-4 pa-sm-6">
          <!-- 概率总览卡片 -->
          <v-card 
            variant="outlined" 
            rounded="lg" 
            class="mb-6 probability-overview"
            :class="totalProbability === 100 ? 'border-success' : 'border-warning'"
          >
            <v-card-text class="pa-4">
              <div class="d-flex align-center justify-space-between mb-3">
                <div class="d-flex align-center">
                  <v-icon 
                    :color="totalProbability === 100 ? 'success' : 'warning'"
                    class="mr-2"
                  >
                    {{ totalProbability === 100 ? 'mdi-check-circle' : 'mdi-alert-circle' }}
                  </v-icon>
                  <span class="text-h6 font-weight-bold">
                    {{ totalProbability === 100 ? '概率配置完成' : '概率需要调整' }}
                  </span>
                </div>
                <v-chip 
                  :color="totalProbability === 100 ? 'success' : 'warning'"
                  variant="flat"
                  size="large"
                  class="font-weight-bold"
                >
                  {{ totalProbability }}%
                </v-chip>
              </div>
              
              <!-- 概率分布条 -->
              <div class="probability-bar-container mb-3">
                <v-progress-linear
                  :model-value="totalProbability"
                  height="12"
                  rounded
                  :color="totalProbability === 100 ? 'success' : 'warning'"
                  :bg-color="totalProbability === 100 ? 'success-lighten-4' : 'warning-lighten-4'"
                ></v-progress-linear>
              </div>
              
              <div class="text-body-2 text-medium-emphasis">
                {{ totalProbability === 100 ? '✓ 所有概率已正确分配' : `还需调整 ${Math.abs(100 - totalProbability)}%` }}
              </div>
            </v-card-text>
          </v-card>

          <!-- 积分配置 -->
          <div class="mb-6">
            <h4 class="text-h6 font-weight-bold mb-4 d-flex align-center">
              <v-icon class="mr-2" color="warning">mdi-coin</v-icon>
              积分配置
            </h4>
            
            <v-row>
              <v-col cols="12" sm="6">
                <v-card variant="outlined" rounded="lg" class="credits-config-card" elevation="2">
                  <v-card-text class="pa-4">
                    <div class="d-flex align-center mb-3">
                      <v-avatar size="32" color="warning" variant="flat" class="mr-3">
                        <v-icon size="18" color="white">mdi-ticket</v-icon>
                      </v-avatar>
                      <div>
                        <div class="text-subtitle-1 font-weight-bold">参与费用</div>
                        <div class="text-body-2 text-medium-emphasis">每次转盘消耗的积分</div>
                      </div>
                    </div>
                    
                    <v-text-field
                      v-model.number="tempWheelConfig.cost_credits"
                      label="消耗积分"
                      type="number"
                      min="1"
                      max="1000"
                      step="1"
                      density="compact"
                      variant="outlined"
                      rounded="lg"
                      :rules="[
                        v => !!v || '消耗积分不能为空',
                        v => v >= 1 || '消耗积分不能少于1',
                        v => v <= 1000 || '消耗积分不能超过1000'
                      ]"
                    >
                      <template v-slot:prepend-inner>
                        <v-icon size="small" color="warning">mdi-minus-circle</v-icon>
                      </template>
                      <template v-slot:append-inner>
                        <v-tooltip location="top">
                          <template v-slot:activator="{ props }">
                            <v-icon v-bind="props" color="grey" size="small">mdi-help-circle-outline</v-icon>
                          </template>
                          <span>用户每次参与转盘需要消耗的积分数量</span>
                        </v-tooltip>
                      </template>
                    </v-text-field>
                  </v-card-text>
                </v-card>
              </v-col>
              
              <v-col cols="12" sm="6">
                <v-card variant="outlined" rounded="lg" class="credits-config-card" elevation="2">
                  <v-card-text class="pa-4">
                    <div class="d-flex align-center mb-3">
                      <v-avatar size="32" color="info" variant="flat" class="mr-3">
                        <v-icon size="18" color="white">mdi-shield-check</v-icon>
                      </v-avatar>
                      <div>
                        <div class="text-subtitle-1 font-weight-bold">最低门槛</div>
                        <div class="text-body-2 text-medium-emphasis">参与转盘的最低积分要求</div>
                      </div>
                    </div>
                    
                    <v-text-field
                      v-model.number="tempWheelConfig.min_credits_required"
                      label="最低积分"
                      type="number"
                      min="1"
                      max="10000"
                      step="1"
                      density="compact"
                      variant="outlined"
                      rounded="lg"
                      :rules="[
                        v => !!v || '最低积分不能为空',
                        v => v >= 1 || '最低积分不能少于1',
                        v => v <= 10000 || '最低积分不能超过10000',
                        v => v >= tempWheelConfig.cost_credits || '最低积分不能少于消耗积分'
                      ]"
                    >
                      <template v-slot:prepend-inner>
                        <v-icon size="small" color="info">mdi-security</v-icon>
                      </template>
                      <template v-slot:append-inner>
                        <v-tooltip location="top">
                          <template v-slot:activator="{ props }">
                            <v-icon v-bind="props" color="grey" size="small">mdi-help-circle-outline</v-icon>
                          </template>
                          <span>用户积分低于此值时无法参与转盘</span>
                        </v-tooltip>
                      </template>
                    </v-text-field>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>
            
            <!-- 特权邀请码配置 -->
            <div class="mt-4">
              <v-card variant="outlined" rounded="lg" class="credits-config-card" elevation="2">
                <v-card-text class="pa-4">
                  <div class="d-flex align-center mb-3">
                    <v-avatar size="32" color="purple" variant="flat" class="mr-3">
                      <v-icon size="18" color="white">mdi-ticket-confirmation</v-icon>
                    </v-avatar>
                    <div>
                      <div class="text-subtitle-1 font-weight-bold">特权邀请码</div>
                      <div class="text-body-2 text-medium-emphasis">是否在奖品中生成特权邀请码</div>
                    </div>
                  </div>
                  
                  <v-switch
                    v-model="tempWheelConfig.gen_privileged_code"
                    label="启用特权邀请码奖品"
                    color="purple"
                    hide-details
                    class="mb-0"
                  >
                    <template v-slot:append>
                      <v-tooltip location="top">
                        <template v-slot:activator="{ props }">
                          <v-icon v-bind="props" color="grey" size="small">mdi-help-circle-outline</v-icon>
                        </template>
                        <span>开启后，"邀请码"类奖品将生成具有特殊权限的邀请码</span>
                      </v-tooltip>
                    </template>
                  </v-switch>
                </v-card-text>
              </v-card>
            </div>
            
            <!-- 积分配置预览 -->
            <v-alert
              type="info"
              variant="tonal"
              rounded="lg"
              class="mt-4"
            >
              <template v-slot:prepend>
                <v-icon size="large">mdi-information-outline</v-icon>
              </template>
              <div class="text-subtitle-2 mb-2 font-weight-bold">配置说明</div>
              <ul class="text-body-2">
                <li>
                  用户每次转盘将消耗 <strong>{{ tempWheelConfig.cost_credits }}</strong> 积分
                </li>
                <li>
                  用户积分需要至少 <strong>{{ tempWheelConfig.min_credits_required }}</strong> 才能参与转盘
                </li>
                <li>
                  转盘后用户最终积分 = 当前积分 - {{ tempWheelConfig.cost_credits }} + 奖品积分
                </li>
                <li v-if="tempWheelConfig.gen_privileged_code">
                  <v-icon size="small" color="purple" class="mr-1">mdi-ticket-confirmation</v-icon>
                  邀请码奖品将生成 <strong class="text-purple">特权邀请码</strong>，具有特殊权限
                </li>
                <li v-else>
                  <v-icon size="small" color="grey" class="mr-1">mdi-ticket-outline</v-icon>
                  邀请码奖品将生成 <strong>普通邀请码</strong>
                </li>
              </ul>
            </v-alert>
          </div>

          <!-- 奖品配置列表 -->
          <div class="mb-4">
            <h4 class="text-h6 font-weight-bold mb-4 d-flex align-center">
              <v-icon class="mr-2" color="primary">mdi-gift-outline</v-icon>
              奖品配置 ({{ tempWheelItems.length }}/10)
            </h4>
            
            <v-row>
              <v-col 
                v-for="(item, index) in tempWheelItems" 
                :key="index" 
                cols="12"
                class="mb-2"
              >
                <v-card 
                  variant="outlined" 
                  rounded="lg" 
                  class="item-config-card"
                  elevation="2"
                >
                  <v-card-text class="pa-4">
                    <div class="d-flex align-center mb-3">
                      <v-avatar 
                        size="32" 
                        :color="getItemColor(index)"
                        variant="flat"
                        class="mr-3"
                      >
                        <span class="text-white font-weight-bold">{{ index + 1 }}</span>
                      </v-avatar>
                      <div class="flex-grow-1">
                        <div class="text-subtitle-1 font-weight-bold">奖品 {{ index + 1 }}</div>
                        <div class="text-body-2 text-medium-emphasis">
                          当前概率：{{ item.probability || 0 }}%
                        </div>
                      </div>
                      <v-btn 
                        icon
                        size="small" 
                        color="error" 
                        variant="text"
                        @click="removeWheelItem(index)"
                        :disabled="tempWheelItems.length <= 2"
                        class="ml-2"
                      >
                        <v-icon>mdi-delete-outline</v-icon>
                        <v-tooltip activator="parent" location="top">
                          删除奖品
                        </v-tooltip>
                      </v-btn>
                    </div>
                    
                    <v-row>
                      <v-col cols="12" sm="7">
                        <v-text-field 
                          v-model="item.name" 
                          label="奖品名称"
                          placeholder="输入奖品名称"
                          density="compact"
                          variant="outlined"
                          rounded="lg"
                          hide-details
                          :rules="[v => !!v || '奖品名称不能为空']"
                        >
                          <template v-slot:prepend-inner>
                            <v-icon size="small" color="grey">mdi-gift</v-icon>
                          </template>
                        </v-text-field>
                      </v-col>
                      <v-col cols="12" sm="5">
                        <v-text-field 
                          v-model.number="item.probability" 
                          label="中奖概率"
                          suffix="%"
                          type="number"
                          min="0"
                          max="100"
                          step="0.01"
                          density="compact"
                          variant="outlined"
                          rounded="lg"
                          hide-details
                          :rules="[
                            v => v >= 0 || '概率不能为负数',
                            v => v <= 100 || '概率不能超过100%'
                          ]"
                          @blur="normalizeprobability(index)"
                        >
                          <template v-slot:prepend-inner>
                            <v-icon size="small" color="grey">mdi-percent</v-icon>
                          </template>
                        </v-text-field>
                      </v-col>
                    </v-row>
                    
                    <!-- 概率可视化条 -->
                    <div class="mt-3" v-if="item.probability > 0">
                      <v-progress-linear
                        :model-value="item.probability"
                        height="6"
                        rounded
                        :color="getItemColor(index)"
                        :bg-color="getItemColor(index) + '-lighten-4'"
                      ></v-progress-linear>
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>
          </div>
          
          <!-- 添加奖品按钮 -->
          <div class="text-center mb-4">
            <v-btn 
              @click="addWheelItem" 
              color="primary" 
              variant="tonal"
              size="large"
              rounded="lg"
              :disabled="tempWheelItems.length >= 10"
              class="add-item-btn mr-3"
            >
              <v-icon class="mr-2">mdi-plus-circle</v-icon>
              添加新奖品
              <v-tooltip activator="parent" location="top">
                最多可添加 10 个奖品
              </v-tooltip>
            </v-btn>
            
            <!-- 概率管理按钮 -->
            <v-btn 
              @click="autoDistributeProbability" 
              color="success" 
              variant="tonal"
              size="large"
              rounded="lg"
              class="mr-3"
            >
              <v-icon class="mr-2">mdi-auto-fix</v-icon>
              平均分配
              <v-tooltip activator="parent" location="top">
                将100%概率平均分配给所有奖品
              </v-tooltip>
            </v-btn>
            
            <v-btn 
              @click="clearAllProbability" 
              color="warning" 
              variant="tonal"
              size="large"
              rounded="lg"
            >
              <v-icon class="mr-2">mdi-refresh</v-icon>
              清空概率
              <v-tooltip activator="parent" location="top">
                将所有奖品概率设为0
              </v-tooltip>
            </v-btn>
          </div>
          
          <!-- 警告提示 -->
          <v-alert 
            v-if="totalProbability !== 100" 
            type="warning" 
            variant="tonal"
            rounded="lg"
            class="mb-4"
            prominent
          >
            <template v-slot:prepend>
              <v-icon size="large">mdi-alert-circle</v-icon>
            </template>
            <div class="text-subtitle-1 font-weight-bold mb-2">概率配置不完整</div>
            <div class="text-body-2 mb-3">
              当前总概率为 <strong>{{ totalProbability }}%</strong>，
              {{ totalProbability < 100 ? `还需要分配 ${(100 - totalProbability).toFixed(2)}%` : `超出了 ${(totalProbability - 100).toFixed(2)}%` }}
            </div>
            
            <!-- 快速调整按钮 -->
            <div class="d-flex flex-wrap gap-2" v-if="totalProbability !== 100">
              <v-btn
                v-if="totalProbability < 100"
                @click="adjustProbabilityToTotal"
                color="warning"
                variant="outlined"
                size="small"
                rounded="lg"
              >
                <v-icon class="mr-1" size="small">mdi-plus</v-icon>
                补齐到100%
              </v-btn>
              
              <v-btn
                v-if="totalProbability > 100"
                @click="normalizeProbabilityToTotal"
                color="warning"
                variant="outlined"
                size="small"
                rounded="lg"
              >
                <v-icon class="mr-1" size="small">mdi-percent</v-icon>
                按比例调整
              </v-btn>
            </div>
          </v-alert>

          <!-- 成功提示 -->
          <v-alert 
            v-if="totalProbability === 100" 
            type="success" 
            variant="tonal"
            rounded="lg"
            class="mb-4"
          >
            <template v-slot:prepend>
              <v-icon size="large">mdi-check-circle</v-icon>
            </template>
            <div class="text-subtitle-1 font-weight-bold">配置完成</div>
            <div class="text-body-2">所有奖品的概率已正确分配，可以保存配置了！</div>
          </v-alert>
        </v-card-text>
        
        <v-card-actions class="pa-4 pa-sm-6 bg-grey-lighten-5">
          <v-spacer></v-spacer>
          <v-btn 
            variant="text" 
            @click="showWheelConfigDialog = false"
            class="mr-2"
          >
            取消
          </v-btn>
          <v-btn
            color="primary"
            :disabled="!isValidConfig"
            :loading="configSaving"
            variant="elevated"
            rounded="lg"
            @click="saveWheelConfig"
          >
            <v-icon class="mr-2">mdi-content-save</v-icon>
            保存配置
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script>
import LuckyWheel from '@/components/LuckyWheel.vue'
import { getLuckyWheelRandomnessConfig, getLuckyWheelRandomnessStats, updateLuckyWheelRandomnessConfig, getLuckyWheelConfig, updateLuckyWheelConfig } from '@/services/wheelService'

export default {
  name: 'WheelAdminPanel',
  components: {
    LuckyWheel
  },
  data() {
    return {
      showTestDialog: false,
      showConfigDialog: false,
      showWheelConfigDialog: false,
      wheelItems: [],
      tempWheelItems: [],
      wheelConfig: {
        cost_credits: 10,
        min_credits_required: 30,
        gen_privileged_code: false
      },
      tempWheelConfig: {
        cost_credits: 10,
        min_credits_required: 30,
        gen_privileged_code: false
      },
      randomnessConfig: {
        use_weighted_protection: true,
        protection_threshold: 2.0,
        protection_factor: 1.2,
        use_time_seed_mixing: true,
        use_user_seed_mixing: true
      },
      lastTestResult: null,
      testRunning: false,
      testIterations: 10000,
      currentTestResult: null,
      configValid: false,
      configSaving: false,
      selectedPreset: null,
      thresholdRules: [
        v => !!v || '保护阈值不能为空',
        v => (v >= 0.1 && v <= 50) || '保护阈值必须在 0.1% 到 50% 之间'
      ],
      factorRules: [
        v => !!v || '保护系数不能为空',
        v => (v >= 1.0 && v <= 3.0) || '保护系数必须在 1.0 到 3.0 之间'
      ],
      presets: {
        conservative: {
          use_weighted_protection: true,
          protection_threshold: 5.0,
          protection_factor: 1.5,
          use_time_seed_mixing: true,
          use_user_seed_mixing: true
        },
        balanced: {
          use_weighted_protection: true,
          protection_threshold: 2.0,
          protection_factor: 1.2,
          use_time_seed_mixing: true,
          use_user_seed_mixing: true
        },
        aggressive: {
          use_weighted_protection: false,
          protection_threshold: 1.0,
          protection_factor: 1.0,
          use_time_seed_mixing: true,
          use_user_seed_mixing: false
        }
      }
    }
  },
  mounted() {
    this.loadRandomnessConfig()
    this.loadLastTestResult()
    this.loadWheelConfig()
  },
  computed: {
    totalProbability() {
      // 使用更精确的浮点数计算方法
      const total = this.tempWheelItems.reduce((sum, item) => {
        const prob = parseFloat(item.probability) || 0
        return sum + prob
      }, 0)
      // 保留两位小数并解决浮点数精度问题
      return Math.round((total + Number.EPSILON) * 100) / 100
    },
    isValidConfig() {
      // 检查所有奖品配置是否有效
      const allItemsValid = this.tempWheelItems.every(item => 
        item.name && item.name.trim() !== '' && 
        item.probability >= 0 && 
        item.probability <= 100 &&
        !isNaN(item.probability)
      )
      
      // 检查概率总和是否为100%（允许0.01的误差）
      const totalValid = Math.abs(this.totalProbability - 100) <= 0.01
      
      // 检查是否至少有2个奖品
      const countValid = this.tempWheelItems.length >= 2
      
      // 检查积分配置是否有效
      const creditsValid = this.tempWheelConfig.cost_credits >= 1 && 
                          this.tempWheelConfig.cost_credits <= 1000 &&
                          this.tempWheelConfig.min_credits_required >= 1 && 
                          this.tempWheelConfig.min_credits_required <= 10000 &&
                          this.tempWheelConfig.min_credits_required >= this.tempWheelConfig.cost_credits &&
                          !isNaN(this.tempWheelConfig.cost_credits) &&
                          !isNaN(this.tempWheelConfig.min_credits_required)
      
      return allItemsValid && totalValid && countValid && creditsValid
    },
    testAnalysis() {
      if (!this.currentTestResult || !this.currentTestResult.stats) {
        return null
      }

      const stats = this.currentTestResult.stats
      const overallFairness = this.currentTestResult.overall_fairness
      const averageDeviation = this.currentTestResult.average_deviation

      // 分析异常项目
      const unfairItems = stats.filter(stat => !stat.is_fair)
      const highDeviationItems = stats.filter(stat => Math.abs(stat.deviation) > 5)
      
      let analysis = {
        type: 'success',
        icon: 'mdi-check-circle',
        title: '测试结果良好',
        message: '所有奖品的随机性表现正常，概率分布符合预期。',
        suggestions: []
      }

      if (!overallFairness || unfairItems.length > 0) {
        analysis.type = 'warning'
        analysis.icon = 'mdi-alert-circle'
        analysis.title = '发现随机性异常'
        analysis.message = `有 ${unfairItems.length} 个奖品的概率分布存在异常，平均偏差为 ${averageDeviation}%。`
        
        if (highDeviationItems.length > 0) {
          analysis.suggestions.push(`${highDeviationItems.length} 个奖品偏差超过5%，建议调整随机性参数`)
        }
        
        if (unfairItems.some(item => item.deviation > 10)) {
          analysis.suggestions.push('部分奖品偏差过大，建议启用低概率保护机制')
        }
        
        if (this.randomnessConfig.use_weighted_protection && unfairItems.length > 0) {
          analysis.suggestions.push('可以尝试调整保护阈值或保护系数')
        }
        
        if (!this.randomnessConfig.use_time_seed_mixing || !this.randomnessConfig.use_user_seed_mixing) {
          analysis.suggestions.push('建议启用时间熵和用户ID熵混合以增强随机性')
        }
      }

      if (averageDeviation > 3) {
        analysis.type = 'error'
        analysis.icon = 'mdi-alert-circle-outline'
        analysis.title = '随机性严重异常'
        analysis.message = `平均偏差高达 ${averageDeviation}%，随机算法可能存在问题。`
        analysis.suggestions.push('建议立即检查和调整随机性配置')
        analysis.suggestions.push('考虑增加测试次数以获得更准确的结果')
      }

      return analysis
    }
  },
  methods: {
    async loadRandomnessConfig() {
      try {
        const response = await getLuckyWheelRandomnessConfig()
        if (response.data && Object.keys(response.data).length > 0) {
          this.randomnessConfig = { ...this.randomnessConfig, ...response.data }
        }
      } catch (error) {
        console.error('加载随机性配置失败:', error)
        // 使用默认配置，不清空现有配置
        console.log('使用默认随机性配置')
      }
    },

    loadLastTestResult() {
      // 从本地存储或API加载最近的测试结果
      const stored = localStorage.getItem('lastRandomnessTest')
      if (stored) {
        this.lastTestResult = JSON.parse(stored)
      }
    },

    async loadWheelConfig() {
      try {
        const response = await getLuckyWheelConfig()
        this.wheelItems = response.data.items || []
        this.wheelConfig = {
          cost_credits: response.data.cost_credits || 10,
          min_credits_required: response.data.min_credits_required || 30,
          gen_privileged_code: response.data.gen_privileged_code || false
        }
      } catch (error) {
        console.error('加载转盘配置失败:', error)
        this.wheelItems = []
        this.wheelConfig = {
          cost_credits: 10,
          min_credits_required: 30,
          gen_privileged_code: false
        }
      }
    },

    openWheelConfig() {
      this.tempWheelItems = JSON.parse(JSON.stringify(this.wheelItems))
      this.tempWheelConfig = JSON.parse(JSON.stringify(this.wheelConfig))
      this.showWheelConfigDialog = true
    },

    openRandomnessTest() {
      // 直接在当前组件中显示测试对话框
      this.showTestDialog = true
    },

    openRandomnessConfig() {
      this.showConfigDialog = true
    },

    viewStats() {
      // 跳转到统计页面
      this.$router.push('/admin/wheel-stats')
    },

    onConfigUpdated(newConfig) {
      this.randomnessConfig = { ...newConfig }
      // 显示成功消息
      this.$emit('show-message', '随机性配置更新成功')
    },

    applyPreset(presetName) {
      if (presetName && this.presets[presetName]) {
        this.randomnessConfig = { ...this.presets[presetName] }
      }
    },

    async saveRandomnessConfig() {
      if (!this.configValid) return
      
      this.configSaving = true
      try {
        await updateLuckyWheelRandomnessConfig(this.randomnessConfig)
        
        this.showConfigDialog = false
        this.selectedPreset = null
        
        // 重新加载配置以确保显示最新状态
        await this.loadRandomnessConfig()
        
        // 通知 LuckyWheel 组件重新加载配置
        if (this.$refs.luckyWheel) {
          this.$refs.luckyWheel.reloadConfig()
        }
        
        // 显示成功消息
        this.$emit('show-message', '随机性配置更新成功')
        
        console.log('随机性配置更新成功')
      } catch (error) {
        console.error('保存随机性配置失败:', error)
        alert('保存配置失败，请稍后重试')
      } finally {
        this.configSaving = false
      }
    },

    async runRandomnessTest() {
      if (this.testRunning) return
      
      this.testRunning = true
      this.currentTestResult = null
      
      try {
        console.log('开始随机性测试，迭代次数:', this.testIterations)
        const response = await getLuckyWheelRandomnessStats(this.testIterations)
        console.log('API响应:', response.data)
        
        // 处理API返回的数据
        const data = response.data
        
        // 将 stats 对象转换为数组格式，以便前端使用
        const statsArray = Object.entries(data.stats || {}).map(([name, stat]) => ({
          name: name,
          expected_probability: stat.expected_rate,
          actual_probability: stat.actual_rate,
          deviation: stat.deviation,
          count: stat.win_count,
          is_fair: stat.is_fair
        }))
        
        this.currentTestResult = {
          iterations: data.iterations,
          valid_items: data.valid_items,
          average_deviation: data.average_deviation,
          overall_fairness: data.overall_fairness,
          stats: statsArray,
          timestamp: new Date().toISOString()
        }
        
        // 更新随机性配置（如果API返回了配置信息）
        if (data.config) {
          this.randomnessConfig = { ...this.randomnessConfig, ...data.config }
        }
        
        // 保存为最近测试结果
        this.lastTestResult = { ...this.currentTestResult }
        localStorage.setItem('lastRandomnessTest', JSON.stringify(this.lastTestResult))
        
        console.log('随机性测试完成:', this.currentTestResult)
      } catch (error) {
        console.error('随机性测试失败:', error)
        console.error('错误详情:', error.response?.data)
        const errorMessage = error.response?.data?.detail || error.message || '随机性测试失败，请稍后重试'
        alert(errorMessage)
      } finally {
        this.testRunning = false
      }
    },

    onTestCompleted(result) {
      this.lastTestResult = {
        ...result,
        timestamp: new Date().toISOString()
      }
      
      // 保存到本地存储
      localStorage.setItem('lastRandomnessTest', JSON.stringify(this.lastTestResult))
      
      this.showTestDialog = false
    },

    formatDate(timestamp) {
      return new Date(timestamp).toLocaleDateString('zh-CN')
    },

    // 转盘事件处理方法
    onSpinComplete(result) {
      console.log('转盘完成:', result)
    },

    onResultClosed(result) {
      console.log('结果弹窗关闭:', result)
    },

    async saveWheelConfig() {
      // 检查概率总和是否精确为100%
      const totalProb = this.totalProbability
      if (Math.abs(totalProb - 100) > 0.01) {
        alert(`总概率必须为100%，当前为${totalProb}%，请检查配置`)
        return
      }

      // 检查是否有无效的配置项
      const invalidItems = this.tempWheelItems.filter(item => 
        !item.name || item.name.trim() === '' || 
        item.probability < 0 || 
        item.probability > 100 ||
        isNaN(item.probability)
      )
      
      if (invalidItems.length > 0) {
        alert('存在无效的奖品配置，请检查奖品名称和概率设置')
        return
      }

      this.configSaving = true
      try {
        // 在保存前再次规范化所有概率值
        this.tempWheelItems.forEach(item => {
          item.probability = Math.round((parseFloat(item.probability) + Number.EPSILON) * 100) / 100
        })
        
        const configData = {
          items: this.tempWheelItems,
          cost_credits: this.tempWheelConfig.cost_credits,
          min_credits_required: this.tempWheelConfig.min_credits_required,
          gen_privileged_code: this.tempWheelConfig.gen_privileged_code
        }
        
        await updateLuckyWheelConfig(configData)
        
        // 更新本地配置
        this.wheelItems = JSON.parse(JSON.stringify(this.tempWheelItems))
        this.wheelConfig = JSON.parse(JSON.stringify(this.tempWheelConfig))
        this.showWheelConfigDialog = false
        
        // 通知 LuckyWheel 组件重新加载配置
        if (this.$refs.luckyWheel) {
          this.$refs.luckyWheel.reloadConfig()
        }
        
        this.$emit('show-message', '转盘配置更新成功')
        console.log('转盘配置更新成功')
        
      } catch (error) {
        console.error('更新转盘配置失败:', error)
        const errorMessage = error.response?.data?.detail || '更新配置失败，请稍后重试'
        alert(errorMessage)
      } finally {
        this.configSaving = false
      }
    },

    addWheelItem() {
      this.tempWheelItems.push({ 
        name: `新奖品 ${this.tempWheelItems.length + 1}`, 
        probability: 0 
      })
    },

    removeWheelItem(index) {
      if (this.tempWheelItems.length > 2) {
        this.tempWheelItems.splice(index, 1)
      }
    },

    getItemColor(index) {
      const colors = [
        'primary', 'secondary', 'success', 'info', 
        'warning', 'error', 'purple', 'teal'
      ]
      return colors[index % colors.length]
    },

    getDeviationColor(deviation) {
      const absDeviation = Math.abs(deviation)
      if (absDeviation <= 2) return 'success'
      if (absDeviation <= 5) return 'warning'
      return 'error'
    },

    getFairnessColor(isFair) {
      return isFair ? 'success' : 'error'
    },

    getStatCardClass(stat) {
      const deviation = Math.abs(stat.deviation)
      if (deviation <= 2) return 'stat-card-success'
      if (deviation <= 5) return 'stat-card-warning'
      return 'stat-card-error'
    },

    // 概率管理辅助方法
    normalizeprobability(index) {
      // 规范化单个概率值，避免浮点数精度问题
      const item = this.tempWheelItems[index]
      if (item && item.probability !== undefined) {
        item.probability = Math.round((parseFloat(item.probability) + Number.EPSILON) * 100) / 100
      }
    },

    autoDistributeProbability() {
      // 平均分配概率
      if (this.tempWheelItems.length === 0) return
      
      const averageProbability = 100 / this.tempWheelItems.length
      const roundedProbability = Math.floor(averageProbability * 100) / 100
      const remainder = 100 - (roundedProbability * this.tempWheelItems.length)
      
      this.tempWheelItems.forEach((item, index) => {
        item.probability = roundedProbability
        // 将余数分配给前几个奖品
        if (index < Math.round(remainder * 100)) {
          item.probability += 0.01
        }
      })
      
      // 确保精确为100%
      this.adjustProbabilityToExact100()
    },

    clearAllProbability() {
      // 清空所有概率
      this.tempWheelItems.forEach(item => {
        item.probability = 0
      })
    },

    adjustProbabilityToTotal() {
      // 补齐到100%，将差值加到第一个奖品上
      if (this.tempWheelItems.length === 0) return
      
      const difference = 100 - this.totalProbability
      if (difference > 0) {
        this.tempWheelItems[0].probability = (this.tempWheelItems[0].probability || 0) + difference
        this.tempWheelItems[0].probability = Math.round((this.tempWheelItems[0].probability + Number.EPSILON) * 100) / 100
      }
    },

    normalizeProbabilityToTotal() {
      // 按比例调整所有概率使其总和为100%
      if (this.totalProbability === 0) return
      
      const factor = 100 / this.totalProbability
      let newTotal = 0
      
      this.tempWheelItems.forEach((item) => {
        const newProbability = (item.probability || 0) * factor
        item.probability = Math.round((newProbability + Number.EPSILON) * 100) / 100
        newTotal += item.probability
      })
      
      // 处理舍入误差
      const finalDifference = 100 - newTotal
      if (Math.abs(finalDifference) > 0.01) {
        // 将差值分配给概率最大的奖品
        const maxIndex = this.tempWheelItems.reduce((maxIdx, item, idx) => 
          (item.probability || 0) > (this.tempWheelItems[maxIdx].probability || 0) ? idx : maxIdx, 0)
        this.tempWheelItems[maxIndex].probability += finalDifference
        this.tempWheelItems[maxIndex].probability = Math.round((this.tempWheelItems[maxIndex].probability + Number.EPSILON) * 100) / 100
      }
    },

    adjustProbabilityToExact100() {
      // 精确调整到100%，处理舍入误差
      const currentTotal = this.totalProbability
      if (Math.abs(currentTotal - 100) < 0.01) return
      
      const difference = 100 - currentTotal
      if (this.tempWheelItems.length > 0) {
        // 找到概率最大的奖品进行微调
        const maxIndex = this.tempWheelItems.reduce((maxIdx, item, idx) => 
          (item.probability || 0) > (this.tempWheelItems[maxIdx].probability || 0) ? idx : maxIdx, 0)
        
        this.tempWheelItems[maxIndex].probability += difference
        this.tempWheelItems[maxIndex].probability = Math.round((this.tempWheelItems[maxIndex].probability + Number.EPSILON) * 100) / 100
      }
    }
  }
}
</script>

<style scoped>
/* 主面板样式 */
.admin-panel {
  min-height: 100vh;
  background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
  padding: 16px 0;
}

@media (min-width: 600px) {
  .admin-panel {
    padding: 24px 0;
  }
}

/* 统一的卡片样式 */
.admin-card {
  height: 100%;
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  border: 1px solid rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.admin-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12) !important;
}

.admin-card-header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
  min-height: 64px;
}

.admin-card .v-card-text {
  min-height: 80px;
  display: flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.95);
}

.admin-card .v-card-actions {
  background: rgba(255, 255, 255, 0.95);
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}

/* 预览卡片样式 */
.preview-card {
  border: 1px solid rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.preview-card-header {
  background: linear-gradient(135deg, #9c27b0 0%, #673ab7 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
}

.wheel-preview-container {
  max-width: 320px;
  margin: 0 auto;
  padding: 16px;
  background: radial-gradient(circle at center, rgba(156, 39, 176, 0.05) 0%, transparent 70%);
  border-radius: 16px;
}

@media (min-width: 600px) {
  .wheel-preview-container {
    max-width: 400px;
    padding: 24px;
  }
}

/* 配置卡片样式 */
.config-card {
  border: 1px solid rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.config-card-header {
  background: linear-gradient(135deg, #009688 0%, #4caf50 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
}

.config-item {
  text-align: center;
  padding: 8px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
  margin: 4px 0;
  transition: all 0.2s ease;
}

.config-item:hover {
  background: rgba(255, 255, 255, 0.9);
  transform: translateY(-1px);
}

.config-label {
  font-size: 0.75rem;
  color: rgba(0, 0, 0, 0.6);
  margin-bottom: 4px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.config-value {
  font-weight: 600;
  font-size: 0.875rem;
}

.config-number {
  color: #1976d2;
  font-family: 'Monaco', 'Courier New', monospace;
}

.config-chip {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.25px;
}

.config-btn {
  border-width: 2px;
  font-weight: 600;
}

@media (min-width: 600px) {
  .config-label {
    font-size: 0.8rem;
  }
  
  .config-value {
    font-size: 1rem;
  }
}

/* 结果卡片样式 */
.result-card {
  border: 1px solid rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.result-card-header {
  background: linear-gradient(135deg, #673ab7 0%, #3f51b5 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
}

.result-chip {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

/* 统计卡片样式 */
.stat-card {
  border: 2px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px !important;
  transition: all 0.2s ease;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.9) 100%);
}

.stat-card:hover {
  border-color: rgba(25, 118, 210, 0.3);
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

.test-result-row .v-col {
  padding: 8px 6px;
}

@media (min-width: 600px) {
  .test-result-row .v-col {
    padding: 12px 8px;
  }
}

/* 对话框样式 */
.dialog-card {
  border: 1px solid rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.dialog-header {
  background: linear-gradient(135deg, #2196f3 0%, #21cbf3 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
  position: sticky;
  top: 0;
  z-index: 2;
}

/* 设置卡片样式 */
.setting-card {
  border: 2px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px !important;
  transition: all 0.2s ease;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.9) 100%);
}

.setting-card:hover {
  border-color: rgba(25, 118, 210, 0.2);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

/* 预设配置按钮组 */
.preset-toggle {
  width: 100%;
  border-radius: 12px !important;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.preset-toggle .v-btn {
  flex: 1;
  border-radius: 0 !important;
  font-weight: 600;
  letter-spacing: 0.25px;
}

.preset-toggle .v-btn:first-child {
  border-radius: 12px 0 0 12px !important;
}

.preset-toggle .v-btn:last-child {
  border-radius: 0 12px 12px 0 !important;
}

/* 全局按钮样式优化 */
.v-btn {
  border-radius: 12px !important;
  font-weight: 600;
  letter-spacing: 0.25px;
  text-transform: none;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transition: all 0.2s ease;
}

.v-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
}

/* 表单字段样式 */
.v-text-field .v-field {
  border-radius: 12px !important;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
}

.v-switch {
  border-radius: 8px;
}

/* 芯片样式 */
.v-chip {
  border-radius: 8px !important;
  font-weight: 600;
  letter-spacing: 0.25px;
}

/* 进度环样式 */
.v-progress-circular {
  filter: drop-shadow(0 2px 8px rgba(25, 118, 210, 0.3));
}

/* 小屏幕优化 */
@media (max-width: 599px) {
  .admin-panel {
    padding: 12px 0;
  }
  
  .admin-card-header {
    min-height: 56px;
  }
  
  .admin-card .v-card-text {
    min-height: 64px;
  }
  
  .admin-card .v-card-title span {
    font-size: 0.8rem;
    line-height: 1.2;
  }
  
  .admin-card .v-card-text div {
    font-size: 0.75rem;
    line-height: 1.3;
  }
  
  .test-result-row .text-caption {
    font-size: 0.65rem;
  }
  
  .config-item {
    padding: 6px;
    margin: 2px 0;
  }
  
  .wheel-preview-container {
    max-width: 280px;
    padding: 12px;
  }
  
  .dialog-header {
    border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  }
}

/* 深色模式支持 */
@media (prefers-color-scheme: dark) {
  .admin-panel {
    background: linear-gradient(135deg, #1a202c 0%, #2d3748 100%);
  }
  
  .stat-card,
  .setting-card {
    background: linear-gradient(135deg, rgba(45, 55, 72, 0.9) 0%, rgba(26, 32, 44, 0.9) 100%);
    border-color: rgba(255, 255, 255, 0.1);
  }
  
  .config-item {
    background: rgba(45, 55, 72, 0.6);
    color: white;
  }
  
  .config-item:hover {
    background: rgba(45, 55, 72, 0.8);
  }
}

/* 转盘配置弹窗样式 */
.wheel-config-dialog {
  max-height: 90vh;
  overflow: hidden;
}

.wheel-config-header {
  background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
  color: white;
  border-radius: 16px 16px 0 0 !important;
  position: sticky;
  top: 0;
  z-index: 10;
}

/* 概率总览卡片样式 */
.probability-overview {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(248, 250, 252, 0.95) 100%);
  border-width: 2px !important;
  transition: all 0.3s ease;
}

.probability-overview.border-success {
  border-color: rgb(var(--v-theme-success)) !important;
  box-shadow: 0 4px 16px rgba(76, 175, 80, 0.2);
}

.probability-overview.border-warning {
  border-color: rgb(var(--v-theme-warning)) !important;
  box-shadow: 0 4px 16px rgba(255, 152, 0, 0.2);
}

.probability-bar-container {
  position: relative;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 8px;
  padding: 2px;
}

/* 奖品配置卡片样式 */
.item-config-card {
  border: 2px solid rgba(0, 0, 0, 0.08);
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.9) 100%);
  position: relative;
  overflow: hidden;
}

.item-config-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, 
    rgb(var(--v-theme-primary)) 0%, 
    rgb(var(--v-theme-secondary)) 50%, 
    rgb(var(--v-theme-success)) 100%
  );
  opacity: 0;
  transition: opacity 0.3s ease;
}

.item-config-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
  border-color: rgba(25, 118, 210, 0.3);
}

.item-config-card:hover::before {
  opacity: 1;
}

/* 添加奖品按钮样式 */
.add-item-btn {
  min-width: 160px;
  height: 56px;
  font-weight: 600;
  letter-spacing: 0.5px;
  box-shadow: 0 4px 16px rgba(25, 118, 210, 0.3);
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
}

.add-item-btn:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 32px rgba(25, 118, 210, 0.4);
}

.add-item-btn:disabled {
  opacity: 0.6;
  transform: none !important;
  box-shadow: none !important;
}

/* 概率管理按钮样式 */
.v-btn.mr-3 {
  margin-right: 12px;
}

/* 快速调整按钮样式 */
.gap-2 {
  gap: 8px;
}

/* 表单字段增强样式 */
.item-config-card .v-text-field .v-field {
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(0, 0, 0, 0.08);
  transition: all 0.2s ease;
}

.item-config-card .v-text-field .v-field:hover {
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(25, 118, 210, 0.3);
}

.item-config-card .v-text-field .v-field--focused {
  background: white;
  border-color: rgb(var(--v-theme-primary));
  box-shadow: 0 0 0 2px rgba(25, 118, 210, 0.2);
}

/* 进度条样式增强 */
.v-progress-linear {
  border-radius: 6px;
  overflow: hidden;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1);
}

.v-progress-linear .v-progress-linear__background {
  opacity: 0.3;
}

.v-progress-linear .v-progress-linear__determinate {
  background: linear-gradient(90deg, currentColor 0%, rgba(255, 255, 255, 0.3) 50%, currentColor 100%);
  background-size: 20px 20px;
  animation: progressShine 2s linear infinite;
}

@keyframes progressShine {
  0% { background-position: -20px 0; }
  100% { background-position: 20px 0; }
}

/* 警告和成功提示样式增强 */
.v-alert {
  border-width: 2px;
  border-style: solid;
}

.v-alert--variant-tonal {
  background: linear-gradient(135deg, rgba(var(--v-theme-surface), 0.95) 0%, rgba(var(--v-theme-surface), 0.85) 100%);
  backdrop-filter: blur(10px);
}

/* 卡片动作区域样式 */
.v-card-actions.bg-grey-lighten-5 {
  background: linear-gradient(135deg, rgba(248, 250, 252, 0.9) 0%, rgba(241, 245, 249, 0.9) 100%) !important;
  backdrop-filter: blur(10px);
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}

/* 测试详情卡片样式 */
.item-stat-card {
  border: 2px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px !important;
  transition: all 0.3s ease;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(248, 250, 252, 0.95) 100%);
  height: 100%;
}

.item-stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
}

.stat-card-success {
  border-color: rgba(76, 175, 80, 0.3);
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.02) 0%, rgba(255, 255, 255, 0.95) 100%);
}

.stat-card-success:hover {
  border-color: rgba(76, 175, 80, 0.5);
  box-shadow: 0 6px 20px rgba(76, 175, 80, 0.15);
}

.stat-card-warning {
  border-color: rgba(255, 152, 0, 0.3);
  background: linear-gradient(135deg, rgba(255, 152, 0, 0.02) 0%, rgba(255, 255, 255, 0.95) 100%);
}

.stat-card-warning:hover {
  border-color: rgba(255, 152, 0, 0.5);
  box-shadow: 0 6px 20px rgba(255, 152, 0, 0.15);
}

.stat-card-error {
  border-color: rgba(244, 67, 54, 0.3);
  background: linear-gradient(135deg, rgba(244, 67, 54, 0.02) 0%, rgba(255, 255, 255, 0.95) 100%);
}

.stat-card-error:hover {
  border-color: rgba(244, 67, 54, 0.5);
  box-shadow: 0 6px 20px rgba(244, 67, 54, 0.15);
}

/* 概率对比可视化样式 */
.probability-comparison {
  background: rgba(248, 250, 252, 0.5);
  border-radius: 8px;
  padding: 8px;
  margin: 4px 0;
}

/* 测试分析提示样式 */
.test-analysis-alert {
  border: 2px solid;
  border-radius: 12px !important;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

.test-analysis-alert .v-alert__content {
  padding: 16px;
}

/* 响应式优化 */
@media (max-width: 959px) {
  .item-stat-card {
    margin-bottom: 16px;
  }
}

@media (max-width: 599px) {
  .probability-comparison {
    padding: 6px;
  }
  
  .item-stat-card .v-card-text {
    padding: 12px;
  }
  
  .test-analysis-alert .v-alert__content {
    padding: 12px;
  }
}

/* 积分配置卡片样式 */
.credits-config-card {
  border: 2px solid rgba(0, 0, 0, 0.08);
  transition: all 0.3s ease;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.9) 100%);
  position: relative;
  overflow: hidden;
}

.credits-config-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, 
    rgb(var(--v-theme-warning)) 0%, 
    rgb(var(--v-theme-info)) 100%
  );
  opacity: 0;
  transition: opacity 0.3s ease;
}

.credits-config-card:hover {
  border-color: rgba(255, 152, 0, 0.3);
  box-shadow: 0 4px 16px rgba(255, 152, 0, 0.1);
}

.credits-config-card:hover::before {
  opacity: 1;
}
</style>
