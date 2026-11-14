<template>
  <div class="month-cal" v-loading="loading">
    <div class="month-head">
      <div class="month-title">
        <el-icon><Calendar /></el-icon>
        <strong>{{ data?.label || '本月' }}</strong>
        <el-tag v-if="data?.totals?.checks_pending" size="small" type="warning" effect="light">
          检查待办 {{ data.totals.checks_pending }}
        </el-tag>
        <el-tag v-if="data?.totals?.passages" size="small" effect="plain" type="info">
          传代 {{ data.totals.passages }}
        </el-tag>
      </div>
      <div class="row" style="gap: 6px">
        <el-button size="small" text circle title="上个月" @click="shift(-1)">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <el-button size="small" @click="goToday">本月</el-button>
        <el-button size="small" text circle title="下个月" @click="shift(1)">
          <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <div class="month-weekdays">
      <span v-for="(name, index) in data?.weekdays || []" :key="name" :class="{ weekend: index >= 5 }">
        {{ name }}
      </span>
    </div>

    <div class="month-grid">
      <div
        v-for="day in data?.days || []"
        :key="day.date"
        class="month-cell"
        :class="{ out: !day.in_month, today: day.is_today, past: day.is_past && !day.is_today, adding: addingDate === day.date }"
        @click.self="startQuickAdd(day)"
      >
        <div class="cell-head" @click.self="startQuickAdd(day)">
          <span class="cell-day">{{ day.day }}</span>
          <span v-if="day.overdue_count" class="cell-badge danger">{{ day.overdue_count }}</span>
          <span v-else-if="day.pending_count" class="cell-badge">{{ day.pending_count }}</span>
        </div>

        <div class="cell-body" @click.self="startQuickAdd(day)">
          <!-- 检查点：前面的小方块可直接勾选完成 -->
          <div
            v-for="item in day.checks.slice(0, maxChecks)"
            :key="`c-${item.id}`"
            class="cell-check"
            :class="[`state-${item.done ? 'done' : item.state}`]"
            :title="checkTooltip(item)"
          >
            <span
              class="cc-box"
              :class="{ checked: item.done, busy: ticking.has(item.id) }"
              role="checkbox"
              :aria-checked="item.done ? 'true' : 'false'"
              @click.stop="toggleCheck(item)"
            >
              <el-icon v-if="item.done"><Check /></el-icon>
            </span>
            <span class="cc-body" @click="$emit('open-check', item)">
              <span class="cc-time">{{ item.due_clock }}</span>
              <span class="cc-name">{{ item.experiment_name }}</span>
            </span>
            <span v-if="!item.done" class="cc-actions">
              <button class="cc-act" title="推迟一天" @click.stop="postpone(item)">
                <el-icon><DArrowRight /></el-icon>
              </button>
              <button class="cc-act danger" title="删除这个时间点" @click.stop="removeCheck(item)">
                <el-icon><Close /></el-icon>
              </button>
            </span>
          </div>

          <!-- 传代待办：只显示简短字样，悬停看详情 -->
          <el-tooltip
            v-if="day.passage_count"
            placement="top"
            :show-after="80"
            popper-class="passage-tooltip"
          >
            <template #content>
              <div class="pt-title">需要传代（{{ day.passage_count }}）</div>
              <div v-for="item in day.passages" :key="item.batch_id" class="pt-line">
                <b>{{ item.cell_line }}</b>
                <span>· {{ item.batch_name }}</span>
                <em v-if="item.passage">P{{ item.passage }}</em>
              </div>
            </template>
            <button class="cell-passage" @click="$emit('open-passage', day)">
              <el-icon><Refresh /></el-icon>
              传代{{ day.passage_count > 1 ? ` ${day.passage_count}` : '' }}
            </button>
          </el-tooltip>

          <!-- 用户自建待办：专属紫色，排在实验检查之后 -->
          <div
            v-for="todo in day.todos.slice(0, maxTodos)"
            :key="`t-${todo.id}`"
            class="cell-todo"
            :class="{ done: todo.done }"
            :title="todoTooltip(todo)"
          >
            <span
              class="cc-box todo"
              :class="{ checked: todo.done, busy: ticking.has(`t${todo.id}`) }"
              role="checkbox"
              :aria-checked="todo.done ? 'true' : 'false'"
              @click.stop="toggleTodo(todo)"
            >
              <el-icon v-if="todo.done"><Check /></el-icon>
            </span>
            <span class="cc-body" @click="$emit('open-todo', todo)">
              <span v-if="todo.due_clock" class="cc-time">{{ todo.due_clock }}</span>
              <span class="cc-name">{{ todo.title }}</span>
            </span>
            <span v-if="!todo.done" class="cc-actions">
              <button class="cc-act" title="推迟一天" @click.stop="postponeTodo(todo)">
                <el-icon><DArrowRight /></el-icon>
              </button>
              <button class="cc-act danger" title="删除待办" @click.stop="removeTodo(todo)">
                <el-icon><Close /></el-icon>
              </button>
            </span>
          </div>

          <!-- 点空白处直接建待办：内联输入，回车保存 -->
          <div v-if="addingDate === day.date" class="cell-quickadd" @click.stop>
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

          <button
            v-if="day.checks.length > maxChecks"
            class="cell-more"
            @click.stop="$emit('more', day)"
          >
            +{{ day.checks.length - maxChecks }}
          </button>
        </div>
      </div>
    </div>

    <div class="month-legend">
      <span class="lg"><i class="dot overdue" />逾期检查</span>
      <span class="lg"><i class="dot due" />今天到点</span>
      <span class="lg"><i class="dot upcoming" />即将到点</span>
      <span class="lg"><i class="dot done" />已完成</span>
      <span class="lg"><i class="dot passage" />需要传代</span>
      <span class="lg"><i class="dot todo" />我的待办</span>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { experimentApi, todoApi } from '../api'
