<template>
  <div class="script-view">
    <!-- P6b：顶部 hint——AI 唯一入口 = 左栏对话；本视图唯一操作 = 直接编辑小说/剧本 -->
    <p class="view-hint">AI 生成/修改请在左侧对话栏说一句话；此处可直接编辑小说/剧本。</p>

    <!-- P5：AI 写盘撤销条（doc=剧本/小说/简报/资产；doc.diff 事件驱动） -->
    <div v-if="undoInfo" class="diff-bar" :key="undoInfo.ts">
      <span class="diff-text">{{ undoInfo.label }} 已更新：{{ undoInfo.summary }}</span>
      <button class="undo-btn" :disabled="undoBusy" @click="undoLatest">
        {{ undoBusy ? '撤销中…' : '撤销' }}
      </button>
      <button class="mini-btn" @click="verOpen = true">🕘 版本历史</button>
      <button class="close-btn" title="关闭" @click="store.lastDocDiff.value = null">✕</button>
    </div>

    <!-- 创作简报卡片（占位，spec 11 §3.3：对话即访谈，简报落在中栏剧本文档此卡，可折叠可编辑；P2 接对话产出） -->
    <section class="brief-card" :class="{ open: briefOpen }">
      <header class="brief-head" @click="briefOpen = !briefOpen">
        <span class="brief-icon">📋</span>
        <span class="brief-title">创作简报</span>
        <span class="brief-state" :class="{ ok: hasBrief }">{{ hasBrief ? '✓ 已有简报' : '尚无简报' }}</span>
        <span class="brief-fold">{{ briefOpen ? '▾ 收起' : '▸ 展开' }}</span>
      </header>
      <div v-if="briefOpen" class="brief-body">
        <p class="hint">
          在左栏对话里用一句话描述创作想法，AI 将追问并产出创作简报，落在本卡（可编辑、可折叠），
          作为后续编剧/分镜的一致性锚点（会话后端 P2 接入，当前为占位）。
        </p>
      </div>
    </section>

    <!-- P5：版本历史（折叠面板，docs/11 §10：AI 写盘/手动保存自动快照，保留最近 20 份） -->
    <section class="ver-card">
      <header class="ver-head" @click="verOpen = !verOpen">
        <span class="ver-title">🕘 版本历史</span>
        <span class="ver-docs" @click.stop>
          <button v-for="v in verDocs" :key="v.key" class="mini-tab" :class="{ on: verDoc === v.key }"
            @click="switchVerDoc(v.key)">{{ v.label }}</button>
        </span>
        <span class="ver-fold">{{ verOpen ? '▾ 收起' : '▸ 展开' }}</span>
      </header>
      <div v-if="verOpen" class="ver-body">
        <p v-if="!verRevs.length" class="hint">暂无版本记录（AI 写盘 / 手动保存时会自动快照）</p>
        <div v-for="r in verRevs" :key="r.rev" class="ver-row">
          <span class="ver-rev">#{{ r.rev }}</span>
          <span class="ver-ts">{{ r.ts }}</span>
          <span class="ver-src">{{ r.source }}</span>
          <span class="ver-note">{{ r.note }}</span>
          <button class="mini-btn" :disabled="verBusy" @click="restoreVer(r)">恢复此版本</button>
        </div>
      </div>
    </section>

    <ScriptPanel />
  </div>
</template>

<script setup>
import { ref, computed, inject, watch } from 'vue'
import ScriptPanel from './ScriptPanel.vue'
import { getDocRevs, restoreDocRev } from '../api'
import { docKeyOf } from '../lib/diff'

// 剧本视图（spec 11 §11 映射）：ScriptPanel 现有内容迁入 + 创作简报卡片占位 +
// P5 撤销条（doc.diff → 回滚上一版本）+ 版本历史（GET /api/docs/revs → 恢复此版本）。
// OnboardPanel 已删除（对话即访谈，废弃访谈概念）；「保存简报并一键生成」链路随 P2 会话对话重建。
const store = inject('store')
const briefOpen = ref(true)
const hasBrief = computed(() => {
  try { return !!localStorage.getItem('onboardBrief:' + store.project.value) } catch (e) { return false }
})

// ---- P5：撤销条（本视图只响应剧本族 doc：script/novel/brief/assets） ----
const SCRIPT_FAMILY = ['script', 'novel', 'brief', 'assets']
const undoInfo = computed(() => {
  const d = store.lastDocDiff.value
  if (!d) return null
  return SCRIPT_FAMILY.includes(docKeyOf(d.doc)) ? d : null
})
const undoBusy = ref(false)
async function undoLatest() {
  const d = undoInfo.value
  if (!d) return
  undoBusy.value = true
  try {
    const key = docKeyOf(d.doc)
    const r = await getDocRevs(store.project.value, key)
    const latest = (r.revs || [])[0]
    if (!latest) { store.setStatus('该文档暂无历史版本', 'err'); return }
    await restoreDocRev(store.project.value, key, latest.rev, store.episode.value)
    store.lastDocDiff.value = null
    store.setStatus(`已回滚 ${d.label} 到 #${latest.rev}（${latest.ts}）`, 'ok')
  } catch (e) { store.setStatus('撤销失败: ' + e.message, 'err') }
  finally { undoBusy.value = false }
}

