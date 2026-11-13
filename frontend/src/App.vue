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
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { http } from './api'
import { logout, store } from './store'
import { downloadUrl } from './utils'

const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const viewKey = ref(0)

const menu = [
  { path: '/', title: '在养细胞', icon: 'Odometer' },
  { path: '/records', title: '历史记录', icon: 'DataLine' },
  { path: '/compare', title: '生长曲线对比', icon: 'TrendCharts' },
  { path: '/batches/new', title: '新建批次', icon: 'MagicStick' },
  { path: '/vials', title: '冻存管', icon: 'Box' },
  { path: '/lines', title: '细胞株', icon: 'Collection' },
  { path: '/groups', title: '细胞组', icon: 'Files' },
  { path: '/tools', title: '数据与工具', icon: 'Tools' },
]

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
