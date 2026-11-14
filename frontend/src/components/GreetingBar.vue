<template>
  <div class="greeting">
    <div class="greeting-main">
      <span class="greeting-hello">{{ hello }}，{{ name }}</span>
      <span class="greeting-sub">{{ subtitle }}</span>
    </div>
    <div class="greeting-date">
      <span>{{ dateText }}</span>
      <span class="greeting-week">{{ weekdayText }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { store } from '../store'

const props = defineProps({
  // 今日待处理数量：>0 时把问候语换成提醒语气
  pendingCount: { type: Number, default: 0 },
  overdueCount: { type: Number, default: 0 },
})

const now = new Date()
const hour = now.getHours()

const name = computed(() => {
  const display = store.auth?.display_name
  const username = store.auth?.username
  if (store.auth?.enabled && display) return display
  return store.auth?.enabled && username ? username : '研究员'
})

const hello = computed(() => {
  if (hour < 5) return '夜深了'
  if (hour < 9) return '早上好'
  if (hour < 12) return '上午好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  if (hour < 23) return '晚上好'
  return '夜深了'
})

// 参考网易邮箱的问候语风格：一句话，轻量，按时间和当天任务切换
const subtitle = computed(() => {
  if (props.overdueCount > 0) {
    return `有 ${props.overdueCount} 个实验已逾期，记得先处理一下`
  }
  if (props.pendingCount > 0) {
    return `今天有 ${props.pendingCount} 个实验要到点检查，美好的一天从照顾细胞开始`
  }
  if (hour < 5) return '细胞也睡了，早点休息吧'
  if (hour < 9) return '美好的一天，从看看细胞开始'
  if (hour < 12) return '实验顺利，今天也要有好数据'
  if (hour < 14) return '记得吃饭，细胞和你都需要营养'
  if (hour < 18) return '进展顺利，继续保持'
  if (hour < 23) return '今天辛苦了，收个尾就休息吧'
  return '夜深了，别熬太晚'
})

const WEEKDAYS = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']
const dateText = computed(
  () => `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日`,
)
const weekdayText = computed(() => WEEKDAYS[now.getDay()])
</script>

<style scoped>
.greeting {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding: 2px 4px 0;
  flex-wrap: wrap;
}

.greeting-main {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.greeting-hello {
  font-size: 22px;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: var(--ct-text);
}

.greeting-sub {
  font-size: 13px;
  color: var(--ct-muted);
}

.greeting-date {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12.5px;
  color: var(--ct-faint);
  white-space: nowrap;
}

.greeting-week {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--ct-primary-soft);
  color: var(--ct-primary);
  font-size: 11.5px;
}

@media (max-width: 560px) {
  .greeting-hello {
    font-size: 18px;
  }
}
</style>
