<template>
  <div class="week-cal" v-loading="loading">
    <div class="week-head">
      <div class="week-title">
        <el-icon><Calendar /></el-icon>
        <strong>{{ data?.label || '本周' }}</strong>
        <el-tag v-if="data?.total_pending" size="small" type="warning" effect="light">
          本周待办 {{ data.total_pending }}
        </el-tag>
        <el-tag v-else size="small" type="success" effect="plain">本周无待办</el-tag>
        <el-tag v-if="totalPassages" size="small" effect="plain" type="info">
          传代 {{ totalPassages }}
        </el-tag>
      </div>
      <div class="row" style="gap: 6px">
        <el-button size="small" text circle title="上一周" @click="shift(-1)">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <el-button size="small" @click="goToday">本周</el-button>
        <el-button size="small" text circle title="下一周" @click="shift(1)">
          <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <div class="week-scroll">
      <div class="week-grid" :class="{ compact }">
        <div
          v-for="day in data?.days || []"
          :key="day.date"
          class="week-day"
          :class="{ today: day.is_today, past: day.is_past && !day.is_today, adding: addingDate === day.date }"
        >
          <div class="day-head" @click.self="startQuickAdd(day)">
            <span class="day-week">{{ day.weekday }}</span>
            <span class="day-num">{{ day.date.slice(5) }}</span>
            <span v-if="day.overdue_count" class="day-badge danger">{{ day.overdue_count }}</span>
            <span v-else-if="day.pending_count" class="day-badge">{{ day.pending_count }}</span>
          </div>

        <div class="day-items" @click.self="startQuickAdd(day)">
          <!-- 检查待办（压缩模式下全部渲染，靠格子内滚动查看） -->
          <div
            v-for="item in day.items"
            :key="`c-${item.id}`"
            class="day-task"
            :class="[`state-${item.done ? 'done' : item.state}`]"
          >
            <span
              class="task-box"
              :class="{ checked: item.done, busy: ticking.has(item.id) }"
              role="checkbox"
              :aria-checked="item.done ? 'true' : 'false'"
              @click.stop="toggleCheck(item)"
            >
              <el-icon v-if="item.done"><Check /></el-icon>
            </span>
            <span class="task-main" @click="$emit('open-check', item)">
              <span class="task-title">
                <em class="task-time">{{ item.due_clock }}</em>
                {{ item.experiment_name }}
              </span>
              <span v-if="item.cell_line_names?.length" class="task-sub">
                {{ item.cell_line_names.join('、') }}
              </span>
            </span>
            <span v-if="!item.done" class="task-actions">
              <button class="task-act" title="推迟一天" @click.stop="postpone(item)">
                <el-icon><DArrowRight /></el-icon>
              </button>
              <button class="task-act danger" title="删除这个时间点" @click.stop="removeCheck(item)">
                <el-icon><Close /></el-icon>
              </button>
            </span>
          </div>

          <!-- 用户自建待办：专属紫色，排在实验检查之后 -->
          <div
            v-for="todo in (day.todos || [])"
            :key="`t-${todo.id}`"
            class="day-task day-todo"
            :class="{ done: todo.done }"
            :title="todoTooltip(todo)"
          >
            <span
              class="task-box todo"
              :class="{ checked: todo.done, busy: ticking.has(`t${todo.id}`) }"
              role="checkbox"
              :aria-checked="todo.done ? 'true' : 'false'"
              @click.stop="toggleTodo(todo)"
            >
              <el-icon v-if="todo.done"><Check /></el-icon>
            </span>
            <span class="task-main" @click="$emit('open-todo', todo)">
              <span class="task-title">
                <em v-if="todo.due_clock" class="task-time">{{ todo.due_clock }}</em>
                {{ todo.title }}
              </span>
              <span v-if="todo.notes" class="task-sub">{{ todo.notes }}</span>
            </span>
            <span v-if="!todo.done" class="task-actions">
              <button class="task-act" title="推迟一天" @click.stop="postponeTodo(todo)">
                <el-icon><DArrowRight /></el-icon>
              </button>
              <button class="task-act danger" title="删除待办" @click.stop="removeTodo(todo)">
                <el-icon><Close /></el-icon>
              </button>
            </span>
          </div>

          <!-- 传代待办：只显示简短字样，悬停看具体批次 -->
          <el-tooltip
            v-if="day.passages?.length"
            placement="top"
            :show-after="80"
            popper-class="passage-tooltip"
          >
            <template #content>
              <div class="pt-title">需要传代（{{ day.passages.length }}）</div>
              <div v-for="item in day.passages" :key="item.batch_id" class="pt-line">
                <b>{{ item.cell_line }}</b>
                <span>· {{ item.batch_name }}</span>
                <em v-if="item.passage">P{{ item.passage }}</em>
              </div>
            </template>
            <button class="day-passage" @click="$emit('open-passage', day)">
              <el-icon><Refresh /></el-icon>
              传代{{ day.passages.length > 1 ? ` ${day.passages.length}` : '' }}
            </button>
          </el-tooltip>

          <div
            v-if="!day.items.length && !day.todos?.length && !day.passages?.length"
            class="day-empty"
          >
            —
          </div>

          <!-- 点空白处直接建待办 -->
          <div v-if="addingDate === day.date" class="day-quickadd" @click.stop>
            <input
              ref="quickInput"
              v-model="quickText"
              class="quick-input"
              placeholder="输入待办，回车保存"
              maxlength="200"
              @keydown.enter.prevent="saveQuickAdd(day)"
              @keydown.esc.prevent="cancelQuickAdd"
              @blur="onQuickBlur(day)"
            />
          </div>
        </div>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { experimentApi, todoApi } from '../api'
