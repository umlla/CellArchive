<template>
  <div class="panel">
    <div class="panel-head">
      <div>
        <h2>冻存管管理</h2>
        <p class="sub">共 {{ boxes.length }} 个冻存盒 · 9×9 孔位，点击孔位可查看或添加冻存管</p>
      </div>
      <div class="row" style="gap: 10px">
        <!-- 待填位置数量常驻显示，切到任何页签都看得到 -->
        <el-button
          v-if="pendingCount"
          size="small"
          type="warning"
          plain
          @click="showUnplaced"
        >
          {{ pendingCount }} 支待录入位置
        </el-button>
        <span v-else class="small faint">位置已全部录入</span>
        <el-button type="primary" @click="openAdd()">
          <el-icon><Plus /></el-icon>添加冻存管
        </el-button>
      </div>
    </div>

    <el-tabs v-model="tab" class="vial-tabs" @tab-change="onTabChange">
      <!-- ==================== 网格视图 ==================== -->
      <el-tab-pane label="冻存盒视图" name="grid">
        <div class="box-toolbar" style="padding: 6px 0 14px">
          <el-select v-model="selectedBox" placeholder="选择冻存盒" style="width: 260px" filterable @change="loadBox">
            <el-option v-for="box in boxes" :key="box.box" :label="`${box.box}（${box.occupied}/${box.capacity}）`" :value="box.box" />
          </el-select>
          <span v-if="boxDetail" class="small muted">
            已占用 {{ boxDetail.occupied }} 孔 · 空闲 {{ boxDetail.capacity - boxDetail.occupied }} 孔
          </span>
          <div style="margin-left: auto" class="row">
            <span class="legend"><i class="dot in-stock" />在库</span>
            <span class="legend"><i class="dot revived" />已复苏</span>
            <span class="legend"><i class="dot discarded" />已丢弃</span>
            <el-button v-if="selectedBox" size="small" type="danger" plain @click="clearBox">清空本盒</el-button>
          </div>
        </div>

        <div v-if="boxDetail" class="grid-scroll">
          <VialGrid :detail="boxDetail" @hole-click="onHoleClick" />
        </div>
        <div v-else class="empty-hint">
          <span class="icon">🧊</span>还没有冻存盒。添加冻存管时填写「罐A/架1/盒1/A1」这样的位置即可自动生成盒子。
        </div>
      </el-tab-pane>

      <!-- ==================== 搜索编辑 ==================== -->
      <el-tab-pane label="搜索编辑" name="search">
        <div class="filter-bar" style="padding: 6px 0 14px">
          <el-input v-model="query" placeholder="搜索细胞名 / 位置 / 备注" clearable class="search-input" @keyup.enter="searchVials">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button @click="searchVials">搜索</el-button>
          <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 120px" @change="searchVials">
            <el-option label="在库" value="在库" />
            <el-option label="已复苏" value="已复苏" />
            <el-option label="已丢弃" value="已丢弃" />
          </el-select>
          <el-checkbox v-model="onlyUnplaced" @change="searchVials">仅看未填位置</el-checkbox>
          <span class="small faint">显示 {{ searchResults.length }} 条，最多 500 条</span>
        </div>

        <el-table
          :data="searchResults"
          size="small"
          max-height="560"
          class="vial-table"
          @row-click="openEdit"
        >
          <el-table-column label="位置" min-width="170" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.location">{{ row.location }}</span>
              <span v-else class="unplaced-tag">未填写（点击编辑补位置）</span>
            </template>
          </el-table-column>
          <el-table-column prop="cell_name" label="细胞株" min-width="120" />
          <el-table-column prop="freeze_date" label="冻存日期" width="108" />
          <el-table-column label="细胞数" width="100" align="right">
            <template #default="{ row }">{{ fmtNum(row.cell_count) }}</template>
          </el-table-column>
          <el-table-column label="PD" width="70" align="right">
            <template #default="{ row }">{{ row.pd ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="88" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.status)" effect="light">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="notes" label="备注" min-width="120" show-overflow-tooltip />
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <!-- 整行可点即编辑，按钮需阻止冒泡，避免点删除时同时弹出编辑框 -->
              <el-button link type="primary" size="small" @click.stop="openEdit(row)">编辑</el-button>
              <el-button link type="danger" size="small" @click.stop="removeVial(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ==================== 导入 Excel ==================== -->
      <el-tab-pane label="导入 Excel" name="import">
        <div class="import-layout">
          <div class="import-form">
            <div class="dialog-section-title">上传规则</div>
            <ul class="rule-list">
              <li>每个 <b>Sheet</b> 代表一个冻存盒，Sheet 名即盒名（例如 <code>罐A-架1-盒1</code>）。</li>
              <li>在 <b>A1:I9</b> 范围内填写 9×9 孔位，一格可多行：细胞名称 / 细胞数 / PD / 冻存日期 / 复苏日期。</li>
              <li>支持 <code>5.1X10^5</code>、<code>PD=10.26</code>、<code>2022.4.15</code> 等写法。</li>
              <li>出现复苏日期即标记为「已复苏」；不存在的细胞株会自动创建。</li>
            </ul>

            <el-radio-group v-model="importMode" style="margin: 10px 0 16px">
              <el-radio value="append">追加（跳过已有孔位）</el-radio>
              <el-radio value="replace">覆盖（先清空该盒）</el-radio>
            </el-radio-group>

            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :limit="1"
              accept=".xlsx"
              :on-change="onFileChange"
              :on-remove="resetImportFile"
              drag
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">把 .xlsx 文件拖到这里，或 <em>点击选择</em></div>
            </el-upload>

            <div class="row" style="margin-top: 14px">
              <el-button type="primary" :loading="importing" :disabled="!importFile" @click="submitImport">开始导入</el-button>
              <span class="small faint">导入前建议先下载数据库备份</span>
            </div>
          </div>

          <div class="import-result">
            <div class="dialog-section-title">导入结果</div>
            <div v-if="importResult">
              <el-alert :type="importResult.errors?.length ? 'warning' : 'success'" :closable="false" show-icon>
                <template #title>
                  成功 {{ importResult.inserted }} 条，跳过 {{ importResult.skipped }} 条
                  <template v-if="importResult.errors?.length">，错误 {{ importResult.errors.length }} 条</template>
                </template>
              </el-alert>
              <div v-if="importResult.boxes?.length" class="box-report">
                <div v-for="box in importResult.boxes" :key="box.box" class="box-report-row">
                  <span>{{ box.box }}</span>
                  <span class="small faint">新增 {{ box.inserted }} · 跳过 {{ box.skipped }}</span>
                </div>
              </div>
              <div v-if="importResult.lines_created?.length" class="small muted" style="margin-top: 10px">
                自动创建细胞株：{{ importResult.lines_created.join('、') }}
              </div>
              <div v-for="error in importResult.errors || []" :key="error" class="small" style="color: var(--ct-danger); margin-top: 4px">
                {{ error }}
              </div>
            </div>
            <div v-else class="small faint">上传文件并点击「开始导入」后，这里会显示每个盒子的结果。</div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 添加 / 编辑冻存管 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑冻存管' : '添加冻存管'" width="min(580px, 94vw)">
      <el-form :model="form" label-width="110px" label-position="left">
        <el-form-item label="细胞株" required>
          <el-select v-model="form.cell_line_id" filterable placeholder="选择细胞株" style="width: 100%">
            <el-option v-for="line in lines" :key="line.id" :label="line.name" :value="line.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="冻存位置">
          <el-input v-model="form.location" placeholder="格式：罐A/架1/盒1/A1，多孔位用逗号分隔" />
          <div class="form-tip">点击冻存盒空格会自动填入位置，也可一次填多个孔位（如 A1,A2,A3）</div>
        </el-form-item>
        <el-form-item v-if="!editingId" label="添加管数">
          <el-input-number v-model="form.count" :min="1" :max="81" :step="1" />
          <span class="small faint" style="margin-left: 8px">每个位置生成的管数</span>
        </el-form-item>
        <el-form-item label="冻存日期">
          <el-date-picker v-model="form.freeze_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="每管细胞数">
          <el-input v-model="form.cell_count" placeholder="可留空，例如 5.1X10^5" />
        </el-form-item>
        <el-form-item label="冻存时 PD">
          <el-input v-model="form.pd" placeholder="可留空" />
        </el-form-item>
        <el-form-item v-if="editingId" label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="在库" value="在库" />
            <el-option label="已复苏" value="已复苏" />
            <el-option label="已丢弃" value="已丢弃" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="row between" style="width: 100%">
          <el-button v-if="editingId" type="danger" plain @click="removeCurrent">删除这支</el-button>
          <span v-else />
          <div class="row">
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="saving" @click="saveVial">{{ editingId ? '保存' : '添加' }}</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { lineApi, vialApi } from '../api'
import { fmtNum, statusTagType, todayISO } from '../utils'
import VialGrid from '../components/VialGrid.vue'

