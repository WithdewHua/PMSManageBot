<template>
  <div class="lucky-wheel-container">
    <div class="wheel-wrapper">
      <!-- 转盘 -->
      <div class="wheel" ref="wheel" :style="{ transform: `rotate(${rotation}deg)` }">
        <!-- 使用SVG绘制扇形 -->
        <svg class="wheel-svg" viewBox="0 0 200 200" width="100%" height="100%">
          <g v-for="(item, index) in wheelItems" :key="index">
            <path 
              :d="getSectorPath(index)"
              :fill="getSectorColor(index)"
              stroke="white"
              stroke-width="2"
            />
            <text 
              :x="getSectorTextX(index)"
              :y="getSectorTextY(index)"
              fill="white"
              :font-size="getTextSize()"
              font-weight="bold"
              text-anchor="middle"
              dominant-baseline="central"
              style="text-shadow: 2px 2px 4px rgba(0,0,0,0.8);"
            >
              {{ getDisplayText(item.name) }}
            </text>
          </g>
        </svg>
      </div>
      
      <!-- 指针 -->
      <div class="pointer">
        <div class="arrow-pointer">
          <div class="arrow-body"></div>
          <div class="arrow-tip"></div>
        </div>
      </div>
      
      <!-- 中心圆 -->
      <div class="center-circle">
        <v-btn 
          :disabled="isSpinning || disabled"
          @click="spin"
          class="spin-btn"
          color="primary"
          variant="elevated"
        >
          {{ isSpinning ? '转动中...' : (disabled ? '已用完' : '开始') }}
        </v-btn>
      </div>
    </div>

    <!-- 结果弹窗 -->
    <v-dialog v-model="showResult" max-width="400">
      <v-card class="result-card">
        <v-card-title class="text-center">
          <v-icon size="60" color="warning">mdi-trophy</v-icon>
        </v-card-title>
        <v-card-text class="text-center">
          <h2 class="mb-4">恭喜您！</h2>
          <p class="text-h5 mb-2">获得了</p>
          <p class="text-h4 text-primary font-weight-bold">{{ winResult?.name }}</p>
        </v-card-text>
        <v-card-actions class="justify-center">
          <v-btn color="primary" @click="closeResult">确定</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 配置弹窗 -->
    <v-dialog v-model="showConfig" max-width="500">
      <v-card>
        <v-card-title>配置转盘</v-card-title>
        <v-card-text>
          <v-row v-for="(item, index) in tempWheelItems" :key="index" class="mb-2">
            <v-col cols="6">
              <v-text-field 
                v-model="item.name" 
                label="奖品名称"
                density="compact"
                variant="outlined"
              ></v-text-field>
            </v-col>
            <v-col cols="4">
              <v-text-field 
                v-model.number="item.probability" 
                label="概率%"
                type="number"
                min="0"
                max="100"
                density="compact"
                variant="outlined"
              ></v-text-field>
            </v-col>
            <v-col cols="2" class="d-flex align-center">
              <v-btn 
                icon="mdi-delete" 
                size="small" 
                color="error" 
                variant="text"
                @click="removeItem(index)"
                :disabled="tempWheelItems.length <= 2"
              ></v-btn>
            </v-col>
          </v-row>
          
          <div class="text-center mb-3">
            <v-btn 
              @click="addItem" 
              color="primary" 
              variant="outlined"
              :disabled="tempWheelItems.length >= 8"
            >
              <v-icon>mdi-plus</v-icon>
              添加奖品
            </v-btn>
          </div>
          
          <v-alert 
            v-if="totalProbability !== 100" 
            type="warning" 
            density="compact"
          >
            当前总概率：{{ totalProbability }}%，请调整使总概率为100%
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn @click="cancelConfig">取消</v-btn>
          <v-btn 
            color="primary" 
            @click="saveConfig"
            :disabled="totalProbability !== 100"
          >
            保存
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 配置按钮 - 只有管理员能看到 -->
    <v-btn 
      v-if="isAdmin"
      class="config-btn"
      icon="mdi-cog"
      color="primary"
      @click="openConfig"
    ></v-btn>
  </div>
</template>

<script>
import { getUserInfo } from '@/api'