import { refreshReminders } from '../reminders'
import { toLocalMinute } from '../utils'

defineProps({
  // 压缩成单行高度：内容超出时在格子里滚动，不截断
  compact: { type: Boolean, default: false },
})
const emit = defineEmits(['open-check', 'open-passage', 'open-todo', 'more', 'changed'])

const loading = ref(false)
const data = ref(null)
const ticking = reactive(new Set())

const totalPassages = computed(() =>
  (data.value?.days || []).reduce((total, day) => total + (day.passages?.length || 0), 0),
)

function todoTooltip(todo) {
  const parts = [todo.title]
  if (todo.due_label) parts.push(todo.due_label)
  if (todo.state !== 'done' && todo.gap_text) parts.push(todo.gap_text)
  if (todo.notes) parts.push(todo.notes)
  if (todo.done) parts.push('（已完成）')
  return parts.join(' · ')
}

// ---------------- 点格子空白处直接建待办 ----------------
const addingDate = ref('')
const quickText = ref('')
const quickInput = ref(null)
const savingQuick = ref(false)

function startQuickAdd(day) {
  addingDate.value = day.date
  quickText.value = ''
  nextTick(() => {
    const el = Array.isArray(quickInput.value) ? quickInput.value[0] : quickInput.value
    el?.focus()
  })
}

function cancelQuickAdd() {
  addingDate.value = ''
  quickText.value = ''
}

async function saveQuickAdd(day) {
  const title = quickText.value.trim()
  if (!title || savingQuick.value) {
    cancelQuickAdd()
    return
  }
  savingQuick.value = true
  try {
    await todoApi.create({ title, due_date: day.date })
    ElMessage.success(`已添加到 ${day.date}`)
    cancelQuickAdd()
    await afterChange()
  } finally {
    savingQuick.value = false
  }
}

function onQuickBlur(day) {
  if (quickText.value.trim()) saveQuickAdd(day)
  else cancelQuickAdd()
}

async function toggleTodo(todo) {
  const key = `t${todo.id}`
  if (ticking.has(key)) return
  ticking.add(key)
  try {
    await todoApi.complete(todo.id, !todo.done)
    ElMessage.success(todo.done ? '已撤销完成' : '待办已完成')
    await afterChange()
  } finally {
    ticking.delete(key)
  }
}

async function postponeTodo(todo) {
  const key = `t${todo.id}`
  if (ticking.has(key)) return
  ticking.add(key)
  try {
    const result = await todoApi.postpone(todo.id, 1)
    ElMessage.success(`已推迟到 ${result.due_date}`)
    await afterChange()
  } finally {
    ticking.delete(key)
  }
}

