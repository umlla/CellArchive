<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { topicApi } from '../api'
import { renderMarkdown } from '../markdown'
import { todayISO } from '../utils'

const props = defineProps({
  visible: { type: Boolean, default: false },
  topicId: { type: Number, default: null },
  discussion: { type: Object, default: null },
})
const emit = defineEmits(['update:visible', 'saved'])

const form = ref(emptyForm())
const saving = ref(false)
const mode = ref('edit') // edit | preview

function emptyForm() {
  return {
    discussed_on: todayISO(),
    title: '',
    participants: '',
    content: '',
  }
}

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    mode.value = 'edit'
    if (props.discussion) {
      form.value = {
        discussed_on: props.discussion.discussed_on || todayISO(),
        title: props.discussion.title || '',
        participants: props.discussion.participants || '',
        content: props.discussion.content || '',
      }
    } else {
      form.value = emptyForm()
    }
  },
  { immediate: true },
)

const isEdit = computed(() => Boolean(props.discussion))
const previewHtml = computed(() => renderMarkdown(form.value.content))
const canSubmit = computed(
  () => form.value.title.trim() || form.value.content.trim(),
)

function setToday() {
  form.value.discussed_on = todayISO()
}

function setYesterday() {
  const d = new Date()
  d.setDate(d.getDate() - 1)
  form.value.discussed_on = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function submit() {
  if (!canSubmit.value) {
    ElMessage.warning('标题和内容至少填一项')
    return
  }
  if (!props.topicId) return
  saving.value = true
  try {
    const payload = {
      discussed_on: form.value.discussed_on,
      title: form.value.title.trim() || null,
      participants: form.value.participants.trim() || null,
      content: form.value.content,
    }
    if (isEdit.value) {
      await topicApi.updateDiscussion(props.discussion.id, payload)
      ElMessage.success('讨论记录已更新')
    } else {
      await topicApi.createDiscussion(props.topicId, payload)
      ElMessage.success('讨论记录已保存')
    }
    emit('update:visible', false)
    emit('saved')
  } catch (error) {
    // 拦截器已统一提示错误信息，这里不重复弹窗
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="isEdit ? '编辑讨论记录' : '记录课题讨论'"
    width="820px"
    top="6vh"
    append-to-body
    @update:model-value="emit('update:visible', $event)"
  >
    <div class="disc-form">
      <div class="disc-row">
        <div class="disc-field">
          <label>讨论日期</label>
          <div class="disc-date">
            <el-date-picker
              v-model="form.discussed_on"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择日期"
              style="width: 150px"
            />
            <el-button size="small" @click="setToday">今天</el-button>
            <el-button size="small" @click="setYesterday">昨天</el-button>
          </div>
        </div>
        <div class="disc-field">
          <label>参与人</label>
          <el-input v-model="form.participants" placeholder="填写参与讨论的人（可留空）" />
        </div>
      </div>

      <div class="disc-field">
        <label>标题</label>
        <el-input v-model="form.title" placeholder="如：确定耐药表型的验证方案（可留空）" maxlength="200" />
      </div>

      <div class="disc-field">
        <div class="disc-label-row">
          <label>内容（支持 Markdown）</label>
          <el-radio-group v-model="mode" size="small">
            <el-radio-button value="edit">编辑</el-radio-button>
            <el-radio-button value="preview">预览</el-radio-button>
          </el-radio-group>
        </div>
        <el-input
          v-if="mode === 'edit'"
          v-model="form.content"
          type="textarea"
          :rows="14"
          resize="vertical"
          placeholder="写下讨论要点、导师建议、下一步计划…&#10;&#10;支持：# 标题、**加粗**、- 列表、> 引用、`代码`"
        />
        <div v-else class="disc-preview markdown-body" v-html="previewHtml || '<p class=disc-empty>暂无内容</p>'" />
      </div>

      <div class="disc-hint">
        支持 <code>#</code> 标题、<code>**加粗**</code>、<code>- 列表</code>、<code>&gt; 引用</code>、<code>`代码`</code>；不支持表格与 HTML。
      </div>
    </div>

    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="!canSubmit" @click="submit">
        {{ isEdit ? '保存修改' : '保存记录' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.disc-form { display: flex; flex-direction: column; gap: 14px; }
.disc-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.disc-field { display: flex; flex-direction: column; gap: 6px; }
.disc-field > label { font-size: 13px; color: var(--ct-muted); font-weight: 500; }
.disc-date { display: flex; align-items: center; gap: 6px; }
.disc-label-row { display: flex; align-items: center; justify-content: space-between; }
.disc-label-row > label { font-size: 13px; color: var(--ct-muted); font-weight: 500; }
.disc-preview {
  min-height: 280px;
  max-height: 420px;
  overflow: auto;
  border: 1px solid var(--ct-border);
  border-radius: 8px;
  padding: 12px 16px;
  background: var(--ct-bg);
}
.disc-hint { font-size: 12px; color: var(--ct-faint); }
.disc-hint code { background: var(--ct-primary-soft); padding: 1px 4px; border-radius: 3px; }
.disc-empty { color: var(--ct-faint); }
</style>
