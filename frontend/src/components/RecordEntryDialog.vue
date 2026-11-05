<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="min(1000px, 96vw)"
    top="5vh"
    append-to-body
    @open="onOpen"
  >
    <el-tabs v-model="tab" @tab-change="onTabChange">
      <!-- ==================== 按组录入 ==================== -->
      <el-tab-pane label="按组录入" name="group">
        <div class="pane-toolbar">
          <el-select v-model="groupId" placeholder="选择细胞组" style="width: 220px" @change="loadGroupRows">
            <el-option
              v-for="group in groups"
              :key="group.id"
              :label="`${group.group_name}（${group.member_count}）`"
              :value="group.id"
            />
          </el-select>
          <el-button size="small" @click="loadGroupRows">刷新</el-button>
          <span class="small faint">勾选要提交的行；改动任意一行的日期，会同步到所有行</span>
          <div style="margin-left: auto">
            <el-button
              type="primary"
              :loading="submittingGroup"
              :disabled="!groupRows.length"
              @click="submitGroup"
            >
              批量提交（{{ selectedGroupRows.length }}）
            </el-button>
          </div>
        </div>

        <div v-if="groupRows.length">
          <el-table :data="groupRows" size="small" max-height="540">
            <el-table-column width="44" align="center">
              <template #header>
                <el-checkbox :model-value="allSelected" :indeterminate="someSelected" @change="toggleAll" />
              </template>
              <template #default="{ row }">
                <el-checkbox v-model="row.selected" />
              </template>
            </el-table-column>
            <el-table-column type="index" label="#" width="46" align="center" />
            <el-table-column prop="cell_line" label="细胞株" min-width="130" fixed />
            <el-table-column prop="batch_name" label="批次" min-width="150" show-overflow-tooltip />
            <el-table-column label="代次" width="82">
              <template #default="{ row }">
                <el-input-number v-model="row.passage" :min="1" :step="1" size="small" controls-position="right" style="width: 100%" />
              </template>
            </el-table-column>
            <el-table-column label="日期" width="146">
              <template #default="{ row }">
                <el-date-picker
                  :model-value="row.date"
                  type="date"
                  value-format="YYYY-MM-DD"
                  size="small"
                  style="width: 100%"
                  @update:model-value="(value) => onGroupDateChange(row, value)"
                />
              </template>
            </el-table-column>
            <el-table-column label="收获总数" width="112">
              <template #default="{ row }">
                <el-input-number v-model="row.harvested_cells" :min="0" :precision="2" size="small" controls-position="right" style="width: 100%" />
              </template>
            </el-table-column>
            <el-table-column label="盘数" width="78">
              <template #default="{ row }">
                <el-input-number v-model="row.inoculum_dishes" :min="1" :step="1" size="small" controls-position="right" style="width: 100%" />
              </template>
            </el-table-column>
            <el-table-column label="每盘细胞数" width="108">
              <template #default="{ row }">
                <el-input-number v-model="row.per_dish_cells" :min="0" :precision="2" size="small" controls-position="right" style="width: 100%" />
              </template>
            </el-table-column>
            <el-table-column label="状态" width="92">
              <template #default="{ row }">
                <el-select v-model="row.status" size="small">
                  <el-option v-for="item in statusChoices" :key="item" :label="item" :value="item" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="间隔天数" width="98">
              <template #default="{ row }">
                <el-input-number v-model="row.next_passage_days" :min="0" :step="1" size="small" controls-position="right" style="width: 100%" />
              </template>
            </el-table-column>
            <el-table-column label="备注" min-width="120">
              <template #default="{ row }"><el-input v-model="row.notes" size="small" placeholder="可选" /></template>
            </el-table-column>
          </el-table>
          <div class="pane-hint">
            行顺序与细胞组里设置的成员顺序一致；收获总数为 0 时 PD 记为 0；每盘细胞数 × 盘数 = 本次接种数。
          </div>
        </div>
        <div v-else class="empty-hint">
          <span class="icon">🧬</span>{{ groupId ? '该组没有活跃批次，先去新建批次' : '选择一个细胞组开始批量录入' }}
        </div>

        <el-alert
          v-if="groupResult"
          :type="groupResult.failed ? 'warning' : 'success'"
          :closable="true"
          style="margin-top: 14px"
          @close="groupResult = null"
        >
          <template #title>成功 {{ groupResult.success }} 条，失败 {{ groupResult.failed }} 条</template>
          <div v-for="item in groupResult.results.filter((r) => !r.ok)" :key="item.index" class="small">
            第 {{ item.index + 1 }} 行：{{ item.error }}
          </div>
        </el-alert>
      </el-tab-pane>

      <!-- ==================== 单批次录入 ==================== -->
      <el-tab-pane label="单批次录入" name="single">
        <div class="single-layout">
          <div>
            <el-form label-position="top">
              <el-form-item label="细胞株">
                <el-select v-model="singleLineId" filterable placeholder="选择细胞株" style="width: 100%" @change="loadSingleBatches">
                  <el-option v-for="line in lines" :key="line.id" :label="line.name" :value="line.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="培养批次">
                <el-select
                  v-model="singleBatchId"
                  placeholder="选择活跃批次"
                  style="width: 100%"
                  :disabled="!singleBatches.length"
                  @change="loadSingleBatch"
                >
                  <el-option v-for="batch in singleBatches" :key="batch.id" :label="batch.batch_name" :value="batch.id" />
                </el-select>
              </el-form-item>
            </el-form>

            <div v-if="singleBatch" class="current-batch">
              <div class="row between">
                <strong>{{ singleBatch.batch_name }}</strong>
                <el-tag size="small" type="info" effect="plain">P{{ singleBatch.current_record?.passage ?? 0 }}</el-tag>
              </div>
              <div class="small muted" style="margin-top: 6px">
                当前累计 PD {{ fmtNum(singleBatch.current_record?.cumulative_pd) }} ·
                上次传代 {{ singleBatch.current_record?.date || '—' }} ·
                建议下次 {{ singleBatch.current_record?.next_passage_date || '未设置' }}
              </div>
            </div>
            <div v-else class="small faint" style="margin-top: 8px">选择批次后可看到当前状态</div>
          </div>

          <div>
            <el-form :model="singleForm" label-width="120px" label-position="left">
              <el-form-item label="传代次数">
                <el-input-number v-model="singleForm.passage" :min="1" :step="1" />
              </el-form-item>
              <el-form-item label="传代日期">
                <el-date-picker v-model="singleForm.date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
              </el-form-item>
              <el-form-item label="收获细胞总数">
                <el-input-number v-model="singleForm.harvested_cells" :min="0" :precision="2" :step="0.1" style="width: 100%" />
              </el-form-item>
              <el-form-item label="种下盘数">
                <el-input-number v-model="singleForm.inoculum_dishes" :min="1" :step="1" style="width: 100%" />
              </el-form-item>
              <el-form-item label="每盘细胞数">
                <el-input-number v-model="singleForm.per_dish_cells" :min="0" :precision="2" :step="0.1" style="width: 100%" />
              </el-form-item>
              <el-form-item label="细胞状态">
                <el-select v-model="singleForm.status" style="width: 100%">
                  <el-option v-for="item in statusChoices" :key="item" :label="item" :value="item" />
                </el-select>
              </el-form-item>
              <el-form-item label="建议间隔天数">
                <el-input-number v-model="singleForm.next_passage_days" :min="0" :step="1" style="width: 100%" />
              </el-form-item>
              <el-form-item label="备注">
                <el-input v-model="singleForm.notes" type="textarea" :rows="2" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="submittingSingle" :disabled="!singleBatchId" @click="submitSingle">
                  提交传代记录
                </el-button>
                <span class="small faint" style="margin-left: 10px">
                  接种数 = {{ singleForm.inoculum_dishes }} × {{ singleForm.per_dish_cells }}
                </span>
              </el-form-item>
            </el-form>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { batchApi, groupApi, recordApi } from '../api'
