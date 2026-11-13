export const palette = [
  '#0f766e',
  '#2563eb',
  '#d97706',
  '#be123c',
  '#7c3aed',
  '#059669',
  '#db2777',
  '#0891b2',
  '#ca8a04',
  '#4b5563',
]

// 没有物种信息时的兜底色，与后端 palette._NO_SPECIES_COLOR 保持一致
export const NO_SPECIES_COLOR = '#94a3b8'

// 后端按「物种 + 细胞株」算好的固定颜色；前端只读不自己算，
// 保证看板、曲线、对比、速率图里同一细胞株永远是同一个颜色
const colorRegistry = { lines: {}, species: {} }

export function registerSpeciesColors(speciesColors) {
  colorRegistry.lines = {}
  colorRegistry.species = {}
  for (const item of speciesColors?.lines || []) {
    colorRegistry.lines[item.cell_line_id] = item.color
  }
  for (const item of speciesColors?.species || []) {
    colorRegistry.species[item.species || ''] = item.color
  }
}

export function lineColor(lineId) {
  return colorRegistry.lines[lineId] || NO_SPECIES_COLOR
}

export function speciesColor(species) {
  return colorRegistry.species[species || ''] || NO_SPECIES_COLOR
}

// 同细胞株不同批次的次要曲线：主色调浅，保持「同色系」
export function lighten(hex, amount = 0.18) {
  const value = String(hex || '').replace('#', '')
  if (value.length !== 6) return hex
  const channels = [0, 2, 4].map((index) => parseInt(value.slice(index, index + 2), 16))
  return `#${channels
    .map((channel) => Math.round(channel + (255 - channel) * amount).toString(16).padStart(2, '0'))
    .join('')}`
}

const axisLine = { lineStyle: { color: '#e5e7eb' } }
const axisLabel = { color: '#6b7280', fontSize: 11 }
const splitLine = { lineStyle: { color: '#f1f5f4', type: 'dashed' } }

const baseGrid = { left: 58, right: 64, top: 42, bottom: 38 }

// 估算文本像素宽度：中日韩字符按整字宽，其余按 0.56 字宽。
// 只用来给纵轴标签留出空间，宁可略宽也不要让标签被裁掉。
function textWidth(text, fontSize = 11) {
  let width = 0
  for (const char of String(text ?? '')) {
    width += /[\u2e80-\u9fff\uff00-\uffef\u3000-\u303f]/.test(char) ? fontSize : fontSize * 0.56
  }
  return width
}

export function batchGrowthOption(records, batchName = '', lineId = null) {
  // 累计 PD 用该细胞株的颜色，与组内曲线、速率图保持一致
  const lineColorValue = lineColor(lineId)
  const dates = (records || []).map((record) => record.date)
  const harvested = (records || []).map((record) =>
    record.harvested_cells > 0 ? record.harvested_cells : null,
  )
  return {
    color: palette,
    grid: { ...baseGrid, top: 46 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: {
      top: 6,
      right: 10,
      type: 'scroll',
      icon: 'roundRect',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#4b5563', fontSize: 11 },
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine,
      axisLabel,
      axisTick: { show: false },
    },
    yAxis: [
      {
        type: 'value',
        name: 'PD',
        nameTextStyle: { color: '#9ca3af', fontSize: 11 },
        axisLine: { show: false },
        axisLabel,
        splitLine,
      },
      {
        type: 'log',
        position: 'right',
        axisLine: { show: false },
        axisLabel,
        splitLine: { show: false },
        minorSplitLine: { show: false },
      },
    ],
    series: [
      {
        name: '累计PD',
        type: 'line',
        smooth: true,
        symbolSize: 6,
        data: (records || []).map((record) => record.cumulative_pd),
        lineStyle: { width: 2.4, color: lineColorValue },
        itemStyle: { color: lineColorValue },
        areaStyle: { opacity: 0.06, color: lineColorValue },
      },
      {
        name: '单次PD',
        type: 'line',
        data: (records || []).map((record) => record.pd),
        lineStyle: { type: 'dotted', width: 1.6, color: lighten(lineColorValue, 0.4) },
        itemStyle: { color: lighten(lineColorValue, 0.4) },
        symbolSize: 4,
      },
      {
        name: '收获细胞数（×10⁵）',
        type: 'line',
        yAxisIndex: 1,
        data: harvested,
        connectNulls: false,
        lineStyle: { type: 'dashed', width: 1.5, color: '#d97706' },
        itemStyle: { color: '#d97706' },
        symbolSize: 4,
      },
    ],
  }
}

export function groupCurvesOption(curves, hiddenLines = []) {
  const dates = curves?.dates || []
  // 图例改由页面渲染（按细胞株合并、自动换行、永不分页），
  // 这里只负责按隐藏集合过滤曲线
  const hidden = new Set((hiddenLines || []).map((id) => Number(id)))
  const series = (curves?.series || [])
    .filter((item) => !hidden.has(Number(item.cell_line_id)))
    .map((item) => {
      // 颜色由后端按细胞株给定：同一物种相近、同一细胞株恒定
      const color = item.color || lineColor(item.cell_line_id)
      return {
        name: item.ended ? `${item.batch_name}（已终止）` : item.name,
        type: 'line',
        smooth: true,
        symbolSize: 5,
        connectNulls: true,
        data: item.points.map((point) => [point.date, point.value]),
        lineStyle: {
          width: item.ended ? 1.6 : 2.2,
          type: item.ended ? 'dashed' : 'solid',
          color,
        },
        itemStyle: { color },
      }
    })
  return {
    color: palette,
    grid: { left: 66, right: 24, top: 18, bottom: 38 },
    tooltip: {
      trigger: 'axis',
      confine: true,
      valueFormatter: (value) => {
        if (value === null || value === undefined) return '—'
        return curves?.normalize ? `${value} 倍` : value
      },
    },
    legend: { show: false },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine,
      axisLabel,
      axisTick: { show: false },
    },
    yAxis: curves?.normalize
      ? {
          type: 'log',
          logBase: 10,
          min: 1,
          name: '扩增倍数',
          nameTextStyle: { color: '#9ca3af', fontSize: 11 },
          axisLine: { show: false },
          axisLabel: { ...axisLabel, formatter: (value) => `${value}×` },
          splitLine,
          minorSplitLine: { show: false },
        }
      : {
          type: 'value',
          axisLine: { show: false },
          axisLabel,
          splitLine,
        },
    series,
  }
}

