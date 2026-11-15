<template>
  <div class="exp-page">
    <!-- ==================== 提醒看板 ==================== -->
    <div class="exp-board">
      <button class="board-card overdue" :class="{ active: boardFilter === 'overdue' }" @click="toggleBoard('overdue')">
        <div class="board-head">
          <span class="board-icon">⏰</span>
          <span>逾期实验</span>
          <span v-if="stats.overdue_checkpoints" class="board-badge">{{ stats.overdue_checkpoints }}</span>
        </div>
        <div class="board-value">{{ stats.overdue_experiments ?? '—' }}</div>
        <div class="board-hint">已过检查时间还没勾选</div>
        <div v-if="boardItems('overdue').length" class="board-list">
          <span v-for="item in boardItems('overdue').slice(0, 3)" :key="item.experiment_id" class="board-line">
            <b>{{ item.experiment_name }}</b>
            <em>{{ item.due_label }}</em>
          </span>
        </div>
      </button>

      <button class="board-card due" :class="{ active: boardFilter === 'today' }" @click="toggleBoard('today')">
        <div class="board-head">
          <span class="board-icon">🧫</span>
          <span>今天到点</span>
          <span v-if="stats.today_checkpoints" class="board-badge">{{ stats.today_checkpoints }}</span>
        </div>
        <div class="board-value">{{ stats.today_experiments ?? '—' }}</div>
        <div class="board-hint">24 小时内需要检查/处理</div>
        <div v-if="boardItems('today').length" class="board-list">
          <span v-for="item in boardItems('today').slice(0, 3)" :key="item.experiment_id" class="board-line">
            <b>{{ item.experiment_name }}</b>
            <em>{{ item.due_label }}</em>
          </span>
        </div>
      </button>

      <button class="board-card upcoming" :class="{ active: boardFilter === 'upcoming' }" @click="toggleBoard('upcoming')">
        <div class="board-head">
          <span class="board-icon">📅</span>
          <span>即将到点</span>
        </div>
        <div class="board-value">{{ stats.upcoming_experiments ?? '—' }}</div>
        <div class="board-hint">{{ reminders.summary?.window_days || 3 }} 天内需要处理</div>
        <div v-if="boardItems('upcoming').length" class="board-list">
          <span v-for="item in boardItems('upcoming').slice(0, 3)" :key="item.experiment_id" class="board-line">
            <b>{{ item.experiment_name }}</b>
            <em>{{ item.due_label }}</em>
          </span>
        </div>
      </button>

      <button class="board-card is-active" :class="{ active: boardFilter === 'active' }" @click="toggleBoard('active')">
        <div class="board-head">
          <span class="board-icon">🔬</span>
          <span>进行中</span>
        </div>
        <div class="board-value">{{ stats.active_experiments ?? '—' }}</div>
        <div class="board-hint">共 {{ experiments.length }} 个实验</div>
        <div class="board-list">
          <span class="board-line muted-line">点击只看进行中的实验</span>
        </div>
      </button>
    </div>

    <!-- ==================== 日程视图（月 / 周） ==================== -->
    <div class="panel">
      <div class="panel-head">
        <div>
          <h2>🗓️ 日程视图</h2>
          <p class="sub">按天查看检查与传代安排，点条目直接定位到对应实验</p>
        </div>
      </div>
      <ScheduleBoard
        ref="weekRef"
        v-model="scheduleMode"
        :max-checks="4"
        week-compact
        @open-check="onCalendarOpen"
        @open-passage="onCalendarPassage"
        @changed="onScheduleChanged"
      />
    </div>

    <!-- ==================== 列表 ==================== -->
    <div class="panel">
      <div class="panel-head" style="align-items: flex-start">
        <div>
          <h2>细胞实验日程</h2>
          <p class="sub">
            每个实验按固定间隔提醒检查时间；勾选检查完成后自动提醒下一次。
            当前时间 {{ reminders.summary?.now || '—' }}
          </p>
        </div>
        <div class="row">
          <el-button @click="refreshAll">
            <el-icon><Refresh /></el-icon>刷新
          </el-button>
          <el-button type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>新建实验
          </el-button>
        </div>
      </div>

      <div class="exp-toolbar">
        <el-input v-model="search" placeholder="搜索实验名 / 条件 / 细胞株" clearable style="width: 260px">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-radio-group v-model="statusFilter" size="default">
          <el-radio-button value="active">进行中</el-radio-button>
          <el-radio-button value="paused">已暂停</el-radio-button>
          <el-radio-button value="ended">已完成</el-radio-button>
          <el-radio-button value="all">全部</el-radio-button>
        </el-radio-group>
        <el-checkbox v-model="showDoneCheckpoints" size="small">显示已完成的检查点</el-checkbox>
        <div class="row" style="margin-left: auto; gap: 8px">
          <el-tooltip content="浏览器通知需要授权；页面关闭后不会提醒" placement="top">
            <el-button size="small" plain @click="enableBrowserNotify">
              <el-icon><Bell /></el-icon>
              {{ notifyLabel }}
            </el-button>
          </el-tooltip>
        </div>
      </div>

      <div v-if="boardFilterLabel" class="filter-chip-bar">
        <span>正在查看：{{ boardFilterLabel }}</span>
        <el-button link type="primary" size="small" @click="boardFilter = null">清除筛选</el-button>
      </div>

      <div v-loading="loading" class="exp-list">
        <div
          v-for="item in visibleExperiments"
          :key="item.id"
          class="exp-row"
          :class="[`state-${item.state}`, { selected: item.id === selectedId }]"
          @click="openDetail(item.id)"
        >
          <div class="exp-row-main">
            <div class="exp-title-line">
              <span class="exp-name">{{ item.name }}</span>
              <el-tag size="small" :type="experimentStatusMeta(item.status).type" effect="light">
                {{ experimentStatusMeta(item.status).label }}
              </el-tag>
              <el-tooltip
                v-if="item.cell_line_names?.length"
                :content="item.cell_line_names.join('、')"
                placement="top"
              >
                <el-tag size="small" effect="plain" type="info">
                  {{ item.cell_line_count > 1 ? `${item.cell_line_count} 株细胞` : item.cell_line_name }}
                </el-tag>
              </el-tooltip>
              <el-tag v-for="group in item.groups || []" :key="group.group_id" size="small" effect="plain" type="warning">
                {{ group.group_name }}
              </el-tag>
              <el-tag v-if="item.overdue_count" size="small" type="danger" effect="dark">
                逾期 {{ item.overdue_count }}
              </el-tag>
            </div>
            <div v-if="item.notes" class="exp-notes">{{ item.notes }}</div>
            <div class="exp-meta">
              <span class="meta-item">
                <el-icon><Timer /></el-icon>{{ item.interval_text }}
              </span>
              <span class="meta-item">
                <el-icon><CircleCheck /></el-icon>已检查 {{ item.done_count }} 次
              </span>
              <span v-if="item.last_done" class="meta-item faint">
                上次 {{ item.last_done.due_label }}
                <template v-if="item.last_done.cell_status">· {{ item.last_done.cell_status }}</template>
              </span>
            </div>
          </div>

          <div class="exp-row-next">
            <template v-if="item.next_checkpoint">
              <div class="next-label">{{ item.next_checkpoint.state === 'overdue' ? '已逾期' : '下次检查' }}</div>
              <div class="next-time" :class="`state-${item.next_checkpoint.state}`">
                {{ item.next_checkpoint.due_label }}
              </div>
              <div class="next-gap" :class="`state-${item.next_checkpoint.state}`">
                {{ item.next_checkpoint.gap_text }}
                <template v-if="item.pending_count > 1"> · 还有 {{ item.pending_count - 1 }} 个待办</template>
              </div>
            </template>
            <template v-else>
              <div class="next-label">没有待办</div>
              <div class="next-time faint">{{ item.status === 'active' ? '待添加时间点' : '—' }}</div>
            </template>
          </div>

          <div class="exp-row-actions" @click.stop>
            <el-button
              v-if="item.next_checkpoint"
              type="primary"
              size="small"
              @click="openComplete(item)"
            >
              <el-icon><Select /></el-icon>检查完成
            </el-button>
            <el-button size="small" text @click="openDetail(item.id)">日程</el-button>
          </div>
        </div>

        <div v-if="!loading && !visibleExperiments.length" class="empty-hint">
          <span class="icon">🧫</span>
          <template v-if="experiments.length">没有符合筛选条件的实验</template>
          <template v-else>
            还没有细胞实验。新建一个实验，设置检查间隔（如 24h、2d），到点会在首页和提醒铃里提示你。
            <div style="margin-top: 12px">
              <el-button type="primary" size="small" @click="openCreate">新建第一个实验</el-button>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- ==================== 详情抽屉 ==================== -->
    <el-drawer v-model="drawerVisible" :size="drawerSize" :with-header="false" class="exp-drawer">
      <div v-if="detail" class="detail-body">
        <div class="detail-head">
          <div style="min-width: 0">
            <div class="row" style="gap: 8px; flex-wrap: wrap">
              <h2 class="detail-title">{{ detail.name }}</h2>
              <el-tag size="small" :type="experimentStatusMeta(detail.status).type" effect="light">
                {{ experimentStatusMeta(detail.status).label }}
              </el-tag>
              <el-tag v-for="line in detail.cell_lines || []" :key="line.cell_line_id" size="small" effect="plain" type="info">
                {{ line.name }}
              </el-tag>
              <el-tag v-for="group in detail.groups || []" :key="group.group_id" size="small" effect="plain" type="warning">
                {{ group.group_name }}
              </el-tag>
            </div>
            <p class="small faint" style="margin: 6px 0 0">
              间隔 {{ detail.interval_text }} · 实验时间 {{ detail.started_at || '—' }} ·
              已检查 {{ detail.done_count }} 次 · 待办 {{ detail.pending_count }} 个
            </p>
          </div>
          <el-button text circle @click="drawerVisible = false">
            <el-icon size="18"><Close /></el-icon>
          </el-button>
        </div>

        <div v-if="detail.notes" class="detail-notes">{{ detail.notes }}</div>
        <div v-if="detail.extra_notes" class="detail-notes extra">{{ detail.extra_notes }}</div>

        <div v-if="detail.ended_at" class="detail-notes ended">
          <el-icon><CircleCheck /></el-icon>
          {{ detail.status === 'done' ? '已完成' : '已终止' }}于 {{ detail.ended_at }}
          <template v-if="detail.end_reason"> · 原因：{{ detail.end_reason }}</template>
        </div>

        <div v-if="detail.next_checkpoint" class="next-banner" :class="`state-${detail.next_checkpoint.state}`">
          <div>
            <div class="nb-label">下次需要检查</div>
            <div class="nb-time">{{ detail.next_checkpoint.due_label }}</div>
          </div>
          <div class="nb-right">
            <div class="nb-gap">{{ detail.next_checkpoint.gap_text }}</div>
            <el-button size="small" type="primary" @click="openComplete(detail)">勾选完成</el-button>
          </div>
        </div>

        <div class="detail-actions">
          <el-button size="small" @click="openEdit(detail)">
            <el-icon><Edit /></el-icon>编辑信息
          </el-button>
          <el-button size="small" @click="openAddCheckpoint">
            <el-icon><Plus /></el-icon>加一个时间点
          </el-button>
          <el-button v-if="detail.status === 'active'" size="small" type="warning" plain @click="setStatus('paused')">
            <el-icon><VideoPause /></el-icon>暂停提醒
          </el-button>
          <el-button v-if="detail.status === 'paused'" size="small" type="success" plain @click="setStatus('active')">
            <el-icon><VideoPlay /></el-icon>恢复提醒
          </el-button>
          <el-button v-if="detail.status === 'active' || detail.status === 'paused'" size="small" plain @click="finishExperiment('done')">
            <el-icon><CircleCheck /></el-icon>标记完成
          </el-button>
          <el-button v-if="detail.status === 'active' || detail.status === 'paused'" size="small" plain @click="finishExperiment('aborted')">
            终止实验
          </el-button>
          <el-button v-if="detail.status === 'done' || detail.status === 'aborted'" size="small" type="primary" plain @click="setStatus('active')">
            重新开始
          </el-button>
          <el-button size="small" type="danger" plain @click="removeExperiment">
            <el-icon><Delete /></el-icon>删除
          </el-button>
        </div>

        <div class="timeline-head">
          <h3>日程时间轴</h3>
          <div class="row" style="gap: 10px">
            <el-checkbox v-model="showDoneCheckpoints" size="small">显示已完成</el-checkbox>
            <span class="small faint">共 {{ timeline.length }} 个时间点</span>
          </div>
        </div>

        <div class="timeline">
          <div
            v-for="checkpoint in timeline"
            :key="checkpoint.id"
            class="tl-item"
            :class="[`state-${checkpoint.state}`, { focused: checkpoint.id === focusedCheckpointId }]"
          >
            <div class="tl-axis">
              <span class="tl-dot" />
              <span class="tl-line" />
            </div>
            <div class="tl-body">
              <div class="tl-top">
                <el-checkbox
                  :model-value="!!checkpoint.done"
                  :disabled="checkpoint.done || completingId === checkpoint.id"
                  class="tl-check"
                  @change="() => toggleCheckpoint(checkpoint)"
                >
                  <span class="tl-time">{{ checkpoint.due_label }}</span>
                </el-checkbox>
                <span class="tl-relative faint">{{ checkpoint.rel_day }} · {{ checkpoint.gap_text }}</span>
                <el-tag size="small" :type="checkStateMeta(checkpoint.state).type" effect="plain">
                  {{ checkpoint.done ? '已完成' : checkStateMeta(checkpoint.state).label }}
                </el-tag>
                <el-tag v-if="checkpoint.kind !== 'schedule'" size="small" effect="plain" type="warning">
                  {{ checkpoint.kind_label }}
                </el-tag>
                <div class="tl-actions">
                  <el-tooltip content="修改这个时间点" placement="top">
                    <el-button text circle size="small" @click="openEditCheckpoint(checkpoint)">
                      <el-icon><EditPen /></el-icon>
                    </el-button>
                  </el-tooltip>
                  <el-tooltip content="删除这个时间点" placement="top">
                    <el-button text circle size="small" @click="removeCheckpoint(checkpoint)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </el-tooltip>
                </div>
              </div>
              <div v-if="checkpoint.done" class="tl-result">
                <el-tag v-if="checkpoint.cell_status" size="small" :type="statusTagType(checkpoint.cell_status)" effect="light">
                  {{ checkpoint.cell_status }}
                </el-tag>
                <span v-if="checkpoint.observation" class="tl-obs">{{ checkpoint.observation }}</span>
                <span v-if="checkpoint.done_at" class="tl-done-at">已于 {{ checkpoint.done_at }} 检查</span>
                <el-button
                  link
                  type="primary"
                  size="small"
                  @click="reopenCheckpoint(checkpoint)"
                >
                  撤销
                </el-button>
              </div>
              <!-- 实际间隔：距上次检查（或实验开始）多久，以及提前/延后了多少 -->
              <div v-if="checkpoint.done && checkpoint.actual_span_minutes !== null" class="tl-span">
                <span class="span-chip" :title="`基准：${checkpoint.actual_from}`">
                  <el-icon><Timer /></el-icon>
                  实际间隔 <b>{{ checkpoint.actual_span_text }}</b>
                  <em class="span-from">（自{{ checkpoint.actual_from }}）</em>
                </span>
                <span
                  v-if="checkpoint.deviation_text"
                  class="span-chip"
                  :class="`dev-${checkpoint.deviation_kind}`"
                >
                  {{ checkpoint.deviation_text }}
                </span>
                <span v-if="checkpoint.interval_delta_text" class="span-note">
                  {{ checkpoint.interval_delta_text }}
                </span>
              </div>
              <div v-else-if="checkpoint.notes" class="tl-result">
                <span class="tl-obs">{{ checkpoint.notes }}</span>
              </div>
            </div>
          </div>
          <div v-if="!timeline.length" class="empty-hint" style="padding: 26px">
            <span class="icon">📅</span>还没有时间点，点「加一个时间点」安排第一次检查
          </div>
        </div>
      </div>
      <div v-else class="empty-hint">
        <span class="icon">🧫</span>加载中…
      </div>
    </el-drawer>

    <!-- ==================== 弹窗 ==================== -->
    <ExperimentFormDialog
      v-model="formVisible"
      :experiment="editingExperiment"
      :lines="lines"
      :groups="groups"
      @saved="onSaved"
    />

    <CheckCompleteDialog
      v-model="completeVisible"
      :experiment="completeTarget"
      :checkpoint="completeCheckpoint"
      :cell-statuses="cellStatuses"
      @saved="onCompleted"
    />

    <el-dialog v-model="finishVisible" :title="finishForm.status === 'done' ? '结束实验' : '终止实验'" width="min(460px, 94vw)">
      <el-form label-width="88px" label-position="left">
        <el-form-item label="结束方式">
          <el-radio-group v-model="finishForm.status">
            <el-radio-button value="done">已完成</el-radio-button>
            <el-radio-button value="aborted">提前终止</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="原因">
          <el-input
            v-model="finishForm.reason"
            type="textarea"
            :rows="3"
            maxlength="200"
            show-word-limit
            placeholder="可不填。例如：结果符合预期 / 细胞污染 / 试剂不足"
          />
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" show-icon>
        结束后不再提醒，剩余的待检查时间点会被清除；已经勾选的检查记录会保留。
      </el-alert>
      <template #footer>
        <el-button @click="finishVisible = false">取消</el-button>
        <el-button type="primary" :loading="finishing" @click="submitFinish">确定结束</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="addVisible" title="加一个检查时间点" width="min(480px, 94vw)">
      <el-form label-width="104px" label-position="left">
        <el-form-item label="检查时间" required>
          <el-date-picker
            v-model="addForm.due_at"
            type="datetime"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DD HH:mm"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="此后间隔">
          <div class="row" style="gap: 8px">
            <el-switch v-model="addForm.use_interval" active-text="改用新间隔" />
            <template v-if="addForm.use_interval">
              <el-input-number v-model="addForm.interval_value" :min="0.5" :step="1" style="width: 120px" />
              <el-select v-model="addForm.interval_unit" style="width: 90px">
                <el-option label="小时" value="h" />
                <el-option label="天" value="d" />
              </el-select>
            </template>
          </div>
          <div class="form-tip">勾选后，从这个时间点往后自动补的检查点会按新间隔排列（原间隔不变）</div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="addForm.notes" maxlength="500" placeholder="可选，例如：加药后首次观察" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="submitAddCheckpoint">添加</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editCheckpointVisible" title="修改检查时间点" width="min(440px, 94vw)">
      <el-form label-width="88px" label-position="left">
        <el-form-item label="检查时间">
          <el-date-picker
            v-model="editCheckpointForm.due_at"
            type="datetime"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DD HH:mm"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editCheckpointForm.notes" maxlength="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editCheckpointVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingCheckpoint" @click="submitEditCheckpoint">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { experimentApi, groupApi, lineApi } from '../api'