// ---- P5：版本历史面板 ----
const verOpen = ref(false)
const verDoc = ref('script')
const verDocs = [
  { key: 'script', label: '剧本' },
  { key: 'novel', label: '小说' },
  { key: 'brief', label: '简报' },
  { key: 'assets', label: '资产' },
]
const verRevs = ref([])
const verBusy = ref(false)
async function loadRevs() {
  if (!store.project.value) { verRevs.value = []; return }
  try {
    const r = await getDocRevs(store.project.value, verDoc.value)
    verRevs.value = r.revs || []
  } catch (e) { verRevs.value = [] }
}
function switchVerDoc(k) { verDoc.value = k; loadRevs() }
async function restoreVer(r) {
  if (!confirm(`恢复「${verDocs.find(v => v.key === verDoc.value)?.label || verDoc.value}」到 #${r.rev}（${r.ts}）？当前内容将被覆盖（可再回滚）。`)) return
  verBusy.value = true
  try {
    await restoreDocRev(store.project.value, verDoc.value, r.rev, store.episode.value)
    await loadRevs()
    store.setStatus(`已恢复 #${r.rev}`, 'ok')
  } catch (e) { store.setStatus('恢复失败: ' + e.message, 'err') }
  finally { verBusy.value = false }
}
watch(verOpen, (o) => { if (o) loadRevs() })
watch(() => store.lastDocDiff.value, () => { if (verOpen.value) loadRevs() })
watch(() => store.project.value, () => { verRevs.value = [] })
</script>

<style scoped>
.script-view { max-width: 1080px; padding: 4px 8px 16px; }
.view-hint { margin: 8px 8px 0; font-size: 12px; color: var(--muted); }
.brief-card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
  margin: 10px 8px 12px; }
.brief-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px; cursor: pointer;
  user-select: none; }
.brief-head:hover { background: var(--panel2); }
.brief-icon { font-size: 14px; }
.brief-title { font-size: 13px; font-weight: 600; color: var(--green-soft); }
.brief-state { font-size: 11px; color: var(--muted); }
.brief-state.ok { color: var(--ok); }
.brief-fold { margin-left: auto; font-size: 12px; color: var(--muted); }
.brief-body { padding: 0 12px 10px; border-top: 1px dashed var(--line); padding-top: 8px; }

/* ---- P5：撤销条（diff-bar）---- */
.diff-bar { display: flex; align-items: center; gap: 8px; margin: 10px 8px 0; padding: 8px 12px;
  background: var(--panel); border: 1px solid rgba(52, 211, 153, .55); border-left: 3px solid var(--green);
  border-radius: 8px; }
.diff-text { flex: 1; font-size: 13px; color: var(--green-soft); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.undo-btn { background: var(--green); color: #04281b; border: none; border-radius: 6px;
  padding: 5px 14px; font-size: 12px; font-weight: 700; cursor: pointer; flex: none; }
.undo-btn:disabled { opacity: .5; cursor: default; }
.mini-btn { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; flex: none; }
.mini-btn:hover { border-color: var(--green); color: var(--green-soft); }
.mini-btn:disabled { opacity: .5; cursor: default; }
.close-btn { background: none; border: none; color: var(--muted); font-size: 13px;
  cursor: pointer; padding: 2px 6px; flex: none; }
.close-btn:hover { color: var(--danger); }

/* ---- P5：版本历史（ver-card）---- */
.ver-card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
  margin: 10px 8px 0; }
.ver-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px; cursor: pointer;
  user-select: none; }
.ver-head:hover { background: var(--panel2); }
.ver-title { font-size: 13px; font-weight: 600; color: var(--green-soft); }
.ver-docs { display: flex; gap: 4px; }
.mini-tab { background: transparent; color: var(--muted); border: 1px solid transparent;
  border-radius: 6px; padding: 2px 8px; font-size: 11px; cursor: pointer; }
.mini-tab.on { color: var(--accent); border-color: var(--accent); }
.ver-fold { margin-left: auto; font-size: 12px; color: var(--muted); }
.ver-body { padding: 4px 12px 10px; border-top: 1px dashed var(--line); max-height: 260px;
  overflow-y: auto; }
.ver-row { display: flex; align-items: center; gap: 10px; padding: 5px 0;
  border-bottom: 1px dashed var(--line); font-size: 12px; }
.ver-row:last-child { border-bottom: none; }
.ver-rev { color: var(--accent); font-weight: 700; font-family: var(--mono); }
.ver-ts { color: var(--muted); }
.ver-src { color: var(--muted); }
.ver-note { flex: 1; color: var(--fg); overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
</style>
