<template>
  <div class="batch-card" :class="{ 'is-ended': !batch.is_active }">
    <div class="bc-head">
      <div style="min-width: 0">
        <div class="bc-title">
          <span class="ellipsis">{{ batch.batch_name }}</span>
          <el-tag v-if="current" size="small" type="info" effect="plain">P{{ current.passage }}</el-tag>
          <el-tag v-if="current" size="small" :type="statusTagType(current.status)" effect="light">
            {{ current.status }}
          </el-tag>
          <el-tag v-if="!batch.is_active" size="small" type="danger" effect="plain">已终止</el-tag>
        </div>
        <div class="small faint" style="margin-top: 4px">
          复苏 {{ batch.revival_date || '—' }}
          <template v-if="batch.source_freeze_date"> · 来源冻存 {{ batch.source_freeze_date }}</template>
          <template v-if="!batch.is_active"> · {{ batch.end_date }} {{ batch.end_reason }}</template>
        </div>
      </div>
      <el-dropdown trigger="click" @command="onCommand">
        <el-button text circle>
          <el-icon><MoreFilled /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-if="batch.is_active" command="record">录入传代</el-dropdown-item>
            <el-dropdown-item command="detail">记录与曲线</el-dropdown-item>
            <el-dropdown-item command="csv">导出 CSV</el-dropdown-item>
            <el-dropdown-item v-if="batch.is_active" command="terminate" divided>终止批次</el-dropdown-item>
            <el-dropdown-item v-else command="restore" divided>撤销终止</el-dropdown-item>
            <el-dropdown-item command="delete" divided>删除批次</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div v-if="current" class="bc-meta">
      <div class="bc-metric">
        <div class="k">盘数</div>
        <div class="v">{{ current.inoculum_dishes ?? '—' }}</div>
      </div>
      <div class="bc-metric">
        <div class="k">细胞总数</div>
        <div class="v">{{ fmtNum(current.inoculum_cells) }}</div>
      </div>
      <div class="bc-metric">
        <div class="k">累计 PD</div>
        <div class="v">{{ fmtNum(current.cumulative_pd) }}</div>
      </div>
      <div class="bc-metric">
        <div class="k">传代次数</div>
        <div class="v">P{{ current.passage }}</div>
      </div>
    </div>
    <div v-else class="small faint" style="padding: 12px 0">
      暂无传代记录
    </div>

    <div class="bc-foot">
      <span v-if="!batch.is_active" class="small faint">
        <template v-if="current">最后传代 {{ current.date }} · </template>已终止，不再计算传代逾期
      </span>
      <span v-else-if="current && current.next_passage_date" class="small">
        <span class="faint">建议传代</span>
        <span class="num">{{ current.next_passage_date }}</span>
        <span :class="['remaining-dot', remaining.type]" style="margin-left: 8px">{{ remaining.text }}</span>
      </span>
      <span v-else-if="current" class="small faint">尚未设置下次传代日期</span>
      <span v-else class="small faint">批次已建立，等待首次传代</span>
      <div class="row">
        <el-button v-if="!batch.is_active" size="small" type="primary" plain @click="restoreBatch">
          撤销终止
        </el-button>
        <el-button v-if="batch.is_active" size="small" type="primary" @click="emit('record', batch)">
          录入传代
        </el-button>
        <el-button size="small" @click="openDetail">记录与曲线</el-button>
        <el-button
          v-if="batch.is_active"
          size="small"
          type="danger"
          plain
          @click="terminateVisible = true"
        >
          终止
        </el-button>
      </div>
    </div>

    <!-- 记录与生长曲线 -->
    <el-dialog
      v-model="detailVisible"
      :title="`${batch.batch_name} · 传代记录`"
      width="min(980px, 94vw)"
      top="5vh"
      @open="loadDetail"
    >
      <div v-loading="detailLoading">
        <div class="row wrap" style="gap: 18px; margin-bottom: 12px">
          <span class="small muted">记录 <b class="num">{{ detail?.summary?.records_count ?? 0 }}</b> 条</span>
          <span class="small muted">累计 PD <b class="num">{{ fmtNum(detail?.summary?.cumulative_pd) }}</b></span>
          <span class="small muted">状态 <b>{{ current?.status || '—' }}</b></span>
          <span class="small muted">复苏 {{ batch.revival_date || '—' }}</span>
        </div>

        <Chart v-if="records.length" :option="growthOption" height="300px" />
        <div v-else class="empty-hint">
          <span class="icon">📈</span>还没有传代记录，录入后即可查看生长曲线
        </div>

        <el-table :data="records" size="small" style="margin-top: 14px" max-height="320">
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
          <el-table-column prop="notes" label="备注" min-width="90" show-overflow-tooltip />
          <el-table-column label="操作" width="96" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="startEdit(row)">编辑</el-button>
              <el-button link type="danger" size="small" @click="removeRecord(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <div class="row between">
          <el-button size="small" :disabled="!records.length" @click="downloadUrl(batchApi.csvUrl(batch.id))">
            导出 CSV
          </el-button>
          <el-button @click="detailVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 编辑单条记录 -->
    <el-dialog v-model="editVisible" title="编辑传代记录" width="min(560px, 94vw)" append-to-body>
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
          <el-input-number v-model="editForm.inoculum_dishes" :min="1" :step="1" :precision="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="每盘细胞数">
          <el-input-number v-model="editForm.per_dish_cells" :min="0" :step="0.01" :precision="2" style="width: 100%" />
          <div class="form-tip">填 8 就是 8，不会被自动改成 8.01</div>
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
        <el-button type="primary" :loading="saving" @click="saveRecord">保存并重算 PD</el-button>
      </template>
    </el-dialog>

    <!-- 终止批次 -->
    <el-dialog v-model="terminateVisible" title="终止批次" width="min(420px, 92vw)">
      <p class="muted small">终止后该批次不再出现在在养列表，所属传代记录都会标记为历史记录，可随时查看。</p>
      <el-form label-width="92px" label-position="left">
        <el-form-item label="终止原因">
          <el-select v-model="terminateReason" style="width: 100%">
            <el-option v-for="item in reasons" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="terminateVisible = false">取消</el-button>
        <el-button type="danger" :loading="terminating" @click="terminateBatch">确认终止</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { batchApi, recordApi } from '../api'
