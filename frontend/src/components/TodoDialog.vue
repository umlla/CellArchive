<template>
  <el-dialog
    :model-value="modelValue"
    :title="todo ? '编辑待办' : '添加待办事项'"
    width="min(520px, 94vw)"
    @update:model-value="(value) => emit('update:modelValue', value)"
    @open="syncForm"
  >
    <el-form :model="form" label-width="72px" label-position="left">
      <el-form-item label="内容" required>
        <el-input
          ref="titleInput"
          v-model="form.title"
          maxlength="200"
          show-word-limit
          placeholder="例如：买 DMEM、预约离心机、整理冻存记录"
          @keyup.enter="save"
        />
      </el-form-item>

      <el-form-item label="日期" required>
        <div class="date-row">
          <el-date-picker
            v-model="form.due_date"
            type="date"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
            :clearable="false"
            style="flex: 1"
          />
          <div class="quick-days">
            <button type="button" class="qd" @click="setDate(0)">今天</button>
            <button type="button" class="qd" @click="setDate(1)">明天</button>
            <button type="button" class="qd" @click="setDate(2)">后天</button>
            <button type="button" class="qd" @click="setDate(7)">下周</button>
          </div>
        </div>
      </el-form-item>

      <el-form-item label="时间">
        <div class="row" style="gap: 10px; width: 100%">
          <el-switch v-model="useClock" active-text="指定时间" />
          <el-time-select
            v-if="useClock"
            v-model="form.due_clock"
            start="06:00"
            step="00:15"
            end="23:45"
            placeholder="选择时间"
            style="width: 140px"
          />
          <span v-else class="small faint">不填时间 = 全天待办</span>
        </div>
      </el-form-item>

      <el-form-item label="备注">
        <el-input
          v-model="form.notes"
          type="textarea"
          :rows="2"
          maxlength="2000"
          placeholder="可选：品牌、数量、注意事项"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">
        {{ todo ? '保存' : '添加' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { nextTick, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { todoApi } from '../api'
import { todayISO } from '../utils'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  todo: { type: Object, default: null },
  // 新建时默认日期（点日历某一天添加时传入）
  defaultDate: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const saving = ref(false)
const useClock = ref(false)
const titleInput = ref(null)
const form = reactive({ title: '', notes: '', due_date: todayISO(), due_clock: '09:00' })

function setDate(offset) {
  const date = new Date()
  date.setDate(date.getDate() + offset)
  const pad = (n) => String(n).padStart(2, '0')
  form.due_date = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function syncForm() {
  if (props.todo) {
    form.title = props.todo.title || ''
    form.notes = props.todo.notes || ''
    form.due_date = props.todo.due_date || todayISO()
    form.due_clock = props.todo.due_clock || '09:00'
    useClock.value = !!props.todo.due_clock
  } else {
    form.title = ''
    form.notes = ''
    form.due_date = props.defaultDate || todayISO()
    form.due_clock = '09:00'
    useClock.value = false
  }
  nextTick(() => titleInput.value?.focus())
}

async function save() {
  if (!form.title.trim()) {
    ElMessage.warning('请填写待办内容')
    return
  }
  if (!form.due_date) {
    ElMessage.warning('请选择日期')
    return
  }
  saving.value = true
  try {
    const payload = {
      title: form.title.trim(),
      notes: form.notes,
      due_date: form.due_date,
      due_clock: useClock.value ? form.due_clock : null,
    }
    if (props.todo) {
      await todoApi.update(props.todo.id, payload)
      ElMessage.success('待办已更新')
    } else {
      await todoApi.create(payload)
      ElMessage.success('待办已添加')
    }
    emit('saved')
    emit('update:modelValue', false)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.date-row {
  display: flex;
  gap: 8px;
  width: 100%;
  flex-wrap: wrap;
}

.quick-days {
  display: flex;
  gap: 4px;
}

.qd {
  border: 1px solid var(--ct-border-strong);
  background: #fff;
  border-radius: 999px;
  padding: 2px 10px;
  font: inherit;
  font-size: 12px;
  color: var(--ct-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.qd:hover {
  border-color: var(--todo-color, #7c3aed);
  color: var(--todo-color, #7c3aed);
}
</style>
