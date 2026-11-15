<template>
  <div class="home-page">
    <!-- ==================== 问候语 ==================== -->
    <GreetingBar :pending-count="todayCheckpointCount" :overdue-count="overdueCheckpointCount" />

    <!-- ==================== 实验提醒 ==================== -->
    <section class="home-section">
      <div class="home-section-head">
        <div>
          <h2>
            <span class="icon">🧫</span>细胞实验提醒
            <el-tag v-if="attention" size="small" type="danger" effect="dark">
              {{ attention }} 个待处理
            </el-tag>
            <el-tag v-else-if="upcomingCount" size="small" type="warning" effect="light">
              {{ upcomingCount }} 个即将到点
            </el-tag>
            <el-tag v-else size="small" type="success" effect="plain">暂无待办</el-tag>
          </h2>
          <p class="sub">
            到点提醒、勾选检查后自动排下一次 · 当前 {{ reminders.summary?.now || '—' }}
          </p>
        </div>
        <div class="row" style="gap: 8px">
          <el-button size="small" :loading="reminders.loading" @click="refreshReminders()">刷新</el-button>
          <el-button size="small" @click="$router.push('/experiments')">全部实验</el-button>
          <el-button size="small" type="primary" @click="openAddTodo">＋ 添加待办</el-button>
          <el-button size="small" type="primary" @click="$router.push({ path: '/experiments', query: { new: '1' } })">
            ＋ 新建实验
          </el-button>
        </div>
      </div>

      <div class="home-reminder-body">
        <div class="reminder-col">
          <div class="reminder-col-title danger">
            <el-icon><WarningFilled /></el-icon>逾期实验
            <span class="count">{{ overdue.length }}</span>
          </div>
          <button
            v-for="item in overdue.slice(0, 4)"
            :key="`o-${item.experiment_id}`"
            class="reminder-task"
            :title="item.experiment_notes || item.experiment_name"
            @click="goExperiment(item.experiment_id, item.first_due?.id)"
          >
            <span class="ri-dot danger" />
            <span class="rt-main">
              <span class="rt-name">{{ item.experiment_name }}</span>
              <span class="rt-meta">
                {{ item.cell_line_name ? `${item.cell_line_name} · ` : '' }}{{ item.due_label }} · {{ item.gap_text }}
              </span>
            </span>
            <span class="rt-time danger">{{ item.overdue_count }} 项</span>
          </button>
          <div v-if="!overdue.length" class="reminder-col-empty">没有逾期实验</div>
        </div>

        <div class="reminder-col">
          <div class="reminder-col-title warning">
            <el-icon><AlarmClock /></el-icon>今天 / 24 小时内
            <span class="count">{{ dueToday.length }}</span>
          </div>
          <button
            v-for="item in dueToday.slice(0, 4)"
            :key="`t-${item.experiment_id}`"
            class="reminder-task"
            :title="item.experiment_notes || item.experiment_name"
            @click="goExperiment(item.experiment_id, item.first_due?.id)"
          >
            <span class="ri-dot warning" />
            <span class="rt-main">
              <span class="rt-name">{{ item.experiment_name }}</span>
              <span class="rt-meta">
                {{ item.cell_line_name ? `${item.cell_line_name} · ` : '' }}{{ item.due_label }} · {{ item.gap_text }}
              </span>
            </span>
            <span class="rt-time warning">{{ item.today_count }} 项</span>
          </button>
          <div v-if="!dueToday.length" class="reminder-col-empty">今天没有到点的检查</div>
        </div>

        <div class="reminder-col">
          <div class="reminder-col-title">
            <el-icon><Calendar /></el-icon>即将到点
            <span class="count">{{ upcoming.length }}</span>
          </div>
          <button
            v-for="item in upcoming.slice(0, 4)"
            :key="`u-${item.experiment_id}`"
            class="reminder-task"
            :title="item.experiment_notes || item.experiment_name"
            @click="goExperiment(item.experiment_id, item.first_due?.id)"
          >
            <span class="ri-dot" />
            <span class="rt-main">
              <span class="rt-name">{{ item.experiment_name }}</span>
              <span class="rt-meta">
                {{ item.cell_line_name ? `${item.cell_line_name} · ` : '' }}{{ item.due_label }} · {{ item.gap_text }}
              </span>
            </span>
            <span class="rt-time info">{{ item.upcoming_count }} 项</span>
          </button>
          <div v-if="!upcoming.length" class="reminder-col-empty">
            {{ reminders.summary?.window_days || 3 }} 天内没有需要处理的检查
          </div>
        </div>

        <div
          class="reminder-col reminder-col-todo"
          :class="{ adding: addingTodo }"
          title="点空白处新建今日待办"
          @click.self="startQuickTodo"
        >
          <div class="reminder-col-title todo" @click.self="startQuickTodo">
            <el-icon><EditPen /></el-icon>{{ todoTitle }}
            <span class="count">{{ todoCount }}</span>
          </div>
          <div class="todo-list-scroll">
            <button
              v-for="todo in todoPreview"
              :key="`todo-${todo.id}`"
              class="reminder-task"
              :title="todo.notes || todo.title"
              @click="scrollToSchedule"
            >
              <span class="ri-dot todo" :class="{ overdue: todo.state === 'overdue' }" />
              <span class="rt-main">
                <span class="rt-name">{{ todo.title }}</span>
                <span class="rt-meta">{{ todoMeta(todo) }}</span>
              </span>
              <!-- 逾期才标出来；今天的待办不再重复显示「今天」 -->
              <span v-if="todo.state === 'overdue'" class="rt-time todo">逾期</span>
            </button>

            <div
              v-if="!todoPreview.length && !addingTodo"
              class="reminder-col-empty reminder-col-empty-clickable"
              @click="startQuickTodo"
            >
              今天没有待办 · 点这里添加
            </div>
          </div>

          <!-- 点空白处直接新建今日待办：回车保存，Esc 取消 -->
          <div v-if="addingTodo" class="todo-quickadd" @click.stop>
            <input
              ref="todoQuickInput"
              v-model="todoQuickText"
              class="todo-quick-input"
              placeholder="新建今日待办，回车保存"
              maxlength="200"
              @keydown.enter.prevent="saveQuickTodo"
              @keydown.esc.prevent="cancelQuickTodo"
              @blur="onQuickTodoBlur"
            />
          </div>

          <div v-else class="reminder-col-add" @click="startQuickTodo">
            ＋ 新建今日待办
          </div>
        </div>
      </div>
    </section>

    <!-- ==================== 日程安排 ==================== -->
    <section class="home-section">
      <div class="home-section-head">
        <div>
          <h2><span class="icon">🗓️</span>日程安排</h2>
          <p class="sub">
            实验检查与细胞传代都在这里 · 点方块直接勾选，悬停条目可推迟一天或删除
          </p>
        </div>
        <div class="row" style="gap: 8px">
          <el-button size="small" @click="$router.push('/experiments')">细胞实验</el-button>
          <el-button size="small" @click="$router.push('/cells')">在养细胞</el-button>
        </div>
      </div>
      <ScheduleBoard
        ref="scheduleRef"
        v-model="scheduleMode"
        @open-check="onCheckOpen"
        @open-passage="onPassageOpen"
        @more="onMonthMore"
        @changed="refreshAll"
      />
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { todoApi } from '../api'
import { refreshReminders, reminders } from '../reminders'
import { todayISO } from '../utils'
import GreetingBar from '../components/GreetingBar.vue'
import ScheduleBoard from '../components/ScheduleBoard.vue'