async function removeTodo(todo) {
  try {
    await ElMessageBox.confirm(`删除待办「${todo.title}」？`, '删除待办', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await todoApi.remove(todo.id)
  ElMessage.success('待办已删除')
  await afterChange()
}

async function load(start = null) {
  loading.value = true
  try {
    data.value = await experimentApi.week(start)
  } finally {
    loading.value = false
  }
}

async function afterChange() {
  await load(data.value?.start || null)
  refreshReminders()
  emit('changed')
}

async function toggleCheck(item) {
  if (ticking.has(item.id)) return
  if (item.done) {
    try {
      await ElMessageBox.confirm(
        `撤销「${item.experiment_name}」${item.due_label} 的检查？撤销后它会重新变成待办。`,
        '撤销勾选',
        { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
    ticking.add(item.id)
    try {
      await experimentApi.reopenCheckpoint(item.experiment_id, item.id)
      ElMessage.success('已撤销勾选')
      await afterChange()
    } finally {
      ticking.delete(item.id)
    }
    return
  }
  ticking.add(item.id)
  try {
    const result = await experimentApi.complete(item.experiment_id, {
      checkpoint_id: item.id,
      done_at: toLocalMinute(new Date()),
    })
    ElMessage.success(
      result.next_due_label ? `已勾选完成，下次检查：${result.next_due_label}` : '已勾选完成',
    )
    await afterChange()
  } finally {
    ticking.delete(item.id)
  }
}

async function postpone(item) {
  try {
    const result = await experimentApi.postponeCheckpoint(item.experiment_id, item.id, 1)
    ElMessage.success(`已推迟到 ${result.postponed_to}`)
    await afterChange()
  } catch {
    /* 错误提示由拦截器统一处理 */
  }
}

async function removeCheck(item) {
  try {
    await ElMessageBox.confirm(
      `删除「${item.experiment_name}」${item.due_label} 这个检查时间点？删除后不再提醒。`,
      '删除待办',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await experimentApi.removeCheckpoint(item.experiment_id, item.id)
  ElMessage.success('已删除该检查时间点')
  await afterChange()
}

function shift(direction) {
  load(direction < 0 ? data.value?.prev_start : data.value?.next_start)
}

function goToday() {
  load(data.value?.this_week_start || null)
}

defineExpose({ reload: () => load(data.value?.start || null) })

onMounted(() => load())
</script>

<style scoped>
.week-cal {
  min-height: 200px;
}

.week-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--ct-border);
  background: #fbfdfc;
  flex-wrap: wrap;
}

.week-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
}

/* 7 天等分铺满，不做横向滚动 */
.week-scroll {
  overflow: hidden;
}

.week-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
}

.week-day {
  border-right: 1px solid var(--ct-border);
  min-height: 420px;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.week-grid.compact .week-day {
  min-height: 148px;
  max-height: 148px;
  overflow: hidden;
}

/* 压缩模式下内容超出时，格子里自己滚动，不会被裁掉 */
.week-grid.compact .day-items {
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.week-grid.compact .day-items::-webkit-scrollbar {
  width: 5px;
}

.week-grid.compact .day-items::-webkit-scrollbar-thumb {
  background: var(--ct-border-strong);
  border-radius: 3px;
}

.week-day:last-child {
  border-right: 0;
}

.week-day.today {
  background: var(--ct-primary-soft);
}

.week-day.past {
  background: #fbfbfb;
}

.day-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 10px;
  border-bottom: 1px dashed var(--ct-border);
  font-size: 12px;
  color: var(--ct-muted);
}

.week-day.today .day-head {
  color: var(--ct-primary);
  font-weight: 600;
}

.day-week {
  font-size: 12px;
}

.day-num {
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.day-badge {
  margin-left: auto;
  min-width: 17px;
  height: 17px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--ct-warning);
  color: #fff;
  font-size: 10.5px;
  line-height: 17px;
  text-align: center;
}

.day-badge.danger {
  background: var(--ct-danger);
}

.day-items {
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  cursor: default;
}

/* 点格子空白处建待办 */
.week-day.adding {
  box-shadow: inset 0 0 0 2px var(--todo-color, #7c3aed);
}

.day-quickadd {
  margin-top: 2px;
}

.quick-input {
  width: 100%;
  padding: 3px 6px;
  border: 1px solid var(--todo-color, #7c3aed);
  border-radius: 5px;
  font: inherit;
  font-size: 11.5px;
  line-height: 1.5;
  outline: none;
  background: #fff;
  color: var(--ct-text);
}

.quick-input::placeholder {
  color: var(--ct-faint);
  font-size: 11px;
}

/* 待办条目 */
.day-task {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 4px 4px 3px;
  border: 1px solid var(--ct-border);
  border-left: 3px solid var(--item-color, #2563eb);
  border-radius: 6px;
  background: #fff;
  min-width: 0;
}

.day-task.state-overdue {
  --item-color: var(--ct-danger);
  background: #fff8f7;
}

.day-task.state-due {
  --item-color: var(--ct-warning);
  background: #fffdf6;
}

.day-task.state-done {
  --item-color: var(--ct-success);
  opacity: 0.75;
}

/* 用户自建待办：专属紫色 */
.day-task.day-todo {
  --item-color: #7c3aed;
  background: #f9f6ff;
}

.day-task.day-todo:hover {
  background: #f2ebff;
}

.day-task.day-todo.done {
  background: #faf9fd;
  opacity: 0.75;
}

.day-task.day-todo.done .task-title {
  text-decoration: line-through;
  text-decoration-color: rgba(124, 58, 237, 0.45);
}

.task-box.todo {
  border-color: #7c3aed;
}

.task-box.todo.checked {
  background: #7c3aed;
  border-color: #7c3aed;
}

.task-box {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  flex: none;
  border: 1.5px solid var(--item-color, #94a3b8);
  border-radius: 3px;
  background: #fff;
  cursor: pointer;
  color: #fff;
  font-size: 9px;
  transition: background 0.12s ease, border-color 0.12s ease, transform 0.12s ease;
}

.task-box:hover {
  border-color: var(--ct-primary);
  transform: scale(1.12);
}

.task-box.checked {
  background: var(--ct-success);
  border-color: var(--ct-success);
}

.task-box.busy {
  opacity: 0.5;
  cursor: progress;
}

.task-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  cursor: pointer;
  line-height: 1.35;
}

.task-title {
  font-size: 11.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.day-task.state-done .task-title {
  text-decoration: line-through;
  text-decoration-color: rgba(18, 128, 92, 0.45);
}

.task-time {
  font-style: normal;
  color: var(--ct-muted);
  font-variant-numeric: tabular-nums;
  margin-right: 3px;
  font-size: 10.5px;
}

.task-sub {
  font-size: 10px;
  color: var(--ct-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 行尾操作：默认隐藏，悬停整行才出现 */
.task-actions {
  display: flex;
  gap: 0;
  flex: none;
  opacity: 0;
  transition: opacity 0.12s ease;
}

.day-task:hover .task-actions,
.day-task:focus-within .task-actions {
  opacity: 1;
}

.task-act {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 17px;
  height: 17px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--ct-faint);
  cursor: pointer;
  padding: 0;
  font-size: 11px;
}

.task-act:hover {
  background: var(--ct-primary-soft);
  color: var(--ct-primary);
}

.task-act.danger:hover {
  background: #fff1f0;
  color: var(--ct-danger);
}

.day-passage {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  align-self: flex-start;
  padding: 1px 7px;
  border-radius: 4px;
  border: 1px dashed #c9b98a;
  background: #fffdf3;
  color: #8a6d1f;
  font: inherit;
  font-size: 10.5px;
  cursor: pointer;
  line-height: 1.7;
}

.day-passage:hover {
  background: #fff7dd;
  border-style: solid;
}

.day-empty {
  color: var(--ct-faint);
  font-size: 11px;
  text-align: center;
  padding: 8px 0;
}

.day-more {
  border: 0;
  background: transparent;
  color: var(--ct-primary);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 4px;
  text-align: left;
}

@media (max-width: 900px) {
  .week-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .week-day {
    border-bottom: 1px solid var(--ct-border);
    min-height: 200px;
  }
}
</style>
