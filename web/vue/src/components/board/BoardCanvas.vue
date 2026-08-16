<template>
  <div class="board-wrap" id="lane-board">
    <div class="board-toolbar">
      <span class="t">{{ rows.length }} 镜</span>
      <button @click="genFromScript">从剧本生成分镜</button>
      <button @click="addRow">＋ 插入镜头</button>
      <button @click="delRow" :disabled="sel < 0">删除</button>
      <button @click="move(-1)" :disabled="sel <= 0">↑</button>
      <button @click="move(1)" :disabled="sel < 0 || sel >= rows.length - 1">↓</button>
      <button class="mode-btn" @click="toggleMode">{{ isTimeline ? '⇦ 网格模式' : '⇨ 时间轴模式' }}</button>
      <span class="spacer" />
      <span class="hint">{{ isTimeline ? '卡宽=时长映射；悬停卡片右上角 ⟳ 重抽本镜；点卡在右侧检查器编辑/抽卡' : '点卡片在右侧检查器抽卡/选片；字段改动后记得「保存分镜」' }}</span>
    </div>

    <!-- 时间轴模式（默认）：刻度尺 + 节拍卡横排 -->
    <template v-if="isTimeline">
      <div v-if="rows.length" class="tl-scroll">
        <BeatRuler :ticks="rulerTicks" :total-width="totalWidth" />
        <div class="tl-cards" :style="{ gap: CARD_GAP + 'px' }">
          <BeatCard v-for="(row, i) in rows" :key="i" :row="row" :index="i" :width="beatWidths[i]"
            :ref-image="refOf(i)" :status="beatStatus(i)" :selected="i === sel" :rendering="redrawing.has(i + 1)"
            :drop-target="dropIdx === i" draggable="true"
            @select="sel = i" @redraw="redrawShot(i)"
            @dragstart="onDragStart(i, $event)" @dragover.prevent="onDragOver(i)"
            @drop="onDrop(i)" @dragend="onDragEnd" />
        </div>
      </div>
      <div v-else class="empty">暂无分镜——点「＋ 插入镜头」或先 AI 编剧生成剧本后一键分镜</div>
    </template>

    <!-- 网格模式：幕树 + 可编辑卡片（原视图保留） -->
    <div v-else class="grid-wrap">
      <ActTree :acts="acts" />
      <section class="board-panel">
        <div class="cards">
          <ShotCard v-for="(row, i) in rows" :key="i" :row="row" :index="i"
            :selected="i === sel" :has-final="finals.has(shotName(i))" :vocab="vocab"
            :drop-target="dropIdx === i" draggable="true"
            @select="sel = i" @dirty="markDirty"
            @dragstart="onDragStart(i, $event)" @dragover.prevent="onDragOver(i)"
            @drop="onDrop(i)" @dragend="onDragEnd" />
          <div v-if="!rows.length" class="empty">暂无分镜——点「＋ 插入镜头」或先 AI 编剧生成剧本后一键分镜</div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, inject, nextTick } from 'vue'
import { api, enc } from '../../api'
import ActTree from './ActTree.vue'
import ShotCard from './ShotCard.vue'
import BeatCard from './BeatCard.vue'
import BeatRuler from './BeatRuler.vue'

const store = inject('store')
const project = computed(() => store.project.value)
const episode = computed(() => store.episode.value)

const acts = ref([])
const rows = store.boardRows        // 共享引用：Inspector 的 ShotFields 直接编辑同一数据
const vocab = store.vocab           // 共享：ShotFields（网格卡/检查器）同源
const refsByShot = ref({})     // 镜号 → { shot, prompt, image }（来自 /api/canvas 聚合包）
const candCounts = store.candCounts   // 共享：节拍卡状态点 + PlanFlow 抽卡行
const sel = ref(-1)
const redrawing = ref(new Set())
// 「✓ 已选」徽标直接由 store.epStatus 推导（ShotInspector 选中后写回 epStatus，天然联动）
const finals = computed(() => new Set(store.epStatus.value.selected || []))

const isTimeline = computed(() => store.timelineMode.value === 'timeline')
function toggleMode() { store.timelineMode.value = isTimeline.value ? 'grid' : 'timeline' }

function shotName(i) { return `shot_${String(i + 1).padStart(2, '0')}.mp4` }
function refOf(i) { const r = refsByShot.value[i + 1]; return (r && r.image) || null }
function beatStatus(i) {
  if (store.pickedShots.value.has(i + 1)) return 'picked'
  if ((candCounts.value[i + 1] || 0) > 0) return 'cands'
  return 'none'
}

