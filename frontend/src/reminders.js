import { reactive } from 'vue'
import { experimentApi } from './api'

// 细胞实验提醒：全站共用一份汇总，顶栏提醒铃、首页卡片、实验页都读它，
// 任意一处勾选检查后调用 refreshReminders()，其它地方立即同步。
export const reminders = reactive({
  summary: null,
  loading: false,
  error: '',
  lastLoadedAt: null,
  // 已弹过浏览器通知的「实验#检查点」键，避免同一时间点重复打扰
  notified: {},
})

let timer = null
let inFlight = null

export async function refreshReminders({ silent = true } = {}) {
  if (inFlight) return inFlight
  reminders.loading = true
  inFlight = experimentApi
    .summary()
    .then((data) => {
      reminders.summary = data
      reminders.error = ''
      reminders.lastLoadedAt = Date.now()
      return data
    })
    .catch((error) => {
      reminders.error = error?.message || '提醒加载失败'
      if (!silent) throw error
      return null
    })
    .finally(() => {
      reminders.loading = false
      inFlight = null
    })
  return inFlight
}

export function reminderStats() {
  return (
    reminders.summary?.stats || {
      overdue_experiments: 0,
      today_experiments: 0,
      upcoming_experiments: 0,
      pending_checkpoints: 0,
      overdue_checkpoints: 0,
      today_checkpoints: 0,
    }
  )
}

export function hasAttention() {
  const stats = reminderStats()
  return stats.overdue_experiments > 0 || stats.today_experiments > 0
}

export function attentionCount() {
  const stats = reminderStats()
  return stats.overdue_experiments + stats.today_experiments
}

/**
 * 启动定时轮询（每 N 分钟），可选同时发浏览器通知。
 * 返回停止函数，组件卸载时调用。
 */
export function startReminderPolling({ intervalMinutes = 15, browserNotify = false } = {}) {
  stopReminderPolling()
  refreshReminders()
  timer = setInterval(() => {
    refreshReminders().then(() => {
      if (browserNotify) notifyNewDue()
    })
  }, Math.max(1, intervalMinutes) * 60 * 1000)
  if (browserNotify) notifyNewDue()
  return stopReminderPolling
}

export function stopReminderPolling() {
  if (timer) clearInterval(timer)
  timer = null
}

export function browserNotifySupported() {
  return typeof window !== 'undefined' && 'Notification' in window
}

export async function requestNotifyPermission() {
  if (!browserNotifySupported()) return 'unsupported'
  if (Notification.permission === 'granted') return 'granted'
  try {
    return await Notification.requestPermission()
  } catch {
    return 'denied'
  }
}

/**
 * 对「逾期 / 今天到点」的检查点发浏览器通知，每个检查点只提醒一次。
 * 同一实验的多个检查点合并成一条通知，避免刷屏。
 */
export function notifyNewDue() {
  if (!browserNotifySupported() || Notification.permission !== 'granted') return 0
  const summary = reminders.summary
  if (!summary) return 0
  const groups = new Map()
  for (const item of [...(summary.overdue || []), ...(summary.due_today || [])]) {
    for (const checkpoint of item.checkpoints || []) {
      if (checkpoint.state !== 'overdue' && checkpoint.state !== 'due') continue
      const key = `${item.experiment_id}#${checkpoint.id}`
      if (reminders.notified[key]) continue
      reminders.notified[key] = true
      if (!groups.has(item.experiment_id)) groups.set(item.experiment_id, { item, lines: [] })
      groups.get(item.experiment_id).lines.push(
        `${checkpoint.due_label}${checkpoint.state === 'overdue' ? `（${checkpoint.gap_text}）` : ''}`,
      )
    }
  }
  let sent = 0
  for (const { item, lines } of groups.values()) {
    try {
      const notification = new Notification(`🧫 ${item.experiment_name} 需要检查`, {
        body: lines.slice(0, 3).join('、') + (lines.length > 3 ? ` 等 ${lines.length} 个时间点` : ''),
        tag: `celltracker-exp-${item.experiment_id}`,
      })
      notification.onclick = () => {
        window.focus()
        window.location.assign(`/experiments?exp=${item.experiment_id}`)
      }
      sent += 1
    } catch {
      /* 浏览器拒绝时忽略 */
    }
  }
  return sent
}

export function jumpToExperiment(router, experimentId, checkpointId = null) {
  const query = { exp: experimentId }
  if (checkpointId) query.check = checkpointId
  router.push({ path: '/experiments', query })
}
