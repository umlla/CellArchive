<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { topicApi } from '../api'

const props = defineProps({
  visible: { type: Boolean, default: false },
  topic: { type: Object, default: null },
})
const emit = defineEmits(['update:visible', 'saved'])

const STATUS_OPTIONS = [
  { value: 'active', label: '进行中' },
  { value: 'paused', label: '暂缓' },
  { value: 'closed', label: '已结题' },
]

const form = ref({ name: '', advisor: '', status: 'active', summary: '' })
const saving = ref(false)

watch(
  () => props.visible,
  (open) => {
    if (!open) return
    if (props.topic) {
      form.value = {
        name: props.topic.name || '',
        advisor: props.topic.advisor || '',
        status: props.topic.status || 'active',
        summary: props.topic.summary || '',
      }
    } else {
      form.value = { name: '', advisor: '', status: 'active', summary: '' }
    }
  },
  { immediate: true },
)

async function submit() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写课题名')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      advisor: form.value.advisor.trim() || null,
      status: form.value.status,
      summary: form.value.summary.trim() || null,
    }
    if (props.topic) {
      await topicApi.update(props.topic.id, payload)
      ElMessage.success('课题已更新')
    } else {
      await topicApi.create(payload)
      ElMessage.success('课题已创建')
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
    :title="topic ? '编辑课题' : '新建课题'"
    width="520px"
    append-to-body
    @update:model-value="emit('update:visible', $event)"
  >
    <el-form label-width="72px" label-position="left">
      <el-form-item label="课题名" required>
        <el-input v-model="form.name" placeholder="如：紫杉醇耐药机制研究" maxlength="120" />
      </el-form-item>
      <el-form-item label="导师">
        <el-input v-model="form.advisor" placeholder="填写导师（可留空）" maxlength="80" />
      </el-form-item>
      <el-form-item label="状态">
        <el-radio-group v-model="form.status">
          <el-radio-button v-for="opt in STATUS_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="简介">
        <el-input
          v-model="form.summary"
          type="textarea"
          :rows="3"
          placeholder="这个课题要解决什么问题（可留空）"
          maxlength="2000"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">
        {{ topic ? '保存修改' : '创建课题' }}
      </el-button>
    </template>
  </el-dialog>
</template>
