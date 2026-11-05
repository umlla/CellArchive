<template>
  <div class="panel">
    <div class="panel-head">
      <div>
        <h2>细胞组管理</h2>
        <p class="sub">
          显示 {{ visibleGroups.length }} 个有在养细胞的组
          <template v-if="hiddenGroups.length">（另有 {{ hiddenGroups.length }} 个组暂无在养细胞，已隐藏）</template>
          · 组内顺序决定看板与批量录入的排列顺序
        </p>
      </div>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建细胞组
      </el-button>
    </div>

    <div v-if="hiddenGroups.length" class="hidden-bar">
      <el-switch v-model="showEmpty" active-text="显示没有在养细胞的组" />
    </div>

    <div v-if="visibleGroups.length" class="group-cards">
      <div v-for="group in visibleGroups" :key="group.id" class="group-card">
        <div class="row between">
          <div>
            <div class="group-name">{{ group.group_name }}</div>
            <div class="small faint" style="margin-top: 3px">
              {{ group.member_count }} 个成员 · {{ activeBatches(group) }} 个在养批次
            </div>
          </div>
          <el-dropdown trigger="click" @command="(cmd) => onCommand(cmd, group)">
            <el-button text circle><el-icon><MoreFilled /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="view">查看组看板</el-dropdown-item>
                <el-dropdown-item command="members">管理成员</el-dropdown-item>
                <el-dropdown-item command="edit" divided>重命名 / 备注</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除组</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <div class="member-tags">
          <el-tag
            v-for="member in group.members"
            :key="member.cell_line_id"
            size="small"
            effect="plain"
            :type="member.active_batch_count ? 'success' : 'info'"
          >
            {{ member.name }}
          </el-tag>
          <span v-if="!group.members.length" class="small faint">暂无成员</span>
        </div>

        <div v-if="group.notes" class="small muted notes">{{ group.notes }}</div>

        <div class="group-actions">
          <el-button size="small" @click="openMembers(group)">成员与排序</el-button>
          <el-button size="small" type="primary" plain @click="viewGroup(group)">查看组看板</el-button>
        </div>
      </div>
    </div>

    <div v-else class="empty-hint">
      <span class="icon">📂</span>
      <template v-if="groups.length">
        当前没有含在养细胞的组<template v-if="!showEmpty">，可打开上方开关查看全部 {{ groups.length }} 个组</template>
      </template>
      <template v-else>还没有细胞组，创建一个把常一起操作的细胞株归类</template>
    </div>

    <!-- 创建 / 编辑 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑细胞组' : '新建细胞组'" width="min(480px, 94vw)">
      <el-form :model="form" label-width="80px" label-position="left">
        <el-form-item label="组名" required>
          <el-input v-model="form.group_name" placeholder="例如：传代实验组、冻存组" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">{{ editing ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>

    <!-- 成员管理 -->
    <el-dialog v-model="membersVisible" :title="`${activeGroup?.group_name || ''} · 成员与排序`" width="min(560px, 94vw)">
      <div class="dialog-section-title">当前成员（按顺序展示）</div>
      <div v-if="members.length" class="member-list">
        <div v-for="(member, index) in members" :key="member.cell_line_id" class="member-row">
          <span class="index">{{ index + 1 }}</span>
          <span class="member-name">{{ member.name }}</span>
          <el-tag size="small" effect="plain" type="info">{{ member.type || '—' }}</el-tag>
          <div class="row" style="margin-left: auto; gap: 2px">
            <el-button text circle size="small" :disabled="index === 0" @click="move(index, -1)">
              <el-icon><Top /></el-icon>
            </el-button>
            <el-button text circle size="small" :disabled="index === members.length - 1" @click="move(index, 1)">
              <el-icon><Bottom /></el-icon>
            </el-button>
            <el-button text circle size="small" @click="members.splice(index, 1)">
              <el-icon><Close /></el-icon>
            </el-button>
          </div>
        </div>
      </div>
      <div v-else class="small faint" style="padding: 8px 0">该组还没有成员</div>

      <div class="dialog-section-title" style="margin-top: 22px; padding-top: 12px; border-top: 1px solid var(--ct-border)">添加成员</div>
      <div class="row">
        <el-select v-model="lineToAdd" placeholder="选择细胞株" filterable style="flex: 1">
          <el-option
            v-for="line in addableLines"
            :key="line.id"
            :label="`${line.name}（${line.type || '未分类'}）`"
            :value="line.id"
          />
        </el-select>
        <el-button :disabled="!lineToAdd" @click="addMember">添加</el-button>
      </div>

      <template #footer>
        <el-button @click="membersVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingMembers" @click="saveMembers">保存成员与排序</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { groupApi, lineApi } from '../api'