const route = useRoute()
const tab = ref('grid')
const lines = ref([])
const boxes = ref([])
const selectedBox = ref(null)
const boxDetail = ref(null)
const pendingCount = ref(0)

const query = ref('')
const statusFilter = ref('')
const onlyUnplaced = ref(false)
const searchResults = ref([])

const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)
const form = ref(emptyForm())

const importMode = ref('append')
const importFile = ref(null)
const importing = ref(false)
const importResult = ref(null)
const uploadRef = ref(null)

function emptyForm() {
  return {
    cell_line_id: null,
    location: '',
    count: 1,
    freeze_date: todayISO(),
    cell_count: '',
    pd: '',
    status: '在库',
    notes: '',
  }
}

async function loadBoxes(keepSelection = true) {
  boxes.value = await vialApi.boxes()
  const pending = await vialApi.list({ unplaced: true, limit: 2000 })
  pendingCount.value = pending.length
  const names = boxes.value.map((box) => box.box)
  if (!keepSelection || !names.includes(selectedBox.value)) {
    selectedBox.value = names[0] || null
  }
  if (selectedBox.value) {
    await loadBox()
  } else {
    boxDetail.value = null
  }
}

async function loadBox() {
  if (!selectedBox.value) {
    boxDetail.value = null
    return
  }
  boxDetail.value = await vialApi.box(selectedBox.value)
}