export default {
  name: 'LuckyWheel',
  props: {
    disabled: {
      type: Boolean,
      default: false
    }
  },
  emits: ['spin-complete', 'result-closed'],
  data() {
    return {
      rotation: 0,
      isSpinning: false,
      showResult: false,
      showConfig: false,
      winResult: null,
      isAdmin: false, // 添加管理员状态
      wheelItems: [
        { name: '谢谢参与', probability: 15 },
        { name: '积分 +10', probability: 25 },
        { name: '积分 -10', probability: 30 },
        { name: '积分 +30', probability: 15 },
        { name: '积分 -30', probability: 10 },
        { name: '邀请码 1 枚', probability: 0.5 },
        { name: '积分 +100', probability: 1.5 },
        { name: '积分 -100', probability: 1.5 },
        { name: '积分翻倍', probability: 0.8 },
        { name: '积分减半', probability: 0.7 },
      ],
      tempWheelItems: []
    }
  },
  mounted() {
    // 检查管理员权限
    this.checkAdminPermission()
  },
  computed: {
    totalProbability() {
      return this.tempWheelItems.reduce((sum, item) => sum + (item.probability || 0), 0)
    }
  },
  methods: {
    // 检查管理员权限
    async checkAdminPermission() {
      try {
        const response = await getUserInfo()
        this.isAdmin = response.data.is_admin
      } catch (error) {
        console.error('检查管理员权限失败:', error)
        this.isAdmin = false
      }
    },
    
    getSectorPath(index) {
      const angle = 360 / this.wheelItems.length
      const startAngle = index * angle
      const endAngle = (index + 1) * angle
      
      // 转换为弧度
      const startRad = (startAngle - 90) * Math.PI / 180
      const endRad = (endAngle - 90) * Math.PI / 180
      
      // 圆心和半径 - 使用SVG viewBox的全部空间
      const centerX = 100
      const centerY = 100
      const radius = 98
      
      // 计算起始和结束点
      const x1 = centerX + radius * Math.cos(startRad)
      const y1 = centerY + radius * Math.sin(startRad)
      const x2 = centerX + radius * Math.cos(endRad)
      const y2 = centerY + radius * Math.sin(endRad)
      
      // 判断是否是大弧
      const largeArc = angle > 180 ? 1 : 0
      
      // 创建SVG路径
      return `M ${centerX} ${centerY} L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z`
    },
    
    getSectorColor(index) {
      const colors = [
        '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', 
        '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F'
      ]
      return colors[index % colors.length]
    },
    
    getSectorTextX(index) {
      const angle = 360 / this.wheelItems.length
      const midAngle = index * angle + angle / 2  // 修正中点角度计算
      const textRadius = 60  // 调整文字距离中心的位置
      const rad = (midAngle - 90) * Math.PI / 180
      return 100 + textRadius * Math.cos(rad)
    },
    
    getSectorTextY(index) {
      const angle = 360 / this.wheelItems.length
      const midAngle = index * angle + angle / 2  // 修正中点角度计算
      const textRadius = 60  // 调整文字距离中心的位置
      const rad = (midAngle - 90) * Math.PI / 180
      return 100 + textRadius * Math.sin(rad)
    },
    
    getDisplayText(name) {
      // 处理过长的文字，超过6个字符时显示省略号
      if (name.length > 6) {
        return name.substring(0, 5) + '...'
      }
      return name
    },
    
    getTextSize() {
      // 根据奖品数量动态调整字体大小
      const itemCount = this.wheelItems.length
      if (itemCount <= 4) return 12
      if (itemCount <= 6) return 10
      if (itemCount <= 8) return 9
      return 8
    },
    
    getSectorTextTransform(index) {
      const x = this.getSectorTextX(index)
      const y = this.getSectorTextY(index)
      
      // 简化旋转逻辑：保持文字水平，不做复杂旋转
      return `rotate(0 ${x} ${y})`
    },
    
    spin() {
      if (this.isSpinning || this.disabled) return
      
      this.isSpinning = true
      
      // 根据概率选择结果
      const winner = this.selectWinner()
      const winnerIndex = this.wheelItems.findIndex(item => item === winner)
      
      // 计算目标角度 - 让箭头指向扇形中央
      const sectorAngle = 360 / this.wheelItems.length
      // 扇形的中心角度（从12点钟方向开始计算）
      const sectorCenterAngle = winnerIndex * sectorAngle + sectorAngle / 2
      // 转盘需要旋转的角度，让指定扇形的中心对准箭头（12点钟方向）
      const targetAngle = 360 - sectorCenterAngle
      
      // 增加随机旋转圈数
      const extraRotations = Math.floor(Math.random() * 5 + 5) * 360
      const finalAngle = this.rotation + extraRotations + targetAngle
      
      this.rotation = finalAngle
      
      // 动画结束后显示结果
      setTimeout(() => {
        this.isSpinning = false
        this.winResult = winner
        this.showResult = true
        
        // 向父组件发送转盘完成事件
        this.$emit('spin-complete', winner)
        
        // 这里可以向后端发送请求
        console.log('中奖结果：', winner)
      }, 3000)
    },
    
    selectWinner() {
      // 计算概率总和，提高算法的健壮性
      const totalProbability = this.wheelItems.reduce((sum, item) => sum + item.probability, 0)
      const random = Math.random() * totalProbability
      let accumulatedProbability = 0
      
      for (const item of this.wheelItems) {
        accumulatedProbability += item.probability
        if (random <= accumulatedProbability) {
          return item
        }
      }
      
      return this.wheelItems[0]
    },   
    
    closeResult() {
      this.showResult = false
      // 发出结果弹窗关闭事件
      this.$emit('result-closed', this.winResult)
    },
    
    openConfig() {
      this.tempWheelItems = JSON.parse(JSON.stringify(this.wheelItems))
      this.showConfig = true
    },
    
    cancelConfig() {
      this.showConfig = false
    },
    
    saveConfig() {
      if (this.totalProbability === 100) {
        this.wheelItems = JSON.parse(JSON.stringify(this.tempWheelItems))
        this.showConfig = false
      }
    },
    
    addItem() {
      this.tempWheelItems.push({ name: '新奖品', probability: 0 })
    },
    
    removeItem(index) {
      this.tempWheelItems.splice(index, 1)
    }
  }
}
</script>