// 卡宽 = 时长映射（min 120 / max 280）；刻度尺在每个卡边界标累计秒数，与卡片行严格对齐
const PX_PER_SEC = 24
const CARD_GAP = 8
const beatWidths = computed(() =>
  rows.value.map(r => Math.min(280, Math.max(120, (parseFloat(r.dur) || 5) * PX_PER_SEC))))
const totalWidth = computed(() =>
  beatWidths.value.reduce((a, w) => a + w, 0) + CARD_GAP * Math.max(0, rows.value.length - 1))
const rulerTicks = computed(() => {
  const ticks = [{ left: 0, label: '0s' }]
  let sec = 0, px = 0
  rows.value.forEach((r, i) => {
    sec += parseFloat(r.dur) || 5
    px += beatWidths.value[i] + CARD_GAP
    ticks.push({ left: px, label: sec + 's' })
  })
  return ticks
})

async function loadAll() {
  try {
    const [p, cv, voc] = await Promise.all([
      api(`/api/project/${enc(project.value)}`),
      api(`/api/canvas/${enc(project.value)}/${episode.value}`),
      api('/api/vocab'),
    ])
    acts.value = p.acts || []
    rows.value = (cv.storyboard && cv.storyboard.rows) || []
    refsByShot.value = Object.fromEntries(((cv.storyboard && cv.storyboard.refs) || []).map(r => [r.shot, r]))
    store.epStatus.value = { selected: (cv.status && cv.status.selected) || [], composed: !!(cv.status && cv.status.composed) }
    vocab.value = voc
    sel.value = -1
    loadCandCounts()
  } catch (e) { store.setStatus('加载失败: ' + e.message, 'err') }
}

async function loadCandCounts() {
  try {
    const d = await api(`/api/review/${enc(project.value)}/${episode.value}`)
    const map = {}
    for (const g of d.shots || []) map[g.shot] = (g.candidates || []).length
    candCounts.value = map
  } catch (e) { candCounts.value = {} }
}

function markDirty() { store.dirty.value = true }

async function saveNow() {
  try {
    const rows2 = rows.value.map((r, i) => ({ ...r, shot: String(i + 1) }))
    await api(`/api/project/${enc(project.value)}/episode/${episode.value}/storyboard`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: rows2, header: [] }),
    })
    store.dirty.value = false
    store.setStatus('已保存', 'ok')
    store.refreshWizard()
    store.refreshEpisode()   // 同步泳道头/检查器的分镜档位（shotCount）
  } catch (e) { store.setStatus('保存失败: ' + e.message, 'err') }
}

// 通用 job 轮询：running 时把后端真实进度文案经 onMsg 透出；resolve 完整 status 对象
function pollJob(job, onMsg) {
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const s = await api(`/api/render/status/${job}`)
        if (s.status === 'done') { clearInterval(timer); resolve(s) }
        else if (s.status === 'error') { clearInterval(timer); reject(new Error(s.message || '任务失败')) }
        else if (s.message && onMsg) onMsg(s.message)
      } catch (e) { /* 轮询继续 */ }
    }, 4000)
  })
}

// storyboard-gen 已改异步：POST 返回 job → 轮询 → done 后 result={ok,path,method}（llm/parser）
async function genFromScript() {
  store.setStatus('正在从剧本生成分镜…', '')
  try {
    const r = await api('/api/storyboard-gen', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: project.value, episode: episode.value }) })
    if (!r.job) throw new Error('后端未返回任务号')
    const s = await pollJob(r.job, (m) => store.setStatus(`分镜生成中…${m}`, ''))
    const res = s.result || {}
    if (res.ok === false) throw new Error('生成失败')
    const src = res.method === 'llm' ? 'AI 拆分' : '解析器提取'
    store.setStatus(`已从剧本生成分镜（${src}）`, 'ok')
    await loadAll()
    store.refreshWizard()
    store.refreshEpisode()
  } catch (e) { store.setStatus('生成分镜失败（需先有剧本）: ' + e.message, 'err') }
}

function addRow() {
  const i = sel.value >= 0 ? sel.value : rows.value.length - 1
  const base = rows.value[i] || {}
  const def = { shot: '', frame: store.tasteDefaults?.frame || 'medium', camera: store.tasteDefaults?.camera || 'static', dur: store.tasteDefaults?.dur || '5', chars: '', scene: 'S01', light: '', dialogue: '', note: '' }
  rows.value.splice(i + 1, 0, { ...def, ...base })
  sel.value = i + 1; markDirty()
}
function delRow() {
  if (sel.value < 0) return
  rows.value.splice(sel.value, 1)
  sel.value = Math.min(sel.value, rows.value.length - 1); markDirty()
}
function move(d) {
  const i = sel.value, j = i + d
  if (i < 0 || j < 0 || j >= rows.value.length) return
  ;[rows.value[i], rows.value[j]] = [rows.value[j], rows.value[i]]
  sel.value = j; markDirty()
}

