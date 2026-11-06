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

const axisLine = { lineStyle: { color: '#e5e7eb' } }
const axisLabel = { color: '#6b7280', fontSize: 11 }
const splitLine = { lineStyle: { color: '#f1f5f4', type: 'dashed' } }

const baseGrid = { left: 58, right: 64, top: 42, bottom: 38 }

export function batchGrowthOption(records, batchName = '') {
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
        lineStyle: { width: 2.4 },
        areaStyle: { opacity: 0.06 },
      },
      {
        name: '单次PD',
        type: 'line',
        data: (records || []).map((record) => record.pd),
        lineStyle: { type: 'dotted', width: 1.6 },
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

export function groupCurvesOption(curves) {
  const dates = curves?.dates || []
  const series = (curves?.series || []).map((item, index) => ({
    name: item.ended ? `${item.batch_name}（已终止）` : item.name,
    type: 'line',
    smooth: true,
    symbolSize: 5,
    connectNulls: true,
    data: item.points.map((point) => [point.date, point.value]),
    lineStyle: {
      width: item.ended ? 1.6 : 2.2,
      type: item.ended ? 'dashed' : 'solid',
      color: palette[index % palette.length],
    },
    itemStyle: { color: palette[index % palette.length] },
  }))
  return {
    color: palette,
    grid: { left: 58, right: 24, top: 52, bottom: 38 },
    tooltip: { trigger: 'axis' },
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
      data: dates,
      boundaryGap: false,
      axisLine,
      axisLabel,
      axisTick: { show: false },
    },
    yAxis: {
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

  const series = (curves?.series || []).map((item, index) => {
    const color = palette[index % palette.length]
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
    : (curves?.normalize ? '相对 PD' : '累计 PD')

  return {
    color: palette,
    grid: { left: 58, right: 24, top: 56, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => (value === null || value === undefined ? '—' : value),
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
      name: basis === 'elapsed' ? '距首条记录（天）' : '',
      nameLocation: 'end',
      nameTextStyle: { color: '#9ca3af', fontSize: 11 },
      axisLine,
      axisLabel,
      axisTick: { show: false },
    },
    yAxis: {
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
    .filter((row) => row.avg_pd_per_day !== null && row.avg_pd_per_day !== undefined)
    .sort((a, b) => a.avg_pd_per_day - b.avg_pd_per_day)
  return {
    color: palette,
    grid: { left: 120, right: 40, top: 20, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const item = params[0]
        return `${item.name}<br/>平均 ${Number(item.value).toFixed(3)} PD/天`
      },
    },
    xAxis: {
      type: 'value',
      name: 'PD / 天',
      nameTextStyle: { color: '#9ca3af', fontSize: 11 },
      axisLine: { show: false },
      axisLabel,
      splitLine,
    },
    yAxis: {
      type: 'category',
      data: sorted.map((row) => `${row.cell_line}`),
      axisLine: { show: false },
      axisLabel: { color: '#4b5563', fontSize: 11 },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        barWidth: 14,
        data: sorted.map((row) => Number(row.avg_pd_per_day.toFixed(3))),
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
          color: (params) => palette[params.dataIndex % palette.length],
        },
        label: { show: true, position: 'right', formatter: (p) => Number(p.value).toFixed(2), color: '#6b7280', fontSize: 11 },
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