const router = useRouter()
const scheduleRef = ref(null)
// 待办预览（逾期 + 今天）
const todoPreview = ref([])
const todoCount = computed(() => {
  const stats = reminders.summary?.stats || {}
  return (stats.todo_overdue || 0) + (stats.todo_today || 0)
})
// 这一栏本来就只列「今天」和「逾期」，所以标题直接说明范围，不再逐条标「今天」
const todoOverdueCount = computed(() => reminders.summary?.stats?.todo_overdue || 0)
const todoTitle = computed(() => (todoOverdueCount.value > 0 ? '今日待办与逾期' : '今日待办'))

/** 待办副标题：今天的不写日期，逾期的写明是哪天，并保留剩余时间 */
function todoMeta(todo) {
  const parts = []
  if (todo.state === 'overdue') parts.push(todo.due_label || '已逾期')
  if (todo.gap_text) parts.push(todo.gap_text)
  return parts.join(' · ')
}
// 月视图 / 周视图，记在本地，下次打开保持上次的选择
const scheduleMode = ref(localStorage.getItem('ct.scheduleMode') === 'week' ? 'week' : 'month')
watch(scheduleMode, (value) => {
  try {
    localStorage.setItem('ct.scheduleMode', value)
  } catch {
    /* 隐私模式写不进去也不影响使用 */
  }
})

