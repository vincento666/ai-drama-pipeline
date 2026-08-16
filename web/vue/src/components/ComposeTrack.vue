<template>
  <!-- P6b：成片编排台（docs/12 §4 ⑥，D1）——已选片段横条（可播放预览）+ 拖拽重排 +
       顺序持久化（PUT /api/compose-order）+ 按当前顺序拼接（POST /api/compose，后端自动读 compose.order.json）+ 成片预览 -->
  <section class="compose-track" id="lane-compose">
    <div class="ct-head">
      <h3>成片编排台</h3>
      <span class="hint">已选 {{ covered }}/{{ rows.length }} 镜 · 拖拽片段调整顺序 · 点片段跳转分镜卡</span>
      <span class="spacer" />
      <button class="mini" :disabled="!isCustomOrder" @click="resetOrder">↺ 重置为分镜顺序</button>
      <button class="primary" :disabled="busy || !finals.length" @click="compose">
        {{ busy ? '拼接中…' : '按当前顺序拼接' }}
      </button>
    </div>

    <div class="ct-scroll">
      <div v-for="(item, i) in displayList" :key="item.key"
           class="ct-clip" :class="{ ok: item.picked, dragging: dragIdx === i, 'drop-target': dropIdx === i }"
           :draggable="item.picked"
           @click="goShot(item.pos)"
           @dragstart="onDragStart(i, $event)" @dragover.prevent="onDragOver(i)"
           @drop="onDrop(i)" @dragend="onDragEnd">
        <span class="ord">{{ i + 1 }}</span>
        <video v-if="item.picked" :src="`/video/${enc(project)}/${episode}/${item.name}`" muted loop preload="metadata" />
        <div v-else class="ct-empty">镜{{ item.pos + 1 }} 未选</div>
        <div class="ct-label">
          <span>镜{{ item.pos + 1 }}</span>
          <span v-if="noteOf(item.pos)" class="ct-note" :title="noteOf(item.pos)">✎ {{ noteOf(item.pos) }}</span>
        </div>
      </div>
      <div v-if="!rows.length" class="strip-empty">暂无分镜——先在③分镜区生成或插入镜头</div>
    </div>

    <div v-if="composedPath" class="ct-preview">
      <video :src="composedPath" controls />
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, inject, watch, nextTick } from 'vue'
import { api, enc, getComposeOrder, putComposeOrder } from '../api'

const store = inject('store')
const project = computed(() => store.project.value)
const episode = computed(() => store.episode.value)

const rows = ref([])
const finals = ref([])          // 已选文件名（P6a：/api/episode-status selected 已过滤幽灵文件）
const notes = ref({})           // shot(字符串) → 选中原因
const composedPath = ref('')
const busy = ref(false)
const order = ref(null)         // null = 分镜行顺序；否则 [镜号1, 镜号2, …]（1-based，P6a 持久化）

function shotName(i) { return `shot_${String(i + 1).padStart(2, '0')}.mp4` }
function picked(n) { return finals.value.includes(`shot_${String(n).padStart(2, '0')}.mp4`) }
function noteOf(i) { return notes.value[String(i + 1)] || '' }
const covered = computed(() => rows.value.reduce((n, _r, i) => n + (picked(i + 1) ? 1 : 0), 0))
const isCustomOrder = computed(() => Array.isArray(order.value) && order.value.length > 0)

// 展示序：order（拖拽覆盖）→ 否则分镜行顺序；含未选占位条（不可拖）
const displayList = computed(() => {
  const n = rows.value.length
  const seq = isCustomOrder.value
    ? order.value.map(x => Number(x)).filter(x => x >= 1 && x <= n)
    : rows.value.map((_r, i) => i + 1)
  return seq.map((no) => ({
    pos: no - 1,
    key: 's' + no,
    name: shotName(no),
    picked: picked(no),
  }))
})

// ---- 拖拽重排（原生 HTML5 DnD，无需新依赖）：落点即新位 → PUT compose-order 持久化 ----
const dragIdx = ref(-1)
const dropIdx = ref(-1)
function onDragStart(i, e) { dragIdx.value = i; if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move' }
function onDragOver(i) { if (dragIdx.value >= 0 && i !== dropIdx.value) dropIdx.value = i }
function onDragEnd() { dragIdx.value = -1; dropIdx.value = -1 }
async function onDrop(i) {
  const from = dragIdx.value
  onDragEnd()
  if (from < 0 || from === i) return
  const seq = isCustomOrder.value
    ? order.value.map(x => Number(x)).filter(x => x >= 1 && x <= rows.value.length)
    : rows.value.map((_r, k) => k + 1)
  const [moved] = seq.splice(from, 1)
  seq.splice(i, 0, moved)
  await persistOrder(seq)
}
async function persistOrder(seq) {
  order.value = seq
  try {
    await putComposeOrder(project.value, episode.value, seq)
    store.setStatus('成片顺序已保存', 'ok')
  } catch (e) {
    store.setStatus('顺序保存失败: ' + e.message, 'err')
  }
}
// 重置为分镜顺序：本地回默认；持久化先试 PUT order=null（P6a 契约），
// 后端 write_order 不接受 null 时退化为显式写分镜行顺序（效果等价）
async function resetOrder() {
  order.value = null
  try { await putComposeOrder(project.value, episode.value, null) }
  catch (e) {
    try {
      const seq = rows.value.map((_r, k) => k + 1)
      await putComposeOrder(project.value, episode.value, seq)
    } catch (e2) { /* 契约未就位时忽略 */ }
  }
  store.setStatus('已重置为分镜顺序', 'ok')
}

function sameOrder(a, b) { return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => x === b[i]) }

