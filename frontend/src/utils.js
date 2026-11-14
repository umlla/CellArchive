export function fmtNum(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (Number.isNaN(number)) return '—'
  return number.toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })
}

export function fmtInt(value) {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

export function fmtPct(value) {
  if (value === null || value === undefined) return '—'
  return `${(Number(value) * 100).toFixed(0)}%`
}

export function todayISO() {
  const now = new Date()
  const offset = now.getTimezoneOffset()
  return new Date(now.getTime() - offset * 60 * 1000).toISOString().slice(0, 10)
}

export function daysFromToday(dateString) {
  if (!dateString) return null
  const target = new Date(`${dateString}T00:00:00`)
  const today = new Date(`${todayISO()}T00:00:00`)
  return Math.round((target - today) / 86400000)
}

export function remainingMeta(days) {
  if (days === null || days === undefined) {
    return { text: '未设置', type: 'info', color: 'muted' }
  }
  if (days < 0) return { text: `逾期 ${Math.abs(days)} 天`, type: 'danger', color: 'danger' }
  if (days === 0) return { text: '今天传代', type: 'danger', color: 'danger' }
  if (days <= 2) return { text: `还剩 ${days} 天`, type: 'warning', color: 'warning' }
  return { text: `还剩 ${days} 天`, type: 'success', color: 'success' }
}

export function statusTagType(status) {
  return {
    良好: 'success',
    一般: 'warning',
    较差: 'danger',
    污染: 'danger',
    在库: 'success',
    已复苏: 'warning',
    已丢弃: 'info',
  }[status] || 'info'
}

export function cellStatusClass(status) {
  return {
    良好: 'good',
    一般: 'fair',
    较差: 'poor',
    污染: 'contaminated',
  }[status] || 'muted'
}

export function initials(name) {
  const text = String(name || '').trim()
  return text.slice(0, 2).toUpperCase()
}

export function sumBy(list, key) {
  return (list || []).reduce((total, item) => total + (Number(item[key]) || 0), 0)
}

export function downloadUrl(url) {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

export function boxLabel(box) {
  return box ? box : '未命名冻存盒'
}

// ---------------- 细胞实验日程 ----------------
// 时间统一用 'YYYY-MM-DD HH:MM' 字符串在前后端之间传递，
// 这里把 Date 对象转成后端认识的本地时间写法（不走 toISOString，避免时区偏移）
export function toLocalMinute(value) {
  if (!value) return null
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return null
  const pad = (number) => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

export function fromLocalMinute(text) {
  if (!text) return null
  const normalized = String(text).replace(' ', 'T')
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

/** 默认首次检查时间：下一个整点（若已过 20 点则顺延到次日 9 点） */
export function defaultFirstDue() {
  const now = new Date()
  const next = new Date(now)
  next.setSeconds(0, 0)
  next.setMinutes(0)
  next.setHours(now.getHours() + 1)
  // 夜间（20:00 之后）默认排到第二天早上 9 点
  if (now.getHours() >= 20) {
    next.setDate(next.getDate() + 1)
    next.setHours(9, 0, 0, 0)
  }
  return next
}

export function checkStateMeta(state) {
  return (
    {
      overdue: { label: '已逾期', type: 'danger', className: 'overdue' },
      due: { label: '待检查', type: 'warning', className: 'due' },
      upcoming: { label: '即将到点', type: 'primary', className: 'upcoming' },
      scheduled: { label: '计划中', type: 'info', className: 'scheduled' },
      done: { label: '已完成', type: 'success', className: 'done' },
    }[state] || { label: '—', type: 'info', className: 'scheduled' }
  )
}

export function experimentStatusMeta(status) {
  return (
    {
      active: { label: '进行中', type: 'success' },
      paused: { label: '已暂停', type: 'warning' },
      done: { label: '已完成', type: 'info' },
      aborted: { label: '已终止', type: 'danger' },
    }[status] || { label: status || '—', type: 'info' }
  )
}

/** 间隔文案（前端兜底：24h → 1d（每 1 天）） */
export function intervalText(value, unit) {
  if (!value) return '未设置'
  const number = Number(value)
  const text = Number.isInteger(number) ? String(number) : String(Number(number.toFixed(2)))
  if (unit === 'd') return `${text}d（每 ${text} 天）`
  if (unit === 'm') return `${text}m（每 ${text} 分钟）`
  if (number % 24 === 0 && number >= 24) return `${text}h（${number / 24}d · 每 ${text} 小时）`
  return `${text}h（每 ${text} 小时）`
}