<style scoped>
.lucky-wheel-container {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px;
}

.wheel-wrapper {
  position: relative;
  width: 300px;
  height: 300px;
}

.wheel {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  position: relative;
  transition: transform 3s cubic-bezier(0.23, 1, 0.32, 1);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  overflow: hidden;
  background: white;
}

.wheel-svg {
  width: 100%;
  height: 100%;
  border-radius: 50%;
}

.pointer {
  position: absolute;
  top: 5px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.3));
}

.arrow-pointer {
  position: relative;
  width: 24px;
  height: 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.arrow-body {
  width: 6px;
  height: 20px;
  background: linear-gradient(180deg, #FFD700 0%, #FFA500 100%);
  border-radius: 3px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.arrow-tip {
  width: 0;
  height: 0;
  border-left: 12px solid transparent;
  border-right: 12px solid transparent;
  border-top: 16px solid #FF6B35;
  filter: drop-shadow(0 2px 3px rgba(0, 0, 0, 0.2));
  margin-top: -2px;
}

.center-circle {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 80px;
  height: 80px;
  background: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  z-index: 5;
}

.spin-btn {
  width: 100% !important;
  height: 100% !important;
  border-radius: 50% !important;
  font-size: 12px !important;
  min-width: unset !important;
  min-height: unset !important;
}

.result-card {
  text-align: center;
  padding: 20px;
}

.config-btn {
  position: absolute;
  top: 10px;
  right: 10px;
}

/* 响应式设计 */
@media (max-width: 480px) {
  .wheel-wrapper {
    width: 250px;
    height: 250px;
  }
  
  .center-circle {
    width: 60px;
    height: 60px;
  }
  
  .spin-btn {
    width: 100% !important;
    height: 100% !important;
    font-size: 10px !important;
    min-width: unset !important;
    min-height: unset !important;
  }
  
  /* 移动端SVG文字大小调整 */
  .wheel-svg text {
    font-size: 6px;
  }
  
  .wheel-svg text tspan:last-child {
    font-size: 5px;
  }
}
</style>