async function searchVials() {
  searchResults.value = await vialApi.list({
    q: query.value || undefined,
    status: statusFilter.value || undefined,
    unplaced: onlyUnplaced.value || undefined,
    limit: 500,
  })
}

async function showUnplaced() {
  tab.value = 'search'
  onlyUnplaced.value = true
  await searchVials()
}

function openAdd(hole) {
  editingId.value = null
  form.value = emptyForm()
  form.value.cell_line_id = lines.value[0]?.id || null
  if (hole) form.value.location = `${selectedBox.value}/${hole}`
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.value = {
    cell_line_id: row.cell_line_id,
    location: row.location || '',
    count: 1,
    freeze_date: row.freeze_date || todayISO(),
    cell_count: row.cell_count === null || row.cell_count === undefined ? '' : String(row.cell_count),
    pd: row.pd === null || row.pd === undefined ? '' : String(row.pd),
    status: row.status || '在库',
    notes: row.notes || '',
  }
  dialogVisible.value = true
}

function onHoleClick({ hole, vial }) {
  if (vial) {
    openEdit(vial)
  } else {
    openAdd(hole)
  }
}

function toNumberOrNull(value) {
  if (value === '' || value === null || value === undefined) return null
  const parsed = Number(String(value).replaceAll(',', ''))
  return Number.isNaN(parsed) ? null : parsed
}

async function saveVial() {
  if (!form.value.cell_line_id) {
    ElMessage.warning('请选择细胞株')
    return
  }
  saving.value = true
  try {
    const payload = {
      cell_line_id: form.value.cell_line_id,
      location: form.value.location,
      freeze_date: form.value.freeze_date,
      cell_count: toNumberOrNull(form.value.cell_count),
      pd: toNumberOrNull(form.value.pd),
      notes: form.value.notes,
    }
    if (editingId.value) {
      await vialApi.update(editingId.value, { ...payload, status: form.value.status })
      ElMessage.success('冻存管已更新')
    } else {
      await vialApi.create({ ...payload, count: form.value.count })
      ElMessage.success('冻存管已添加')
    }
    dialogVisible.value = false
    if (tab.value === 'search') await searchVials()
    await loadBoxes()
  } finally {
    saving.value = false
  }
}

