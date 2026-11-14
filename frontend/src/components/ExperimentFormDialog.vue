<template>
  <el-dialog
    :model-value="modelValue"
    :title="experiment ? '编辑细胞实验' : '新建细胞实验'"
    width="min(680px, 95vw)"
    top="5vh"
    @update:model-value="close"
    @open="syncForm"
  >
    <el-form :model="form" label-width="104px" label-position="left" class="exp-form">
      <el-form-item label="实验名" required>
        <el-input
          v-model="form.name"
          maxlength="120"
          show-word-limit
          placeholder="例如：A549 紫杉醇梯度实验"
          @keyup.enter="save"
        />
      </el-form-item>

      <el-form-item label="细胞与条件">
        <el-input
          v-model="form.notes"
          type="textarea"
          :rows="2"
          maxlength="4000"
          placeholder="细胞株、处理条件，例如：A549 P12，紫杉醇 0/10/50 nM，每孔 2×10⁴，三复孔"
        />
      </el-form-item>

      <!-- 关联细胞株：先按组带入，再自由增减 -->
      <el-form-item label="关联细胞株">
        <div class="line-picker">
          <div class="picker-row">
            <el-select
              v-model="groupToAdd"
              placeholder="按细胞组选择（可多选）"
              multiple
              collapse-tags
              collapse-tags-tooltip
              filterable
              :disabled="!groups.length"
              style="flex: 1"
              @change="onGroupsPicked"
            >
              <el-option
                v-for="group in groups"
                :key="group.id"
                :label="`${group.group_name}（${group.member_count}）`"
                :value="group.id"
              />
            </el-select>
          </div>
          <div class="picker-row">
            <el-select
              v-model="lineToAdd"
              placeholder="或单独选择细胞株"
              filterable
              clearable
              :disabled="!availableLines.length"
              style="flex: 1"
            >
              <el-option
                v-for="line in availableLines"
                :key="line.id"
                :label="`${line.name}${line.species ? `（${line.species}）` : ''}`"
                :value="line.id"
              />
            </el-select>
            <el-button :disabled="!lineToAdd" @click="addLine">加入</el-button>
          </div>

          <div v-if="pickedLines.length" class="picked-list">
            <span
              v-for="line in pickedLines"
              :key="line.cell_line_id"
              class="picked-chip"
              :style="{ '--chip-color': lineColor(line.cell_line_id) }"
            >
              <i class="swatch" />
              {{ line.name }}
              <button type="button" class="chip-remove" title="移除" @click="removeLine(line.cell_line_id)">
                ×
              </button>
            </span>
          </div>
          <div v-else class="form-tip">
            可不选。选了细胞组会自动带入组内全部细胞株，带入后仍可单独增删。
          </div>
          <div v-if="pickedGroupNames.length" class="form-tip">
            已关联细胞组：{{ pickedGroupNames.join('、') }}
          </div>
        </div>
      </el-form-item>

      <el-form-item label="实验时间" required>
        <el-date-picker
          v-model="form.started_at"
          type="datetime"
          format="YYYY-MM-DD HH:mm"
          value-format="YYYY-MM-DD HH:mm"
          :clearable="false"
          style="width: 100%"
        />
        <div class="form-tip">实验开始 / 处理的时间，下一次操作时间由此往后推算</div>
      </el-form-item>

      <el-form-item label="操作间隔" required>
        <div style="width: 100%">
          <div class="interval-row">
            <el-radio-group v-model="form.interval_unit" size="default" @change="onUnitChange">
              <el-radio-button value="h">按小时</el-radio-button>
              <el-radio-button value="d">按天</el-radio-button>
            </el-radio-group>
            <el-input-number
              v-model="form.interval_value"
              :min="form.interval_unit === 'h' ? 1 : 0.5"
              :max="form.interval_unit === 'h' ? 720 : 90"
              :step="form.interval_unit === 'h' ? 6 : 1"
              :precision="form.interval_unit === 'h' ? 0 : 1"
              style="width: 150px"
            />
            <span class="unit-label">{{ form.interval_unit === 'h' ? '小时' : '天' }}</span>
          </div>
          <div class="preset-row">
            <button
              v-for="preset in presets"
              :key="preset.label"
              type="button"
              class="preset-chip"
              :class="{ active: preset.active }"
              @click="applyPreset(preset)"
            >
              {{ preset.label }}
            </button>
          </div>
        </div>
      </el-form-item>

      <el-form-item label="下次操作">
        <div class="next-preview-box">
          <el-icon><Clock /></el-icon>
          <div>
            <div class="np-time">{{ nextDueLabel }}</div>
            <div class="np-sub">
              {{ previewText }} · 之后每次勾选「检查完成」都会自动排下一次
            </div>
          </div>
        </div>
      </el-form-item>

      <el-form-item label="备注">
        <el-input
          v-model="form.extra_notes"
          type="textarea"
          :rows="2"
          maxlength="4000"
          placeholder="其他信息：仪器、试剂批号、分组安排、注意事项等（可选）"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <span v-if="error" class="form-error">{{ error }}</span>
      <el-button @click="close(false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">
        {{ experiment ? '保存修改' : '创建实验' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { experimentApi } from '../api'
import { lineColor } from '../charts'
import { intervalText, toLocalMinute } from '../utils'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  experiment: { type: Object, default: null },
  lines: { type: Array, default: () => [] },
  groups: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const saving = ref(false)
const error = ref('')
const groupToAdd = ref([])
const lineToAdd = ref(null)

const form = reactive({
  name: '',
  notes: '',
  extra_notes: '',
  started_at: toLocalMinute(new Date()),
  interval_unit: 'h',
  interval_value: 24,
})

// 已选细胞株（保持选择顺序）与已关联的细胞组
const pickedLines = ref([])
const pickedGroups = ref([])

const PRESETS = [
  { label: '12h', interval_value: 12, interval_unit: 'h' },
  { label: '24h', interval_value: 24, interval_unit: 'h' },
  { label: '48h', interval_value: 48, interval_unit: 'h' },
  { label: '72h', interval_value: 72, interval_unit: 'h' },
  { label: '1d', interval_value: 1, interval_unit: 'd' },
  { label: '2d', interval_value: 2, interval_unit: 'd' },
  { label: '3d', interval_value: 3, interval_unit: 'd' },
]

const presets = computed(() =>
  PRESETS.map((preset) => ({
    ...preset,
    active:
      Number(preset.interval_value) === Number(form.interval_value) &&
      preset.interval_unit === form.interval_unit,
  })),
)

const availableLines = computed(() => {
  const picked = new Set(pickedLines.value.map((line) => line.cell_line_id))
  return props.lines.filter((line) => !picked.has(line.id))
})

const pickedGroupNames = computed(() => pickedGroups.value.map((group) => group.group_name))

const previewText = computed(() => intervalText(form.interval_value, form.interval_unit))

function intervalMinutes() {
  const value = Number(form.interval_value) || 0
  if (form.interval_unit === 'd') return value * 1440
  return value * 60
}

/** 下次操作时间 = 实验时间 + 间隔 */
const nextDue = computed(() => {
  if (!form.started_at) return null
  const base = new Date(String(form.started_at).replace(' ', 'T'))
  if (Number.isNaN(base.getTime())) return null
  return new Date(base.getTime() + intervalMinutes() * 60000)
})

const nextDueLabel = computed(() => {
  const due = nextDue.value
  if (!due) return '—'
  const pad = (number) => String(number).padStart(2, '0')
  const now = new Date()
  const dayLabel = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][due.getDay()]
  const sameDay = due.toDateString() === now.toDateString()
  const tomorrow = new Date(now)
  tomorrow.setDate(now.getDate() + 1)
  const prefix = sameDay
    ? '今天'
    : due.toDateString() === tomorrow.toDateString()
      ? '明天'
      : `${due.getMonth() + 1}-${pad(due.getDate())} ${dayLabel}`
  return `${prefix} ${pad(due.getHours())}:${pad(due.getMinutes())}`
})

function syncForm() {
  error.value = ''
  groupToAdd.value = []
  lineToAdd.value = null
  if (props.experiment) {
    const exp = props.experiment
    form.name = exp.name || ''
    form.notes = exp.notes || ''
    form.extra_notes = exp.extra_notes || ''
    form.started_at = exp.started_at || toLocalMinute(new Date())
    form.interval_unit = exp.interval_unit === 'd' || exp.interval_unit === 'm' ? exp.interval_unit : 'h'
    form.interval_value = Number(exp.interval_value) || 24
    pickedLines.value = (exp.cell_lines || []).map((line) => ({ ...line }))
    pickedGroups.value = (exp.groups || []).map((group) => ({ ...group }))
  } else {
    form.name = ''
    form.notes = ''
    form.extra_notes = ''
    form.started_at = toLocalMinute(new Date())
    form.interval_unit = 'h'
    form.interval_value = 24
    pickedLines.value = []
    pickedGroups.value = []
  }
}

function addPickedLine(line) {
  if (!line) return false
  if (pickedLines.value.some((item) => item.cell_line_id === line.id)) return false
  pickedLines.value = [
    ...pickedLines.value,
    { cell_line_id: line.id, name: line.name, species: line.species, type: line.type },
  ]
  return true
}

function addLine() {
  const line = props.lines.find((item) => item.id === lineToAdd.value)
  addPickedLine(line)
  lineToAdd.value = null
}

function removeLine(lineId) {
  pickedLines.value = pickedLines.value.filter((line) => line.cell_line_id !== lineId)
}

/** 选中细胞组：把组内成员一次性带入（已选的不重复加） */
function onGroupsPicked(ids) {
  pickedGroups.value = props.groups
    .filter((group) => ids.includes(group.id))
    .map((group) => ({ group_id: group.id, group_name: group.group_name }))
  let added = 0
  for (const group of props.groups.filter((item) => ids.includes(item.id))) {
    for (const member of group.members || []) {
      if (addPickedLine({ id: member.cell_line_id, name: member.name, species: member.species, type: member.type })) {
        added += 1
      }
    }
  }
  if (added) ElMessage.success(`已带入 ${added} 株细胞，可继续单独增删`)
}

function onUnitChange(unit) {
  if (unit === 'd') {
    if (form.interval_value >= 24) form.interval_value = Math.max(1, Math.round(form.interval_value / 24))
    if (form.interval_value > 90) form.interval_value = 1
  } else if (form.interval_value <= 3) {
    form.interval_value = Math.round(form.interval_value * 24)
  }
}

function applyPreset(preset) {
  form.interval_unit = preset.interval_unit
  form.interval_value = preset.interval_value
}

function close(value = false) {
  if (value === false) emit('update:modelValue', false)
}

async function save() {
  error.value = ''
  if (!form.name.trim()) {
    error.value = '请填写实验名'
    return
  }
  if (!form.started_at) {
    error.value = '请选择实验时间'
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      notes: form.notes,
      extra_notes: form.extra_notes,
      started_at: form.started_at,
      interval_unit: form.interval_unit,
      interval_value: form.interval_value,
      cell_line_ids: pickedLines.value.map((line) => line.cell_line_id),
      group_ids: pickedGroups.value.map((group) => group.group_id),
    }
    if (props.experiment) {
      await experimentApi.update(props.experiment.id, payload)
      ElMessage.success('实验信息已更新')
    } else {
      await experimentApi.create(payload)
      ElMessage.success(`实验已创建，下次操作：${nextDueLabel.value}`)
    }
    emit('saved')
    emit('update:modelValue', false)
  } catch (err) {
    error.value = err?.message || '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.exp-form {
  padding-right: 8px;
}

.interval-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.unit-label {
  font-size: 12px;
  color: var(--ct-muted);
}

.preset-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.preset-chip {
  border: 1px solid var(--ct-border-strong);
  background: #fff;
  border-radius: 999px;
  padding: 3px 12px;
  font: inherit;
  font-size: 12px;
  color: var(--ct-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}

.preset-chip:hover {
  border-color: var(--ct-accent);
  color: var(--ct-primary);
}

.preset-chip.active {
  background: var(--ct-primary-soft);
  border-color: var(--ct-primary);
  color: var(--ct-primary);
  font-weight: 600;
}

/* 细胞株选择 */
.line-picker {
  width: 100%;
}

.picker-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.picked-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.picked-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px 3px 8px;
  border-radius: 999px;
  background: #f4f9f8;
  border: 1px solid var(--ct-border);
  font-size: 12px;
}

.picked-chip .swatch {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--chip-color, var(--ct-primary));
  flex: none;
}

.chip-remove {
  border: 0;
  background: transparent;
  color: var(--ct-faint);
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  padding: 0 2px;
}

.chip-remove:hover {
  color: var(--ct-danger);
}

.next-preview-box {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--ct-primary-soft);
  color: var(--ct-primary);
}

.next-preview-box .np-time {
  display: block;
  font-size: 16px;
  font-weight: 650;
  line-height: 1.3;
  font-variant-numeric: tabular-nums;
  color: var(--ct-primary);
}

.next-preview-box .np-sub {
  display: block;
  font-size: 11.5px;
  color: var(--ct-muted);
  margin-top: 2px;
  line-height: 1.5;
}

.form-error {
  color: var(--ct-danger);
  font-size: 12px;
  margin-right: 12px;
}
</style>
