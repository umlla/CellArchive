<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { topicApi } from '../api'
import { markdownSummary, renderMarkdown } from '../markdown'
import TopicDialog from '../components/TopicDialog.vue'
import DiscussionDialog from '../components/DiscussionDialog.vue'

const topics = ref([])
const discussions = ref([])
const activeTopic = ref(null)
const loadingTopics = ref(false)
const loadingDiscussions = ref(false)

const topicKeyword = ref('')
const statusFilter = ref('')
const discussionKeyword = ref('')

const topicDialogVisible = ref(false)
const editingTopic = ref(null)
const discussionDialogVisible = ref(false)
const editingDiscussion = ref(null)
const expanded = ref(new Set())

const STATUS_LABELS = { active: '进行中', paused: '暂缓', closed: '已结题' }

const filteredTopics = computed(() => {
  const keyword = topicKeyword.value.trim().toLowerCase()
  if (!keyword) return topics.value
  return topics.value.filter(
    (t) =>
      (t.name || '').toLowerCase().includes(keyword) ||
      (t.advisor || '').toLowerCase().includes(keyword),
  )
})

const activeTopicTitle = computed(() => activeTopic.value?.name || '')

async function loadTopics(keepSelection = true) {
  loadingTopics.value = true
  try {
    // 拦截器已把响应解包为数据本身，这里直接拿数组
    const data = await topicApi.list({
      status: statusFilter.value || undefined,
    })
    topics.value = data
    if (!keepSelection || !activeTopic.value) {
      if (data.length) selectTopic(data[0])
      else {
        activeTopic.value = null
        discussions.value = []
      }
    } else {
      const still = data.find((t) => t.id === activeTopic.value.id)
      activeTopic.value = still || (data.length ? data[0] : null)
      if (activeTopic.value && !still) selectTopic(activeTopic.value)
    }
  } catch (error) {
    ElMessage.error('加载课题失败')
  } finally {
    loadingTopics.value = false
  }
}

async function selectTopic(topic) {
  activeTopic.value = topic
  discussionKeyword.value = ''
  expanded.value = new Set()
  await loadDiscussions()
}

async function loadDiscussions() {
  if (!activeTopic.value) return
  loadingDiscussions.value = true
  try {
    const data = await topicApi.discussions(activeTopic.value.id, {
      q: discussionKeyword.value.trim() || undefined,
    })
    discussions.value = data
    // 只有一条时自动展开，方便阅读
    if (data.length === 1) expanded.value = new Set([data[0].id])
  } catch (error) {
    ElMessage.error('加载讨论记录失败')
  } finally {
    loadingDiscussions.value = false
  }
}

function toggleExpand(id) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function openNewTopic() {
  editingTopic.value = null
  topicDialogVisible.value = true
}

function openEditTopic() {
  if (!activeTopic.value) return
  editingTopic.value = activeTopic.value
  topicDialogVisible.value = true
}

function openNewDiscussion() {
  if (!activeTopic.value) {
    ElMessage.warning('请先选择一个课题')
    return
  }
  editingDiscussion.value = null
  discussionDialogVisible.value = true
}

function openEditDiscussion(item) {
  editingDiscussion.value = item
  discussionDialogVisible.value = true
}

async function onTopicSaved() {
  const created = !editingTopic.value
  await loadTopics(false)
  if (created && topics.value.length) {
    // 新建的课题按 id 倒序排在最前，直接选中它
    const newest = topics.value.reduce((a, b) => (a.id > b.id ? a : b))
    await selectTopic(newest)
  }
}

async function onDiscussionSaved() {
  await loadDiscussions()
  await loadTopics()
}

