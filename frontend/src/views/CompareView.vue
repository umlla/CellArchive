<template>
  <div class="panel">
    <div class="panel-head">
      <div>
        <h2>生长曲线对比</h2>
        <p class="sub">任选多个细胞株，把它们的生长曲线放在同一张图里比较</p>
      </div>
      <div class="row">
        <el-button size="small" :disabled="!selectedLineIds.length" @click="selectAll">全选</el-button>
        <el-button size="small" :disabled="!selectedLineIds.length" @click="selectedLineIds = []">清空</el-button>
      </div>
    </div>

    <div class="compare-layout">
      <aside class="line-picker">
        <el-input v-model="search" placeholder="搜索细胞株" clearable size="default">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div class="picker-list">
          <label
            v-for="line in filteredLines"
            :key="line.id"
            :class="['picker-item', { active: selectedLineIds.includes(line.id) }]"
            :title="line.name"
          >
            <el-checkbox :model-value="selectedLineIds.includes(line.id)" @change="toggleLine(line.id)" />
            <i class="swatch" :style="{ background: lineColor(line.id) }" />
            <!-- 名称独占一行、完整显示；物种与批次数移到第二行，不再挤压名字 -->
            <span class="picker-text">
              <span class="picker-name">{{ line.name }}</span>
              <span class="picker-meta">
                <span v-if="line.species" class="picker-species">{{ line.species }}</span>
                <span class="small faint">{{ line.active_batch_count }} 批</span>
              </span>
            </span>
          </label>
          <div v-if="!filteredLines.length" class="empty-hint" style="padding: 22px 12px">
            <span class="icon">🧫</span>没有匹配的细胞株
          </div>
        </div>
      </aside>

      <section class="compare-main">
        <div class="toolbar">
          <span class="small muted">已选 {{ selectedLineIds.length }} 个细胞株</span>
          <div class="row" style="margin-left: auto; gap: 14px; flex-wrap: wrap">
            <el-checkbox v-model="includeEnded" @change="loadCurves">包含已终止批次</el-checkbox>
            <el-checkbox v-model="normalize" @change="onNormalizeChange">
              标准化（扩增倍数 2^ΔPD）
            </el-checkbox>
            <el-select
              v-if="normalize"
              v-model="startDate"
              placeholder="基准日期"
              size="small"
              style="width: 150px"
              @change="loadCurves"
            >
              <el-option v-for="day in curves.dates || []" :key="day" :label="day" :value="day" />
            </el-select>
            <el-radio-group v-model="basis" size="small" @change="loadCurves">
              <el-radio-button value="date">按日期</el-radio-button>
              <el-radio-button value="elapsed">按培养天数</el-radio-button>
            </el-radio-group>
            <el-radio-group v-model="metric" size="small">
              <el-radio-button v-for="item in compareMetrics" :key="item.value" :value="item.value">
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
            <el-button size="small" type="primary" :disabled="!selectedLineIds.length" :loading="loading" @click="loadCurves">
              刷新
            </el-button>
          </div>
        </div>

        <div v-if="!selectedLineIds.length" class="empty-hint" style="padding: 60px 20px">
          <span class="icon">📈</span>从左侧勾选要对比的细胞株
        </div>
        <template v-else>
          <Chart v-if="curves.series?.length" :option="chartOption" height="440px" />
          <div v-else class="empty-hint" style="padding: 60px 20px">
            <span class="icon">📈</span>{{ loading ? '加载中…' : '所选细胞株还没有可用的传代记录' }}
          </div>

          <div v-if="normalize" class="small faint" style="margin-top: 8px">
            标准化：以各批次在 {{ startDate || '基准日' }} 或之后最近一条记录为基准，
            纵轴为相对基准点的扩增倍数 2^(ΔPD)，起点均为 1 倍，可直接比较增速。
          </div>

          <div v-if="curves.skipped?.length" class="small faint" style="margin-top: 8px">
            未参与对比：{{ curves.skipped.map((item) => `${item.name}（${item.reason}）`).join('；') }}
          </div>

          <div v-if="summaryRows.length" class="summary">
            <div class="dialog-section-title">对比数据</div>
            <el-table :data="summaryRows" size="small" max-height="260">
              <el-table-column label="细胞株" min-width="140">
                <template #default="{ row }">
                  <span class="line-label">
                    <i class="swatch" :style="{ background: row.color }" />
                    {{ row.cell_line }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="标签" width="86">
                <template #default="{ row }">{{ row.species || '—' }}</template>
              </el-table-column>
              <el-table-column prop="batch_name" label="批次" min-width="180">
                <template #default="{ row }">
                  <!-- 批次名是区分同株不同批次的关键，换行显示而不截断 -->
                  <span class="cell-wrap">{{ row.batch_name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="记录数" width="80" align="center">
                <template #default="{ row }">{{ row.records }}</template>
              </el-table-column>
              <el-table-column prop="first_date" label="首条记录" width="106" />
              <el-table-column prop="last_date" label="最近记录" width="106" />
              <el-table-column label="培养天数" width="90" align="right">
                <template #default="{ row }">{{ row.days }}</template>
              </el-table-column>
              <el-table-column label="累计 PD" width="86" align="right">
                <template #default="{ row }">{{ fmtNum(row.cumulative_pd) }}</template>
              </el-table-column>
              <el-table-column label="平均 PD/天" width="98" align="right">
                <template #default="{ row }">{{ row.avg_pd_per_day }}</template>
              </el-table-column>
              <el-table-column label="平均倍增时间" width="110" align="right">
                <template #default="{ row }">
                  {{ row.avg_doubling_hours === null ? '—' : `${row.avg_doubling_hours} h` }}
                </template>
              </el-table-column>
              <el-table-column label="整段 PD/天" width="100" align="right">
                <template #default="{ row }">{{ row.overall_pd_per_day ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="整段倍增时间" width="118" align="right">
                <template #default="{ row }">
                  {{ row.overall_doubling_hours === null ? '—' : `${row.overall_doubling_hours} h` }}
                </template>
              </el-table-column>
              <el-table-column label="状态" width="80" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.ended ? 'info' : 'success'" effect="plain">
                    {{ row.ended ? '已终止' : '在养' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { compareApi, lineApi } from '../api'
import { compareCurvesOption, compareMetrics, lineColor } from '../charts'
import { loadMeta } from '../store'
import { fmtNum } from '../utils'
import Chart from '../components/Chart.vue'

const route = useRoute()
const lines = ref([])
const search = ref('')
const selectedLineIds = ref([])
const includeEnded = ref(false)
const normalize = ref(false)
const startDate = ref(null)
const basis = ref('date')
const metric = ref('cumulative')
const loading = ref(false)
const curves = ref({ series: [], dates: [], skipped: [], normalize: false, basis: 'date' })

const filteredLines = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  const list = keyword
    ? lines.value.filter((line) => line.name.toLowerCase().includes(keyword))
    : lines.value
  return [...list].sort((a, b) => (b.active_batch_count || 0) - (a.active_batch_count || 0))
})

const chartOption = computed(() => compareCurvesOption(curves.value, metric.value))

const summaryRows = computed(() =>
  (curves.value.series || []).map((item) => {
    const points = item.points || []
    const first = points[0]
    const last = points[points.length - 1]
    const days = first && last ? Math.max(0, last.day) : 0
    return {
      cell_line: item.cell_line,
      species: item.species,
      color: item.color,
      batch_name: item.batch_name,
      records: points.length,
      first_date: first?.date || '—',
      last_date: last?.date || '—',
      days,
      cumulative_pd: last?.cumulative_pd ?? null,
      avg_pd_per_day: item.avg_pd_per_day ?? '—',
      avg_doubling_hours: item.avg_doubling_hours ?? null,
      overall_pd_per_day: item.overall_pd_per_day ?? null,
      overall_doubling_hours: item.overall_doubling_hours ?? null,
      ended: item.ended,
    }
  }),
)

function toggleLine(id) {
  const index = selectedLineIds.value.indexOf(id)
  if (index >= 0) selectedLineIds.value.splice(index, 1)
  else selectedLineIds.value.push(id)
}

function selectAll() {
  selectedLineIds.value = filteredLines.value.map((line) => line.id)
}

function onNormalizeChange(value) {
  if (value && !startDate.value) startDate.value = curves.value.dates?.[0] || null
  loadCurves()
}

async function loadCurves() {
  if (!selectedLineIds.value.length) {
    curves.value = { series: [], dates: [], skipped: [], normalize: false, basis: basis.value }
    return
  }
  if (normalize.value && !startDate.value) {
    startDate.value = curves.value.dates?.[0] || null
    if (!startDate.value) {
      curves.value = { ...curves.value, series: [], skipped: [] }
      return
    }
  }
  loading.value = true
  try {
    curves.value = await compareApi.curves({
      line_ids: selectedLineIds.value.join(','),
      include_ended: includeEnded.value,
      normalize: normalize.value,
      start_date: normalize.value ? startDate.value : undefined,
      basis: basis.value,
    })
  } finally {
    loading.value = false
  }
}

watch(selectedLineIds, loadCurves, { deep: true })

onMounted(async () => {
  await loadMeta()
  lines.value = await lineApi.list()
  const fromQuery = String(route.query.lines || '')
    .split(',')
    .map((value) => Number(value))
    .filter((value) => Number.isInteger(value) && value > 0)
  if (fromQuery.length) {
    selectedLineIds.value = fromQuery.filter((id) => lines.value.some((line) => line.id === id))
  } else {
    selectedLineIds.value = lines.value
      .filter((line) => line.active_batch_count > 0)
      .slice(0, 3)
      .map((line) => line.id)
  }
  await loadCurves()
})
</script>

<style scoped>
.compare-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  min-height: 520px;
}

.line-picker {
  border-right: 1px solid var(--ct-border);
  padding: 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.picker-list {
  overflow-y: auto;
  max-height: 620px;
}

.picker-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 9px;
  cursor: pointer;
}

.picker-item :deep(.el-checkbox) {
  height: 18px;
  margin-top: 1px;
}

.picker-item .swatch {
  margin-top: 5px;
}

.picker-item:hover {
  background: #f4f9f8;
}

.picker-item.active {
  background: var(--ct-primary-soft);
}

.picker-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
}

/* 细胞株名必须完整可读：允许换行，不做省略号截断 */
.picker-name {
  font-size: 13px;
  line-height: 18px;
  word-break: break-all;
  overflow-wrap: anywhere;
}

.picker-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  line-height: 16px;
}

/* 物种小标签：同物种共用色系，便于一眼分辨分组 */
.picker-species {
  font-size: 11px;
  padding: 0 6px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  line-height: 17px;
  white-space: nowrap;
}

.swatch {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: none;
  display: inline-block;
}

.line-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* 表格内长名称换行完整显示，不用省略号 */
.cell-wrap {
  word-break: break-all;
  overflow-wrap: anywhere;
  line-height: 1.45;
}

.compare-main {
  min-width: 0;
  padding: 14px 18px 20px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.summary {
  margin-top: 18px;
  border-top: 1px solid var(--ct-border);
  padding-top: 12px;
}

@media (max-width: 1000px) {
  .compare-layout {
    grid-template-columns: 1fr;
  }
  .line-picker {
    border-right: 0;
    border-bottom: 1px solid var(--ct-border);
  }
  .picker-list {
    max-height: 220px;
  }
}
</style>
