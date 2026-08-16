<template>
  <aside class="panel detail-panel">
    <h3>镜 {{ shot + 1 }} · 分镜详情 / 抽卡</h3>
    <template v-if="shot >= 0">
      <!-- Shot 字段就地编辑（与网格卡共用 ShotFields；编辑置 dirty，顶栏「保存分镜」保存） -->
      <section v-if="editRow" class="fields-sec">
        <ShotFields :row="editRow" :vocab="store.vocab.value" @dirty="store.dirty.value = true" />
        <div class="fields-note mono">{{ editRow.note || '' }}</div>
      </section>
      <ShotRefPanel :data="refData" :busy="refBusy" @refresh="onRefreshRef" />
      <CandidateWall
        :files="gallery" :review="review" :cmp="cmp" :cmp-mode="cmpMode"
        :rendering="rendering" :render-status="renderStatus" :pending-file="pendingFile"
        :assets="assetsWithImg"
        v-model:shots="shotsN" v-model:mode="mode" v-model:ref-code="refCode" v-model:note="note"
        @render="startRender" @cand-click="onCandClick" @toggle-cmp="cmpMode = !cmpMode; cmp = []"
        @confirm="confirmSelect" @cancel="pendingFile = ''; note = ''" />
      <ABCompare v-if="cmpMode && cmp.length === 2" :cmp="cmp" @choose="chooseShot" />
      <h3>提示词预览</h3>
      <pre class="mono box">{{ prompt }}</pre>
    </template>
    <p v-else class="hint">点击左侧某张分镜卡片，查看详情与抽卡。</p>
  </aside>
</template>

<script setup>
import { ref, computed, watch, inject } from 'vue'
import { api, enc, getShotRef, refreshShotRef } from '../../api'
import ShotFields from './ShotFields.vue'
import ShotRefPanel from './ShotRefPanel.vue'
import CandidateWall from './CandidateWall.vue'
import ABCompare from './ABCompare.vue'

const props = defineProps({
  shot: { type: Number, default: -1 },            // 选中镜下标（-1 = 未选）
  // 有图资产（Ref2VA 参考图下拉）；store.assets 为非响应式纯对象，由 BoardCanvas 以 prop 传入
  assetsWithImg: { type: Array, default: () => [] },
})
const emit = defineEmits(['selected'])   // 选中候选后上抛最新 episode-status

const store = inject('store')
const project = computed(() => store.project.value)
const episode = computed(() => store.episode.value)

const prompt = ref('')
const gallery = ref([])
const review = ref({})
const renderStatus = ref('')
const rendering = ref(false)
const cmpMode = ref(false)
const cmp = ref([])
const pendingFile = ref('')
const note = ref('')
const shotsN = ref(2)
const mode = ref('quick')
const refCode = ref('')
const refData = ref({ shot: 0, prompt: '', image: null })
const refBusy = ref(false)

// 字段编辑目标：与 BoardCanvas 共享同一 rows 引用（保存链路 = 顶栏「保存分镜」→ saveNow）
const editRow = computed(() => store.boardRows.value[props.shot] || null)

async function loadShot() {
  cmpMode.value = false; cmp.value = []; pendingFile.value = ''; note.value = ''
  if (props.shot < 0) {
    prompt.value = ''; gallery.value = []; review.value = {}
    refData.value = { shot: 0, prompt: '', image: null }
    return
  }
  await Promise.all([loadPrompt(), loadRef()])
  await loadGallery()
}

async function loadPrompt() {
  try {
    const d = await api(`/api/prompt/${enc(project.value)}/${episode.value}/${props.shot + 1}`)
    prompt.value = d.prompt
  } catch (e) { prompt.value = '提示词生成失败' }
}

async function loadRef() {
  try {
    refData.value = await getShotRef(project.value, episode.value, props.shot + 1)
  } catch (e) { refData.value = { shot: props.shot + 1, prompt: '', image: null } }
}

