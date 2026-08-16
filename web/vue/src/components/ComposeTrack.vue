<template>
  <section class="compose-track" id="lane-compose">
    <div class="ct-head">
      <h3>成片轨</h3>
      <span class="hint">已选 {{ covered }}/{{ rows.length }} 镜 · 点片段跳转分镜卡</span>
      <span class="spacer" />
      <button class="primary" :disabled="busy || !finals.length" @click="compose">{{ busy ? '拼接中…' : '拼接成片' }}</button>
    </div>

    <div class="ct-scroll">
      <div v-for="(r, i) in rows" :key="i" class="ct-clip" :class="{ ok: picked(i + 1) }" @click="goShot(i)">
        <video v-if="picked(i + 1)" :src="`/video/${enc(project)}/${episode}/${shotName(i)}`" muted loop preload="metadata" />
        <div v-else class="ct-empty">镜{{ i + 1 }} 未选</div>
        <div class="ct-label">
          <span>镜{{ i + 1 }}</span>
          <span v-if="noteOf(i)" class="ct-note" :title="noteOf(i)">✎ {{ noteOf(i) }}</span>
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
import { api, enc } from '../api'

const store = inject('store')
const project = computed(() => store.project.value)
const episode = computed(() => store.episode.value)

const rows = ref([])
const finals = ref([])
const notes = ref({})   // shot(字符串) → 选中原因
const composedPath = ref('')
const busy = ref(false)

function shotName(i) { return `shot_${String(i + 1).padStart(2, '0')}.mp4` }
function picked(n) { return finals.value.includes(`shot_${String(n).padStart(2, '0')}.mp4`) }
function noteOf(i) { return notes.value[String(i + 1)] || '' }
const covered = computed(() => rows.value.reduce((n, _r, i) => n + (picked(i + 1) ? 1 : 0), 0))

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
}

async function compose() {
  busy.value = true
  try {
    const r = await api('/api/compose', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: project.value, episode: episode.value }) })
    if (r.ok) { store.setStatus('成片已生成', 'ok'); composedPath.value = `/video/${enc(project.value)}/${episode.value}/成片.mp4` }
    else store.setStatus('拼接失败：检查每镜是否已选', 'err')
    await store.refreshWizard()
    await store.refreshEpisode()   // 同步泳道头/总览态的成片档位
    await load()
  } catch (e) { store.setStatus('拼接失败: ' + e.message, 'err') }
  busy.value = false
}

// 点片段 → 选中该镜并滚回分镜区（画布联动）
function goShot(i) {
  store.selection.value = { type: 'shot', id: i }
  nextTick(() => document.getElementById('lane-board')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

watch(project, load)
watch(episode, load)
watch(() => store.canvasTick.value, load)   // AgentBar 执行后成片轨同步刷新
onMounted(load)
</script>

<style scoped>
.compose-track { padding: 8px 16px 16px; border-top: 1px solid var(--line); }
.ct-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.ct-head h3 { margin-bottom: 0; }
.ct-head .spacer { flex: 1; }
.primary { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 7px 16px;
  cursor: pointer; font-size: 13px; }
.primary:disabled { background: var(--line); color: var(--muted); cursor: default; }
.ct-scroll { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
.ct-clip { flex: none; width: 132px; background: var(--panel2); border: 1px solid var(--line);
  border-radius: 8px; overflow: hidden; cursor: pointer; }
.ct-clip:hover { border-color: var(--accent); }
.ct-clip.ok { border-left: 3px solid var(--ok); }
.ct-clip video { width: 100%; height: 68px; object-fit: cover; display: block; background: #000; }
.ct-empty { width: 100%; height: 68px; display: flex; align-items: center; justify-content: center;
  color: var(--muted); font-size: 11px; background: var(--panel); text-align: center; }
.ct-label { display: flex; align-items: center; gap: 6px; padding: 4px 8px; font-size: 12px; }
.ct-note { color: var(--muted); font-size: 11px; max-width: 80px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.strip-empty { color: var(--muted); font-size: 12px; padding: 12px 4px; }
.ct-preview { margin-top: 10px; max-width: 720px; }
.ct-preview video { width: 100%; max-height: 380px; background: #000; border-radius: 8px; }
</style>