import { refreshReminders } from '../reminders'
import { toLocalMinute } from '../utils'

const props = defineProps({
  maxChecks: { type: Number, default: 3 },
  maxTodos: { type: Number, default: 2 },
})
const emit = defineEmits(['open-check', 'open-passage', 'open-todo', 'more', 'changed'])

const loading = ref(false)
const data = ref(null)
// 正在提交勾选的检查点 id（待办用 `t{id}` 前缀避免冲突）
const ticking = reactive(new Set())

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
  // 失焦时如果已经输入内容就保存，空内容则取消
  if (quickText.value.trim()) saveQuickAdd(day)
  else cancelQuickAdd()
}

/** 勾选 / 撤销用户待办 */
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

function checkTooltip(item) {
  const cells = item.cell_line_names?.length ? ` · ${item.cell_line_names.join('、')}` : ''
  if (item.done) {
    const parts = [`${item.experiment_name}${cells} · ${item.due_label}（已完成`]
    if (item.cell_status) parts.push(` · ${item.cell_status}`)
    if (item.observation) parts.push(` · ${item.observation}`)
    parts.push('）')
    return parts.join('')
  }
  return `${item.experiment_name}${cells} · ${item.due_label} · 点击方块直接勾选完成`
}

/** 在月视图里直接勾选 / 取消勾选检查点 */
async function toggleCheck(item) {
  if (ticking.has(item.id)) return
  if (item.done) {
    // 已完成的：确认后撤销
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
    // 直接勾选：不填备注，按当前时间记为实际检查时间
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

async function afterChange() {
  await load(data.value?.month || null)
  // 顶栏提醒铃 / 首页提醒栏同步刷新
  refreshReminders()
  emit('changed')
}

/** 推迟一天：只挪这一个时间点，不改循环间隔 */
async function postpone(item) {
  if (ticking.has(item.id)) return
  ticking.add(item.id)
  try {
    const result = await experimentApi.postponeCheckpoint(item.experiment_id, item.id, 1)
    ElMessage.success(`已推迟到 ${result.postponed_to}`)
    await afterChange()
  } finally {
    ticking.delete(item.id)
  }
}

/** 删除这个待办（检查时间点） */
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

async function load(month = null) {
  loading.value = true
  try {
    data.value = await experimentApi.month(month)
  } finally {
    loading.value = false
  }
}

function shift(direction) {
  load(direction < 0 ? data.value?.prev_month : data.value?.next_month)
}

function goToday() {
  load(data.value?.this_month || null)
}

defineExpose({ reload: () => load(data.value?.month || null) })

onMounted(() => load())
</script>

<style scoped>
.month-cal {
  min-height: 320px;
}

.month-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--ct-border);
  background: #fbfdfc;
  flex-wrap: wrap;
}