import { fmtNum, todayISO } from '../utils'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  groups: { type: Array, default: () => [] },
  lines: { type: Array, default: () => [] },
  // 默认细胞株 / 批次 / 细胞组，由打开入口决定
  defaultLineId: { type: Number, default: null },
  defaultBatchId: { type: Number, default: null },
  defaultGroupId: { type: Number, default: null },
})

const emit = defineEmits(['update:modelValue', 'saved'])

const statusChoices = ['良好', '一般', '较差', '污染']

const tab = ref('group')
const groupId = ref(null)
const groupRows = ref([])
const submittingGroup = ref(false)
const groupResult = ref(null)

const singleLineId = ref(null)
const singleBatchId = ref(null)
const singleBatches = ref([])
const singleBatch = ref(null)
const submittingSingle = ref(false)
const singleForm = ref(defaultSingleForm())

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const title = computed(() => (tab.value === 'group' ? '录入传代记录 · 按组' : '录入传代记录 · 单批次'))

const selectedGroupRows = computed(() => groupRows.value.filter((row) => row.selected))
const allSelected = computed(
  () => groupRows.value.length > 0 && selectedGroupRows.value.length === groupRows.value.length,
)
const someSelected = computed(
  () => selectedGroupRows.value.length > 0 && !allSelected.value,
)

function defaultSingleForm() {
  return {
    passage: 1,
    date: todayISO(),
    harvested_cells: 0,
    inoculum_dishes: 1,
    per_dish_cells: 0,
    status: '良好',
    next_passage_days: 0,
    notes: '',
  }
}

function toggleAll(value) {
  groupRows.value.forEach((row) => {
    row.selected = value
  })
}