import {
  browserNotifySupported,
  refreshReminders,
  reminders,
  requestNotifyPermission,
} from '../reminders'
import {
  checkStateMeta,
  defaultFirstDue,
  experimentStatusMeta,
  statusTagType,
  toLocalMinute,
} from '../utils'
import ExperimentFormDialog from '../components/ExperimentFormDialog.vue'
import CheckCompleteDialog from '../components/CheckCompleteDialog.vue'
import ScheduleBoard from '../components/ScheduleBoard.vue'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const experiments = ref([])
const lines = ref([])
const groups = ref([])
const search = ref('')
const statusFilter = ref('active')
const showDoneCheckpoints = ref(false)
const boardFilter = ref(null)

const drawerVisible = ref(false)
const detail = ref(null)
const selectedId = ref(null)
const focusedCheckpointId = ref(null)
const completingId = ref(null)
const drawerSize = ref(window.innerWidth < 900 ? '100%' : '620px')
const weekRef = ref(null)
const scheduleMode = ref(localStorage.getItem('ct.scheduleMode') === 'month' ? 'month' : 'week')

const formVisible = ref(false)
const editingExperiment = ref(null)

const completeVisible = ref(false)
const completeTarget = ref(null)
const completeCheckpoint = ref(null)

const addVisible = ref(false)
const adding = ref(false)
const addForm = reactive({
  due_at: toLocalMinute(defaultFirstDue()),
  use_interval: false,
  interval_value: 12,
  interval_unit: 'h',
  notes: '',
})