const overdue = computed(() => reminders.summary?.overdue || [])
const dueToday = computed(() => reminders.summary?.due_today || [])
const upcoming = computed(() => reminders.summary?.upcoming || [])
const attention = computed(() => overdue.value.length + dueToday.value.length)
const upcomingCount = computed(() => upcoming.value.length)
// 问候语用的计数：按「检查点」而不是「实验」来数
const todayCheckpointCount = computed(() => reminders.summary?.stats?.today_checkpoints || 0)
const overdueCheckpointCount = computed(() => reminders.summary?.stats?.overdue_checkpoints || 0)

function goExperiment(experimentId, checkpointId = null) {
  const query = { exp: experimentId }
  if (checkpointId) query.check = checkpointId
  router.push({ path: '/experiments', query })
}

// 月视图里的检查条目 → 打开对应实验并定位到该时间点
function onCheckOpen(item) {
  goExperiment(item.experiment_id, item.id)
}

// 传代待办 → 去在养细胞页（默认定位到该细胞株）
function onPassageOpen(day) {
  const first = day.passages?.[0]
  router.push({ path: '/cells', query: first ? { line: first.cell_line_id } : {} })
}

function onMonthMore() {
  router.push('/experiments')
}

// 顶部「添加待办」直接打开日程面板里的待办弹窗
function openAddTodo() {
  scheduleRef.value?.addTodo()
}

function scrollToSchedule() {
  document.querySelector('.home-section:last-of-type')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ---------------- 「今日待办」点空白处直接新建 ----------------
const addingTodo = ref(false)
const todoQuickText = ref('')
const todoQuickInput = ref(null)
const savingQuickTodo = ref(false)

function startQuickTodo() {
  if (addingTodo.value) return
  addingTodo.value = true
  todoQuickText.value = ''
  nextTick(() => {
    const el = Array.isArray(todoQuickInput.value) ? todoQuickInput.value[0] : todoQuickInput.value
    el?.focus()
  })
}

function cancelQuickTodo() {
  addingTodo.value = false
  todoQuickText.value = ''
}

async function saveQuickTodo() {
  const title = todoQuickText.value.trim()
  if (!title || savingQuickTodo.value) {
    cancelQuickTodo()
    return
  }
  savingQuickTodo.value = true
  try {
    await todoApi.create({ title, due_date: todayISO() })
    ElMessage.success('已新建今日待办')
    cancelQuickTodo()
    await refreshAll()
    scheduleRef.value?.reload?.()
  } catch {
    // 拦截器已统一提示错误信息
  } finally {
    savingQuickTodo.value = false
  }
}

function onQuickTodoBlur() {
  // 失焦时已有内容就保存，空内容则取消
  if (todoQuickText.value.trim()) saveQuickTodo()
  else cancelQuickTodo()
}

/** 取逾期 + 今天的待办，供提醒栏预览 */
async function loadTodoPreview() {
  try {
    const rows = await todoApi.list({ include_done: false })
    todoPreview.value = rows
      .filter((item) => item.state === 'overdue' || item.state === 'due')
      .sort((a, b) => {
        const rank = (item) => (item.state === 'overdue' ? 0 : 1)
        return rank(a) - rank(b) || a.due_date.localeCompare(b.due_date)
      })
  } catch {
    todoPreview.value = []
  }
}

async function refreshAll() {
  await Promise.all([refreshReminders(), loadTodoPreview()])
}

onMounted(() => {
  refreshAll()
})
</script>

<style scoped>
.home-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.home-section {
  background: var(--ct-surface);
  border: 1px solid var(--ct-border);
  border-radius: var(--ct-radius);
  box-shadow: var(--ct-shadow);
  overflow: hidden;
}

.home-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--ct-border);
  background: #fbfdfc;
  flex-wrap: wrap;
}

.home-section-head h2 {
  margin: 0;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.home-section-head .icon {
  font-size: 16px;
}

.home-section-head .sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ct-faint);
}

.home-reminder-body {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

@media (max-width: 900px) {
  .home-reminder-body {
    grid-template-columns: 1fr;
  }
}
</style>