async function removeCurrent() {
  const id = editingId.value
  dialogVisible.value = false
  await confirmRemove({ id, location: form.value.location })
}

async function removeVial(row) {
  await confirmRemove(row)
}

async function confirmRemove(row) {
  try {
    await ElMessageBox.confirm(
      `删除位置「${row.location || '未填写'}」的冻存管？此操作不可恢复。`,
      '删除冻存管',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await vialApi.remove(row.id)
  ElMessage.success('冻存管已删除')
  if (tab.value === 'search') await searchVials()
  await loadBoxes()
}

async function clearBox() {
  try {
    await ElMessageBox.confirm(
      `清空冻存盒「${selectedBox.value}」中的全部冻存管？此操作不可恢复。`,
      '清空冻存盒',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const result = await vialApi.clearBox(selectedBox.value)
  ElMessage.success(`已删除 ${result.deleted} 支冻存管`)
  await loadBoxes()
}

function onFileChange(file) {
  importFile.value = file.raw
  importResult.value = null
}

function resetImportFile() {
  importFile.value = null
}

async function submitImport() {
  if (!importFile.value) return
  importing.value = true
  try {
    const formData = new FormData()
    formData.append('file', importFile.value)
    formData.append('mode', importMode.value)
    importResult.value = await vialApi.import(formData)
    ElMessage.success(`导入完成：新增 ${importResult.value.inserted} 条`)
    uploadRef.value?.clearFiles()
    importFile.value = null
    await loadBoxes(false)
  } finally {
    importing.value = false
  }
}

async function onTabChange(name) {
  if (name === 'search') await searchVials()
  if (name === 'grid') await loadBoxes()
}

onMounted(async () => {
  lines.value = await lineApi.list()
  await loadBoxes(false)
  if (route.query.unplaced) {
    tab.value = 'search'
    onlyUnplaced.value = true
    // 从首页「待录入位置」卡片跳来时，口径限定在库（卡片只统计在库的管）
    if (route.query.status) statusFilter.value = String(route.query.status)
    await searchVials()
  }
})
</script>

<style scoped>
.vial-tabs {
  padding: 0 18px 4px;
}

.legend {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--ct-muted);
  margin-right: 10px;
}

.unplaced-tag {
  color: var(--ct-warning);
  font-size: 12px;
}

/* 整行可点即编辑：手型光标 + 悬停高亮，让「能点」一眼可见 */
.vial-table :deep(.el-table__body tr) {
  cursor: pointer;
}

.vial-table :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: var(--ct-primary-soft, #eef7f5);
}

.legend .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.dot.in-stock { background: #12805c; }
.dot.revived { background: #c47f17; }
.dot.discarded { background: #adb5bd; }

.import-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  gap: 26px;
  padding: 6px 0 18px;
}

.rule-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 1.8;
  color: var(--ct-muted);
}

.rule-list code {
  background: #f2f7f6;
  padding: 1px 5px;
  border-radius: 5px;
  font-size: 11.5px;
}

.import-result {
  border-left: 1px solid var(--ct-border);
  padding-left: 22px;
}

.box-report {
  margin-top: 10px;
  border: 1px solid var(--ct-border);
  border-radius: 9px;
  overflow: hidden;
}

.box-report-row {
  display: flex;
  justify-content: space-between;
  padding: 7px 10px;
  font-size: 12px;
  border-bottom: 1px solid var(--ct-border);
}

.box-report-row:last-child {
  border-bottom: none;
}

@media (max-width: 900px) {
  .import-layout {
    grid-template-columns: 1fr;
  }
  .import-result {
    border-left: 0;
    border-top: 1px solid var(--ct-border);
    padding-left: 0;
    padding-top: 14px;
  }
}
</style>
