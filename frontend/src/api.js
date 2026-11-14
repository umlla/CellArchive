import axios from 'axios'
import { ElMessage } from 'element-plus'

export const http = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

let unauthorizedHandler = null
export function onUnauthorized(handler) {
  unauthorizedHandler = handler
}

http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const payload = error.response?.data
    const message = payload?.error?.message || payload?.message || error.message || '请求失败'
    if (status === 401) {
      unauthorizedHandler?.()
    } else if (!error.config?.silent) {
      ElMessage.error(message)
    }
    const wrapped = new Error(message)
    wrapped.status = status
    wrapped.payload = payload
    return Promise.reject(wrapped)
  },
)

export const authApi = {
  status: () => http.get('/auth/status', { silent: true }),
  me: () => http.get('/auth/me', { silent: true }),
  login: (username, password) => http.post('/auth/login', { username, password }),
  logout: () => http.post('/auth/logout', { silent: true }),
}

export const metaApi = {
  meta: () => http.get('/meta'),
  dashboard: () => http.get('/dashboard'),
  audit: () => http.get('/maintenance/audit'),
  backups: () => http.get('/maintenance/backups'),
  migrationReport: () => http.get('/maintenance/migration-report'),
  recalculate: () => http.post('/maintenance/recalculate'),
  restore: (formData, onProgress) =>
    http.post('/maintenance/restore', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    }),
  importLegacy: (formData, onProgress) =>
    http.post('/maintenance/import-legacy', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    }),
}

export const lineApi = {
  list: (search) => http.get('/cell-lines', { params: search ? { search } : {} }),
  detail: (id, includeEnded = true) =>
    http.get(`/cell-lines/${id}`, { params: { include_ended: includeEnded } }),
  create: (payload) => http.post('/cell-lines', payload),
  update: (id, payload) => http.patch(`/cell-lines/${id}`, payload),
  remove: (id) => http.delete(`/cell-lines/${id}`),
  assignSpecies: (payload) => http.post('/cell-lines/species', payload),
  batches: (id, includeEnded = true) =>
    http.get(`/cell-lines/${id}/batches`, { params: { include_ended: includeEnded } }),
  vials: (id) => http.get(`/cell-lines/${id}/vials`),
}

export const batchApi = {
  list: (params) => http.get('/batches', { params }),
  detail: (id) => http.get(`/batches/${id}`),
  create: (payload) => http.post('/batches', payload),
  update: (id, payload) => http.patch(`/batches/${id}`, payload),
  remove: (id) => http.delete(`/batches/${id}`),
  terminate: (id, reason) => http.post(`/batches/${id}/terminate`, { reason }),
  restore: (id) => http.post(`/batches/${id}/restore`),
  records: (id) => http.get(`/batches/${id}/records`),
  csvUrl: (id) => `/api/batches/${id}/records.csv`,
}

export const recordApi = {
  create: (payload) => http.post('/records', payload),
  bulkCreate: (entries) => http.post('/records/bulk', { entries }),
  update: (id, payload) => http.patch(`/records/${id}`, payload),
  bulkUpdate: (entries) => http.post('/records/bulk-update', { entries }),
  remove: (id) => http.delete(`/records/${id}`),
}

export const vialApi = {
  list: (params) => http.get('/vials', { params }),
  boxes: () => http.get('/vials/boxes'),
  box: (box) => http.get('/vials/boxes/detail', { params: { box } }),
  create: (payload) => http.post('/vials', payload),
  update: (id, payload) => http.patch(`/vials/${id}`, payload),
  remove: (id) => http.delete(`/vials/${id}`),
  clearBox: (box) => http.delete('/vials/boxes', { params: { box } }),
  import: (formData) =>
    http.post('/vials/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
}

export const groupApi = {
  list: () => http.get('/groups'),
  detail: (id) => http.get(`/groups/${id}`),
  create: (payload) => http.post('/groups', payload),
  update: (id, payload) => http.patch(`/groups/${id}`, payload),
  remove: (id) => http.delete(`/groups/${id}`),
  setMembers: (id, memberIds) => http.put(`/groups/${id}/members`, { members: memberIds }),
  status: (id) => http.get(`/groups/${id}/status`),
  records: (id) => http.get(`/groups/${id}/records`),
  rates: (id, params) => http.get(`/groups/${id}/rates`, { params }),
  curves: (id, params) => http.get(`/groups/${id}/curves`, { params }),
  createBatches: (id, payload) => http.post(`/groups/${id}/batches`, payload),
  terminate: (id, reason) => http.post(`/groups/${id}/terminate`, { reason }),
  exportUrl: (id, includeAll = true) =>
    `/api/groups/${id}/export?include_all=${includeAll ? 'true' : 'false'}`,
}

export const compareApi = {
  curves: (params) => http.get('/compare/curves', { params }),
}

// 待办事项（用户自建，独立于实验）
export const todoApi = {
  list: (params) => http.get('/todos', { params }),
  stats: () => http.get('/todos/stats'),
  create: (payload) => http.post('/todos', payload),
  update: (id, payload) => http.patch(`/todos/${id}`, payload),
  complete: (id, done = true) => http.post(`/todos/${id}/complete`, { done }),
  postpone: (id, days = 1) => http.post(`/todos/${id}/postpone`, { days }),
  remove: (id) => http.delete(`/todos/${id}`),
}

// 课题讨论（课题 + 与导师的讨论记录）
export const topicApi = {
  list: (params) => http.get('/topics', { params }),
  stats: () => http.get('/topics/stats'),
  create: (payload) => http.post('/topics', payload),
  get: (id) => http.get(`/topics/${id}`),
  update: (id, payload) => http.patch(`/topics/${id}`, payload),
  remove: (id) => http.delete(`/topics/${id}`),
  discussions: (topicId, params) => http.get(`/topics/${topicId}/discussions`, { params }),
  createDiscussion: (topicId, payload) => http.post(`/topics/${topicId}/discussions`, payload),
  updateDiscussion: (id, payload) => http.patch(`/discussions/${id}`, payload),
  removeDiscussion: (id) => http.delete(`/discussions/${id}`),
}

// 细胞实验（实验日程与检查提醒）
export const experimentApi = {
  list: (params) => http.get('/experiments', { params }),
  summary: () => http.get('/experiments/summary'),
  choices: () => http.get('/experiments/meta'),
  detail: (id) => http.get(`/experiments/${id}`),
  create: (payload) => http.post('/experiments', payload),
  update: (id, payload) => http.patch(`/experiments/${id}`, payload),
  remove: (id) => http.delete(`/experiments/${id}`),
  complete: (id, payload) => http.post(`/experiments/${id}/complete`, payload),
  finish: (id, payload) => http.post(`/experiments/${id}/finish`, payload),
  week: (start) => http.get('/experiments/week', { params: start ? { start } : {} }),
  month: (month) => http.get('/experiments/month', { params: month ? { month } : {} }),
  addCheckpoint: (id, payload) => http.post(`/experiments/${id}/checkpoints`, payload),
  updateCheckpoint: (id, checkpointId, payload) =>
    http.patch(`/experiments/${id}/checkpoints/${checkpointId}`, payload),
  reopenCheckpoint: (id, checkpointId) =>
    http.post(`/experiments/${id}/checkpoints/${checkpointId}/reopen`),
  postponeCheckpoint: (id, checkpointId, days = 1) =>
    http.post(`/experiments/${id}/checkpoints/${checkpointId}/postpone`, { days }),
  removeCheckpoint: (id, checkpointId) =>
    http.delete(`/experiments/${id}/checkpoints/${checkpointId}`),
}

export function downloadUrl(url) {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}
