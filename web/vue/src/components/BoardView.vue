<template>
  <div class="board-view">
    <!-- P5：分镜撤销条（doc.diff doc=分镜/board、成片/compose → 视图头撤销条） -->
    <div v-if="undoInfo" class="diff-bar" :key="undoInfo.ts">
      <span class="diff-text">{{ undoInfo.label }} 已更新：{{ undoInfo.summary }}</span>
      <button class="undo-btn" :disabled="undoBusy" @click="undoLatest">
        {{ undoBusy ? '撤销中…' : '撤销' }}
      </button>
      <button class="mini-btn" @click="verOpen = !verOpen">🕘 版本历史</button>
      <button class="close-btn" title="关闭" @click="store.lastDocDiff.value = null">✕</button>
    </div>

    <div class="board-main">
      <div class="board-col">
        <BoardCanvas ref="bc" />
      </div>
      <Inspector />
    </div>

    <!-- P5：分镜版本历史入口（右上角常驻，docs/11 §10） -->
    <button v-if="!undoInfo" class="ver-fab" :title="verOpen ? '收起版本历史' : '分镜版本历史'"
      @click="verOpen = !verOpen">🕘 {{ verOpen ? '收起' : '历史' }}</button>
    <div v-if="verOpen" class="ver-panel">
      <header class="ver-head">
        <span class="ver-title">分镜版本历史（E{{ store.episode.value }}）</span>
        <button class="close-btn" title="关闭" @click="verOpen = false">✕</button>
      </header>
      <div class="ver-body">
        <p v-if="!verRevs.length" class="hint">暂无版本记录（AI 写盘 / 手动保存时会自动快照）</p>
        <div v-for="r in verRevs" :key="r.rev" class="ver-row">
          <span class="ver-rev">#{{ r.rev }}</span>
          <span class="ver-ts">{{ r.ts }}</span>
          <span class="ver-src">{{ r.source }}</span>
          <span class="ver-note">{{ r.note }}</span>
          <button class="mini-btn" :disabled="verBusy" @click="restoreVer(r)">恢复此版本</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, inject, watch } from 'vue'
import BoardCanvas from './board/BoardCanvas.vue'
import Inspector from './Inspector.vue'
import { getDocRevs, restoreDocRev } from '../api'
import { docKeyOf } from '../lib/diff'

// 分镜视图（spec 11 §11 映射）：BoardCanvas（时间轴/网格画布，全部功能保留）+ Inspector（详情/抽卡/候选墙/A-B）迁入
// + P5 撤销条（doc.diff doc=分镜 → 回滚上一版本）+ 分镜版本历史（GET /api/docs/revs → 恢复此版本）。
// 视图头「从剧本生成分镜」经此转发到 BoardCanvas.genFromScript（按钮从画布工具栏移入视图头，避免重复）。
const bc = ref(null)
defineExpose({ genFromScript: () => bc.value?.genFromScript() })

const store = inject('store')

// ---- P5：撤销条（分镜/成片）----
const BOARD_FAMILY = ['board', 'compose']
const undoInfo = computed(() => {
  const d = store.lastDocDiff.value
  if (!d) return null
  return BOARD_FAMILY.includes(docKeyOf(d.doc)) ? d : null
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

// ---- P5：分镜版本历史 ----
const verOpen = ref(false)
const verRevs = ref([])
const verBusy = ref(false)
async function loadRevs() {
  if (!store.project.value) { verRevs.value = []; return }
  try {
    const r = await getDocRevs(store.project.value, 'board')
    verRevs.value = r.revs || []
  } catch (e) { verRevs.value = [] }
}
async function restoreVer(r) {
  if (!confirm(`恢复分镜到 #${r.rev}（${r.ts}）？当前分镜将被覆盖（可再回滚）。`)) return
  verBusy.value = true
  try {
    await restoreDocRev(store.project.value, 'board', r.rev, store.episode.value)
    await loadRevs()
    store.setStatus(`已恢复 #${r.rev}`, 'ok')
  } catch (e) { store.setStatus('恢复失败: ' + e.message, 'err') }
  finally { verBusy.value = false }
}
watch(verOpen, (o) => { if (o) loadRevs() })
watch(() => store.episode.value, () => { verRevs.value = [] })
watch(() => store.lastDocDiff.value, () => { if (verOpen.value) loadRevs() })
</script>

<style scoped>
.board-view { position: relative; display: flex; flex-direction: column; min-height: 0; height: 100%; }
.board-main { flex: 1; display: flex; min-height: 0; }
.board-col { flex: 1; min-width: 0; overflow-y: auto; }

/* ---- P5：撤销条 ---- */
.diff-bar { flex: none; display: flex; align-items: center; gap: 8px; margin: 8px 12px 0;
  padding: 8px 12px; background: var(--panel); border: 1px solid rgba(52, 211, 153, .55);
  border-left: 3px solid var(--green); border-radius: 8px; z-index: 5; }
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

/* ---- P5：版本历史（浮层面板）---- */
.ver-fab { position: absolute; top: 8px; right: 12px; z-index: 6; background: var(--panel2);
  color: var(--green-soft); border: 1px solid var(--line); border-radius: 6px;
  padding: 4px 10px; font-size: 12px; cursor: pointer; }
.ver-fab:hover { border-color: var(--green); }
.ver-panel { position: absolute; top: 40px; right: 12px; z-index: 6; width: 460px;
  max-height: 60%; display: flex; flex-direction: column; background: var(--panel);
  border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 6px 24px rgba(0, 0, 0, .35); }
.ver-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px;
  border-bottom: 1px solid var(--line); }
.ver-title { flex: 1; font-size: 13px; font-weight: 600; color: var(--green-soft); }
.ver-body { padding: 4px 12px 10px; overflow-y: auto; }
.ver-row { display: flex; align-items: center; gap: 10px; padding: 5px 0;
  border-bottom: 1px dashed var(--line); font-size: 12px; }
.ver-row:last-child { border-bottom: none; }
.ver-rev { color: var(--accent); font-weight: 700; font-family: var(--mono); }
.ver-ts { color: var(--muted); }
.ver-src { color: var(--muted); }
.ver-note { flex: 1; color: var(--fg); overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
</style>
