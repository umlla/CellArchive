<template>
  <div v-if="!store.ready" class="boot-screen">
    <div class="boot-mark">🧬</div>
    <p>正在连接数据库…</p>
  </div>

  <router-view v-else-if="loginMode" />

  <el-container v-else class="app-shell">
    <el-aside class="sidebar" :class="{ 'is-open': mobileOpen }" width="230px">
      <div class="brand">
        <div class="brand-text">
          <strong>细胞档案</strong>
          <small>CellArchive</small>
        </div>
      </div>

      <el-menu :default-active="activePath" router class="app-menu" @select="mobileOpen = false">
        <el-menu-item v-for="item in menu" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-foot">
        <div class="db-chip" :title="store.meta?.database">
          <el-icon><Coin /></el-icon>
          <div>
            <small>数据库</small>
            <span>{{ dbName }}</span>
          </div>
        </div>
        <div v-if="store.meta?.migration" class="migration-note">
          <el-icon class="ok"><CircleCheckFilled /></el-icon>
          <span>旧版数据已迁移 · 校验通过</span>
        </div>
        <button class="backup-button" @click="backupNow">
          <el-icon><Download /></el-icon>
          <span>备份数据库</span>
        </button>
        <button class="quit-button" @click="quitApp">
          <el-icon><SwitchButton /></el-icon>
          <span>退出程序</span>
        </button>
      </div>
    </el-aside>

    <div v-if="mobileOpen" class="sidebar-mask" @click="mobileOpen = false" />

    <el-container class="content-shell">
      <el-header class="topbar" height="68px">
        <div class="topbar-left">
          <el-button class="mobile-toggle" text circle @click="mobileOpen = !mobileOpen">
            <el-icon size="20"><Menu /></el-icon>
          </el-button>
          <div>
            <h1>{{ route.meta.title || '细胞培养追踪' }}</h1>
            <p>{{ route.meta.subtitle }}</p>
          </div>
        </div>
        <div class="topbar-right">
          <el-popover
            v-model:visible="bellOpen"
            placement="bottom-end"
            :width="380"
            trigger="click"
            popper-class="reminder-popover"
            @show="onBellOpen"
          >
            <template #reference>
              <button class="bell-button" :class="{ alert: attention > 0 }" :title="bellTitle">
                <el-icon size="18"><Bell /></el-icon>
                <span v-if="attention > 0" class="bell-badge">{{ attention > 99 ? '99+' : attention }}</span>
              </button>
            </template>

            <div class="reminder-panel">
              <div class="reminder-head">
                <div>
                  <strong>细胞实验提醒</strong>
                  <span class="small faint"> · {{ reminders.summary?.now || '—' }}</span>
                </div>
                <el-button link type="primary" size="small" @click="goExperiments()">全部实验 →</el-button>
              </div>

              <div v-if="!hasReminderItems" class="reminder-empty">
                <span class="icon">✅</span>
                暂时没有到点的检查
              </div>

              <template v-else>
                <div v-if="overdueItems.length" class="reminder-group">
                  <div class="reminder-group-title danger">逾期（{{ overdueItems.length }}）</div>
                  <button
                    v-for="item in overdueItems"
                    :key="`o-${item.experiment_id}`"
                    class="reminder-item"
                    @click="goExperiment(item.experiment_id, item.first_due?.id)"
                  >
                    <span class="ri-dot danger" />
                    <span class="ri-main">
                      <span class="ri-name">{{ item.experiment_name }}</span>
                      <span class="ri-meta">{{ item.due_label }} · {{ item.gap_text }}</span>
                    </span>
                    <el-icon class="ri-arrow"><ArrowRight /></el-icon>
                  </button>
                </div>

                <div v-if="todayItems.length" class="reminder-group">
                  <div class="reminder-group-title warning">今天 / 24 小时内（{{ todayItems.length }}）</div>
                  <button
                    v-for="item in todayItems"
                    :key="`t-${item.experiment_id}`"
                    class="reminder-item"
                    @click="goExperiment(item.experiment_id, item.first_due?.id)"
                  >
                    <span class="ri-dot warning" />
                    <span class="ri-main">
                      <span class="ri-name">{{ item.experiment_name }}</span>
                      <span class="ri-meta">{{ item.due_label }} · {{ item.gap_text }}</span>
                    </span>
                    <el-icon class="ri-arrow"><ArrowRight /></el-icon>
                  </button>
                </div>

                <div v-if="upcomingItems.length" class="reminder-group">
                  <div class="reminder-group-title">即将到点（{{ upcomingItems.length }}）</div>
                  <button
                    v-for="item in upcomingItems.slice(0, 4)"
                    :key="`u-${item.experiment_id}`"
                    class="reminder-item"
                    @click="goExperiment(item.experiment_id, item.first_due?.id)"
                  >
                    <span class="ri-dot" />
                    <span class="ri-main">
                      <span class="ri-name">{{ item.experiment_name }}</span>
                      <span class="ri-meta">{{ item.due_label }} · {{ item.gap_text }}</span>
                    </span>
                    <el-icon class="ri-arrow"><ArrowRight /></el-icon>
                  </button>
                </div>
              </template>

              <div class="reminder-foot">
                <el-button size="small" @click="refreshRemindersNow" :loading="reminders.loading">刷新</el-button>
                <el-button size="small" type="primary" @click="goExperiments()">去处理</el-button>
              </div>
            </div>
          </el-popover>

          <div class="quick-stats">
            <span class="quick-stat"><b>{{ store.meta?.counts?.cell_lines ?? '—' }}</b> 细胞株</span>
            <span class="quick-stat"><b>{{ store.meta?.counts?.culture_batches ?? '—' }}</b> 批次</span>
            <span class="quick-stat"><b>{{ store.meta?.counts?.frozen_vials ?? '—' }}</b> 冻存管</span>
          </div>
          <el-tooltip content="重新加载页面数据" placement="bottom">
            <el-button circle text @click="refreshView">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </el-tooltip>
          <el-dropdown v-if="store.auth.enabled" trigger="click" @command="handleCommand">
            <span class="user-chip">
              <el-icon><UserFilled /></el-icon>
              {{ store.auth.display_name || store.auth.username }}
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main-area">
        <router-view v-slot="{ Component }">
          <component :is="Component" :key="viewKey" />
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from './api'
import { logout, store } from './store'
import {
  attentionCount,
  refreshReminders,
  reminders,
  startReminderPolling,
  stopReminderPolling,
} from './reminders'
import { downloadUrl } from './utils'