// 组内大多数情况同一天传代：改任意一行的日期，所有行同步。
// 日期框绑定 :model-value + update 事件，由这里统一写回所有行，
// 避免每行各自 v-model 导致只有被编辑的那一行生效。
function onGroupDateChange(source, value) {
  if (!value) return
  groupRows.value.forEach((row) => {
    row.date = value
  })
}

async function onOpen() {
  tab.value = props.defaultBatchId ? 'single' : 'group'
  groupId.value = props.defaultGroupId || props.groups[0]?.id || null
  singleLineId.value = props.defaultLineId || props.lines.find((line) => line.active_batch_count > 0)?.id
    || props.lines[0]?.id
    || null
  singleBatchId.value = props.defaultBatchId || null
  singleBatch.value = null
  groupResult.value = null
  await loadGroupRows()
  await loadSingleBatches()
}

async function onTabChange(name) {
  if (name === 'group' && groupId.value && !groupRows.value.length) await loadGroupRows()
  if (name === 'single' && singleLineId.value && !singleBatches.value.length) await loadSingleBatches()
}

async function loadGroupRows() {
  groupResult.value = null
  if (!groupId.value) {
    groupRows.value = []
    return
  }
  const statusRows = await groupApi.status(groupId.value)
  const date = todayISO()
  groupRows.value = statusRows.map((row) => ({
    batch_id: row.batch_id,
    cell_line: row.cell_name,
    batch_name: row.batch_name,
    selected: true,
    passage: (row.passage || 0) + 1,
    date,
    harvested_cells: 0,
    inoculum_dishes: row.inoculum_dishes || 1,
    per_dish_cells: row.inoculum_dishes
      ? Number(((row.inoculum_cells || 0) / row.inoculum_dishes).toFixed(2))
      : 0,
    status: '良好',
    next_passage_days: row.default_passage_interval || 0,
    notes: '',
  }))
}

async function submitGroup() {
  const rows = selectedGroupRows.value
  if (!rows.length) {
    ElMessage.warning('请至少勾选一行')
    return
  }
  submittingGroup.value = true
  try {
    const entries = rows.map((row) => ({
      batch_id: row.batch_id,
      passage: row.passage,
      date: row.date,
      harvested_cells: row.harvested_cells,
      inoculum_dishes: row.inoculum_dishes,
      per_dish_cells: row.per_dish_cells,
      status: row.status,
      next_passage_days: row.next_passage_days,
      notes: row.notes,
    }))
    groupResult.value = await recordApi.bulkCreate(entries)
    if (!groupResult.value.failed) ElMessage.success('传代记录已提交')
    await loadGroupRows()
    emit('saved')
  } finally {
    submittingGroup.value = false
  }
}

async function loadSingleBatches() {
  singleBatches.value = []
  if (!singleLineId.value) {
    singleBatch.value = null
    singleBatchId.value = null
    return
  }
  const data = await batchApi.list({ cell_line_id: singleLineId.value, is_active: true })
  singleBatches.value = data
  const keep = singleBatchId.value && data.some((batch) => batch.id === singleBatchId.value)
  singleBatchId.value = keep ? singleBatchId.value : data[0]?.id || null
  await loadSingleBatch()
}

async function loadSingleBatch() {
  if (!singleBatchId.value) {
    singleBatch.value = null
    singleForm.value = defaultSingleForm()
    return
  }
  const detail = await batchApi.detail(singleBatchId.value)
  singleBatch.value = detail.batch
  const current = detail.batch?.current_record
  singleForm.value = {
    ...defaultSingleForm(),
    passage: (current?.passage || 0) + 1,
    next_passage_days: detail.cell_line?.default_passage_interval || 0,
  }
}

async function submitSingle() {
  if (!singleBatchId.value) return
  submittingSingle.value = true
  try {
    await recordApi.create({ batch_id: singleBatchId.value, ...singleForm.value })
    ElMessage.success('传代记录已添加')
    await loadSingleBatch()
    singleForm.value = {
      ...singleForm.value,
      harvested_cells: 0,
      per_dish_cells: 0,
      notes: '',
      passage: (singleBatch.value?.current_record?.passage || 0) + 1,
      date: todayISO(),
    }
    emit('saved')
  } finally {
    submittingSingle.value = false
  }
}
</script>

<style scoped>
.pane-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 0 14px;
}

.pane-hint {
  margin-top: 10px;
  font-size: 12px;
  color: var(--ct-faint);
}

.single-layout {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 28px;
  align-items: start;
}

.current-batch {
  border: 1px solid var(--ct-border);
  background: #fbfdfc;
  border-radius: 12px;
  padding: 12px 14px;
}

@media (max-width: 900px) {
  .single-layout {
    grid-template-columns: 1fr;
    gap: 8px;
  }
}
</style>