export const compareMetrics = [
  { value: 'cumulative', label: '累计 PD' },
  { value: 'pd_per_day', label: 'PD/天' },
]

export function compareCurvesOption(curves, metric = 'cumulative') {
  const basis = curves?.basis || 'date'
  const xKey = basis === 'elapsed' ? 'day' : 'date'
  // 标准化后是扩增倍数，跨度可达上千倍，用对数轴才能看出差异
  const logAxis = metric !== 'pd_per_day' && Boolean(curves?.normalize)

  const series = (curves?.series || []).map((item) => {
    // 同一细胞株的多个批次共用该细胞株色系，只靠深浅与实/虚线区分
    const color = item.color || lineColor(item.cell_line_id)
    // 首条记录没有「上一次接种」，PD/天 为空，折线从第二个点开始
    const data = item.points.map((point) => {
      const value = metric === 'pd_per_day' ? point.pd_per_day : point.value
      return [point[xKey], value === null || value === undefined ? null : value]
    })
    return {
      name: item.cell_line,
      type: 'line',
      smooth: true,
      symbolSize: 6,
      showSymbol: true,
      connectNulls: false,
      data,
      lineStyle: {
        width: item.ended ? 1.6 : 2.4,
        type: item.ended ? 'dashed' : 'solid',
        color,
      },
      itemStyle: { color },
    }
  })

  const allDates = new Set(curves?.dates || [])
  ;(curves?.series || []).forEach((item) => item.points.forEach((point) => allDates.add(point.date)))
  const dates = [...allDates].sort()
  const elapsed = (curves?.series || []).flatMap((item) => item.points.map((point) => point.day))
  const maxDay = elapsed.length ? Math.max(...elapsed) : 0
  const elapsedAxis = Array.from({ length: maxDay + 1 }, (_, index) => index)

  const yName = metric === 'pd_per_day'
    ? 'PD / 天'
    : (curves?.normalize ? '扩增倍数（相对基准）' : '累计 PD')

  return {
    color: palette,
    grid: { left: 66, right: 24, top: 56, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => {
        if (value === null || value === undefined) return '—'
        return curves?.normalize && metric !== 'pd_per_day' ? `${value} 倍` : value
      },
    },
    legend: {
      top: 6,
      type: 'scroll',
      icon: 'roundRect',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#4b5563', fontSize: 11 },
    },
    xAxis: {
      type: 'category',
      data: basis === 'elapsed' ? elapsedAxis : dates,
      boundaryGap: false,
      name: basis === 'elapsed' ? '距基准点（天）' : '',
      nameLocation: 'end',
      nameTextStyle: { color: '#9ca3af', fontSize: 11 },
      axisLine,
      axisLabel,
      axisTick: { show: false },
    },
    yAxis: logAxis
      ? {
          type: 'log',
          logBase: 10,
          min: 1,
          name: yName,
          nameTextStyle: { color: '#9ca3af', fontSize: 11 },
          axisLine: { show: false },
          axisLabel: { ...axisLabel, formatter: (value) => `${value}×` },
          splitLine,
          minorSplitLine: { show: false },
        }
      : {
          type: 'value',
          name: yName,
          nameTextStyle: { color: '#9ca3af', fontSize: 11 },
          axisLine: { show: false },
          axisLabel,
          splitLine,
        },
    series,
  }
}

