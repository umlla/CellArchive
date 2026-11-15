<template>
  <div class="schedule-board">
    <div class="sb-toolbar">
      <el-radio-group v-if="!hideSwitch" v-model="mode" size="small" class="sb-switch">
        <el-radio-button value="month">月视图</el-radio-button>
        <el-radio-button value="week">周视图</el-radio-button>
      </el-radio-group>
      <span class="sb-hint">
        {{ hideSwitch ? '按天查看检查与传代安排' : (mode === 'month' ? '按月看整体安排' : '每天空间更大，能看到更多待办') }}
      </span>
      <div class="row" style="margin-left: auto; gap: 8px">
        <el-button size="small" type="primary" plain @click="addVisible = true">
          <el-icon><Plus /></el-icon>添加待办
        </el-button>
        <el-button size="small" @click="openDone">已完成</el-button>
      </div>
    </div>

    <MonthCalendar
      v-if="mode === 'month'"
      ref="monthRef"
      @open-check="$emit('open-check', $event)"
      @open-passage="$emit('open-passage', $event)"
      @open-todo="openTodo"
      @more="$emit('more', $event)"
      @changed="onChanged"
    />
    <WeekCalendar
      v-else
      ref="weekRef"
      :compact="weekCompact"
      @open-check="$emit('open-check', $event)"
      @open-passage="$emit('open-passage', $event)"
      @open-todo="openTodo"
      @more="$emit('more', $event)"
      @changed="onChanged"
    />

    <!-- 添加 / 编辑待办 -->
    <TodoDialog
      v-model="addVisible"
      :todo="editingTodo"
      :default-date="defaultDate"
      @saved="onTodoSaved"
    />

    <!-- 已完成待办查询 -->
    <DoneTodosDialog v-model="doneVisible" @changed="onChanged" />
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import MonthCalendar from './MonthCalendar.vue'
import WeekCalendar from './WeekCalendar.vue'
import TodoDialog from './TodoDialog.vue'
import DoneTodosDialog from './DoneTodosDialog.vue'

const props = defineProps({
  modelValue: { type: String, default: 'month' },
  // 周视图是否压缩成单行高度（细胞实验页用，避免和首页功能重复）
  weekCompact: { type: Boolean, default: false },
  // 是否隐藏「月视图 / 周视图」切换（细胞实验页固定用周视图）
  hideSwitch: { type: Boolean, default: false },
})
const emit = defineEmits([
  'update:modelValue',
  'open-check',
  'open-passage',
  'more',
  'changed',
])

// 隐藏切换时固定用周视图
const mode = ref(props.hideSwitch || props.modelValue === 'week' ? 'week' : 'month')
const monthRef = ref(null)
const weekRef = ref(null)

const addVisible = ref(false)
const editingTodo = ref(null)
const defaultDate = ref('')
const doneVisible = ref(false)

watch(mode, (value) => emit('update:modelValue', value))

function addTodo(date = '') {
  editingTodo.value = null
  defaultDate.value = date
  addVisible.value = true
}

function openTodo(todo) {
  editingTodo.value = todo
  defaultDate.value = todo.due_date || ''
  addVisible.value = true
}

function openDone() {
  doneVisible.value = true
}

function reload() {
  if (mode.value === 'month') monthRef.value?.reload()
  else weekRef.value?.reload()
}

function onTodoSaved() {
  reload()
  emit('changed')
}

function onChanged() {
  reload()
  emit('changed')
}

defineExpose({
  reload,
  getMode: () => mode.value,
  addTodo,
})
</script>

<style scoped>
.schedule-board {
  min-width: 0;
}

.sb-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 18px;
  border-bottom: 1px solid var(--ct-border);
  background: #fbfdfc;
  flex-wrap: wrap;
}

.sb-hint {
  font-size: 11.5px;
  color: var(--ct-faint);
}
</style>
