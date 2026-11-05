<template>
  <div class="panel">
    <div class="panel-head" style="align-items: flex-start">
      <div>
        <h2>传代记录</h2>
        <p class="sub">这里查看和编辑历史记录；录入新记录请到「在养细胞」页</p>
      </div>
      <el-button size="small" type="primary" @click="$router.push('/')">去在养细胞录入</el-button>
    </div>

    <el-tabs v-model="tab" class="records-tabs" @tab-change="onTabChange">
      <!-- ==================== 按组查看编辑 ==================== -->
      <el-tab-pane label="按组查看编辑" name="group-edit">
        <div class="pane-toolbar">
          <el-select v-model="editGroupId" placeholder="选择细胞组" style="width: 220px" @change="loadEditRows">
            <el-option v-for="group in groups" :key="group.id" :label="`${group.group_name}（${group.member_count}）`" :value="group.id" />
          </el-select>
          <el-button size="small" @click="loadEditRows">刷新</el-button>
          <span class="small faint">修改后点击保存，系统会按批次重算累计 PD</span>
          <div style="margin-left: auto">
            <el-button type="primary" :loading="savingEdits" :disabled="!editRows.length" @click="saveEdits">保存全部修改</el-button>
          </div>
        </div>

        <div v-if="editRows.length" class="pane-body">
          <el-table :data="editRows" size="small" max-height="560">
            <el-table-column prop="cell_line" label="细胞株" min-width="110" fixed />
            <el-table-column prop="batch_name" label="批次" min-width="130" show-overflow-tooltip />
            <el-table-column label="代次" width="78">
              <template #default="{ row }"><el-input-number v-model="row.passage" :min="1" :step="1" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="日期" width="130">
              <template #default="{ row }"><el-date-picker v-model="row.date" type="date" value-format="YYYY-MM-DD" size="small" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="收获" width="112">
              <template #default="{ row }"><el-input-number v-model="row.harvested_cells" :min="0" :precision="2" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="盘数" width="80">
              <template #default="{ row }"><el-input-number v-model="row.inoculum_dishes" :min="1" :step="1" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="每盘" width="108">
              <template #default="{ row }"><el-input-number v-model="row.per_dish_cells" :min="0" :precision="2" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="状态" width="92">
              <template #default="{ row }">
                <el-select v-model="row.status" size="small">
                  <el-option v-for="item in statusChoices" :key="item" :label="item" :value="item" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="间隔天数" width="98">
              <template #default="{ row }"><el-input-number v-model="row.next_passage_days" :min="0" :step="1" size="small" controls-position="right" style="width: 100%" /></template>
            </el-table-column>
            <el-table-column label="备注" min-width="110">
              <template #default="{ row }"><el-input v-model="row.notes" size="small" /></template>
            </el-table-column>
            <el-table-column label="操作" width="70" fixed="right">
              <template #default="{ row }">
                <el-button link type="danger" size="small" @click="removeEditRow(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pane-hint">间隔天数填 0 表示保留该记录原有的建议下次传代日期。</div>
        </div>
        <div v-else class="empty-hint">
          <span class="icon">✏️</span>{{ editGroupId ? '该组没有可编辑的活跃传代记录' : '选择一个细胞组开始编辑' }}
        </div>

        <el-alert v-if="editResult" :type="editResult.failed ? 'warning' : 'success'" style="margin: 0 18px 18px" @close="editResult = null">
          <template #title>成功保存 {{ editResult.success }} 条，失败 {{ editResult.failed }} 条</template>
          <div v-for="item in editResult.results.filter((r) => !r.ok)" :key="item.index" class="small">
            第 {{ item.index + 1 }} 行：{{ item.error }}
          </div>
        </el-alert>
      </el-tab-pane>

      <!-- ==================== 按批次查看 ==================== -->
      <el-tab-pane label="按批次查看" name="batch">
        <div class="pane-toolbar">
          <el-select v-model="batchLineId" filterable placeholder="选择细胞株" style="width: 200px" @change="loadBatchList">
            <el-option v-for="line in lines" :key="line.id" :label="line.name" :value="line.id" />
          </el-select>
          <el-select v-model="batchId" placeholder="选择批次" style="width: 240px" :disabled="!batchList.length" @change="loadBatchRecords">
            <el-option
              v-for="batch in batchList"
              :key="batch.id"
              :label="`${batch.batch_name}${batch.is_active ? '' : '（已终止）'}`"
              :value="batch.id"
            />
          </el-select>
          <el-checkbox v-model="includeEndedBatches" @change="loadBatchList">显示已终止批次</el-checkbox>
          <span class="small faint">共 {{ batchRecords.length }} 条记录</span>
          <div style="margin-left: auto">
            <el-button size="small" :disabled="!batchId || !batchRecords.length" @click="downloadUrl(batchApi.csvUrl(batchId))">
              导出 CSV
            </el-button>
          </div>
        </div>

        <div v-if="batchRecords.length" class="pane-body">
          <el-table :data="batchRecords" size="small" max-height="560">
            <el-table-column prop="passage" label="代次" width="66" align="center" />
            <el-table-column prop="date" label="日期" width="104" />
            <el-table-column label="接种" width="82" align="right">
              <template #default="{ row }">{{ fmtNum(row.inoculum_cells) }}</template>
            </el-table-column>
            <el-table-column prop="inoculum_dishes" label="盘数" width="60" align="center" />
            <el-table-column label="收获" width="82" align="right">
              <template #default="{ row }">{{ fmtNum(row.harvested_cells) }}</template>
            </el-table-column>
            <el-table-column label="单次PD" width="76" align="right">
              <template #default="{ row }">
                <span :style="{ color: row.pd < 0 ? 'var(--ct-danger)' : 'inherit' }">{{ fmtNum(row.pd) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="累计PD" width="82" align="right">
              <template #default="{ row }">{{ fmtNum(row.cumulative_pd) }}</template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="72" align="center" />
            <el-table-column prop="next_passage_date" label="下次传代" width="104" />
            <el-table-column prop="notes" label="备注" min-width="100" show-overflow-tooltip />
            <el-table-column label="操作" width="96" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="startEdit(row)">编辑</el-button>
                <el-button link type="danger" size="small" @click="removeRecord(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div v-else class="empty-hint">
          <span class="icon">📄</span>{{ batchId ? '该批次还没有传代记录' : '选择细胞株和批次查看历史记录' }}
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 编辑单条记录 -->
    <el-dialog v-model="editVisible" title="编辑传代记录" width="min(560px, 94vw)">
      <el-form v-if="editForm" :model="editForm" label-width="110px" label-position="left">
        <el-form-item label="传代次数">
          <el-input-number v-model="editForm.passage" :min="1" :step="1" />
        </el-form-item>
        <el-form-item label="传代日期">
          <el-date-picker v-model="editForm.date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="收获细胞总数">
          <el-input-number v-model="editForm.harvested_cells" :min="0" :step="0.1" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="种下盘数">
          <el-input-number v-model="editForm.inoculum_dishes" :min="1" :step="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="每盘细胞数">
          <el-input-number v-model="editForm.per_dish_cells" :min="0" :step="0.1" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="细胞状态">
          <el-select v-model="editForm.status" style="width: 100%">
            <el-option v-for="item in statusChoices" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="下次间隔天数">
          <el-input-number v-model="editForm.next_passage_days" :min="0" :step="1" style="width: 100%" />
          <div class="form-tip">填 0 表示保留原来的建议传代日期</div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingRecord" @click="saveRecord">保存并重算 PD</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { batchApi, groupApi, lineApi, recordApi } from '../api'
import { downloadUrl, fmtNum } from '../utils'

const statusChoices = ['良好', '一般', '较差', '污染']

const groups = ref([])
const lines = ref([])
const tab = ref('group-edit')

const editGroupId = ref(null)
const editRows = ref([])
const savingEdits = ref(false)
const editResult = ref(null)

const batchLineId = ref(null)
const batchList = ref([])
const batchId = ref(null)
const batchRecords = ref([])
const includeEndedBatches = ref(true)

const editVisible = ref(false)
const editForm = ref(null)
const savingRecord = ref(false)

async function loadEditRows() {
  editResult.value = null
  if (!editGroupId.value) {
    editRows.value = []
    return
  }
  const records = await groupApi.records(editGroupId.value)
  editRows.value = records.map((row) => ({
    id: row.id,
    batch_id: row.batch_id,
    cell_line: row.cell_line,
    batch_name: row.batch_name,
    passage: row.passage,
    date: row.date,
    harvested_cells: row.harvested_cells,
    inoculum_dishes: row.inoculum_dishes,
    per_dish_cells: row.per_dish_cells,
    status: row.status,
    next_passage_days: 0,
    notes: row.notes || '',
  }))
}

async function saveEdits() {
  savingEdits.value = true
  try {
    const entries = editRows.value.map((row) => ({
      id: row.id,
      passage: row.passage,
      date: row.date,
      harvested_cells: row.harvested_cells,
      inoculum_dishes: row.inoculum_dishes,
      per_dish_cells: row.per_dish_cells,
      status: row.status,
      next_passage_days: row.next_passage_days,
      notes: row.notes,
    }))
    editResult.value = await recordApi.bulkUpdate(entries)
    if (!editResult.value.failed) ElMessage.success('修改已保存，累计 PD 已重算')
    await loadEditRows()
  } finally {
    savingEdits.value = false
  }
}

async function removeEditRow(row) {
  try {
    await ElMessageBox.confirm(
      `删除 ${row.cell_line} · ${row.batch_name} 的 P${row.passage}（${row.date}）记录？`,
      '删除记录',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await recordApi.remove(row.id)
  ElMessage.success('记录已删除')
  await loadEditRows()
  await loadBatchRecords()
}

async function loadBatchList() {
  batchList.value = []
  batchId.value = null
  batchRecords.value = []
  if (!batchLineId.value) return
  const data = await batchApi.list({ cell_line_id: batchLineId.value })
  batchList.value = includeEndedBatches.value ? data : data.filter((batch) => batch.is_active)
  if (batchList.value.length) {
    batchId.value = batchList.value[0].id
    await loadBatchRecords()
  }
}

async function loadBatchRecords() {
  batchRecords.value = []
  if (!batchId.value) return
  batchRecords.value = await batchApi.records(batchId.value)
}

function startEdit(row) {
  editForm.value = {
    id: row.id,
    passage: row.passage,
    date: row.date,
    harvested_cells: row.harvested_cells,
    inoculum_dishes: row.inoculum_dishes,
    per_dish_cells: row.per_dish_cells ?? 0,
    status: row.status || '良好',
    next_passage_days: 0,
    notes: row.notes || '',
  }
  editVisible.value = true
}

async function saveRecord() {
  if (!editForm.value) return
  savingRecord.value = true
  try {
    await recordApi.update(editForm.value.id, editForm.value)
    ElMessage.success('记录已更新，累计 PD 已重算')
    editVisible.value = false
    await loadBatchRecords()
    await loadEditRows()
  } finally {
    savingRecord.value = false
  }
}

async function removeRecord(row) {
  try {
    await ElMessageBox.confirm(
      `删除 P${row.passage}（${row.date}）这条记录？删除后会重算整批累计 PD。`,
      '删除传代记录',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await recordApi.remove(row.id)
  ElMessage.success('记录已删除')
  await loadBatchRecords()
  await loadEditRows()
}

async function onTabChange(name) {
  if (name === 'batch' && batchLineId.value && !batchList.value.length) await loadBatchList()
}

onMounted(async () => {
  const [groupList, lineList] = await Promise.all([groupApi.list(), lineApi.list()])
  groups.value = groupList
  lines.value = lineList
  const withActivity = groupList.find((group) =>
    (group.members || []).some((member) => member.active_batch_count > 0),
  )
  editGroupId.value = withActivity?.id || groupList[0]?.id || null
  if (editGroupId.value) await loadEditRows()

  const withBatches = lineList.find((line) => line.active_batch_count > 0)
  batchLineId.value = withBatches?.id || lineList[0]?.id || null
  if (batchLineId.value) await loadBatchList()
})
</script>

<style scoped>
.records-tabs {
  padding: 0 18px 4px;
}

.pane-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 0 14px;
}

.pane-body {
  padding-bottom: 16px;
}

.pane-hint {
  margin-top: 10px;
  font-size: 12px;
  color: var(--ct-faint);
}
</style>