import { batchGrowthOption } from '../charts'
import { daysFromToday, downloadUrl, fmtNum, remainingMeta, statusTagType } from '../utils'
import Chart from './Chart.vue'

const props = defineProps({
  batch: { type: Object, required: true },
})
const emit = defineEmits(['refresh', 'record'])

const statusChoices = ['良好', '一般', '较差', '污染']
const reasons = ['污染', '全部冻存', '丢弃', '实验结束', '其他']

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const records = ref([])
const editVisible = ref(false)
const editForm = ref(null)
const saving = ref(false)
const terminateVisible = ref(false)
const terminateReason = ref('其他')
const terminating = ref(false)

const current = computed(() => {
  if (detail.value?.batch?.current_record) return detail.value.batch.current_record
  if (detail.value?.summary?.current_record) return detail.value.summary.current_record
  return props.batch.current_record || null
})

const remaining = computed(() => remainingMeta(daysFromToday(current.value?.next_passage_date)))

const growthOption = computed(() =>
  batchGrowthOption(records.value, props.batch.batch_name, props.batch.cell_line_id),
)

async function loadDetail() {
  detailLoading.value = true
  try {
    detail.value = await batchApi.detail(props.batch.id)
    records.value = detail.value.records || []
  } finally {
    detailLoading.value = false
  }
}

function openDetail() {
  detailVisible.value = true
}

async function onCommand(command) {
  if (command === 'record') {
    emit('record', props.batch)
  } else if (command === 'restore') {
    await restoreBatch()
  } else if (command === 'detail') {
    detailVisible.value = true
  } else if (command === 'csv') {
    downloadUrl(batchApi.csvUrl(props.batch.id))
  } else if (command === 'terminate') {
    terminateVisible.value = true
  } else if (command === 'delete') {
    try {
      await ElMessageBox.confirm(
        `删除批次「${props.batch.batch_name}」将同时永久删除其全部传代记录，且不可恢复。`,
        '删除批次',
        { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
    await batchApi.remove(props.batch.id)
    ElMessage.success('批次已删除')
    emit('refresh')
  }
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
  saving.value = true
  try {
    await recordApi.update(editForm.value.id, editForm.value)
    ElMessage.success('记录已更新，累计 PD 已重算')
    editVisible.value = false
    await loadDetail()
    emit('refresh')
  } finally {
    saving.value = false
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
  await loadDetail()
  emit('refresh')
}

async function restoreBatch() {
  try {
    await ElMessageBox.confirm(
      `撤销「${props.batch.batch_name}」的终止，恢复为在养批次？`,
      '撤销终止',
      { type: 'info', confirmButtonText: '撤销终止', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await batchApi.restore(props.batch.id)
  ElMessage.success('已恢复为在养批次')
  emit('refresh')
}

async function terminateBatch() {
  terminating.value = true
  try {
    await batchApi.terminate(props.batch.id, terminateReason.value)
    ElMessage.success('批次已终止')
    terminateVisible.value = false
    detailVisible.value = false
    emit('refresh')
  } finally {
    terminating.value = false
  }
}
</script>

<style scoped>
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
}
</style>
