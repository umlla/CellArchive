<template>
  <div v-loading="loading">
    <div class="stat-grid">
      <StatTile
        label="在养细胞株"
        :value="dashboard?.stats?.active_cell_lines ?? '—'"
        icon="Collection"
        hint="有活跃批次的细胞株 · 点击查看"
        class="clickable-tile"
        @click="openLineList"
      />
      <StatTile
        label="在养批次"
        :value="dashboard?.stats?.active_batches ?? '—'"
        icon="Histogram"
        hint="复苏中的培养批次 · 点击查看"
        tint="rgba(37, 99, 235, 0.08)"
        class="clickable-tile"
        @click="openBatchDialog"
      />
      <StatTile
        label="需要传代"
        :value="dashboard?.due_soon?.length ?? '—'"
        icon="AlarmClock"
        hint="3 天内或已逾期 · 点击查看"
        tint="rgba(196, 127, 23, 0.1)"
        class="clickable-tile"
        @click="dueDialogVisible = true"
      />
      <StatTile
        label="在库冻存管"
        :value="dashboard?.stats?.in_stock_vials ?? '—'"
        icon="Box"
        hint="状态为「在库」的冻存管 · 点击查看"
        tint="rgba(190, 18, 60, 0.08)"
        class="clickable-tile"
        @click="openVialDialogList"
      />
    </div>

    <div class="panel">
      <div class="panel-head" style="padding-bottom: 0; border-bottom: none">
        <el-tabs v-model="mode" style="width: 100%" @tab-change="onTabChange">
          <el-tab-pane label="按细胞株查看" name="line" />
          <el-tab-pane label="按细胞组查看" name="group" />
        </el-tabs>
      </div>

      <!-- ==================== 按细胞株 ==================== -->
      <div v-if="mode === 'line'" class="line-layout">
        <aside class="line-list">
          <div style="padding: 12px">
            <el-input v-model="search" placeholder="搜索细胞株" clearable size="default">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </div>
          <div class="line-items">
            <button
              v-for="line in filteredLines"
              :key="line.id"
              :class="['line-item', { active: line.id === selectedLineId }]"
              @click="selectLine(line.id)"
            >
              <span class="line-item-main">
                <span class="line-name">{{ line.name }}</span>
                <span class="line-sub">
                  {{ line.type || '—' }} · {{ line.active_batch_count }} 个在养批次
                </span>
              </span>
              <span class="line-count" :class="{ zero: !line.active_batch_count }" :title="`在养批次 ${line.active_batch_count} 个`">
                {{ line.active_batch_count }}
              </span>
            </button>
            <div v-if="!filteredLines.length" class="empty-hint" style="padding: 26px 12px">
              <span class="icon">🧫</span>没有匹配的细胞株
            </div>
          </div>
        </aside>

        <section class="line-detail">
          <div v-if="lineDetail" class="line-detail-inner">
            <div class="line-head">
              <div>
                <div class="row" style="gap: 8px">
                  <h2 style="margin: 0; font-size: 19px">{{ lineDetail.cell_line.name }}</h2>
                  <el-tag size="small" effect="plain">{{ lineDetail.cell_line.type || '未分类' }}</el-tag>
                </div>
                <p class="small muted" style="margin: 6px 0 0">
                  默认传代间隔 {{ lineDetail.cell_line.default_passage_interval || 0 }} 天 ·
                  首次复苏 {{ lineDetail.cell_line.revival_date || '—' }} ·
                  共 {{ lineDetail.cell_line.batch_count }} 个批次
                  <template v-if="lineDetail.cell_line.notes"> · {{ lineDetail.cell_line.notes }}</template>
                </p>
              </div>
              <div class="row">
                <el-button
                  size="small"
                  type="primary"
                  :disabled="!activeBatches.length"
                  @click="openRecordEntry(lineDetail.cell_line.id, activeBatches[0]?.id)"
                >
                  ＋ 录入传代
                </el-button>
                <el-switch v-model="includeEnded" active-text="显示已终止" @change="reloadLine" />
                <el-button
                  v-if="endedBatches.length"
                  size="small"
                  type="warning"
                  plain
                  @click="restoreLineBatches"
                >
                  撤销全部终止（{{ endedBatches.length }}）
                </el-button>
                <el-button size="small" @click="openLineEdit">编辑信息</el-button>
              </div>
            </div>

            <div class="row between" style="margin: 16px 0 10px">
              <h3 style="margin: 0; font-size: 14px">🧪 培养批次</h3>
              <span class="small faint">共 {{ lineDetail.batches.length }} 个</span>
            </div>

            <div v-if="lineDetail.batches.length" class="batch-grid">
              <BatchCard
                v-for="batch in lineDetail.batches"
                :key="batch.id"
                :batch="batch"
                @refresh="reloadAll"
                @record="(target) => openRecordEntry(lineDetail.cell_line.id, target.id)"
              />
            </div>
            <div v-else class="empty-hint">
              <span class="icon">🧪</span>该细胞株还没有培养批次
              <div style="margin-top: 10px">
                <el-button type="primary" size="small" @click="$router.push('/batches/new')">新建批次</el-button>
              </div>
            </div>

            <div class="row between" style="margin: 22px 0 10px">
              <h3 style="margin: 0; font-size: 14px">❄️ 冻存状态</h3>
              <div class="row" style="gap: 12px">
                <span class="small faint">
                  共 {{ lineDetail.vials.length }} 支 · 总细胞数 {{ fmtNum(totalVialCells) }}
                </span>
                <el-button size="small" type="primary" plain @click="openVialDialog">
                  ＋ 新增冻存管
                </el-button>
              </div>
            </div>
            <el-table v-if="lineDetail.vials.length" :data="lineDetail.vials" size="small" max-height="260">
              <el-table-column prop="freeze_date" label="冻存日期" width="110" />
              <el-table-column prop="location" label="位置" min-width="160" show-overflow-tooltip />
              <el-table-column label="细胞数" width="110" align="right">
                <template #default="{ row }">{{ fmtNum(row.cell_count) }}</template>
              </el-table-column>
              <el-table-column label="PD" width="76" align="right">
                <template #default="{ row }">{{ row.pd === null || row.pd === undefined ? '—' : fmtNum(row.pd) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusTagType(row.status)" effect="light">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
            <div v-else class="empty-hint" style="padding: 22px">
              <span class="icon">❄️</span>暂无冻存记录
            </div>
          </div>
          <div v-else class="empty-hint">
            <span class="icon">🧬</span>从左侧选择一个细胞株
          </div>
        </section>
      </div>

      <!-- ==================== 按细胞组 ==================== -->
      <div v-else>
        <div class="group-toolbar">
          <el-select v-model="selectedGroupId" placeholder="选择细胞组" style="width: 220px" @change="loadGroupAll">
            <el-option v-for="group in groups" :key="group.id" :label="`${group.group_name}（${group.member_count}）`" :value="group.id" />
          </el-select>
          <el-button
            size="small"
            type="primary"
            :disabled="!selectedGroupId || !groupStatus.length"
            @click="openRecordEntry(null, null, selectedGroupId)"
          >
            ＋ 录入传代
          </el-button>
          <el-button size="small" :disabled="!selectedGroupId" @click="terminateGroupVisible = true">批量终止</el-button>
          <el-button size="small" :disabled="!selectedGroupId" @click="openGroupBatchCreate">批量新建批次</el-button>
          <div class="row" style="margin-left: auto">
            <el-checkbox v-model="exportAll" size="small">导出含已终止</el-checkbox>
            <el-button size="small" :disabled="!selectedGroupId" @click="exportGroup">导出 Excel</el-button>
          </div>
        </div>

        <div style="padding: 16px 18px">
          <div v-if="!groups.length" class="empty-hint">
            <span class="icon">📂</span>还没有细胞组
            <div style="margin-top: 10px"><el-button size="small" @click="$router.push('/groups')">去创建</el-button></div>
          </div>
          <template v-else>
            <div class="row between" style="margin-bottom: 10px">
              <span class="small muted">组内活跃批次（{{ groupStatus.length }}）</span>
              <span class="small faint">红色=已逾期 · 黄色=2 天内 · 绿色=时间充裕</span>
            </div>
            <el-table :data="groupStatus" size="small" :row-class-name="rowClass" max-height="440">
              <el-table-column prop="cell_name" label="细胞株" min-width="130" fixed />
              <el-table-column prop="batch_name" label="批次" min-width="150" show-overflow-tooltip />
              <el-table-column prop="type" label="类型" width="76" />
              <el-table-column label="代次" width="64" align="center">
                <template #default="{ row }">P{{ row.passage ?? '—' }}</template>
              </el-table-column>
              <el-table-column prop="last_passage" label="上次传代" width="104" />
              <el-table-column prop="inoculum_dishes" label="盘数" width="60" align="center" />
              <el-table-column label="细胞总数" width="94" align="right">
                <template #default="{ row }">{{ fmtNum(row.inoculum_cells) }}</template>
              </el-table-column>
              <el-table-column label="累计PD" width="80" align="right">
                <template #default="{ row }">{{ fmtNum(row.cumulative_pd) }}</template>
              </el-table-column>
              <el-table-column prop="status" label="状态" width="70" align="center" />
              <el-table-column prop="next_passage_date" label="下次传代" width="104" />
              <el-table-column label="剩余" width="104">
                <template #default="{ row }">
                  <span :class="['remaining-dot', remainingMeta(row.remaining_days).type]">
                    {{ remainingMeta(row.remaining_days).text }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="" width="46" align="center">
                <template #default="{ row }">
                  <el-button link size="small" @click="$router.push({ path: '/', query: { mode: 'line', line: row.cell_line_id } })">
                    查看
                  </el-button>
                </template>
              </el-table-column>
            </el-table>

            <div class="charts-grid section-gap">
              <div class="panel">
                <div class="panel-head">
                  <div>
                    <h2>📊 增殖速度对比</h2>
                    <p class="sub">整段 PD/天 · 柱子右侧为倍增时间</p>
                  </div>
                </div>
                <div class="panel-body">
                  <Chart
                    v-if="rateRowsSorted.length"
                    :option="ratesOpt"
                    :height="`${Math.max(200, rateRowsSorted.length * 46 + 40)}px`"
                  />
                  <div v-else class="empty-hint" style="padding: 26px">
                    <span class="icon">📊</span>组内还没有足够记录计算速率
                  </div>
                </div>
              </div>

              <div class="panel">
                <div class="panel-head" style="align-items: flex-start">
                  <div>
                    <h2>📈 组内生长曲线</h2>
                    <p class="sub">累计 PD 随日期变化</p>
                  </div>
                  <div class="curves-controls">
                    <el-switch v-model="normalize" active-text="标准化" size="small" @change="onNormalizeChange" />
                    <el-select
                      v-if="normalize"
                      v-model="startDate"
                      placeholder="起始日期"
                      size="small"
                      style="width: 132px"
                      @change="loadCurves"
                    >
                      <el-option v-for="day in curves.dates || []" :key="day" :label="day" :value="day" />
                    </el-select>
                  </div>
                </div>
                <div class="panel-body">
                  <div v-if="curves.ended_batches?.length" class="row wrap" style="margin-bottom: 8px; gap: 6px">
                    <span class="small faint">已终止批次：</span>
                    <el-checkbox-group v-model="endedIds" size="small" @change="loadCurves">
                      <el-checkbox
                        v-for="batch in curves.ended_batches"
                        :key="batch.batch_id"
                        :value="batch.batch_id"
                      >
                        {{ batch.cell_line }} · {{ batch.batch_name }}
                      </el-checkbox>
                    </el-checkbox-group>
                  </div>
                  <Chart v-if="curves.series?.length" :option="curvesOpt" height="320px" />
                  <div v-else class="empty-hint" style="padding: 40px">
                    <span class="icon">📈</span>组内尚无传代记录
                  </div>
                  <div v-if="normalize && curves.skipped?.length" class="small faint" style="margin-top: 8px">
                    未参与标准化：{{ curves.skipped.map((item) => `批次 #${item.batch_id}（${item.reason}）`).join('；') }}
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 编辑细胞株 -->
    <el-dialog v-model="lineEditVisible" title="编辑细胞株信息" width="min(540px, 94vw)">
      <el-form v-if="lineForm" :model="lineForm" label-width="110px" label-position="left">
        <el-form-item label="名称"><el-input v-model="lineForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="lineForm.type" style="width: 100%">
            <el-option label="永生化" value="永生化" />
            <el-option label="原代" value="原代" />
          </el-select>
        </el-form-item>
        <el-form-item label="默认间隔（天）">
          <el-input-number v-model="lineForm.default_passage_interval" :min="0" :step="1" />
        </el-form-item>
        <el-form-item label="首次复苏日期">
          <el-date-picker v-model="lineForm.revival_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="lineForm.notes" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="lineEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingLine" @click="saveLine">保存</el-button>
      </template>
    </el-dialog>

    <!-- 在养批次明细 -->
    <el-dialog v-model="batchDialogVisible" title="在养批次" width="min(900px, 94vw)" top="8vh">
      <div v-if="activeBatchRows.length">
        <div class="small muted" style="margin-bottom: 10px">
          共 {{ activeBatchRows.length }} 个批次正在培养，点击「查看」跳转到对应细胞株。
        </div>
        <el-table :data="activeBatchRows" size="small" max-height="480">
          <el-table-column prop="cell_line" label="细胞株" min-width="130" fixed />
          <el-table-column prop="batch_name" label="批次" min-width="150" show-overflow-tooltip />
          <el-table-column label="代次" width="64" align="center">
            <template #default="{ row }">P{{ row.passage ?? '—' }}</template>
          </el-table-column>
          <el-table-column prop="last_passage" label="上次传代" width="104" />
          <el-table-column label="累计PD" width="86" align="right">
            <template #default="{ row }">{{ fmtNum(row.cumulative_pd) }}</template>
          </el-table-column>
          <el-table-column prop="next_passage_date" label="下次传代" width="104" />
          <el-table-column label="剩余" width="104">
            <template #default="{ row }">
              <span :class="['remaining-dot', remainingMeta(row.remaining_days).type]">
                {{ remainingMeta(row.remaining_days).text }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="132" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="jumpToLine(row)">查看</el-button>
              <el-button link type="primary" size="small" @click="openRecordEntry(row.cell_line_id, row.batch_id)">录入</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div v-else class="empty-hint">
        <span class="icon">🧪</span>当前没有在养批次
      </div>
      <template #footer>
        <el-button @click="batchDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 在库冻存管明细 -->
    <el-dialog v-model="vialListVisible" title="在库冻存管" width="min(920px, 94vw)" top="8vh">
      <div v-if="vialListRows.length">
        <div class="small muted" style="margin-bottom: 10px">
          共 {{ vialListRows.length }} 支在库，按冻存日期倒序显示。
        </div>
        <el-table :data="vialListRows" size="small" max-height="480">
          <el-table-column prop="cell_name" label="细胞株" min-width="130" fixed />
          <el-table-column prop="freeze_date" label="冻存日期" width="110" />
          <el-table-column label="位置" min-width="170" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.location">{{ row.location }}</span>
              <span v-else class="small faint">未填写</span>
            </template>
          </el-table-column>
          <el-table-column label="细胞数" width="96" align="right">
            <template #default="{ row }">{{ fmtNum(row.cell_count) }}</template>
          </el-table-column>
          <el-table-column label="PD" width="76" align="right">
            <template #default="{ row }">{{ row.pd === null || row.pd === undefined ? '—' : fmtNum(row.pd) }}</template>
          </el-table-column>
          <el-table-column prop="notes" label="备注" min-width="120" show-overflow-tooltip />
          <el-table-column label="操作" width="76" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="jumpToVialLine(row)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div v-else class="empty-hint">
        <span class="icon">❄️</span>当前没有在库冻存管
      </div>
      <template #footer>
        <el-button @click="vialListVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 录入传代记录 -->
    <RecordEntryDialog
      v-model="recordEntryVisible"
      :groups="groups"
      :lines="lines"
      :default-line-id="recordEntryLineId"
      :default-batch-id="recordEntryBatchId"
      :default-group-id="recordEntryGroupId"
      @saved="reloadAll"
    />

    <!-- 需要传代的细胞 -->
    <el-dialog v-model="dueDialogVisible" title="需要传代的细胞" width="min(880px, 94vw)" top="8vh">
      <div v-if="dashboard?.due_soon?.length">
        <div class="small muted" style="margin-bottom: 10px">
          共 {{ dashboard.due_soon.length }} 个批次在 3 天内到期或已逾期，按建议传代日期排序。
        </div>
        <el-table :data="dashboard.due_soon" size="small" max-height="480">
          <el-table-column prop="cell_line" label="细胞株" min-width="130" fixed />
          <el-table-column prop="batch_name" label="批次" min-width="150" show-overflow-tooltip />
          <el-table-column label="分组" min-width="170">
            <template #default="{ row }">
              <template v-if="(groupsByLine[row.cell_line_id] || []).length">
                <el-tag
                  v-for="name in groupsByLine[row.cell_line_id]"
                  :key="name"
                  size="small"
                  effect="plain"
                  style="margin-right: 4px; margin-bottom: 2px"
                >
                  {{ name }}
                </el-tag>
              </template>
              <span v-else class="small faint">未分组</span>
            </template>
          </el-table-column>
          <el-table-column label="代次" width="60" align="center">
            <template #default="{ row }">P{{ row.passage ?? '—' }}</template>
          </el-table-column>
          <el-table-column prop="next_passage_date" label="建议传代" width="104" />
          <el-table-column label="剩余" width="104">
            <template #default="{ row }">
              <span :class="['remaining-dot', remainingMeta(row.remaining_days).type]">
                {{ remainingMeta(row.remaining_days).text }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="" width="60" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="jumpToLine(row)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div v-else class="empty-hint">
        <span class="icon">✅</span>暂时没有需要传代的细胞
      </div>
      <template #footer>
        <el-button @click="dueDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新增冻存管 -->
    <el-dialog v-model="vialDialogVisible" title="新增冻存管" width="min(540px, 94vw)">
      <div v-if="lineDetail" class="vial-dialog-head">
        <strong>{{ lineDetail.cell_line.name }}</strong>
        <el-tag size="small" effect="plain">{{ lineDetail.cell_line.type || '未分类' }}</el-tag>
        <span v-if="lineCurrentPd !== null && lineCurrentPd !== undefined" class="small faint">
          当前累计 PD {{ fmtNum(lineCurrentPd) }}
        </span>
      </div>
      <el-form :model="vialForm" label-width="112px" label-position="left">
        <el-form-item label="冻存日期">
          <el-date-picker v-model="vialForm.freeze_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="每管细胞数" required>
          <el-input-number v-model="vialForm.cell_count" :min="0.01" :precision="2" :step="0.5" style="width: 100%" />
          <div class="form-tip">单位 ×10⁵ cells，例如填 5 表示每管 5×10⁵</div>
        </el-form-item>
        <el-form-item label="复管数量">
          <el-input-number v-model="vialForm.count" :min="1" :max="200" :step="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="从记录填入">
          <div style="width: 100%">
            <el-select
              v-model="vialPdRecordId"
              clearable
              filterable
              placeholder="选择某次传代记录（可选）"
              style="width: 100%"
              @change="applyPdRecord"
            >
              <el-option
                v-for="record in vialPdRecords"
                :key="record.id"
                :value="record.id"
                :label="pdRecordLabel(record)"
              />
            </el-select>
            <el-radio-group
              v-if="vialPdRecordId"
              v-model="vialPdMode"
              size="small"
              style="margin-top: 8px"
              @change="applyPdRecord"
            >
              <el-radio value="cumulative">累计 PD</el-radio>
              <el-radio value="single">本次 PD</el-radio>
            </el-radio-group>
            <div class="form-tip">用于补录之前传代时冻存的细胞：选一条记录即可自动填入对应 PD</div>
          </div>
        </el-form-item>
        <el-form-item label="冻存 PD">
          <template v-if="isPrimaryLine">
            <el-input-number v-model="vialForm.pd" :min="0" :precision="2" :step="0.1" style="width: 100%" />
            <div class="form-tip">原代细胞必须记录 PD；已自动填入当前累计 PD，可手动修正</div>
          </template>
          <template v-else>
            <el-checkbox v-model="vialIncludePd">记录当前累计 PD</el-checkbox>
            <el-input-number
              v-if="vialIncludePd"
              v-model="vialForm.pd"
              :min="0"
              :precision="2"
              :step="0.1"
              style="width: 100%; margin-top: 6px"
            />
            <div class="form-tip">永生化细胞可以不填 PD，只记录日期和管数</div>
          </template>
        </el-form-item>
        <el-form-item label="存放位置">
          <el-input v-model="vialForm.location" placeholder="可留空，稍后在冻存管页补充" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="vialForm.notes" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="vialDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="vialSaving" @click="saveVial">添加</el-button>
      </template>
    </el-dialog>

    <!-- 批量终止 -->
    <el-dialog v-model="terminateGroupVisible" title="终止组内全部批次" width="min(420px, 92vw)">
      <p class="small muted">将终止「{{ currentGroupName }}」中所有活跃批次。</p>
      <el-form label-width="92px" label-position="left">
        <el-form-item label="终止原因">
          <el-select v-model="groupTerminateReason" style="width: 100%">
            <el-option v-for="item in reasons" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="terminateGroupVisible = false">取消</el-button>
        <el-button type="danger" :loading="terminatingGroup" @click="terminateGroup">确认终止</el-button>
      </template>
    </el-dialog>

    <!-- 批量新建批次 -->
    <el-dialog v-model="groupBatchVisible" title="为组内所有细胞株新建批次" width="min(560px, 94vw)">
      <el-form :model="groupBatchForm" label-width="120px" label-position="left">
        <el-form-item label="复苏日期">
          <el-date-picker v-model="groupBatchForm.revival_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="初始 PD">
          <el-input-number v-model="groupBatchForm.initial_pd" :min="0" :precision="2" :step="0.1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="复苏接种细胞数">
          <el-input-number v-model="groupBatchForm.initial_cell_count" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="冻存来源日期">
          <el-date-picker v-model="groupBatchForm.source_freeze_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="批次备注">
          <el-input v-model="groupBatchForm.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="groupBatchVisible = false">取消</el-button>
        <el-button type="primary" :loading="creatingGroupBatches" @click="createGroupBatches">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { batchApi, groupApi, lineApi, metaApi, vialApi } from '../api'
import { groupCurvesOption, ratesOption } from '../charts'
import { loadMeta } from '../store'
import { daysFromToday, downloadUrl, fmtNum, remainingMeta, statusTagType, todayISO } from '../utils'
import Chart from '../components/Chart.vue'
import StatTile from '../components/StatTile.vue'
import BatchCard from '../components/BatchCard.vue'
import RecordEntryDialog from '../components/RecordEntryDialog.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const dashboard = ref(null)
const lines = ref([])
const groups = ref([])
const search = ref('')
const selectedLineId = ref(null)
const lineDetail = ref(null)
const includeEnded = ref(false)
const mode = ref('line')

const selectedGroupId = ref(null)
const groupStatus = ref([])
const groupRates = ref([])
const curves = ref({ series: [], dates: [], ended_batches: [] })
const normalize = ref(false)
const startDate = ref(null)
const endedIds = ref([])
const exportAll = ref(true)

const lineEditVisible = ref(false)
const lineForm = ref(null)
const savingLine = ref(false)

const vialDialogVisible = ref(false)
const vialIncludePd = ref(true)
const vialSaving = ref(false)
const vialForm = ref(defaultVialForm())
const vialPdRecords = ref([])
const vialPdRecordId = ref(null)
const vialPdMode = ref('cumulative')
const dueDialogVisible = ref(false)

const batchDialogVisible = ref(false)
const activeBatchRows = ref([])
const vialListVisible = ref(false)
const vialListRows = ref([])

const recordEntryVisible = ref(false)
const recordEntryLineId = ref(null)
const recordEntryBatchId = ref(null)
const recordEntryGroupId = ref(null)

const terminateGroupVisible = ref(false)
const groupTerminateReason = ref('其他')
const terminatingGroup = ref(false)
const groupBatchVisible = ref(false)
const creatingGroupBatches = ref(false)
const groupBatchForm = ref({
  revival_date: todayISO(),
  initial_pd: 0,
  initial_cell_count: 0,
  source_freeze_date: todayISO(),
  notes: '',
})

const reasons = ['污染', '全部冻存', '丢弃', '实验结束', '其他']

const filteredLines = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  if (!keyword) return lines.value
  return lines.value.filter((line) => line.name.toLowerCase().includes(keyword))
})

const totalVialCells = computed(() =>
  (lineDetail.value?.vials || []).reduce((total, vial) => total + (Number(vial.cell_count) || 0), 0),
)

const isPrimaryLine = computed(() => lineDetail.value?.cell_line?.type === '原代')

const activeBatches = computed(() =>
  (lineDetail.value?.batches || []).filter((batch) => batch.is_active),
)

const endedBatches = computed(() =>
  (lineDetail.value?.batches || []).filter((batch) => !batch.is_active),
)

// 优先用后端汇总的 latest_pd；旧版后端没有该字段时，从批次当前记录里取
const lineCurrentPd = computed(() => {
  const line = lineDetail.value?.cell_line
  if (!line) return null
  if (line.latest_pd !== null && line.latest_pd !== undefined) return line.latest_pd
  const batches = lineDetail.value?.batches || []
  const candidates = batches
    .filter((batch) => batch.current_record)
    .sort((a, b) => {
      const dateA = a.current_record?.date || ''
      const dateB = b.current_record?.date || ''
      return dateB.localeCompare(dateA) || (b.current_record?.id || 0) - (a.current_record?.id || 0)
    })
  return candidates[0]?.current_record?.cumulative_pd ?? null
})

// 细胞株 → 所属细胞组，供「需要传代」弹窗展示
const groupsByLine = computed(() => {
  const mapping = {}
  for (const group of groups.value) {
    for (const member of group.members || []) {
      if (!mapping[member.cell_line_id]) mapping[member.cell_line_id] = []
      mapping[member.cell_line_id].push(group.group_name)
    }
  }
  return mapping
})

const currentGroupName = computed(
  () => groups.value.find((group) => group.id === selectedGroupId.value)?.group_name || '',
)

const rateRowsSorted = computed(() =>
  [...groupRates.value]
    .filter((row) => row.overall_pd_per_day !== null && row.overall_pd_per_day !== undefined)
    .sort((a, b) => b.overall_pd_per_day - a.overall_pd_per_day),
)
const ratesOpt = computed(() => ratesOption(groupRates.value))
const curvesOpt = computed(() => groupCurvesOption(curves.value))

async function loadBase() {
  const [dash, lineList, groupList] = await Promise.all([
    metaApi.dashboard(),
    lineApi.list(),
    groupApi.list(),
  ])
  dashboard.value = dash
  lines.value = lineList
  groups.value = groupList
  activeBatchRows.value = []
  vialListRows.value = []
}

async function reloadAll() {
  await loadBase()
  if (mode.value === 'line' && selectedLineId.value) await reloadLine()
  if (mode.value === 'group') await loadGroupAll()
}

async function reloadLine() {
  if (!selectedLineId.value) return
  lineDetail.value = await lineApi.detail(selectedLineId.value, includeEnded.value)
}

async function selectLine(id) {
  selectedLineId.value = id
  lineDetail.value = null
  await reloadLine()
}

async function loadGroupAll() {
  if (!selectedGroupId.value) return
  const [statusRows, rateRows] = await Promise.all([
    groupApi.status(selectedGroupId.value),
    groupApi.rates(selectedGroupId.value),
  ])
  groupStatus.value = statusRows
  groupRates.value = rateRows
  normalize.value = false
  endedIds.value = []
  startDate.value = null
  await loadCurves()
}

async function loadCurves() {
  if (!selectedGroupId.value) return
  if (normalize.value && !startDate.value) {
    const first = curves.value.dates?.[0]
    if (first) startDate.value = first
  }
  const data = await groupApi.curves(selectedGroupId.value, {
    normalize: normalize.value,
    start_date: normalize.value ? startDate.value : undefined,
    ended_ids: endedIds.value.join(','),
  })
  curves.value = data
}

function onNormalizeChange(value) {
  if (value && !startDate.value) startDate.value = curves.value.dates?.[0] || null
  loadCurves()
}

function onTabChange() {
  if (mode.value === 'group' && selectedGroupId.value) {
    loadGroupAll()
  }
}

function rowClass({ row }) {
  const days = row.remaining_days
  if (days === null || days === undefined) return ''
  if (days <= 0) return 'row-danger'
  if (days <= 2) return 'row-warning'
  return ''
}

function openLineEdit() {
  const line = lineDetail.value.cell_line
  lineForm.value = {
    id: line.id,
    name: line.name,
    type: line.type || '永生化',
    default_passage_interval: line.default_passage_interval || 0,
    revival_date: line.revival_date,
    notes: line.notes || '',
  }
  lineEditVisible.value = true
}

async function restoreLineBatches() {
  const batches = endedBatches.value
  if (!batches.length) return
  try {
    await ElMessageBox.confirm(
      `撤销「${lineDetail.value.cell_line.name}」的 ${batches.length} 个已终止批次，全部恢复为在养？`,
      '撤销终止',
      { type: 'info', confirmButtonText: '撤销终止', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  let ok = 0
  for (const batch of batches) {
    try {
      await batchApi.restore(batch.id)
      ok += 1
    } catch {
      // 单条失败不阻断其余批次
    }
  }
  ElMessage.success(`已恢复 ${ok} 个批次`)
  await reloadAll()
}

async function saveLine() {
  savingLine.value = true
  try {
    await lineApi.update(lineForm.value.id, lineForm.value)
    ElMessage.success('细胞株信息已更新')
    lineEditVisible.value = false
    await reloadAll()
  } finally {
    savingLine.value = false
  }
}

function defaultVialForm() {
  return {
    freeze_date: todayISO(),
    cell_count: 5,
    count: 1,
    pd: null,
    location: '',
    notes: '',
  }
}

function openVialDialog() {
  if (!lineDetail.value) return
  vialForm.value = {
    ...defaultVialForm(),
    pd: lineCurrentPd.value ?? null,
  }
  vialIncludePd.value = true
  vialPdRecordId.value = null
  vialPdMode.value = 'cumulative'
  vialPdRecords.value = []
  vialDialogVisible.value = true
  loadVialPdRecords()
}

async function loadVialPdRecords() {
  if (!lineDetail.value) return
  const lineId = lineDetail.value.cell_line.id
  try {
    const batches = await lineApi.batches(lineId, true)
    const chunks = await Promise.all(
      batches.map(async (batch) => {
        const rows = await batchApi.records(batch.id)
        return rows.map((row) => ({
          ...row,
          batch_name: batch.batch_name,
          batch_active: batch.is_active,
        }))
      }),
    )
    if (lineDetail.value?.cell_line?.id !== lineId) return
    const records = chunks.flat()
    records.sort(
      (a, b) => (b.date || '').localeCompare(a.date || '') || (b.id || 0) - (a.id || 0),
    )
    vialPdRecords.value = records.slice(0, 200)
  } catch {
    vialPdRecords.value = []
  }
}

function pdRecordLabel(record) {
  const cumulative = record.cumulative_pd ?? '—'
  const single = record.pd ?? '—'
  return `P${record.passage} · ${record.date} · 累计 ${cumulative} / 本次 ${single} · ${record.batch_name}`
}

function applyPdRecord() {
  const record = vialPdRecords.value.find((item) => item.id === vialPdRecordId.value)
  if (!record) return
  const value = vialPdMode.value === 'cumulative' ? record.cumulative_pd : record.pd
  vialForm.value.pd = value ?? 0
  if (!isPrimaryLine.value) vialIncludePd.value = true
}

function jumpToLine(row) {
  dueDialogVisible.value = false
  batchDialogVisible.value = false
  router.push({ path: '/', query: { mode: 'line', line: row.cell_line_id } })
}

function jumpToVialLine(row) {
  vialListVisible.value = false
  router.push({ path: '/', query: { mode: 'line', line: row.cell_line_id } })
}

async function openLineList() {
  mode.value = 'line'
  await nextTick()
  const list = document.querySelector('.line-items')
  if (list) list.scrollTop = 0
}

async function openBatchDialog() {
  batchDialogVisible.value = true
  if (activeBatchRows.value.length) return
  try {
    const rows = await batchApi.list({ is_active: true })
    activeBatchRows.value = rows
      .map((batch) => ({
        batch_id: batch.id,
        batch_name: batch.batch_name,
        cell_line: batch.cell_name,
        cell_line_id: batch.cell_line_id,
        passage: batch.current_record?.passage ?? null,
        last_passage: batch.current_record?.date ?? '—',
        cumulative_pd: batch.cumulative_pd,
        next_passage_date: batch.current_record?.next_passage_date ?? '',
        remaining_days: daysFromToday(batch.current_record?.next_passage_date),
      }))
      .sort((a, b) => (a.remaining_days ?? 9999) - (b.remaining_days ?? 9999))
  } catch {
    activeBatchRows.value = []
  }
}

async function openVialDialogList() {
  vialListVisible.value = true
  if (vialListRows.value.length) return
  try {
    const rows = await vialApi.list({ status: '在库', limit: 500 })
    vialListRows.value = rows
      .slice()
      .sort((a, b) => (b.freeze_date || '').localeCompare(a.freeze_date || ''))
  } catch {
    vialListRows.value = []
  }
}

function openRecordEntry(lineId = null, batchId = null, groupId = null) {
  recordEntryLineId.value = lineId ?? lineDetail.value?.cell_line?.id ?? null
  recordEntryBatchId.value = batchId ?? null
  recordEntryGroupId.value = groupId ?? selectedGroupId.value ?? null
  recordEntryVisible.value = true
}

async function saveVial() {
  if (!lineDetail.value) return
  const perVial = Number(vialForm.value.cell_count)
  if (!perVial || perVial <= 0) {
    ElMessage.warning('请填写每管冻存细胞数')
    return
  }
  if (isPrimaryLine.value && (vialForm.value.pd === null || vialForm.value.pd === undefined || vialForm.value.pd === '')) {
    ElMessage.warning('原代细胞必须填写冻存 PD，可先在传代记录中录入')
    return
  }
  const pdValue = isPrimaryLine.value || vialIncludePd.value ? vialForm.value.pd : null
  vialSaving.value = true
  try {
    const created = await vialApi.create({
      cell_line_id: lineDetail.value.cell_line.id,
      freeze_date: vialForm.value.freeze_date,
      cell_count: perVial,
      count: vialForm.value.count,
      pd: pdValue,
      location: vialForm.value.location || '',
      notes: vialForm.value.notes,
    })
    ElMessage.success(
      `已新增 ${created.length} 支冻存管${vialForm.value.location ? '' : '，位置可稍后在冻存管页补充'}`,
    )
    vialDialogVisible.value = false
    await reloadAll()
    await loadMeta()
  } finally {
    vialSaving.value = false
  }
}

async function terminateGroup() {
  terminatingGroup.value = true
  try {
    const result = await groupApi.terminate(selectedGroupId.value, groupTerminateReason.value)
    ElMessage.success(`已终止 ${result.count} 个批次`)
    terminateGroupVisible.value = false
    await reloadAll()
  } finally {
    terminatingGroup.value = false
  }
}

function openGroupBatchCreate() {
  if (!groupStatus.value.length && !groups.value.find((group) => group.id === selectedGroupId.value)?.member_count) {
    ElMessage.warning('该细胞组还没有成员')
    return
  }
  groupBatchVisible.value = true
}

async function createGroupBatches() {
  creatingGroupBatches.value = true
  try {
    const result = await groupApi.createBatches(selectedGroupId.value, groupBatchForm.value)
    if (result.errors?.length) {
      ElMessage.warning(`创建 ${result.created.length} 个，失败 ${result.errors.length} 个`)
    } else {
      ElMessage.success(`已创建 ${result.created.length} 个批次`)
    }
    groupBatchVisible.value = false
    await reloadAll()
  } finally {
    creatingGroupBatches.value = false
  }
}

function exportGroup() {
  downloadUrl(groupApi.exportUrl(selectedGroupId.value, exportAll.value))
}

onMounted(async () => {
  try {
    await loadBase()
    if (route.query.mode === 'group') mode.value = 'group'
    const groupFromQuery = Number(route.query.group)
    if (groupFromQuery && groups.value.some((group) => group.id === groupFromQuery)) {
      selectedGroupId.value = groupFromQuery
    } else {
      const withActivity = groups.value.find((group) =>
        (group.members || []).some((member) => member.active_batch_count > 0),
      )
      selectedGroupId.value = withActivity?.id || groups.value[0]?.id || null
    }
    const lineFromQuery = Number(route.query.line)
    if (lineFromQuery && lines.value.some((line) => line.id === lineFromQuery)) {
      selectedLineId.value = lineFromQuery
    } else {
      const withBatches = lines.value.find((line) => line.active_batch_count > 0)
      selectedLineId.value = withBatches?.id || lines.value[0]?.id || null
    }
    if (mode.value === 'line' && selectedLineId.value) await reloadLine()
    if (mode.value === 'group' && selectedGroupId.value) await loadGroupAll()
  } finally {
    loading.value = false
  }
})

// 支持在同一页面内通过路由参数切换（例如组状态表的「查看」按钮）
watch(
  () => route.query,
  async (query) => {
    if (!storeReady()) return
    if (query.mode === 'group' && mode.value !== 'group') mode.value = 'group'
    if (query.mode === 'line' && mode.value !== 'line') mode.value = 'line'
    const groupId = Number(query.group)
    if (groupId && groups.value.some((group) => group.id === groupId) && groupId !== selectedGroupId.value) {
      selectedGroupId.value = groupId
      await loadGroupAll()
    }
    const lineId = Number(query.line)
    if (lineId && lines.value.some((line) => line.id === lineId) && lineId !== selectedLineId.value) {
      await selectLine(lineId)
    }
  },
  { deep: true },
)

function storeReady() {
  return lines.value.length > 0 || groups.value.length > 0
}
</script>

<style scoped>
.line-layout {
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
  min-height: 520px;
}

.line-list {
  border-right: 1px solid var(--ct-border);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.line-items {
  overflow-y: auto;
  padding: 0 8px 12px;
  max-height: 640px;
}

.line-item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border: 0;
  background: transparent;
  border-radius: 10px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s ease;
  font: inherit;
  color: inherit;
}

.line-item:hover {
  background: #f4f9f8;
}

.line-item.active {
  background: var(--ct-primary-soft);
}

.line-item-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.line-name {
  font-weight: 550;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.line-sub {
  font-size: 11px;
  color: var(--ct-faint);
}

.line-count {
  min-width: 24px;
  height: 22px;
  padding: 0 7px;
  border-radius: 999px;
  background: #eef7f5;
  color: var(--ct-primary);
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-variant-numeric: tabular-nums;
}

.line-count.zero {
  background: #f4f6f6;
  color: var(--ct-faint);
}

.line-detail {
  min-width: 0;
  padding: 20px 22px;
}

.line-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--ct-border);
}

.charts-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 14px;
}

.vial-dialog-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fbfa;
  border: 1px solid var(--ct-border);
}

.curves-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

@media (max-width: 1100px) {
  .line-layout {
    grid-template-columns: 1fr;
  }
  .line-list {
    border-right: 0;
    border-bottom: 1px solid var(--ct-border);
  }
  .line-items {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    max-height: none;
    padding-bottom: 10px;
  }
  .line-item {
    min-width: 200px;
  }
  .charts-grid {
    grid-template-columns: 1fr;
  }
}
</style>
