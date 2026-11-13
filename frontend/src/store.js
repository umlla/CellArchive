import { reactive } from 'vue'
import { authApi, metaApi, onUnauthorized } from './api'
import { registerSpeciesColors } from './charts'

export const store = reactive({
  ready: false,
  meta: null,
  auth: {
    enabled: false,
    authenticated: true,
    username: 'local',
    display_name: '本地用户',
  },
  lines: [],
  groups: [],
})

export async function refreshAuth() {
  try {
    const status = await authApi.status()
    store.auth = {
      enabled: !!status.enabled,
      authenticated: !!status.authenticated,
      username: status.username,
      display_name: status.display_name,
    }
  } catch {
    store.auth.authenticated = false
  }
  return store.auth
}

export async function loadMeta() {
  store.meta = await metaApi.meta()
  // 物种配色表随元信息一起加载，保证所有图表取到同一套颜色
  registerSpeciesColors(store.meta?.species_colors)
  return store.meta
}

export async function bootstrap() {
  await refreshAuth()
  if (store.auth.enabled && !store.auth.authenticated) {
    store.ready = true
    return
  }
  try {
    await loadMeta()
  } catch {
    /* 元信息加载失败不阻塞页面 */
  }
  store.ready = true
}

export function logout() {
  return authApi.logout().finally(async () => {
    await refreshAuth()
    store.meta = null
  })
}

onUnauthorized(() => {
  store.auth.authenticated = false
})
