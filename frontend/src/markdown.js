/**
 * 轻量 Markdown 渲染器（零依赖）。
 *
 * 只支持记录课题讨论够用的子集：
 *   # 标题、**加粗**、*斜体*、`代码`、```代码块```、
 *   - 无序列表、1. 有序列表、> 引用、[链接](url)、分隔线、段落
 *
 * 不支持表格与内嵌 HTML（保持轻快，也避免注入风险）。
 * 所有文本先做 HTML 转义，再生成标签，因此内容里的 <script> 只会原样显示。
 */

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 行内语法：先转义，再处理 **粗体** / *斜体* / `代码` / [链接] */
function inline(text) {
  // 用占位符保护行内代码，避免里面的符号被当成语法
  const codes = []
  let out = escapeHtml(text).replace(/`([^`]+)`/g, (_, code) => {
    codes.push(code)
    return `\u0000CODE${codes.length - 1}\u0000`
  })

  // 链接：只允许 http/https/相对路径，防止 javascript: 伪协议
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, url) => {
    const safe = /^(https?:\/\/|\/|#)/i.test(url) ? url : '#'
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${label}</a>`
  })

  out = out
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')

  return out.replace(/\u0000CODE(\d+)\u0000/g, (_, index) => `<code>${codes[Number(index)]}</code>`)
}

/**
 * 把 Markdown 文本渲染为 HTML 字符串。
 */
export function renderMarkdown(source) {
  if (!source) return ''
  const lines = String(source).replace(/\r\n/g, '\n').split('\n')
  const html = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    // 代码块
    if (/^```/.test(line.trim())) {
      const buffer = []
      index += 1
      while (index < lines.length && !/^```/.test(lines[index].trim())) {
        buffer.push(lines[index])
        index += 1
      }
      index += 1 // 跳过结束的 ```
      html.push(`<pre><code>${escapeHtml(buffer.join('\n'))}</code></pre>`)
      continue
    }

    // 空行
    if (!line.trim()) {
      index += 1
      continue
    }

    // 标题
    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`)
      index += 1
      continue
    }

    // 分隔线
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      html.push('<hr />')
      index += 1
      continue
    }

    // 引用（连续的 > 行合并）
    if (/^>\s?/.test(line)) {
      const buffer = []
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        buffer.push(lines[index].replace(/^>\s?/, ''))
        index += 1
      }
      html.push(`<blockquote>${inline(buffer.join(' '))}</blockquote>`)
      continue
    }

    // 无序列表
    if (/^\s*[-*+]\s+/.test(line)) {
      const items = []
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+]\s+/, ''))
        index += 1
      }
      html.push(`<ul>${items.map((item) => `<li>${inline(item)}</li>`).join('')}</ul>`)
      continue
    }

    // 有序列表
    if (/^\s*\d+\.\s+/.test(line)) {
      const items = []
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ''))
        index += 1
      }
      html.push(`<ol>${items.map((item) => `<li>${inline(item)}</li>`).join('')}</ol>`)
      continue
    }

    // 普通段落：连续非空行合并为一个段落
    const paragraph = []
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^```/.test(lines[index].trim()) &&
      !/^#{1,6}\s+/.test(lines[index]) &&
      !/^>\s?/.test(lines[index]) &&
      !/^\s*[-*+]\s+/.test(lines[index]) &&
      !/^\s*\d+\.\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index])
      index += 1
    }
    html.push(`<p>${inline(paragraph.join(' '))}</p>`)
  }

  return html.join('\n')
}

/** 取纯文本摘要，用于列表预览。 */
export function markdownSummary(source, limit = 120) {
  if (!source) return ''
  const text = String(source)
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#>*`_-]/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}
