<template>
  <div class="status-panel">
    <!-- 执行状态：全局任务队列（保留原逻辑，JobDrawer 迁入） -->
    <section class="sp-sec">
      <h4>执行状态</h4>
      <div class="sp-status" :class="store.statusCls.value">{{ store.status.value }}</div>
      <div v-if="!jobs.length" class="sp-empty">暂无任务</div>
      <div v-for="j in jobs" :key="j.id" class="sp-job" :title="j.message">
        <span class="badge" :class="j.status">{{ statusLabel(j.status) }}</span>
        <span class="mono jid">{{ j.id }}</span>
        <span class="jmeta">{{ metaLabel(j.meta) }}</span>
        <span class="jmsg">{{ j.message }}</span>
      </div>
    </section>

    <!-- 会话任务（P2 接真：GET /api/sessions/<id>/tasks；运行中任务转圈 + 最近事件摘要） -->
    <section class="sp-sec">
      <h4>会话任务</h4>
      <div v-if="!store.selectedSessionId.value" class="sp-empty">未选择会话</div>
      <div v-else-if="!tasks.length" class="sp-empty">暂无会话任务</div>
      <div v-for="t in tasks" :key="t.id" class="sp-task" :title="t.summary">
        <span class="task-icon" :class="'st-' + t.status">
          <span v-if="t.status === 'running'" class="spin"></span>
        </span>
        <span class="task-title">{{ t.title }}</span>
        <span class="task-sum">{{ latestEvent(t.id) || t.summary }}</span>
        <span class="task-time">{{ fmtTime(t.updated) }}</span>
      </div>
    </section>

    <!-- 上下文消耗占位（P4 设置页写入 context_limit 后展示） -->
    <section class="sp-sec">
      <h4>上下文消耗</h4>
      <p class="sp-placeholder">会话 token 用量与压缩状态将显示于此（P4 接入）</p>
    </section>

    <!-- 执行记录：只读审计时间线（P2 接真：GET /api/sessions/<id>/events，复用 EventTrace 样式，可筛选） -->
    <section class="sp-sec">
      <button class="exec-entry" @click="execOpen = !execOpen">
        执行记录 <span class="exec-flag">{{ execOpen ? '▾' : '▸' }}</span>
      </button>
      <div v-if="execOpen" class="exec-body">
        <div v-if="!store.selectedSessionId.value" class="sp-placeholder">未选择会话</div>
        <template v-else>
          <div class="exec-filters">
            <select v-model="fKind" class="exec-filter" title="按事件类型筛选">
              <option value="">全部类型</option>
              <option v-for="(label, k) in KIND_LABEL" :key="k" :value="k">{{ label }}</option>
            </select>
            <select v-model="fStatus" class="exec-filter" title="按状态筛选">
              <option value="">全部状态</option>
              <option v-for="(label, s) in STATUS_LABEL" :key="s" :value="s">{{ label }}</option>
            </select>
            <span class="exec-count mono">{{ filteredEvents.length }}/{{ events.length }}</span>
          </div>
          <EventTrace :items="filteredEvents" title="审计时间线" :collapsed="false" />
          <button v-if="events.length < total" class="exec-more" :disabled="loadingMore"
            @click="loadMore">
            {{ loadingMore ? '加载中…' : `加载更多（${events.length}/${total}）` }}
          </button>
        </template>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch, onBeforeUnmount, inject } from 'vue'
import { api, getSessionTasks, getSessionEvents } from '../api'
import EventTrace from './EventTrace.vue'

// 右栏执行状态区（spec 11 §5-2）：任务队列 UI 保留原逻辑；P2 接真——
// 会话任务（运行中标题 + 转圈 + 最近事件摘要）+ 执行记录审计时间线（只读，可筛选类型/状态）。
// P3：job 事件 SSE 实时 upsert；审计时间线服务端筛选 + 倒序分页「加载更多」+ trace 实时补新。
const props = defineProps({ active: { type: Boolean, default: true } })
const store = inject('store')

const jobs = ref([])
const tasks = ref([])
const events = ref([])
const total = ref(0)
const loadingMore = ref(false)
const execOpen = ref(false)
const fKind = ref('')
const fStatus = ref('')
const PAGE = 100
let timer = null

