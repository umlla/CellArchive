<template>
  <el-dialog
    :model-value="modelValue"
    title="勾选检查完成"
    width="min(520px, 94vw)"
    @update:model-value="(value) => emit('update:modelValue', value)"
    @open="syncForm"
  >
    <div v-if="checkpoint" class="check-head">
      <div class="check-exp">{{ experimentName }}</div>
      <div class="check-due">
        <el-icon><Clock /></el-icon>
        计划检查：<b>{{ checkpoint.due_label }}</b>
        <span v-if="checkpoint.state === 'overdue'" class="overdue-tip">{{ checkpoint.gap_text }}</span>
      </div>
    </div>

    <el-form :model="form" label-width="88px" label-position="left">
      <el-form-item label="备注">
        <el-input
          v-model="form.observation"
          type="textarea"
          :rows="3"
          maxlength="2000"
          placeholder="可选：细胞状况、融合度、形态、污染情况、加药后变化…不填也可以直接打勾"
        />
        <div class="form-tip">
          <el-checkbox v-model="useStatus" size="small">同时标记细胞状况（良好 / 一般 / 较差 / 污染）</el-checkbox>
        </div>
      </el-form-item>
      <el-form-item v-if="useStatus" label="细胞状况">
        <el-radio-group v-model="form.cell_status">
          <el-radio-button v-for="item in cellStatuses" :key="item" :value="item">
            {{ item }}
          </el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="实际检查">
        <el-date-picker
          v-model="form.done_at"
          type="datetime"
          format="YYYY-MM-DD HH:mm"
          value-format="YYYY-MM-DD HH:mm"
          :clearable="false"
          style="width: 100%"
        />
        <div class="form-tip">下一次检查时间从「计划时间」往后推；改了这里则按实际检查时间往后推</div>
      </el-form-item>
    </el-form>

    <div class="next-preview">
      <el-icon><DArrowRight /></el-icon>
      <span>
        勾选后自动提醒下一个时间点：
        <b>{{ nextPreview }}</b>
      </span>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">完成检查</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { experimentApi } from '../api'
import { toLocalMinute } from '../utils'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  experiment: { type: Object, default: null },
  checkpoint: { type: Object, default: null },
  cellStatuses: { type: Array, default: () => ['良好', '一般', '较差', '污染'] },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const saving = ref(false)
const form = reactive({ cell_status: '', observation: '', done_at: '' })
// 默认只填备注；需要时才展开「细胞状况」标记
const useStatus = ref(false)

const experimentName = computed(() => props.experiment?.name || '')

const nextPreview = computed(() => {
  if (!props.experiment || !props.checkpoint) return '—'
  const base = form.done_at ? new Date(form.done_at.replace(' ', 'T')) : new Date()
  const minutes =
    props.experiment.interval_unit === 'd'
      ? Number(props.experiment.interval_value) * 1440
      : props.experiment.interval_unit === 'm'
        ? Number(props.experiment.interval_value)
        : Number(props.experiment.interval_value) * 60
  if (!Number.isFinite(minutes) || minutes <= 0) return '—'
  const next = new Date(base.getTime() + minutes * 60000)
  const pad = (number) => String(number).padStart(2, '0')
  const dayLabel = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][next.getDay()]
  return `${next.getMonth() + 1}-${pad(next.getDate())} ${dayLabel} ${pad(next.getHours())}:${pad(
    next.getMinutes(),
  )}`
})

function syncForm() {
  form.cell_status = ''
  form.observation = ''
  form.done_at = toLocalMinute(new Date())
  useStatus.value = false
}

async function submit() {
  if (!props.experiment || !props.checkpoint) return
  saving.value = true
  try {
    const payload = {
      checkpoint_id: props.checkpoint.id,
      cell_status: useStatus.value ? form.cell_status || null : null,
      observation: form.observation,
      done_at: form.done_at,
    }
    const result = await experimentApi.complete(props.experiment.id, payload)
    emit('saved', result)
    emit('update:modelValue', false)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.check-head {
  background: #f7faf9;
  border: 1px solid var(--ct-border);
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 14px;
}

.check-exp {
  font-weight: 600;
  font-size: 14px;
}

.check-due {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--ct-muted);
}

.check-due b {
  color: var(--ct-text);
}

.overdue-tip {
  color: var(--ct-danger);
  margin-left: 4px;
}

.next-preview {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--ct-primary-soft);
  color: var(--ct-primary);
  font-size: 12.5px;
}

.next-preview b {
  font-size: 13px;
}
</style>
