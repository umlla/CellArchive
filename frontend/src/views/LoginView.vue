<template>
  <div class="login-page">
    <div class="login-card">
      <span class="brand-mark">🧬</span>
      <h1>细胞档案</h1>
      <p class="sub">CellArchive · 细胞培养管理追踪 · 请登录后使用</p>

      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input v-model="username" size="large" placeholder="用户名" autocomplete="username">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="password"
            size="large"
            type="password"
            show-password
            placeholder="密码"
            autocomplete="current-password"
            @keyup.enter="submit"
          >
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="submit">
          登录
        </el-button>
      </el-form>

      <p class="small faint" style="margin: 16px 0 0; text-align: center">
        首次开启认证会自动创建管理员账号，可在 config.json 中查看
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '../api'
import { loadMeta, refreshAuth } from '../store'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)

async function submit() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await authApi.login(username.value, password.value)
    await refreshAuth()
    await loadMeta()
    ElMessage.success('登录成功')
    router.replace('/')
  } finally {
    loading.value = false
  }
}
</script>
