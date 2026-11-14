<template>
  <el-dialog
    :model-value="modelValue"
    title="已完成待办"
    width="min(720px, 95vw)"
    top="8vh"
    @update:model-value="(value) => emit('update:modelValue', value)"
    @open="load"
  >
    <div class="done-toolbar">
      <el-date-picker
        v-model="range"
        type="daterange"
        value-format="YYYY-MM-DD"
        format="YYYY-MM-DD"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        size="small"
        style="width: 260px"
        @change="load"
      />
      <el-input
        v-model="keyword"
        placeholder="搜索内容 / 备注"
        clearable
        size="small"
        style="width: 200px"
        @keyup.enter="load"
        @clear="load"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button size="small" @click="clearRange">全部时间</el-button>
      <span class="small faint" style="margin-left: auto">共 {{ rows.length }} 条</span>
    </div>

    <div v-loading="loading" class="done-list">
      <div v-for="todo in rows" :key="todo.id" class="done-item">
        <span class="done-check"><el-icon><Check /></el-icon></span>
        <div class="done-main">
          <div class="done-title">{{ todo.title }}</div>
          <div v-if="todo.notes" class="done-notes">{{ todo.notes }}</div>
        </div>
        <div class="done-meta">
          <span class="done-date">{{ dueText(todo) }}</span>
          <span class="done-at">完成于 {{ todo.done_at || '—' }}</span>
        </div>
        <el-button link type="primary" size="small" @click="reopen(todo)">撤销</el-button>
      </div>
      <div v-if="!loading && !rows.length" class="empty-hint" style="padding: 36px">
        <span class="icon">✅</span>这段时间还没有已完成的待办
      </div>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { todoApi } from '../api'

defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue', 'changed'])

const loading = ref(false)
const rows = ref([])
const range = ref(null)
const keyword = ref('')

async function load() {
  loading.value = true
  try {
    const params = { only_done: true }
    if (range.value?.length === 2) {
      params.start = range.value[0]
      params.end = range.value[1]
    }
    if (keyword.value.trim()) params.q = keyword.value.trim()
    const data = await todoApi.list(params)
    // 最近完成的排前面
    rows.value = data
      .slice()
      .sort((a, b) => (b.done_at || '').localeCompare(a.done_at || ''))
  } finally {
    loading.value = false
  }
}

function clearRange() {
  range.value = null
  load()
}

/** 计划日期 + 时间（全天待办只显示日期） */
function dueText(todo) {
  return todo.due_clock ? `${todo.due_date} ${todo.due_clock}` : `${todo.due_date} 全天`
}

async function reopen(todo) {
  await todoApi.complete(todo.id, false)
  ElMessage.success('已撤销完成，待办重新出现在日程里')
  await load()
  emit('changed')
}
</script>

<style scoped>
.done-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.done-list {
  max-height: 460px;
  overflow-y: auto;
  min-height: 120px;
}

.done-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--ct-border);
  margin-bottom: 6px;
  background: #fdfefe;
}

.done-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex: none;
  border-radius: 4px;
  background: #7c3aed;
  color: #fff;
  font-size: 10px;
}

.done-main {
  min-width: 0;
  flex: 1;
}

.done-title {
  font-size: 13px;
  text-decoration: line-through;
  text-decoration-color: rgba(124, 58, 237, 0.45);
  color: var(--ct-muted);
}

.done-notes {
  font-size: 11.5px;
  color: var(--ct-faint);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.done-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  font-size: 11px;
  color: var(--ct-faint);
  white-space: nowrap;
}

.done-date {
  font-variant-numeric: tabular-nums;
  color: var(--ct-muted);
}
</style>