const KIND_LABEL = { subtask: '子任务', command: '命令', search: '搜索', tool: '工具', patch: '写盘' }
const STATUS_LABEL = { running: '执行中', success: '成功', error: '失败', skip: '跳过' }

const MODES = { t2va: '文生', i2va: '图生', ref: '参考图', aiwrite: 'AI 编剧' }
function metaLabel(meta) {
  if (!meta) return ''
  const bits = []
  if (meta.type === 'aiwrite') bits.push('AI 编剧')
  else if (meta.mode) bits.push(MODES[meta.mode] || meta.mode)
  if (meta.project) bits.push(meta.project)
  if (meta.episode != null) bits.push('E' + String(meta.episode).padStart(2, '0'))
  if (meta.only && meta.only.length) bits.push('镜' + meta.only.join(','))
  return bits.join(' · ')
}
const STATUS = { running: '运行中', done: '完成', error: '失败' }
function statusLabel(s) { return STATUS[s] || s }

function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// 事件 → EventTrace item（时间并入标题，审计可读）
function toTraceItem(e, i) {
  return { id: e.ts + '-' + i, kind: e.kind, title: `${fmtTime(e.ts)} · ${e.title}`,
           status: e.status, summary: e.summary || e.detail || '' }
}
const filteredEvents = computed(() => {
  return events.value
    .filter(e =>
      (!fKind.value || e.kind === fKind.value) &&
      (!fStatus.value || e.status === fStatus.value))
    .map((e, i) => toTraceItem(e, i))
})

// 某任务最近一条事件摘要（events 已按新→旧）
function latestEvent(taskId) {
  if (!taskId) return ''
  const e = events.value.find(x => x.task_id === taskId)
  return e ? (e.summary || '') : ''
}

// 任务队列/会话任务：轮询权威刷新（保留）；job 事件经 sseJobs 实时 upsert
async function refresh() {
  try {
    const r = await api('/api/jobs')
    jobs.value = r.jobs || []
  } catch (e) { /* 桥不可达时静默 */ }
  const sid = store.selectedSessionId.value
  if (!sid) { tasks.value = []; return }
  try {
    const tr = await getSessionTasks(sid)
    tasks.value = tr.tasks || []
  } catch (e) { /* 会话不存在时静默 */ }
}

// P3：SSE job 事件 → 任务列表实时更新（进度条/状态点；轮询仍为权威兜底）
watch(() => store.sseJobs.value, (list) => {
  if (!list.length) return
  for (const j of list) {
    const i = jobs.value.findIndex(x => x.id === j.id)
    if (i >= 0) jobs.value[i] = j
    else jobs.value.unshift(j)
  }
}, { deep: true })

// P3：审计时间线接真（GET /api/sessions/<id>/events），服务端筛选 kind/status，倒序分页加载更多
async function loadEvents(reset = false) {
  const sid = store.selectedSessionId.value
  if (!sid) { events.value = []; total.value = 0; return }
  if (reset) { events.value = []; total.value = 0 }
  loadingMore.value = true
  try {
    const r = await getSessionEvents(sid, PAGE, reset ? 0 : events.value.length,
                                     fKind.value, fStatus.value)
    events.value = reset ? (r.events || []) : events.value.concat(r.events || [])
    total.value = r.total || 0
  } catch (e) { /* 会话不存在时静默 */ }
  loadingMore.value = false
}
function loadMore() { if (events.value.length < total.value) loadEvents(false) }

// P3：SSE trace（当前会话）→ 审计时间线即时补新事件（新→旧，按 ts+title 去重）
watch(() => store.liveEvents.value, (evs) => {
  if (!evs.length) return
  const last = evs[evs.length - 1]
  if (last && !events.value.some(e => e.ts === last.ts && e.title === last.title)) {
    events.value.unshift(last)
    total.value++
  }
}, { deep: true })