import { loadMeta } from '../store'

const router = useRouter()
const groups = ref([])
const lines = ref([])
const showEmpty = ref(false)
const dialogVisible = ref(false)
const editing = ref(false)
const saving = ref(false)
const form = ref({ id: null, group_name: '', notes: '' })

const membersVisible = ref(false)
const activeGroup = ref(null)
const members = ref([])
const lineToAdd = ref(null)
const savingMembers = ref(false)

const addableLines = computed(() => {
  const taken = new Set(members.value.map((member) => member.cell_line_id))
  return lines.value.filter((line) => !taken.has(line.id))
})

function activeBatches(group) {
  return (group.members || []).reduce((total, member) => total + (member.active_batch_count || 0), 0)
}

const hiddenGroups = computed(() => groups.value.filter((group) => activeBatches(group) === 0))
const visibleGroups = computed(() =>
  showEmpty.value ? groups.value : groups.value.filter((group) => activeBatches(group) > 0),
)

async function reload() {
  groups.value = await groupApi.list()
  await loadMeta()
}

function openCreate() {
  editing.value = false
  form.value = { id: null, group_name: '', notes: '' }
  dialogVisible.value = true
}

function openEdit(group) {
  editing.value = true
  form.value = { id: group.id, group_name: group.group_name, notes: group.notes || '' }
  dialogVisible.value = true
}

async function save() {
  if (!form.value.group_name.trim()) {
    ElMessage.warning('请输入组名')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await groupApi.update(form.value.id, form.value)
      ElMessage.success('细胞组已更新')
    } else {
      await groupApi.create(form.value)
      ElMessage.success('细胞组已创建')
    }
    dialogVisible.value = false
    await reload()
  } finally {
    saving.value = false
  }
}

async function onCommand(command, group) {
  if (command === 'view') {
    viewGroup(group)
  } else if (command === 'members') {
    openMembers(group)
  } else if (command === 'edit') {
    openEdit(group)
  } else if (command === 'delete') {
    try {
      await ElMessageBox.confirm(`删除细胞组「${group.group_name}」？组成员关系会一并删除，细胞株和批次不受影响。`, '删除细胞组', {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
    await groupApi.remove(group.id)
    ElMessage.success('细胞组已删除')
    await reload()
  }
}

function viewGroup(group) {
  router.push({ path: '/', query: { mode: 'group', group: group.id } })
}

async function openMembers(group) {
  activeGroup.value = group
  members.value = (group.members || []).map((member) => ({ ...member }))
  lineToAdd.value = null
  membersVisible.value = true
}

function addMember() {
  const line = lines.value.find((item) => item.id === lineToAdd.value)
  if (!line) return
  members.value.push({ cell_line_id: line.id, name: line.name, type: line.type })
  lineToAdd.value = null
}

function move(index, delta) {
  const target = index + delta
  if (target < 0 || target >= members.value.length) return
  const [item] = members.value.splice(index, 1)
  members.value.splice(target, 0, item)
}

async function saveMembers() {
  savingMembers.value = true
  try {
    await groupApi.setMembers(activeGroup.value.id, members.value.map((member) => member.cell_line_id))
    ElMessage.success('成员与排序已保存')
    membersVisible.value = false
    await reload()
  } finally {
    savingMembers.value = false
  }
}

onMounted(async () => {
  const [groupList, lineList] = await Promise.all([groupApi.list(), lineApi.list()])
  groups.value = groupList
  lines.value = lineList
})
</script>

<style scoped>
.hidden-bar {
  display: flex;
  justify-content: flex-end;
  padding: 14px 18px 0;
}

.group-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 14px;
  padding: 18px;
}

.group-card {
  border: 1px solid var(--ct-border);
  border-radius: 12px;
  padding: 14px 16px;
  background: #fdfefe;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: box-shadow 0.18s ease, border-color 0.18s ease;
}

.group-card:hover {
  border-color: var(--ct-border-strong);
  box-shadow: 0 8px 24px -20px rgba(15, 118, 110, 0.55);
}

.group-name {
  font-size: 15px;
  font-weight: 600;
}

.member-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-height: 22px;
}

.notes {
  border-top: 1px dashed var(--ct-border);
  padding-top: 8px;
  font-size: 12px;
}

.group-actions {
  display: flex;
  gap: 8px;
  margin-top: auto;
  padding-top: 4px;
}

.member-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 300px;
  overflow-y: auto;
}

.member-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid var(--ct-border);
  border-radius: 9px;
  background: #fbfdfc;
}

.index {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  background: var(--ct-primary-soft);
  color: var(--ct-primary);
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.member-name {
  font-size: 13px;
  font-weight: 500;
}
</style>