// 拖拽重排（HTML5 DnD，时间轴/网格共用）：落点即新位，保存时 saveNow 按 shot=i+1 重编镜号
const dragIdx = ref(-1)
const dropIdx = ref(-1)
function onDragStart(i, e) { dragIdx.value = i; if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move' }
function onDragOver(i) { if (dragIdx.value >= 0 && i !== dropIdx.value) dropIdx.value = i }
function onDragEnd() { dragIdx.value = -1; dropIdx.value = -1 }
function onDrop(i) {
  const from = dragIdx.value
  onDragEnd()
  if (from < 0 || from === i) return
  const [row] = rows.value.splice(from, 1)
  rows.value.splice(i, 0, row)
  sel.value = i
  markDirty()
}

// 卡级重抽（F22）：单镜 Draw，快速档默认参数；完成后刷新画布数据
async function redrawShot(i) {
  const n = i + 1
  if (redrawing.value.has(n)) return
  redrawing.value = new Set(redrawing.value).add(n)
  store.setStatus(`镜${n} 重抽中…`, '')
  try {
    const body = { project: project.value, episode: episode.value, only: [n], shots: 2,
      width: 512, height: 288, frames: 22, steps: 2 }
    const r = await api('/api/render', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const job = r.job
    const timer = setInterval(async () => {
      try {
        const s = await api(`/api/render/status/${job}`)
        if (s.status === 'done') {
          clearInterval(timer)
          redrawing.value.delete(n); redrawing.value = new Set(redrawing.value)
          store.setStatus(`镜${n} 重抽完成`, 'ok')
          store.lastRedrawn.value = n   // 检查器若正选中该镜 → 联动刷新候选墙
          loadCandCounts(); store.refreshWizard()
        } else if (s.status === 'error') {
          clearInterval(timer)
          redrawing.value.delete(n); redrawing.value = new Set(redrawing.value)
          store.setStatus(`镜${n} 重抽失败`, 'err')
        } else if (s.message) {
          store.setStatus(`镜${n} 重抽中…${s.message}`, '')
        }
      } catch (e) { /* 轮询继续 */ }
    }, 4000)
  } catch (e) {
    redrawing.value.delete(n); redrawing.value = new Set(redrawing.value)
    store.setStatus(`镜${n} 重抽提交失败: ` + e.message, 'err')
  }
}

// 选中镜镜像到全局 selection → Inspector 切 shot 态
watch(sel, (v) => { store.selection.value = v >= 0 ? { type: 'shot', id: v } : null })
// 反向联动：成片轨/外部选中某镜时同步本地 sel（时间轴高亮 + 横向滚动定位到该卡）
watch(() => store.selection.value, (s) => {
  if (s && s.type === 'shot' && s.id !== sel.value) sel.value = s.id
  if (s && s.type === 'shot') {
    nextTick(() => {
      document.querySelector('.tl-cards .beat-card.selected')
        ?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
    })
  }
})

watch(project, loadAll)
watch(episode, loadAll)
watch(() => store.canvasTick.value, loadAll)   // AgentBar 执行后整画布刷新

onMounted(async () => {
  const [ass, voc, t] = await Promise.all([api('/api/assets'), api('/api/vocab'), api('/api/taste')])
  store.assets = Object.fromEntries((ass.assets || []).map(a => [a.code, a]))
  store.assetsWithImg.value = (ass.assets || []).filter(a => a.image)
  vocab.value = voc
  store.tasteDefaults = t.defaults || {}
  store.saveBoard = saveNow
  await loadAll()
})
onBeforeUnmount(() => { store.selection.value = null })
</script>

<style scoped>
.board-wrap { padding: 8px 16px; }
.board-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.board-toolbar .t { color: var(--muted); font-size: 13px; }
.board-toolbar .spacer { flex: 1; }
.board-toolbar button { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 12px; cursor: pointer; font-size: 12px; }
.board-toolbar button:disabled { opacity: .4; cursor: default; }
.board-toolbar .mode-btn { border-color: var(--accent); color: var(--accent); }

.tl-scroll { overflow-x: auto; padding-bottom: 8px; }
.tl-cards { display: flex; }

.grid-wrap { display: flex; min-width: 0; }
.board-panel { flex: 1; min-width: 0; padding: 4px 8px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.empty { color: var(--muted); text-align: center; padding: 32px 0; border: 1px dashed var(--line);
  border-radius: 8px; }
.cards .empty { grid-column: 1 / -1; border: none; padding: 40px 0; }
</style>