const editCheckpointVisible = ref(false)
const savingCheckpoint = ref(false)
const editCheckpointForm = reactive({ id: null, due_at: '', notes: '' })

// 结束实验（原因自填可空）
const finishVisible = ref(false)
const finishing = ref(false)
const finishForm = reactive({ status: 'done', reason: '' })

const cellStatuses = ['良好', '一般', '较差', '污染']
const stats = computed(() => reminders.summary?.stats || {})

const notifyLabel = computed(() => {
  if (!browserNotifySupported()) return '不支持浏览器通知'
  if (Notification.permission === 'granted') return '浏览器通知已开启'
  if (Notification.permission === 'denied') return '浏览器通知被拒绝'
  return '开启浏览器通知'
})

const boardFilterLabel = computed(
  () => ({ overdue: '逾期实验', today: '今天到点', upcoming: '即将到点', active: '进行中' })[boardFilter.value] || '',
)

const visibleExperiments = computed(() => {
  let rows = experiments.value
  if (statusFilter.value === 'active') rows = rows.filter((item) => item.status === 'active' || item.status === 'paused')
  else if (statusFilter.value === 'paused') rows = rows.filter((item) => item.status === 'paused')
  else if (statusFilter.value === 'ended') rows = rows.filter((item) => item.status === 'done' || item.status === 'aborted')
  const keyword = search.value.trim().toLowerCase()
  if (keyword) {
    rows = rows.filter((item) =>
      [
        item.name,
        item.notes,
        item.extra_notes,
        ...(item.cell_line_names || []),
        ...(item.groups || []).map((group) => group.group_name),
      ]
        .filter(Boolean)
        .some((text) => String(text).toLowerCase().includes(keyword)),
    )
  }
  if (boardFilter.value === 'overdue') rows = rows.filter((item) => item.state === 'overdue')
  if (boardFilter.value === 'today') rows = rows.filter((item) => item.state === 'due')
  if (boardFilter.value === 'upcoming') rows = rows.filter((item) => item.state === 'upcoming')
  if (boardFilter.value === 'active') rows = rows.filter((item) => item.status === 'active' || item.status === 'paused')
  return rows
})

