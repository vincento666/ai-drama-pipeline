<template>
  <aside class="inspector">
    <div class="insp-col">
      <!-- 选中条：显示当前对象路径，✕ 返回总览 -->
      <div v-if="sel" class="insp-bar">
        <span class="mono">{{ selPath }}</span>
        <button class="x" title="返回总览" @click="store.selection.value = null">✕</button>
      </div>

      <!-- shot 态：完整复用现有 ShotInspector（参考图/候选墙/A-B/选中原因/提示词） -->
      <ShotInspector v-if="shotSel" :key="shotSel.id" :shot="shotSel.id" />

      <!-- asset 态：资产详情 -->
      <div v-else-if="assetSel" class="panel asset-detail">
        <h3>资产 {{ assetSel.code }}</h3>
        <img class="ad-img" :src="`/asset-img/${assetSel.code}`" :alt="assetSel.name" />
        <div class="ad-row"><span>名称</span><b>{{ assetSel.name }}</b></div>
        <div class="ad-row"><span>类型</span><b>{{ TYPE_LABEL[assetSel.type] || assetSel.type }}</b></div>
        <div class="ad-row"><span>角色圣经</span><b :class="{ ok: assetSel.bible }">{{ assetSel.bible ? '✓ 已建' : '未建' }}</b></div>
        <p class="hint">抽卡时该镜角色/场景资产会自动关联为参考图（Ref2VA 一致性锚点）。登记/上传在「美术·资产」视图。</p>
        <button class="danger-btn" @click="removeAsset">删除该资产</button>
      </div>

      <!-- 空态（P3.5 问题 7）：无选中时只显示单行引导（画布总览面板已删除——
           四步状态/进度/泳道摘要与右栏 StageNav 状态点重复） -->
      <div v-else class="insp-empty">
        点选分镜卡 / 资产卡，在右侧检查器编辑
      </div>
    </div>
  </aside>
</template>

<script setup>
// 分镜视图右侧检查器（详情）。Agent 会话工作台已迁入左栏 ChatThread（P1 三栏壳）；
// 右栏 StageNav 状态点承担四步状态（P3.5 问题 7：画布总览面板已删除，避免重复）。
import { computed, inject } from 'vue'
import { deleteAsset } from '../api'
import ShotInspector from './board/ShotInspector.vue'

const store = inject('store')

const TYPE_LABEL = { C: '角色', S: '场景', P: '道具', R: '风格参考' }

const sel = computed(() => store.selection.value)
const shotSel = computed(() => sel.value && sel.value.type === 'shot' ? sel.value : null)
const assetSel = computed(() => {
  const s = sel.value
  if (!s || s.type !== 'asset') return null
  return store.assetsWithImg.value.find(a => a.code === s.id) || (store.assets || {})[s.id] || { code: s.id, name: '', type: s.id[0] }
})
const selPath = computed(() => {
  const s = sel.value
  if (!s) return ''
  if (s.type === 'shot') return `③分镜 / 镜${String(s.id + 1).padStart(2, '0')}`
  if (s.type === 'asset') return `资产条 / ${s.id}`
  return s.type
})

async function removeAsset() {
  const a = assetSel.value
  if (!a || !a.code) return
  if (!window.confirm(`确认删除资产 ${a.code} ${a.name || ''}？登记痕迹与图片将一并移除。`)) return
  try {
    await deleteAsset(a.code)
    store.setStatus('资产已删除：' + a.code, 'ok')
    store.selection.value = null
    await store.reloadAssets()
  } catch (e) { store.setStatus('删除失败: ' + e.message, 'err') }
}
</script>

<style scoped>
.inspector { width: 380px; flex: none; display: flex; min-height: 0; border-left: 1px solid var(--line); }
.insp-col { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
.insp-col > .panel, .insp-col > aside { flex: 1; min-height: 0; }
.insp-bar { display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 8px 12px; background: var(--panel); border-bottom: 1px solid var(--line); flex: none; }
.insp-bar .mono { color: var(--accent); font-size: 12px; }
.x { background: var(--panel2); color: var(--muted); border: 1px solid var(--line); border-radius: 6px;
  padding: 2px 8px; cursor: pointer; font-size: 12px; }
.x:hover { color: var(--fg); border-color: var(--accent); }

.asset-detail { overflow-y: auto; }
.ad-img { width: 100%; border-radius: 8px; border: 1px solid var(--line); background: #000;
  display: block; margin-bottom: 10px; }
.ad-row { display: flex; gap: 10px; font-size: 13px; padding: 5px 0; border-bottom: 1px dashed var(--line); }
.ad-row span { color: var(--muted); width: 64px; flex: none; }
.ad-row b.ok { color: var(--ok); }
.danger-btn { margin-top: 12px; background: none; color: var(--danger); border: 1px solid var(--danger);
  border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 12px; }
.danger-btn:hover { background: rgba(255,107,107,.12); }

/* 空态：单行引导（P3.5 问题 7） */
.insp-empty { padding: 10px 12px; font-size: 12px; color: var(--muted);
  display: flex; align-items: center; gap: 6px; }
.insp-empty::before { content: '▸'; color: var(--green); }
</style>