const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const viewKey = ref(0)
const bellOpen = ref(false)

const menu = [
  { path: '/', title: '首页', icon: 'HomeFilled' },
  { path: '/experiments', title: '细胞实验', icon: 'AlarmClock' },
  { path: '/topics', title: '课题讨论', icon: 'ChatLineSquare' },
  { path: '/cells', title: '在养细胞', icon: 'Odometer' },
  { path: '/records', title: '历史记录', icon: 'DataLine' },
  { path: '/compare', title: '生长曲线对比', icon: 'TrendCharts' },
  { path: '/batches/new', title: '新建批次', icon: 'MagicStick' },
  { path: '/vials', title: '冻存管', icon: 'Box' },
  { path: '/lines', title: '细胞株', icon: 'Collection' },
  { path: '/groups', title: '细胞组', icon: 'Files' },
  { path: '/tools', title: '数据与工具', icon: 'Tools' },
]

const attention = computed(() => attentionCount())
const overdueItems = computed(() => reminders.summary?.overdue || [])
const todayItems = computed(() => reminders.summary?.due_today || [])
const upcomingItems = computed(() => reminders.summary?.upcoming || [])
const hasReminderItems = computed(
  () => overdueItems.value.length + todayItems.value.length + upcomingItems.value.length > 0,
)
const bellTitle = computed(() => {
  const stats = reminders.summary?.stats
  if (!stats) return '细胞实验提醒'
  return `细胞实验：逾期 ${stats.overdue_checkpoints} 个 · 今天到点 ${stats.today_checkpoints} 个`
})

let stopPolling = null

function goExperiment(id, checkpointId = null) {
  bellOpen.value = false
  const query = { exp: id }
  if (checkpointId) query.check = checkpointId
  router.push({ path: '/experiments', query })
}

function goExperiments() {
  bellOpen.value = false
  router.push('/experiments')
}

async function refreshRemindersNow() {
  await refreshReminders({ silent: false })
}

async function onBellOpen() {
  await refreshReminders()
}

onMounted(async () => {  // 顶栏提醒铃 / 首页卡片 / 实验页共用同一份汇总，按配置的间隔轮询
  let intervalMinutes = 15
  let browserNotify = false
  try {
    const meta = await http.get('/meta')
    const settings = meta?.reminders || {}
    if (settings.enabled === false) return
    intervalMinutes = Number(settings.interval_minutes) || 15
    browserNotify = settings.browser_notify !== false
  } catch {
    /* 元信息拿不到就用默认值继续轮询 */
  }
  stopPolling = startReminderPolling({ intervalMinutes, browserNotify })
})

onUnmounted(() => {
  stopPolling?.()
  stopReminderPolling()
})

const activePath = computed(() => {
  if (route.path.startsWith('/batches')) return '/batches/new'
  if (route.path.startsWith('/records')) return '/records'
  return route.path
})

const loginMode = computed(
  () => route.name === 'login' || (store.auth.enabled && !store.auth.authenticated),
)

const dbName = computed(() => {
  const path = store.meta?.database || ''
  return path.split(/[\\/]/).pop() || 'cell_data.db'
})

function refreshView() {
  viewKey.value += 1
}

async function handleCommand(command) {
  if (command === 'logout') {
    await logout()
    router.push({ name: 'login' })
  }
}

function backupNow() {
  downloadUrl('/api/maintenance/backup')
  ElMessage.success('正在生成并下载数据库备份')
}

async function quitApp() {
  try {
    await ElMessageBox.confirm(
      '退出后需要重新启动「细胞档案」才能继续使用。',
      '退出 细胞档案',
      { type: 'warning', confirmButtonText: '退出', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await http.post('/shutdown', null, {
      headers: { 'X-CellTracker-Shutdown': '1' },
      silent: true,
    })
  } catch {
    // 服务可能先关闭连接再返回响应，忽略即可。
  }
  showShutdownScreen()
}

function showShutdownScreen() {
  const overlay = document.createElement('div')
  overlay.className = 'shutdown-overlay'
  overlay.innerHTML = `
    <div class="shutdown-card">
      <div class="shutdown-mark">🧬</div>
      <h2>细胞档案 已退出</h2>
      <p>可以关闭此页面。下次使用请重新打开「细胞档案」。</p>
    </div>`
  document.body.appendChild(overlay)
}
</script>
