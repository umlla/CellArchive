<template>
  <div v-if="!store.ready" class="boot-screen">
    <div class="boot-mark">🧬</div>
    <p>正在连接数据库…</p>
  </div>

  <router-view v-else-if="loginMode" />

  <el-container v-else class="app-shell">
    <el-aside class="sidebar" :class="{ 'is-open': mobileOpen }" width="230px">
      <div class="brand">
        <span class="brand-mark">🧬</span>
        <div class="brand-text">
          <strong>CellTracker</strong>
          <small>细胞培养追踪 v{{ store.meta?.app_version || '4' }}</small>
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
import { logout, store } from './store'

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
</script>
