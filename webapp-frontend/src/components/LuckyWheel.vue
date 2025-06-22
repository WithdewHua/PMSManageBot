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
            <!-- 从圆心向外发散的文字 -->
            <text 
              :x="getSectorTextX(index)"
              :y="getSectorTextY(index)"
              fill="white"
              :font-size="getTextSize()"
              font-weight="bold"
              text-anchor="middle"
              dominant-baseline="central"
              :transform="getSectorTextTransform(index)"
              style="text-shadow: 2px 2px 4px rgba(0,0,0,0.8);"
            >
              {{ item.name }}
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
          
          <!-- 显示积分变化 -->
          <div v-if="winResult?.credits_change !== undefined" class="mt-4">
            <v-divider class="my-3"></v-divider>
            <div class="credits-info">
              <p class="text-body-1 mb-1">
                积分变化：
                <span :class="winResult.credits_change >= 0 ? 'text-success' : 'text-error'" class="font-weight-bold">
                  {{ winResult.credits_change >= 0 ? '+' : '' }}{{ winResult.credits_change }}
                </span>
              </p>
              <p class="text-body-2 text-medium-emphasis">
                当前积分：{{ winResult.current_credits?.toFixed(2) }}
              </p>
            </div>
          </div>
        </v-card-text>
        <v-card-actions class="justify-center">
          <v-btn color="primary" @click="closeResult">确定</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>


  </div>
</template>