export function ratesOption(rates) {
  const sorted = [...(rates || [])]
    .filter((row) => row.overall_pd_per_day !== null && row.overall_pd_per_day !== undefined)
    .sort((a, b) => a.overall_pd_per_day - b.overall_pd_per_day)
  const isEnded = (row) => row.is_active === 0 || row.is_active === false

  // 同一细胞株可能有多个批次，需要靠批次尾号区分
  const nameCounts = {}
  sorted.forEach((row) => {
    nameCounts[row.cell_line] = (nameCounts[row.cell_line] || 0) + 1
  })

  // 纵轴标签拆成两行：第一行细胞株名，第二行「物种 · 批次尾号 · 状态」。
  // 单行标签在窄卡片里放不下会被 ECharts 截断，拆行后长名字也能完整显示。
  const names = sorted.map((row) => row.cell_line)
  const metas = sorted.map((row) => {
    const parts = []
    if (row.species) parts.push(row.species)
    if (nameCounts[row.cell_line] > 1) {
      const tail = String(row.batch_name || '').split('-').pop()
      if (tail && tail !== row.batch_name) parts.push(tail)
    }
    if (isEnded(row)) parts.push('已终止')
    return parts.join(' · ')
  })

  // 按最长标签留左边距，避免标签在卡片左缘被裁掉
  const widest = Math.max(
    0,
    ...names.map((text) => textWidth(text, 11)),
    ...metas.map((text) => textWidth(text, 10)),
  )
  const gridLeft = Math.min(Math.max(76, Math.ceil(widest) + 22), 210)

  // 类别值用下标，保证同一细胞株多批次时 tooltip 能定位到唯一一行
  const keys = sorted.map((_, index) => `r${index}`)
  const byKey = {}
  keys.forEach((key, index) => {
    byKey[key] = sorted[index]
  })
  const fmtPdt = (row) =>
    row.overall_doubling_hours ? `倍增时间 ${row.overall_doubling_hours} h` : '倍增时间 —'

  return {
    color: palette,
    grid: { left: gridLeft, right: 96, top: 24, bottom: 36 },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const item = params[0]
        const row = byKey[item.name]
        if (!row) return item.name
        const lines = [
          `${row.cell_line}${row.species ? `（${row.species}）` : ''}`,
          `批次 ${row.batch_name}`,
          `状态 ${isEnded(row) ? '已终止' : '在养'}`,
          `整段 PD/天 ${row.overall_pd_per_day}`,
          fmtPdt(row),
          `平均 PD/天 ${row.avg_pd_per_day ?? '—'}`,
          `区间数 ${row.interval_count} · 跨度 ${row.span_days} 天`,
        ]
        if (row.cv !== null && row.cv !== undefined) lines.push(`波动 CV ${row.cv}`)
        return lines.join('<br/>')
      },
    },
    xAxis: {
      type: 'value',
      name: '整段 PD / 天',
      nameTextStyle: { color: '#9ca3af', fontSize: 11 },
      axisLine: { show: false },
      axisLabel,
      splitLine,
    },
    yAxis: {
      type: 'category',
      data: keys,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        interval: 0,
        margin: 10,
        align: 'right',
        formatter: (key) => {
          const index = Number(String(key).slice(1))
          const meta = metas[index]
          return meta ? `{n|${names[index]}}\n{m|${meta}}` : `{n|${names[index]}}`
        },
        rich: {
          n: { fontSize: 11, color: '#374151', lineHeight: 14, align: 'right' },
          m: { fontSize: 10, color: '#9ca3af', lineHeight: 13, align: 'right' },
        },
      },
    },
    series: [
      {
        type: 'bar',
        barWidth: 16,
        data: sorted.map((row) => ({
          value: Number(row.overall_pd_per_day.toFixed(3)),
          itemStyle: {
            // 与累计 PD 曲线同色：柱子的颜色就是该细胞株的颜色
            color: row.color || lineColor(row.cell_line_id),
            opacity: isEnded(row) ? 0.55 : 1,
          },
        })),
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
        },
        label: {
          show: true,
          position: 'right',
          formatter: (params) => {
            const row = sorted[params.dataIndex]
            const value = Number(params.value).toFixed(2)
            return row.overall_doubling_hours
              ? `${value} · ${row.overall_doubling_hours}h`
              : value
          },
          color: '#6b7280',
          fontSize: 11,
        },
      },
    ],
  }
}

export function monthlyOption(months) {
  return {
    color: palette,
    grid: { left: 44, right: 16, top: 24, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: (months || []).map((row) => row.month.slice(2)),
      axisLine,
      axisLabel,
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel,
      splitLine,
      minInterval: 1,
    },
    series: [
      {
        type: 'bar',
        barWidth: 18,
        data: (months || []).map((row) => row.count),
        itemStyle: { borderRadius: [5, 5, 0, 0], color: '#14b8a6' },
      },
    ],
  }
}