.month-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
}

.month-weekdays {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  border-bottom: 1px solid var(--ct-border);
  background: #fbfdfc;
}

.month-weekdays span {
  padding: 6px 8px;
  font-size: 11.5px;
  color: var(--ct-muted);
  text-align: center;
}

.month-weekdays span.weekend {
  color: var(--ct-faint);
}

.month-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  grid-auto-rows: minmax(96px, auto);
}

.month-cell {
  border-right: 1px solid var(--ct-border);
  border-bottom: 1px solid var(--ct-border);
  padding: 5px 6px 7px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.month-cell:nth-child(7n) {
  border-right: 0;
}

.month-cell.out {
  background: #fcfcfc;
  opacity: 0.55;
}

.month-cell.today {
  background: var(--ct-primary-soft);
  box-shadow: inset 0 0 0 2px var(--ct-primary);
}

.month-cell.past:not(.today) {
  background: #fbfbfb;
}

.cell-head {
  display: flex;
  align-items: center;
  gap: 5px;
}

.cell-day {
  font-size: 12.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--ct-text);
}

.month-cell.today .cell-day {
  color: var(--ct-primary);
}

.cell-badge {
  margin-left: auto;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--ct-warning);
  color: #fff;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
}

.cell-badge.danger {
  background: var(--ct-danger);
}

.cell-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

/* 点格子空白处建待办：悬停时格子底色轻微变化，提示可点 */
.month-cell {
  cursor: default;
}

.month-cell:hover:not(.adding) {
  background: #f9fcfb;
}

.month-cell.today:hover:not(.adding) {
  background: var(--ct-primary-soft);
}

.cell-quickadd {
  margin-top: 2px;
}