const timeline = computed(() => {
  const rows = detail.value?.checkpoints || []
  if (showDoneCheckpoints.value) return rows
  const pending = rows.filter((item) => !item.done)
  const done = rows.filter((item) => item.done)
  // 未勾选「显示已完成」时，仍保留最近一次已完成的检查，方便回看细胞状况
  return done.length ? [done[done.length - 1], ...pending] : pending
})

function boardItems(kind) {
  const summary = reminders.summary
  if (!summary) return []
  if (kind === 'overdue') return summary.overdue || []
  if (kind === 'today') return summary.due_today || []
  return summary.upcoming || []
}

function toggleBoard(kind) {
  boardFilter.value = boardFilter.value === kind ? null : kind
}

async function loadList() {
  loading.value = true
  try {
    experiments.value = await experimentApi.list({ scope: 'all' })
  } finally {
    loading.value = false
  }
}

function onCalendarOpen(item) {
  openDetail(item.experiment_id, item.id)
}

// 日程里的传代待办 → 去在养细胞页定位到该细胞株
function onCalendarPassage(day) {
  const first = day.passages?.[0]
  router.push({ path: '/cells', query: first ? { line: first.cell_line_id } : {} })
}

// 在日程里勾选 / 推迟 / 删除后，列表和提醒同步刷新（日历自身已刷新）
async function onScheduleChanged() {
  await Promise.all([loadList(), refreshReminders()])
  if (selectedId.value && drawerVisible.value) await loadDetail(selectedId.value, { keepFocus: true })
}