async function removeTopic() {
  if (!activeTopic.value) return
  const topic = activeTopic.value
  try {
    await ElMessageBox.confirm(
      `删除课题「${topic.name}」将同时删除它的 ${topic.discussion_count} 条讨论记录，且无法恢复。确定删除吗？`,
      '删除课题',
      { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const data = await topicApi.remove(topic.id)
    ElMessage.success(`已删除，同时移除 ${data.removed_discussions} 条讨论记录`)
    activeTopic.value = null
    await loadTopics(false)
  } catch (error) {
    // 拦截器已统一提示错误信息，这里不重复弹窗
  }
}

async function removeDiscussion(item) {
  try {
    await ElMessageBox.confirm(`确定删除「${item.title || '这条讨论记录'}」吗？`, '删除讨论记录', {
      type: 'warning',
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await topicApi.removeDiscussion(item.id)
    ElMessage.success('已删除')
    await loadDiscussions()
    await loadTopics()
  } catch (error) {
    // 拦截器已统一提示错误信息，这里不重复弹窗
  }
}

function formatDate(value) {
  if (!value) return ''
  const [y, m, d] = value.split('-')
  const week = ['日', '一', '二', '三', '四', '五', '六'][new Date(`${value}T00:00:00`).getDay()]
  return `${y}-${m}-${d} 周${week}`
}

function relativeDate(value) {
  if (!value) return ''
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const target = new Date(`${value}T00:00:00`)
  const diff = Math.round((target - today) / 86400000)
  if (diff === 0) return '今天'
  if (diff === -1) return '昨天'
  if (diff === -2) return '前天'
  if (diff > 0) return `${diff} 天后`
  return `${-diff} 天前`
}

function renderItem(item) {
  return renderMarkdown(item.content)
}

onMounted(() => loadTopics(false))
</script>

<template>
  <div class="topics-view">
    <!-- 左侧：课题列表 -->
    <aside class="topic-panel">
      <div class="topic-panel-head">
        <el-input v-model="topicKeyword" placeholder="搜索课题 / 导师" clearable size="small" />
        <el-button type="primary" size="small" @click="openNewTopic">＋ 新建课题</el-button>
      </div>

      <el-radio-group v-model="statusFilter" size="small" class="topic-status-filter" @change="loadTopics(false)">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="active">进行中</el-radio-button>
        <el-radio-button value="closed">已结题</el-radio-button>
      </el-radio-group>

      <div v-loading="loadingTopics" class="topic-list">
        <div
          v-for="topic in filteredTopics"
          :key="topic.id"
          class="topic-item"
          :class="{ active: activeTopic && activeTopic.id === topic.id }"
          @click="selectTopic(topic)"
        >
          <div class="topic-item-top">
            <span class="topic-name">{{ topic.name }}</span>
            <span class="topic-badge" :class="`st-${topic.status}`">{{ topic.status_label }}</span>
          </div>
          <div class="topic-item-meta">
            <span v-if="topic.advisor">{{ topic.advisor }}</span>
            <span>{{ topic.discussion_count }} 条讨论</span>
          </div>
          <div v-if="topic.last_discussed_on" class="topic-item-last">
            最近：{{ topic.last_discussed_on }}（{{ relativeDate(topic.last_discussed_on) }}）
          </div>
        </div>

        <el-empty v-if="!loadingTopics && !filteredTopics.length" description="还没有课题，先新建一个" :image-size="70" />
      </div>
    </aside>

    <!-- 右侧：讨论记录 -->
    <section class="disc-panel">
      <template v-if="activeTopic">
        <header class="disc-head">
          <div class="disc-head-main">
            <h2>{{ activeTopicTitle }}</h2>
            <div class="disc-head-meta">
              <span v-if="activeTopic.advisor">导师：{{ activeTopic.advisor }}</span>
              <span>{{ activeTopic.discussion_count }} 条讨论记录</span>
            </div>
            <p v-if="activeTopic.summary" class="disc-head-summary">{{ activeTopic.summary }}</p>
          </div>
          <div class="disc-head-actions">
            <el-button size="small" @click="openEditTopic">编辑课题</el-button>
            <el-button size="small" type="danger" plain @click="removeTopic">删除课题</el-button>
            <el-button type="primary" @click="openNewDiscussion">＋ 记录讨论</el-button>
          </div>
        </header>

        <div class="disc-toolbar">
          <el-input
            v-model="discussionKeyword"
            placeholder="搜索标题或内容"
            clearable
            size="small"
            style="width: 260px"
            @keyup.enter="loadDiscussions"
            @clear="loadDiscussions"
          />
          <el-button size="small" @click="loadDiscussions">搜索</el-button>
        </div>

        <div v-loading="loadingDiscussions" class="disc-list">
          <el-empty
            v-if="!loadingDiscussions && !discussions.length"
            :description="discussionKeyword ? '没有匹配的讨论记录' : '还没有讨论记录，点右上角「记录讨论」开始'"
            :image-size="80"
          />

          <article v-for="item in discussions" :key="item.id" class="disc-card">
            <div class="disc-card-head">
              <div class="disc-card-title-row">
                <span class="disc-date-chip">{{ formatDate(item.discussed_on) }}</span>
                <span class="disc-rel">{{ relativeDate(item.discussed_on) }}</span>
                <span v-if="item.title" class="disc-title">{{ item.title }}</span>
              </div>
              <div class="disc-card-actions">
                <el-button link size="small" @click="toggleExpand(item.id)">
                  {{ expanded.has(item.id) ? '收起' : '展开' }}
                </el-button>
                <el-button link size="small" @click="openEditDiscussion(item)">编辑</el-button>
                <el-button link size="small" type="danger" @click="removeDiscussion(item)">删除</el-button>
              </div>
            </div>

            <div v-if="item.participants" class="disc-participants">参与人：{{ item.participants }}</div>

            <div v-if="expanded.has(item.id)" class="markdown-body disc-content" v-html="renderItem(item)" />
            <p v-else class="disc-summary">{{ markdownSummary(item.content) || '（无正文）' }}</p>
          </article>
        </div>
      </template>

      <el-empty v-else description="从左侧选择一个课题，或先新建课题" :image-size="100" />
    </section>

    <TopicDialog
      v-model:visible="topicDialogVisible"
      :topic="editingTopic"
      @saved="onTopicSaved"
    />
    <DiscussionDialog
      v-model:visible="discussionDialogVisible"
      :topic-id="activeTopic?.id || null"
      :discussion="editingDiscussion"
      @saved="onDiscussionSaved"
    />
  </div>
</template>

<style scoped>
.topics-view {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

/* 左侧课题列表 */
.topic-panel {
  background: var(--ct-surface);
  border: 1px solid var(--ct-border);
  border-radius: var(--ct-radius);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  position: sticky;
  top: 12px;
  max-height: calc(100vh - 130px);
}
.topic-panel-head { display: flex; gap: 8px; }
.topic-panel-head .el-input { flex: 1; }
.topic-status-filter { width: 100%; display: flex; }
.topic-status-filter :deep(.el-radio-button) { flex: 1; }
.topic-status-filter :deep(.el-radio-button__inner) { width: 100%; padding: 5px 0; }
.topic-list { overflow: auto; display: flex; flex-direction: column; gap: 6px; min-height: 120px; }
.topic-item {
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 9px 10px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.topic-item:hover { background: var(--ct-bg); }
.topic-item.active { background: var(--ct-primary-soft); border-color: var(--ct-primary); }
.topic-item-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.topic-name { font-weight: 600; font-size: 14px; color: var(--ct-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.topic-badge { font-size: 11px; padding: 1px 6px; border-radius: 999px; white-space: nowrap; flex-shrink: 0; }
.topic-badge.st-active { background: #e6f6ef; color: var(--ct-success); }
.topic-badge.st-paused { background: #fdf3e2; color: var(--ct-warning); }
.topic-badge.st-closed { background: #eef1f0; color: var(--ct-muted); }
.topic-item-meta { display: flex; gap: 10px; font-size: 12px; color: var(--ct-muted); margin-top: 3px; }
.topic-item-last { font-size: 11px; color: var(--ct-faint); margin-top: 2px; }

/* 右侧讨论区 */
.disc-panel {
  background: var(--ct-surface);
  border: 1px solid var(--ct-border);
  border-radius: var(--ct-radius);
  padding: 16px;
  min-height: 420px;
}
.disc-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.disc-head-main h2 { margin: 0 0 4px; font-size: 18px; color: var(--ct-text); }
.disc-head-meta { display: flex; gap: 12px; font-size: 12px; color: var(--ct-muted); }
.disc-head-summary { margin: 6px 0 0; font-size: 13px; color: var(--ct-muted); max-width: 60ch; }
.disc-head-actions { display: flex; gap: 8px; flex-shrink: 0; align-items: center; }

.disc-toolbar { display: flex; gap: 8px; margin: 14px 0 10px; align-items: center; }

.disc-list { display: flex; flex-direction: column; gap: 10px; min-height: 200px; }
.disc-card {
  border: 1px solid var(--ct-border);
  border-radius: 10px;
  padding: 10px 12px;
  background: var(--ct-surface);
}
.disc-card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.disc-card-title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.disc-date-chip {
  font-size: 12px;
  font-weight: 600;
  color: var(--ct-primary);
  background: var(--ct-primary-soft);
  padding: 1px 8px;
  border-radius: 999px;
}
.disc-rel { font-size: 11px; color: var(--ct-faint); }
.disc-title { font-weight: 600; font-size: 14px; color: var(--ct-text); }
.disc-card-actions { display: flex; gap: 2px; flex-shrink: 0; }
.disc-participants { font-size: 12px; color: var(--ct-muted); margin-top: 4px; }
.disc-summary { margin: 8px 0 0; font-size: 13px; color: var(--ct-muted); line-height: 1.6; }
.disc-content { margin-top: 8px; }

@media (max-width: 900px) {
  .topics-view { grid-template-columns: 1fr; }
  .topic-panel { position: static; max-height: none; }
}
</style>