.quick-input {
  width: 100%;
  padding: 2px 5px;
  border: 1px solid var(--todo-color, #7c3aed);
  border-radius: 4px;
  font: inherit;
  font-size: 10.5px;
  line-height: 1.6;
  outline: none;
  background: #fff;
  color: var(--ct-text);
}

.quick-input::placeholder {
  color: var(--ct-faint);
  font-size: 10px;
}

.month-cell.adding {
  box-shadow: inset 0 0 0 2px var(--todo-color, #7c3aed);
}

/* 悬停时在格子底部提示「点空白添加」 */
.month-cell:not(.adding):hover .cell-body::after {
  content: '+ 点空白添加待办';
  display: block;
  margin-top: 2px;
  padding: 1px 4px;
  font-size: 10px;
  color: #7c3aed;
  opacity: 0.55;
  border: 1px dashed #c4b5fd;
  border-radius: 4px;
  text-align: center;
}

.cell-check {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 1px 4px 1px 2px;
  border: 0;
  border-left: 2px solid var(--item-color, #2563eb);
  border-radius: 3px;
  background: #f4f8ff;
  font: inherit;
  font-size: 10.5px;
  text-align: left;
  color: inherit;
  min-width: 0;
  line-height: 1.6;
}

.cell-check:hover {
  background: #e8f1ff;
}

.cell-check.state-overdue {
  --item-color: var(--ct-danger);
  background: #fff1f0;
}

.cell-check.state-due {
  --item-color: var(--ct-warning);
  background: #fffaf0;
}

.cell-check.state-done {
  --item-color: var(--ct-success);
  background: #f2f7f6;
  color: var(--ct-muted);
}

/* 勾选方块 */
.cc-box {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 13px;
  height: 13px;
  flex: none;
  border: 1.5px solid var(--item-color, #94a3b8);
  border-radius: 3px;
  background: #fff;
  cursor: pointer;
  color: #fff;
  font-size: 9px;
  transition: background 0.12s ease, border-color 0.12s ease, transform 0.12s ease;
}

.cc-box:hover {
  border-color: var(--ct-primary);
  transform: scale(1.12);
}

.cc-box.checked {
  background: var(--ct-success);
  border-color: var(--ct-success);
}

.cc-box.busy {
  opacity: 0.5;
  cursor: progress;
}

.cc-body {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex: 1;
  cursor: pointer;
}

.cc-body:hover .cc-name {
  color: var(--ct-primary);
}

/* 行尾操作：默认隐藏，悬停整条才出现 */
.cc-actions {
  display: flex;
  flex: none;
  opacity: 0;
  transition: opacity 0.12s ease;
}

.cell-check:hover .cc-actions,
.cell-check:focus-within .cc-actions {
  opacity: 1;
}

.cc-act {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 15px;
  padding: 0;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: var(--ct-faint);
  cursor: pointer;
  font-size: 10px;
}

.cc-act:hover {
  background: var(--ct-primary-soft);
  color: var(--ct-primary);
}

.cc-act.danger:hover {
  background: #fff1f0;
  color: var(--ct-danger);
}

/* 用户自建待办：专属紫色 */
.cell-todo {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 1px 4px 1px 2px;
  border-left: 2px solid var(--todo-color, #7c3aed);
  border-radius: 3px;
  background: #f7f3ff;
  font-size: 10.5px;
  min-width: 0;
  line-height: 1.6;
}

.cell-todo:hover {
  background: #f0e9ff;
}

.cell-todo.done {
  background: #f7f5fb;
  color: var(--ct-muted);
}

.cell-todo.done .cc-name {
  text-decoration: line-through;
  text-decoration-color: rgba(124, 58, 237, 0.45);
}

.cc-box.todo {
  border-color: var(--todo-color, #7c3aed);
}

.cc-box.todo.checked {
  background: var(--todo-color, #7c3aed);
  border-color: var(--todo-color, #7c3aed);
}

.cell-todo:hover .cc-actions,
.cell-todo:focus-within .cc-actions {
  opacity: 1;
}

.cc-time {
  font-variant-numeric: tabular-nums;
  color: var(--ct-muted);
  flex: none;
  font-size: 10px;
}

.cc-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell-check.state-done .cc-name {
  text-decoration: line-through;
  text-decoration-color: rgba(18, 128, 92, 0.45);
}

.cell-passage {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  align-self: flex-start;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px dashed #c9b98a;
  background: #fffdf3;
  color: #8a6d1f;
  font: inherit;
  font-size: 10.5px;
  cursor: pointer;
  line-height: 1.6;
}

.cell-passage:hover {
  background: #fff7dd;
  border-style: solid;
}

.cell-more {
  border: 0;
  background: transparent;
  color: var(--ct-primary);
  font-size: 10.5px;
  cursor: pointer;
  padding: 0 4px;
  text-align: left;
}

.month-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  padding: 9px 18px 12px;
  font-size: 11.5px;
  color: var(--ct-faint);
}

.lg {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: #2563eb;
}

.dot.overdue { background: var(--ct-danger); }
.dot.due { background: var(--ct-warning); }
.dot.upcoming { background: #2563eb; }
.dot.done { background: var(--ct-success); }
.dot.passage { background: #c9b98a; }
.dot.todo { background: #7c3aed; }

@media (max-width: 900px) {
  .month-grid {
    grid-auto-rows: minmax(80px, auto);
  }
  .cc-name {
    display: none;
  }
}
</style>

<style>
/* 传代悬停提示（tooltip 渲染在 body 下，需要全局样式） */
.passage-tooltip .pt-title {
  font-weight: 600;
  margin-bottom: 4px;
}

.passage-tooltip .pt-line {
  font-size: 12px;
  line-height: 1.7;
}

.passage-tooltip .pt-line em {
  font-style: normal;
  color: #fbbf24;
  margin-left: 4px;
}
</style>