async function refreshAll() {
  await Promise.all([loadList(), refreshReminders()])
  // 周视图与列表同源，任何操作后一起刷新
  weekRef.value?.reload()
  if (selectedId.value && drawerVisible.value) await loadDetail(selectedId.value, { keepFocus: true })
}

async function loadDetail(id, { keepFocus = false } = {}) {
  if (!keepFocus) detail.value = null
  detail.value = await experimentApi.detail(id)
  selectedId.value = id
  if (!keepFocus) focusedCheckpointId.value = null
}

async function openDetail(id, checkpointId = null) {
  drawerVisible.value = true
  await loadDetail(id)
  if (checkpointId) {
    focusedCheckpointId.value = Number(checkpointId)
  }
}

function openCreate() {
  editingExperiment.value = null
  formVisible.value = true
}

function openEdit(experiment) {
  editingExperiment.value = experiment
  formVisible.value = true
}

async function onSaved() {
  await refreshAll()
  if (selectedId.value) await loadDetail(selectedId.value, { keepFocus: true })
}

function openComplete(item) {
  const checkpoint = item.next_checkpoint || (item.checkpoints || []).find((cp) => !cp.done)
  if (!checkpoint) {
    ElMessage.warning('这个实验没有待检查的时间点')
    return
  }
  completeTarget.value = item
  completeCheckpoint.value = checkpoint
  completeVisible.value = true
}

