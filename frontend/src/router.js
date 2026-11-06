import { createRouter, createWebHistory } from 'vue-router'
import { bootstrap, store } from './store'
import DashboardView from './views/DashboardView.vue'
import LinesView from './views/LinesView.vue'
import GroupsView from './views/GroupsView.vue'
import RecordsView from './views/RecordsView.vue'
import CompareView from './views/CompareView.vue'
import NewBatchView from './views/NewBatchView.vue'
import VialsView from './views/VialsView.vue'
import ToolsView from './views/ToolsView.vue'
import LoginView from './views/LoginView.vue'

const routes = [
  { path: '/', name: 'dashboard', component: DashboardView, meta: { title: '在养细胞', subtitle: '按细胞株或细胞组查看培养状态' } },
  { path: '/records', name: 'records', component: RecordsView, meta: { title: '传代记录', subtitle: '历史记录查看与编辑' } },
  { path: '/compare', name: 'compare', component: CompareView, meta: { title: '生长曲线对比', subtitle: '任选多个细胞株在同一张图里比较' } },
  { path: '/batches/new', name: 'batch-new', component: NewBatchView, meta: { title: '新建培养批次', subtitle: '复苏细胞并绑定来源冻存管' } },
  { path: '/vials', name: 'vials', component: VialsView, meta: { title: '冻存管管理', subtitle: '9×9 冻存盒视图、搜索编辑与 Excel 导入' } },
  { path: '/lines', name: 'lines', component: LinesView, meta: { title: '细胞株', subtitle: '添加、编辑与删除细胞株' } },
  { path: '/groups', name: 'groups', component: GroupsView, meta: { title: '细胞组', subtitle: '创建分组、调整成员与排序' } },
  { path: '/tools', name: 'tools', component: ToolsView, meta: { title: '数据与工具', subtitle: '备份恢复、数据体检与认证设置' } },
  { path: '/login', name: 'login', component: LoginView, meta: { title: '登录' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  if (!store.ready) {
    await bootstrap()
  }
  if (store.auth.enabled && !store.auth.authenticated) {
    return to.name === 'login' ? true : { name: 'login' }
  }
  if (to.name === 'login') {
    return { name: 'dashboard' }
  }
  return true
})

export default router