async function onRefreshRef() {
  refBusy.value = true
  try {
    refData.value = await refreshShotRef(project.value, episode.value, props.shot + 1)
    store.setStatus('参考图提示词已刷新', 'ok')
  } catch (e) { store.setStatus('参考图提示词刷新失败: ' + e.message, 'err') }
  refBusy.value = false
}

async function loadGallery() {
  try {
    const { files } = await api(`/api/candidates/${enc(project.value)}/${episode.value}/${props.shot + 1}`)
    gallery.value = files
  } catch (e) { gallery.value = [] }
  await loadReview()
}
async function loadReview() {
  try {
    const d = await api(`/api/review/${enc(project.value)}/${episode.value}`)
    const map = {}
    for (const g of d.shots || []) for (const c of g.candidates || []) map[c.file] = c
    review.value = map
  } catch (e) { review.value = {} }
}

function onCandClick(file) {
  if (cmpMode.value) {
    const idx = cmp.value.indexOf(file)
    if (idx >= 0) cmp.value.splice(idx, 1)
    else if (cmp.value.length < 2) cmp.value.push(file)
    else cmp.value = [cmp.value[1], file]
  } else {
    chooseShot(file)
  }
}
function chooseShot(file) { pendingFile.value = file; note.value = '' }

async function startRender() {
  const shotNo = props.shot + 1
  rendering.value = true; renderStatus.value = '提交中…'
  const body = { project: project.value, episode: episode.value, only: [shotNo], shots: shotsN.value, ref: refCode.value }
  if (mode.value === 'quick') Object.assign(body, { width: 512, height: 288, frames: 22, steps: refCode.value ? 8 : 2 })
  else Object.assign(body, { steps: refCode.value ? 20 : 4 })
  try {
    const r = await api('/api/render', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const job = r.job
    const timer = setInterval(async () => {
      try {
        const s = await api(`/api/render/status/${job}`)
        if (s.status === 'done') { clearInterval(timer); renderStatus.value = '生成完成'; rendering.value = false; loadGallery(); store.refreshWizard() }
        else if (s.status === 'error') { clearInterval(timer); renderStatus.value = '生成失败'; rendering.value = false }
        else renderStatus.value = s.message || '生成中…'
      } catch (e) { /* 轮询继续 */ }
    }, 4000)
  } catch (e) { renderStatus.value = '提交失败: ' + e.message; rendering.value = false }
}

async function confirmSelect() {
  const file = pendingFile.value
  if (!file) return
  try {
    await api('/api/select', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: project.value, episode: episode.value, shot: props.shot + 1, file, note: note.value }) })
    store.setStatus('已选中 ' + file, 'ok')
    pendingFile.value = ''; note.value = ''; cmpMode.value = false; cmp.value = []
    const st = await api(`/api/episode-status/${enc(project.value)}/${episode.value}`)
    store.epStatus.value = st   // 同步泳道头/总览态档位（不动 dirty）
    emit('selected', st)        // 容器更新卡片「✓ 已选」徽标
    loadRef()                   // 后端 F9：选片后该片首帧晋升为参考图，重新拉取
  } catch (e) { store.setStatus('选中失败: ' + e.message, 'err') }
}

watch(() => props.shot, loadShot)
// 卡级重抽完成后，若检查器正选中该镜则联动刷新候选墙
watch(() => store.lastRedrawn.value, (n) => {
  if (n != null && n === props.shot + 1) loadGallery()
})
</script>

<style scoped>
.detail-panel { width: 100%; min-height: 0; }
.fields-sec { background: var(--panel2); border: 1px solid var(--line); border-radius: 8px;
  padding: 10px; margin-bottom: 12px; }
.fields-note { color: var(--muted); font-size: 11px; margin-top: 4px; }
.box { background: var(--panel2); border: 1px solid var(--line); border-radius: 6px; padding: 8px;
  white-space: pre-wrap; word-break: break-all; max-height: 240px; overflow-y: auto; }
</style>