async function onCompleted(result) {
  await refreshAll()
  if (selectedId.value) await loadDetail(selectedId.value, { keepFocus: true })
  if (result?.next_due_label) {
    ElMessage.success(`已记录检查，下次检查：${result.next_due_label}`)
  } else {
    ElMessage.success('已记录检查')
  }
}

async function toggleCheckpoint(checkpoint) {
  if (checkpoint.done) return
  // 在时间轴上直接打勾：不填状况，直接用当前时间完成
  completingId.value = checkpoint.id
  try {
    const result = await experimentApi.complete(detail.value.id, {
      checkpoint_id: checkpoint.id,
      done_at: toLocalMinute(new Date()),
    })
    await refreshAll()
    await loadDetail(detail.value.id, { keepFocus: true })
    ElMessage.success(
      result.next_due_label ? `已勾选完成，下次检查：${result.next_due_label}` : '已勾选完成',
    )
  } finally {
    completingId.value = null
  }
}

async function reopenCheckpoint(checkpoint) {
  await experimentApi.reopenCheckpoint(detail.value.id, checkpoint.id)
  await refreshAll()
  await loadDetail(detail.value.id, { keepFocus: true })
  ElMessage.success('已撤销勾选')
}

function openAddCheckpoint() {
  const last = (detail.value?.checkpoints || []).slice(-1)[0]
  const minutes =
    detail.value?.interval_unit === 'd'
      ? Number(detail.value?.interval_value) * 1440
      : detail.value?.interval_unit === 'm'
        ? Number(detail.value?.interval_value)
        : Number(detail.value?.interval_value) * 60
  const base = last ? new Date(last.due_at.replace(' ', 'T')) : new Date()
  addForm.due_at = toLocalMinute(new Date(base.getTime() + (minutes || 1440) * 60000))
  addForm.use_interval = false
  addForm.interval_value = 12
  addForm.interval_unit = 'h'
  addForm.notes = ''
  addVisible.value = true
}

async function submitAddCheckpoint() {
  adding.value = true
  try {
    const payload = { due_at: addForm.due_at, notes: addForm.notes }
    if (addForm.use_interval) {
      payload.interval_value = addForm.interval_value
      payload.interval_unit = addForm.interval_unit
    }
    await experimentApi.addCheckpoint(detail.value.id, payload)
    addVisible.value = false
    await refreshAll()
    await loadDetail(detail.value.id, { keepFocus: true })
    ElMessage.success('已添加检查时间点')
  } finally {
    adding.value = false
  }
}

function openEditCheckpoint(checkpoint) {
  editCheckpointForm.id = checkpoint.id
  editCheckpointForm.due_at = checkpoint.due_at
  editCheckpointForm.notes = checkpoint.notes || ''
  editCheckpointVisible.value = true
}

async function submitEditCheckpoint() {
  savingCheckpoint.value = true
  try {
    await experimentApi.updateCheckpoint(detail.value.id, editCheckpointForm.id, {
      due_at: editCheckpointForm.due_at,
      notes: editCheckpointForm.notes,
    })
    editCheckpointVisible.value = false
    await refreshAll()
    await loadDetail(detail.value.id, { keepFocus: true })
    ElMessage.success('时间点已更新')
  } finally {
    savingCheckpoint.value = false
  }
}