<script>
import { getLuckyWheelConfig, spinLuckyWheel } from '@/services/wheelService'

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
      winResult: null,
      wheelItems: [],
      loading: true,
      error: null
    }
  },
  mounted() {
    // 加载转盘配置
    this.loadWheelConfig()
  },
  computed: {
    // 这里可以根据需要添加其他计算属性
  },
  methods: {
    // 加载转盘配置
    async loadWheelConfig() {
      try {
        this.loading = true
        this.error = null
        const response = await getLuckyWheelConfig()
        this.wheelItems = response.data.items
        this.loading = false
        
        // 配置加载完成后进行测试
        if (this.wheelItems.length > 0) {
          this.$nextTick(() => {
            this.testSectorCalculations()
          })
        }
      } catch (error) {
        console.error('加载转盘配置失败:', error)
        this.error = '加载转盘配置失败'
        this.loading = false
        // 如果加载失败，使用默认配置
        this.wheelItems = []
      }
    },
    
    getSectorPath(index) {
      const angle = 360 / this.wheelItems.length
      const startAngle = index * angle
      const endAngle = (index + 1) * angle
      
      // 转换为弧度，从12点钟方向开始（-90度）
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
    
    // 计算文字的X坐标位置
    getSectorTextX(index) {
      const angle = 360 / this.wheelItems.length
      const midAngle = index * angle + angle / 2  // 扇形中心角度
      const textRadius = 60  // 文字距离中心的位置
      // 从12点钟方向开始计算（-90度偏移）
      const rad = (midAngle - 90) * Math.PI / 180
      return 100 + textRadius * Math.cos(rad)
    },
    
    // 计算文字的Y坐标位置
    getSectorTextY(index) {
      const angle = 360 / this.wheelItems.length
      const midAngle = index * angle + angle / 2  // 扇形中心角度
      const textRadius = 60  // 文字距离中心的位置
      // 从12点钟方向开始计算（-90度偏移）
      const rad = (midAngle - 90) * Math.PI / 180
      return 100 + textRadius * Math.sin(rad)
    },
    
    // 计算文字的旋转变换，让文字沿着从圆心向外的方向
    getSectorTextTransform(index) {
      const angle = 360 / this.wheelItems.length
      const midAngle = index * angle + angle / 2  // 扇形中心角度
      const textX = this.getSectorTextX(index)
      const textY = this.getSectorTextY(index)
      
      // 计算文字的旋转角度
      // 当扇形在右半边时，文字正常显示
      // 当扇形在左半边时，文字需要旋转180度避免倒置
      let rotationAngle = midAngle - 90  // 基础旋转角度
      
      // 如果角度在左半边（90度到270度之间），需要额外旋转180度
      if (midAngle > 90 && midAngle < 270) {
        rotationAngle += 180
      }
      
      return `rotate(${rotationAngle} ${textX} ${textY})`
    },
    
    getTextSize() {
      // 根据奖品数量动态调整字体大小
      const itemCount = this.wheelItems.length
      
      // 基础字体大小
      let baseSize = 12
      
      // 根据扇形数量调整大小
      if (itemCount <= 4) baseSize = 16
      else if (itemCount <= 6) baseSize = 14
      else if (itemCount <= 8) baseSize = 12
      else if (itemCount <= 10) baseSize = 10
      else baseSize = 9
      
      // 如果有文字，根据最长文字长度进一步调整
      if (this.wheelItems.length > 0) {
        const maxTextLength = Math.max(...this.wheelItems.map(item => item.name.length))
        if (maxTextLength > 8) baseSize = Math.max(baseSize - 2, 7)
        else if (maxTextLength > 6) baseSize = Math.max(baseSize - 1, 8)
      }
      
      return baseSize
    },
    
    spin() {
      if (this.isSpinning || this.disabled) return
      
      this.isSpinning = true
      
      // 调用后端API进行转盘
      this.callSpinAPI()
    },
    
    async callSpinAPI() {
      try {
        const response = await spinLuckyWheel()
        const result = response.data
        
        // 使用后端返回的结果
        const winner = result.item
        const winnerIndex = this.wheelItems.findIndex(item => item.name === winner.name)
        
        if (winnerIndex === -1) {
          console.error('未找到中奖项目:', winner.name)
          this.isSpinning = false
          return
        }
        
        // 计算目标角度
        const sectorAngle = 360 / this.wheelItems.length
        
        // 计算中奖扇形的中心角度（从12点钟方向顺时针开始）
        const sectorCenterAngle = winnerIndex * sectorAngle + sectorAngle / 2
        
        // 计算需要旋转的角度，让中奖扇形的中心对准指针
        // 指针固定在12点钟方向（0度位置）
        // 要让扇形中心移动到指针位置，转盘需要逆时针旋转扇形当前的角度
        // 但是CSS transform: rotate() 是顺时针的，所以我们需要用负值，或者用360度减去角度
        let targetAngle = 360 - sectorCenterAngle
        
        // 标准化角度 - 确保角度在0-360范围内
        targetAngle = targetAngle % 360
        if (targetAngle < 0) targetAngle += 360
        
        // 增加随机旋转圈数（至少5圈，最多10圈）
        const extraRotations = Math.floor(Math.random() * 5 + 5) * 360
        
        // 重要：计算最终角度时，需要确保我们到达正确的目标位置
        // 不是简单地在当前角度基础上加目标角度，而是要到达一个绝对的目标位置
        const currentNormalized = this.rotation % 360
        let rotationNeeded = targetAngle - currentNormalized
        
        // 如果需要的旋转角度是负数，加上360度让它变成正向旋转
        if (rotationNeeded < 0) {
          rotationNeeded += 360
        }
        
        const finalAngle = this.rotation + extraRotations + rotationNeeded
        
        console.log('转盘计算信息：', {
          winnerIndex,
          winnerName: winner.name,
          sectorAngle,
          sectorCenterAngle,
          targetAngle,
          currentRotation: this.rotation,
          currentNormalized: this.rotation % 360,
          rotationNeeded,
          extraRotations,
          finalAngle,
          finalAngleNormalized: finalAngle % 360
        })
        
        this.rotation = finalAngle
        
        // 动画结束后显示结果
        setTimeout(() => {
          this.isSpinning = false
          
          // 验证指针是否指向正确位置
          const pointing = this.getCurrentPointingSector()
          const isAccurate = this.validatePointerAccuracy(winnerIndex)
          
          console.log('=== 转盘停止验证 ===')
          console.log('期望中奖项目:', winner.name, '(索引:', winnerIndex, ')')
          console.log('指针实际指向:', pointing)
          console.log('最终角度验证:', {
            finalRotation: this.rotation,
            normalizedAngle: this.rotation % 360,
            expectedSectorCenter: winnerIndex * sectorAngle + sectorAngle / 2
          })
          
          if (isAccurate) {
            console.log('✅ 指针位置精确正确！')
          } else {
            console.warn('❌ 指针位置不够精确！')
            if (pointing && pointing.item) {
              console.warn('期望:', winner.name, '实际指向:', pointing.item.name)
              console.warn('期望索引:', winnerIndex, '实际索引:', pointing.sectorIndex)
              console.warn('调试信息:', {
                expectedCenterAngle: sectorCenterAngle,
                expectedFinalAngle: targetAngle,
                actualRotation: this.rotation % 360,
                actualPointerAngle: pointing.pointerAngle,
                sectorAngle: pointing.sectorAngle
              })
            }
          }
          
          this.winResult = {
            ...winner,
            credits_change: result.credits_change,
            current_credits: result.current_credits
          }
          this.showResult = true
          
          // 向父组件发送转盘完成事件
          this.$emit('spin-complete', this.winResult)
          
          console.log('转盘结果：', this.winResult)
        }, 3000)
        
      } catch (error) {
        console.error('转盘失败:', error)
        this.isSpinning = false
        
        // 显示错误信息
        const errorMessage = error.response?.data?.detail || '转盘失败，请稍后重试'
        // 这里可以显示一个错误提示
        alert(errorMessage)
      }
    },
    
    closeResult() {
      this.showResult = false
      // 发出结果弹窗关闭事件
      this.$emit('result-closed', this.winResult)
    },
    
    // 供外部调用，重新加载转盘配置
    reloadConfig() {
      this.loadWheelConfig()
    },
    
    // 调试方法：获取当前指针指向的扇形
    getCurrentPointingSector() {
      if (this.wheelItems.length === 0) return null
      
      // 获取当前转盘的角度（去除多圈旋转）
      let currentAngle = this.rotation % 360
      if (currentAngle < 0) currentAngle += 360
      
      // 指针在12点钟方向（0度），计算指针相对于转盘上扇形的角度
      // 由于转盘顺时针旋转，指针相对于转盘的角度应该是逆向的
      let pointerAngle = (360 - currentAngle) % 360
      
      const sectorAngle = 360 / this.wheelItems.length
      
      // 计算指针指向哪个扇形
      // 扇形从12点钟方向开始，按索引顺时针排列
      let sectorIndex = Math.floor(pointerAngle / sectorAngle)
      
      // 处理边界情况
      if (sectorIndex >= this.wheelItems.length) {
        sectorIndex = 0
      }
      
      // 确保索引在有效范围内
      sectorIndex = Math.max(0, Math.min(sectorIndex, this.wheelItems.length - 1))
      
      return {
        sectorIndex,
        item: this.wheelItems[sectorIndex],
        currentAngle,
        pointerAngle,
        sectorAngle,
        calculatedSectorStart: sectorIndex * sectorAngle,
        calculatedSectorEnd: (sectorIndex + 1) * sectorAngle
      }
    },
    
    // 测试方法：验证所有扇形的角度计算
    testSectorCalculations() {
      if (this.wheelItems.length === 0) return
      
      console.log('=== 扇形角度计算测试 ===')
      const sectorAngle = 360 / this.wheelItems.length
      
      this.wheelItems.forEach((item, index) => {
        const startAngle = index * sectorAngle
        const endAngle = (index + 1) * sectorAngle
        const centerAngle = startAngle + sectorAngle / 2
        
        console.log(`扇形 ${index} (${item.name}):`, {
          startAngle: startAngle.toFixed(1),
          centerAngle: centerAngle.toFixed(1),
          endAngle: endAngle.toFixed(1)
        })
      })
      
      // 测试每个扇形中心对准指针时的旋转角度
      console.log('=== 旋转角度计算测试 ===')
      this.wheelItems.forEach((item, index) => {
        const sectorCenterAngle = index * sectorAngle + sectorAngle / 2
        const targetAngle = (360 - sectorCenterAngle) % 360
        console.log(`让扇形 ${index} (${item.name}) 对准指针需要旋转: ${targetAngle.toFixed(1)}度`)
      })
      
      // 简单测试角度计算
      console.log('=== 角度计算验证 ===')
      console.log('当前转盘角度:', this.rotation % 360)
      const testIndex = 3 // 测试索引3
      const testSectorCenter = testIndex * sectorAngle + sectorAngle / 2
      const testTargetAngle = 360 - testSectorCenter
      console.log(`测试索引${testIndex}:`, {
        sectorCenter: testSectorCenter,
        targetAngle: testTargetAngle,
        normalizedTarget: testTargetAngle % 360
      })
    },
    
    // 添加精确的角度验证方法
    validatePointerAccuracy(expectedIndex) {
      const pointing = this.getCurrentPointingSector()
      if (!pointing) return false
      
      const sectorAngle = 360 / this.wheelItems.length
      const expectedCenterAngle = expectedIndex * sectorAngle + sectorAngle / 2
      const expectedFinalAngle = 360 - expectedCenterAngle
      const actualAngle = this.rotation % 360
      
      // 计算角度差异（考虑360度边界）
      let angleDiff = Math.abs(actualAngle - expectedFinalAngle)
      if (angleDiff > 180) {
        angleDiff = 360 - angleDiff
      }
      
      // 允许的误差范围（扇形角度的20%，稍微放宽一些）
      const tolerance = sectorAngle * 0.2
      
      console.log('精确验证:', {
        expectedIndex,
        actualIndex: pointing.sectorIndex,
        expectedCenterAngle: expectedCenterAngle.toFixed(2),
        expectedFinalAngle: expectedFinalAngle.toFixed(2),
        actualAngle: actualAngle.toFixed(2),
        angleDiff: angleDiff.toFixed(2),
        tolerance: tolerance.toFixed(2),
        isAccurate: angleDiff <= tolerance,
        indexMatch: pointing.sectorIndex === expectedIndex
      })
      
      // 使用扇形索引匹配作为主要判断标准
      return pointing.sectorIndex === expectedIndex
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

/* 文字样式优化 */
.wheel-svg text {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-weight: bold;
  text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
  user-select: none;
  pointer-events: none;
}

.pointer {
  position: absolute;
  top: 0px;  /* 精确对齐到转盘边缘 */
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
  height: 18px;
  background: linear-gradient(180deg, #FFD700 0%, #FFA500 100%);
  border-radius: 3px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.arrow-tip {
  width: 0;
  height: 0;
  border-left: 12px solid transparent;
  border-right: 12px solid transparent;
  border-top: 22px solid #FF6B35;
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
  
  /* 移动端文字大小调整 */
  .wheel-svg text {
    font-size: 6px !important;
  }
}
</style>