async function load() {
  try {
    const [sb, st, nt] = await Promise.all([
      api(`/api/project/${enc(project.value)}/episode/${episode.value}/storyboard`),
      api(`/api/episode-status/${enc(project.value)}/${episode.value}`),
      api(`/api/selection-notes/${enc(project.value)}/${episode.value}`),
    ])
    rows.value = sb.rows || []
    finals.value = st.selected || []
    composedPath.value = st.composed ? `/video/${enc(project.value)}/${episode.value}/成片.mp4` : ''
    const list = Array.isArray(nt) ? nt : (nt.notes || [])
    const map = {}
    for (const n of list) if (n && n.shot != null) map[String(n.shot)] = n.note || ''
    notes.value = map
  } catch (e) { /* ignore */ }
  await loadOrder()
}
// 成片顺序：GET /api/compose-order；持久化顺序 = 分镜行顺序 → 归一化为 null（默认态，重置按钮禁用）
async function loadOrder() {
  try {
    const r = await getComposeOrder(project.value, episode.value)
    const o = r && r.order
    if (Array.isArray(o) && o.length) {
      const nat = rows.value.map((_r, k) => k + 1)
      order.value = o.map(Number)
      if (sameOrder(order.value, nat)) order.value = null
    } else order.value = null
  } catch (e) { order.value = null }
}

// 拼接按当前顺序（后端 /api/compose 自动读 compose.order.json，缺省=分镜行顺序）
async function compose() {
  busy.value = true
  try {
    const r = await api('/api/compose', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: project.value, episode: episode.value }) })
    if (r.ok) { store.setStatus('成片已按当前顺序生成', 'ok'); composedPath.value = `/video/${enc(project.value)}/${episode.value}/成片.mp4` }
    else store.setStatus('拼接失败：检查每镜是否已选', 'err')
    await store.refreshWizard()
    await store.refreshEpisode()   // 同步泳道头/总览态的成片档位
    await load()
  } catch (e) { store.setStatus('拼接失败: ' + e.message, 'err') }
  busy.value = false
}

// 点片段 → 选中该镜并切到分镜视图（P1 三栏壳：成片/分镜已是独立视图，先切视图再滚动画布）
function goShot(i) {
  store.selection.value = { type: 'shot', id: i }
  store.view.value = 'board'
  nextTick(() => document.getElementById('lane-board')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

watch(project, load)
watch(episode, load)
watch(() => store.canvasTick.value, load)   // AgentBar 执行后成片轨同步刷新
onMounted(load)
</script>

<style scoped>
.compose-track { padding: 8px 16px 16px; border-top: 1px solid var(--line); }
.ct-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.ct-head h3 { margin-bottom: 0; }
.ct-head .spacer { flex: 1; }
.primary { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 7px 16px;
  cursor: pointer; font-size: 13px; }
.primary:disabled { background: var(--line); color: var(--muted); cursor: default; }
.mini { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); border-radius: 6px;
  padding: 6px 12px; font-size: 12px; cursor: pointer; }
.mini:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.mini:disabled { opacity: .4; cursor: default; }
.ct-scroll { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
.ct-clip { position: relative; flex: none; width: 132px; background: var(--panel2); border: 1px solid var(--line);
  border-radius: 8px; overflow: hidden; cursor: pointer; }
.ct-clip:hover { border-color: var(--accent); }
.ct-clip.ok { border-left: 3px solid var(--ok); }
.ct-clip.dragging { opacity: .45; }
.ct-clip.drop-target { border-color: var(--warn); border-style: dashed; }
.ct-clip video { width: 100%; height: 68px; object-fit: cover; display: block; background: #000; pointer-events: none; }
.ct-empty { width: 100%; height: 68px; display: flex; align-items: center; justify-content: center;
  color: var(--muted); font-size: 11px; background: var(--panel); text-align: center; }
.ord { position: absolute; top: 4px; right: 4px; z-index: 2; min-width: 18px; text-align: center;
  background: rgba(0,0,0,.65); color: #fff; border-radius: 8px; font-size: 10px; padding: 1px 4px;
  font-family: var(--mono); }
.ct-label { display: flex; align-items: center; gap: 6px; padding: 4px 8px; font-size: 12px; }
.ct-note { color: var(--muted); font-size: 11px; max-width: 80px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.strip-empty { color: var(--muted); font-size: 12px; padding: 12px 4px; }
.ct-preview { margin-top: 10px; max-width: 720px; }
.ct-preview video { width: 100%; max-height: 380px; background: #000; border-radius: 8px; }
</style>