async function removeCheckpoint(checkpoint) {
  try {
    await ElMessageBox.confirm(
      `删除 ${checkpoint.due_label} 这个检查时间点？`,
      '删除时间点',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await experimentApi.removeCheckpoint(detail.value.id, checkpoint.id)
  await refreshAll()
  await loadDetail(detail.value.id, { keepFocus: true })
  ElMessage.success('时间点已删除')
}

async function setStatus(status) {
  await experimentApi.update(detail.value.id, { status })
  await refreshAll()
  await loadDetail(detail.value.id, { keepFocus: true })
  ElMessage.success(status === 'paused' ? '已暂停提醒' : '已恢复提醒')
}

function finishExperiment(status) {
  // 结束实验：原因自填可空，同时清除剩余的待检查时间点
  finishForm.status = status === 'aborted' ? 'aborted' : 'done'
  finishForm.reason = ''
  finishVisible.value = true
}

async function submitFinish() {
  if (!detail.value) return
  finishing.value = true
  try {
    const result = await experimentApi.finish(detail.value.id, {
      status: finishForm.status,
      end_reason: finishForm.reason.trim() || null,
    })
    finishVisible.value = false
    await refreshAll()
    await loadDetail(detail.value.id, { keepFocus: true })
    const removed = result.removed_checkpoints || 0
    ElMessage.success(
      `${finishForm.status === 'done' ? '实验已完成' : '实验已终止'}${removed ? `，清除 ${removed} 个待检查时间点` : ''}`,
    )
  } finally {
    finishing.value = false
  }
}

async function removeExperiment() {
  try {
    await ElMessageBox.confirm(
      `删除实验「${detail.value.name}」及其全部检查记录？此操作不可恢复。`,
      '删除实验',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await experimentApi.remove(detail.value.id)
  drawerVisible.value = false
  detail.value = null
  selectedId.value = null
  await refreshAll()
  ElMessage.success('实验已删除')
}

async function enableBrowserNotify() {
  if (!browserNotifySupported()) {
    ElMessage.info('当前浏览器不支持通知，页面内的提醒铃依然有效')
    return
  }
  const permission = await requestNotifyPermission()
  if (permission === 'granted') {
    ElMessage.success('已开启浏览器通知')
    try {
      new Notification('🧫 细胞档案提醒已开启', { body: '实验到点时会在这里提醒你' })
    } catch {
      /* 忽略 */
    }
  } else {
    ElMessage.warning('未获得通知权限，可在浏览器地址栏左侧的站点设置里允许通知')
  }
}

onMounted(async () => {
  drawerSize.value = window.innerWidth < 900 ? '100%' : '620px'
  await Promise.all([loadList(), refreshReminders()])
  // 新建实验弹窗需要细胞株 + 细胞组（按组带入成员）
  try {
    const [lineList, groupList] = await Promise.all([lineApi.list(), groupApi.list()])
    lines.value = lineList
    groups.value = groupList
  } catch {
    lines.value = []
    groups.value = []
  }
  if (route.query.new === '1') openCreate()
  const expFromQuery = Number(route.query.exp)
  if (expFromQuery) {
    await openDetail(expFromQuery, route.query.check)
  }
})

onUnmounted(() => {
  /* 轮询由 App.vue 统一管理 */
})

watch(
  () => route.query.exp,
  async (value) => {
    const id = Number(value)
    if (id && id !== selectedId.value) await openDetail(id, route.query.check)
  },
)
</script>

<style scoped>
.exp-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---------------- 看板 ---------------- */
.exp-board {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.board-card {
  text-align: left;
  font: inherit;
  background: var(--ct-surface);
  border: 1px solid var(--ct-border);
  border-radius: var(--ct-radius);
  padding: 14px 16px;
  box-shadow: var(--ct-shadow);
  cursor: pointer;
  transition: border-color 0.16s ease, transform 0.16s ease, box-shadow 0.16s ease;
  position: relative;
  overflow: hidden;
}

.board-card::after {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
  background: var(--board-color, var(--ct-primary));
  opacity: 0.85;
}

.board-card:hover {
  transform: translateY(-1px);
  border-color: var(--ct-border-strong);
}

.board-card.active {
  border-color: var(--board-color, var(--ct-primary));
  box-shadow: 0 10px 26px -20px rgba(15, 118, 110, 0.7);
}

.board-card.overdue {
  --board-color: var(--ct-danger);
}

.board-card.due {
  --board-color: var(--ct-warning);
}

.board-card.upcoming {
  --board-color: #2563eb;
}

.board-card.is-active {
  --board-color: var(--ct-primary);
}

.board-head {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--ct-muted);
}

.board-badge {
  margin-left: auto;
  background: var(--board-color, var(--ct-primary));
  color: #fff;
  border-radius: 999px;
  font-size: 11px;
  padding: 0 7px;
  line-height: 17px;
}

.board-value {
  font-size: 27px;
  font-weight: 650;
  letter-spacing: -0.02em;
  margin-top: 6px;
  font-variant-numeric: tabular-nums;
}

.board-hint {
  font-size: 11px;
  color: var(--ct-faint);
  margin-top: 2px;
}

.board-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 8px;
  border-top: 1px dashed var(--ct-border);
  padding-top: 7px;
}

.board-line {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
  color: var(--ct-muted);
  min-width: 0;
}

.board-line b {
  font-weight: 500;
  color: var(--ct-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.board-line em {
  font-style: normal;
  color: var(--board-color, var(--ct-muted));
  white-space: nowrap;
}

.muted-line {
  color: var(--ct-faint);
}

/* ---------------- 工具条 ---------------- */
.exp-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 18px;
  border-bottom: 1px solid var(--ct-border);
  background: #fbfdfc;
}

.filter-chip-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 18px;
  font-size: 12px;
  color: var(--ct-primary);
  background: var(--ct-primary-soft);
}

/* ---------------- 列表 ---------------- */
.exp-list {
  padding: 8px 12px 14px;
  min-height: 160px;
}

.exp-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 200px auto;
  gap: 18px;
  align-items: center;
  padding: 12px 14px 12px 12px;
  border-radius: 12px;
  border: 1px solid transparent;
  border-left: 3px solid var(--row-color, var(--ct-border-strong));
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.exp-row + .exp-row {
  margin-top: 4px;
}

.exp-row:hover {
  background: #f7faf9;
  border-color: var(--ct-border);
}

.exp-row.selected {
  background: var(--ct-primary-soft);
  border-color: var(--ct-primary);
}

.exp-row.state-overdue {
  --row-color: var(--ct-danger);
  background: #fff8f7;
}

.exp-row.state-due {
  --row-color: var(--ct-warning);
  background: #fffdf6;
}

.exp-row.state-upcoming {
  --row-color: #2563eb;
}

.exp-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.exp-name {
  font-size: 14.5px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.exp-notes {
  margin-top: 4px;
  font-size: 12px;
  color: var(--ct-muted);
  white-space: pre-wrap;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.exp-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--ct-faint);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.exp-row-next {
  border-left: 1px dashed var(--ct-border);
  padding-left: 16px;
  min-width: 0;
}

.next-label {
  font-size: 11px;
  color: var(--ct-faint);
}

.next-time {
  font-size: 14px;
  font-weight: 600;
  margin-top: 2px;
  font-variant-numeric: tabular-nums;
}

.next-gap {
  font-size: 11.5px;
  margin-top: 2px;
  color: var(--ct-muted);
}

.next-time.state-overdue,
.next-gap.state-overdue {
  color: var(--ct-danger);
}

.next-time.state-due,
.next-gap.state-due {
  color: var(--ct-warning);
}

.next-time.state-upcoming,
.next-gap.state-upcoming {
  color: #2563eb;
}

.exp-row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  justify-content: flex-end;
  white-space: nowrap;
}

/* ---------------- 抽屉 ---------------- */
.detail-body {
  padding: 18px 22px 30px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.detail-title {
  margin: 0;
  font-size: 19px;
  letter-spacing: -0.01em;
}

.detail-notes {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #f7faf9;
  border: 1px solid var(--ct-border);
  font-size: 12.5px;
  color: var(--ct-muted);
  white-space: pre-wrap;
  line-height: 1.7;
}

.detail-notes.extra {
  margin-top: 8px;
  background: #fffdf6;
  border-color: #f0dfb8;
}

.detail-notes.ended {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f2f7f6;
  color: var(--ct-success);
}

.next-banner {
  margin-top: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  background: var(--ct-primary-soft);
  border: 1px solid #cfe4e2;
}

.next-banner.state-overdue {
  background: #fff1f0;
  border-color: #f3c9c9;
}

.next-banner.state-due {
  background: #fffaf0;
  border-color: #f0dfb8;
}

.nb-label {
  font-size: 11px;
  color: var(--ct-faint);
}

.nb-time {
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -0.01em;
  font-variant-numeric: tabular-nums;
}

.next-banner.state-overdue .nb-time {
  color: var(--ct-danger);
}

.next-banner.state-due .nb-time {
  color: var(--ct-warning);
}

.nb-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nb-gap {
  font-size: 12px;
  color: var(--ct-muted);
}

.detail-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.timeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 24px 0 10px;
}

.timeline-head h3 {
  margin: 0;
  font-size: 14px;
}

.timeline {
  display: flex;
  flex-direction: column;
}

.tl-item {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  gap: 4px;
}

.tl-axis {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.tl-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid var(--ct-border-strong);
  background: #fff;
  margin-top: 7px;
  flex: none;
}

.tl-item.state-overdue .tl-dot {
  border-color: var(--ct-danger);
  background: var(--ct-danger);
}

.tl-item.state-due .tl-dot {
  border-color: var(--ct-warning);
  background: var(--ct-warning);
}

.tl-item.state-upcoming .tl-dot {
  border-color: #2563eb;
}

.tl-item.state-done .tl-dot {
  border-color: var(--ct-success);
  background: var(--ct-success);
}

.tl-line {
  flex: 1;
  width: 2px;
  background: var(--ct-border);
  margin: 4px 0 0;
}

.tl-body {
  padding: 2px 0 16px 10px;
  border-bottom: 1px dashed var(--ct-border);
  min-width: 0;
}

.tl-item:last-child .tl-body {
  border-bottom: 0;
}

.tl-item.focused .tl-body {
  background: var(--ct-primary-soft);
  border-radius: 8px;
  padding-left: 12px;
}

.tl-top {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tl-check :deep(.el-checkbox__label) {
  font-weight: 600;
  font-size: 13.5px;
  color: var(--ct-text);
}

.tl-item.state-overdue .tl-time {
  color: var(--ct-danger);
}

.tl-item.state-due .tl-time {
  color: var(--ct-warning);
}

.tl-relative {
  font-size: 11.5px;
}

.tl-actions {
  margin-left: auto;
  display: flex;
  gap: 0;
}

.tl-result {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;
  color: var(--ct-muted);
}

.tl-obs {
  color: var(--ct-text);
}

.tl-done-at {
  font-size: 11px;
  color: var(--ct-faint);
}

/* 实际间隔（提前 / 延后） */
.tl-span {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 5px;
  font-size: 11.5px;
}

.span-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: 999px;
  background: #f2f7f6;
  border: 1px solid var(--ct-border);
  color: var(--ct-muted);
}

.span-chip b {
  color: var(--ct-text);
  font-weight: 600;
}

.span-from {
  font-style: normal;
  font-size: 10.5px;
  color: var(--ct-faint);
}

.span-chip.dev-early {
  background: #eef4ff;
  border-color: #cddffb;
  color: #2563eb;
}

.span-chip.dev-late {
  background: #fff6f0;
  border-color: #f5d5bd;
  color: #c2410c;
}

.span-chip.dev-on_time {
  background: #eef8f3;
  border-color: #c6e7d8;
  color: var(--ct-success);
}

.span-note {
  font-size: 11px;
  color: var(--ct-faint);
}

@media (max-width: 1180px) {
  .exp-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .exp-row {
    grid-template-columns: minmax(0, 1fr);
  }
  .exp-row-next {
    border-left: 0;
    padding-left: 0;
    display: flex;
    gap: 10px;
    align-items: baseline;
    flex-wrap: wrap;
  }
  .exp-row-actions {
    justify-content: flex-end;
  }
}

@media (max-width: 560px) {
  .exp-board {
    grid-template-columns: 1fr;
  }
  .exp-toolbar {
    gap: 8px;
  }
}
</style>
