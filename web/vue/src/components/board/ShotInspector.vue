<template>
  <aside class="panel detail-panel">
    <h3>镜 {{ shot + 1 }} · 分镜详情 / 抽卡</h3>
    <template v-if="shot >= 0">
      <!-- ① 字段编辑（唯一编辑点；编辑置 dirty，顶栏「保存分镜」保存） -->
      <section v-if="editRow" class="fields-sec">
        <ShotFields :row="editRow" :vocab="store.vocab.value" @dirty="store.dirty.value = true" />
        <div class="fields-note mono">{{ editRow.note || '' }}</div>
      </section>
      <!-- ② 分镜提示词面板（原 ShotRefPanel 改名；提示词为空 → 候选墙抽卡按钮禁用；
           P7a：参考图只读展示自动关联资产，不再手动选择） -->
      <ShotPromptPanel :shot="shot + 1" :data="refData" :busy="refBusy"
        :ref-asset="refAsset" @refresh="onRefreshRef" />
      <!-- ③ 候选墙（候选数 + 抽卡 + 试看 + 确认选中；P7a：参数收敛——仅候选数可选） -->
      <CandidateWall
        :files="gallery" :review="review" :cmp="cmp" :cmp-mode="cmpMode"
        :rendering="rendering" :render-status="renderStatus"
        :has-prompt="hasPrompt"
        v-model:shots="shotsN" v-model:note="note"
        @render="startRender" @cand-click="onCandClick" @toggle-cmp="cmpMode = !cmpMode; cmp = []"
        @confirm="confirmSelect" />
      <!-- ④ A/B 对比（选片） -->
      <ABCompare v-if="cmpMode && cmp.length === 2" :cmp="cmp" @choose="chooseShot" />
    </template>
    <p v-else class="hint">点击左侧某张分镜卡片，查看详情与抽卡。</p>
  </aside>
</template>

<script setup>
import { ref, computed, watch, inject } from 'vue'
import { api, enc, getShotRef, refreshShotRef } from '../../api'
import ShotFields from './ShotFields.vue'
import ShotPromptPanel from './ShotPromptPanel.vue'
import CandidateWall from './CandidateWall.vue'
import ABCompare from './ABCompare.vue'

const props = defineProps({
  shot: { type: Number, default: -1 },            // 选中镜下标（-1 = 未选）
})
const emit = defineEmits(['selected'])   // 选中候选后上抛最新 episode-status

const store = inject('store')
const project = computed(() => store.project.value)
const episode = computed(() => store.episode.value)

const gallery = ref([])
const review = ref({})
const renderStatus = ref('')
const rendering = ref(false)
const cmpMode = ref(false)
const cmp = ref([])
const note = ref('')
const shotsN = ref(2)
const refData = ref({ shot: 0, prompt: '', image: null })
const refBusy = ref(false)

// 字段编辑目标：与 BoardCanvas 共享同一 rows 引用（保存链路 = 顶栏「保存分镜」→ saveNow）
const editRow = computed(() => store.boardRows.value[props.shot] || null)

// 分镜提示词是否已生成（候选墙抽卡硬前置，docs/12 §4 4e）
const hasPrompt = computed(() => !!(refData.value.prompt && String(refData.value.prompt).trim()))

// P6b/P7a：参考图唯一路径 = 自动关联——从该镜 chars/scene 解析资产（store.assets 查 C/S 代号），
// 自动选中首个有图资产作为 Ref2VA 参考图；不再提供手动覆盖。
const autoRefCode = computed(() => {
  const r = editRow.value
  if (!r) return ''
  const codes = [...(r.chars || '').split(',').map(c => c.trim()).filter(Boolean),
    (r.scene || '').trim()].filter(Boolean)
  for (const c of codes) {
    const a = store.assets[c]
    if (a && a.image) return a.code
  }
  return ''
})
// P7a：参考图资产对象（ShotPromptPanel 只读展示缩略+代号；无图 → 面板显示「该镜无关联资产图」）
const refAsset = computed(() => {
  const code = autoRefCode.value
  return code ? (store.assets[code] || null) : null
})

async function loadShot() {
  cmpMode.value = false; cmp.value = []; note.value = ''
  if (props.shot < 0) {
    gallery.value = []; review.value = {}
    refData.value = { shot: 0, prompt: '', image: null }
    return
  }
  await loadRef()       // refData.prompt = refs/<shot>.prompt.md（文件真理源 → hasPrompt 硬前置）
  await loadGallery()
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
    store.setStatus('分镜提示词已生成/刷新', 'ok')
  } catch (e) { store.setStatus('分镜提示词生成失败: ' + e.message, 'err') }
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

// A/B 对比模式下点候选 = 设定 A/B；普通模式点候选 = 播放试看（overlay 在 CandidateWall 内部）
function onCandClick(file) {
  const idx = cmp.value.indexOf(file)
  if (idx >= 0) cmp.value.splice(idx, 1)
  else if (cmp.value.length < 2) cmp.value.push(file)
  else cmp.value = [cmp.value[1], file]
}
function chooseShot(file) { cmpMode.value = false; cmp.value = []; confirmSelect(file) }

// P7a：抽卡参数收敛——仅 候选数 可选；时长/分辨率/步数由分镜行 + config generate 段派生（P6a 契约）。
// 参考图唯一路径 = 自动关联（autoRefCode）；only 传镜号字符串（P6a render_precheck 契约：逗号分隔，如 "3"；单镜渲染）
async function startRender() {
  const shotNo = props.shot + 1
  rendering.value = true; renderStatus.value = '提交中…'
  const body = {
    project: project.value, episode: episode.value,
    only: String(shotNo), shots: shotsN.value, ref: autoRefCode.value || '',
  }
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

// 显式「确认选中」（播放层内按钮触发，file 由 CandidateWall 传入）
async function confirmSelect(file) {
  if (!file) return
  try {
    await api('/api/select', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: project.value, episode: episode.value, shot: props.shot + 1, file, note: note.value }) })
    store.setStatus('已选中 ' + file, 'ok')
    note.value = ''; cmpMode.value = false; cmp.value = []
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
</style>