// 切会话 → 立即刷新任务 + 重置审计分页；筛选变化 → 从 0 重拉
watch(() => store.selectedSessionId.value, () => { refresh(); loadEvents(true) })
watch(execOpen, (v) => { if (v) loadEvents(true) })
watch([fKind, fStatus], () => loadEvents(true))
watch(() => store.sessionTick.value, refresh)

// 仅在右栏展开（active）期间轮询，折叠后停表；挂载即拉一次
watch(() => props.active, (v) => {
  if (v) {
    refresh()
    timer = setInterval(refresh, 3000)
  } else if (timer) {
    clearInterval(timer); timer = null
  }
}, { immediate: true })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.status-panel { flex: 1; min-height: 0; overflow-y: auto; background: var(--panel); }
.sp-sec { padding: 10px 12px; border-bottom: 1px solid var(--line); }
.sp-sec h4 { font-size: 12px; color: var(--muted); letter-spacing: .5px; margin-bottom: 8px; }
.sp-status { font-size: 12px; margin-bottom: 8px; }
.sp-status.ok { color: var(--ok); } .sp-status.err { color: var(--danger); }
.sp-empty { color: var(--muted); font-size: 12px; }
.sp-placeholder { color: var(--muted); font-size: 12px; line-height: 1.7; }
.sp-job { display: flex; align-items: center; gap: 6px; padding: 4px 0; font-size: 12px;
  flex-wrap: wrap; }
.badge { display: inline-block; padding: 0 8px; border-radius: 10px; font-size: 11px; line-height: 1.7; }
.badge.running { background: rgba(255,180,84,.18); color: var(--warn); }
.badge.done { background: rgba(89,201,125,.18); color: var(--ok); }
.badge.error { background: rgba(255,107,107,.18); color: var(--danger); }
.jid { color: var(--muted); font-size: 11px; }
.jmeta { color: var(--accent); font-size: 11px; max-width: 100%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jmsg { color: var(--muted); font-size: 11px; width: 100%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mono { font-family: var(--mono); }

/* ---- 会话任务 ---- */
.sp-task { display: flex; align-items: center; gap: 6px; padding: 4px 0; font-size: 12px;
  flex-wrap: wrap; }
.task-icon { flex: none; width: 14px; height: 14px; text-align: center; font-size: 11px;
  line-height: 14px; border-radius: 50%; }
.task-icon.st-success { color: var(--green); }
.task-icon.st-success::before { content: '✓'; }
.task-icon.st-error { color: var(--danger); }
.task-icon.st-error::before { content: '✕'; }
.task-icon.st-skip { color: var(--muted); }
.task-icon.st-skip::before { content: '–'; }
.spin { display: inline-block; width: 11px; height: 11px; border: 2px solid rgba(52,211,153,.25);
  border-top-color: var(--green); border-radius: 50%; animation: sp-spin .8s linear infinite; }
@keyframes sp-spin { to { transform: rotate(360deg); } }
.task-title { flex: none; font-size: 12px; color: var(--fg); }
.task-sum { flex: 1; min-width: 0; font-size: 11px; color: var(--muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-time { flex: none; font-size: 10px; color: var(--muted); font-family: var(--mono); }

/* ---- 执行记录 ---- */
.exec-entry { width: 100%; text-align: left; background: var(--panel2); color: var(--green-soft);
  border: 1px solid rgba(52,211,153,.35); border-radius: 6px; padding: 6px 10px;
  font-size: 12px; cursor: pointer; }
.exec-entry:hover { background: var(--green-deep); }
.exec-flag { float: right; color: var(--muted); }
.exec-body { margin-top: 8px; }
.exec-filters { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.exec-filter { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 5px; font-size: 11px; padding: 2px 4px; }
.exec-count { font-size: 11px; color: var(--muted); margin-left: auto; }
.exec-body .evt-trace { max-height: 320px; overflow-y: auto; }
.exec-more { width: 100%; margin-top: 8px; background: var(--panel2); color: var(--green-soft);
  border: 1px solid rgba(52,211,153,.35); border-radius: 6px; padding: 5px 10px;
  font-size: 12px; cursor: pointer; }
.exec-more:hover:not(:disabled) { background: var(--green-deep); }
.exec-more:disabled { opacity: .5; cursor: default; }
</style>
