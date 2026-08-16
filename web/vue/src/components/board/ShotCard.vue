<template>
  <!-- P6b：只读摘要卡（网格模式）——去内嵌 ShotFields 编辑；编辑唯一入口 = 右侧 Inspector -->
  <div class="shot-card" :class="{ selected, 'has-final': hasFinal, 'drop-target': dropTarget }" @click="emit('select')">
    <div class="thumb">
      <img v-if="refSrc" :src="refSrc" :alt="'镜' + (index + 1)" loading="lazy" />
      <div v-else class="thumb-empty">未出图</div>
    </div>
    <div class="card-body">
      <div class="card-head">
        <span class="shot-no">镜 {{ index + 1 }}</span>
        <span class="shot-title" :title="row.note || ''">{{ row.note || '（无备注）' }}</span>
        <span v-if="hasFinal" class="final-badge">✓ 已选</span>
        <span class="dot" :class="status" :title="statusTitle"></span>
      </div>
      <div class="meta-row">
        <span class="kv"><b>景别</b>{{ row.frame || '—' }}</span>
        <span class="kv"><b>运镜</b>{{ row.camera || '—' }}</span>
        <span class="kv"><b>时长</b>{{ row.dur || 5 }}s</span>
      </div>
      <div class="meta-row">
        <span class="kv"><b>角色</b>{{ charsText || '—' }}</span>
        <span class="kv"><b>场景</b>{{ sceneText || '—' }}</span>
        <span class="kv"><b>灯光</b>{{ row.light || '—' }}</span>
      </div>
      <div class="dialogue" :title="row.dialogue">{{ row.dialogue ? '💬 ' + row.dialogue : '（无对白）' }}</div>
      <div class="edit-hint">点击卡片 → 右侧 Inspector 编辑</div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'

const props = defineProps({
  row: { type: Object, required: true },   // 只读展示 store.boardRows 元素（编辑在 Inspector）
  index: { type: Number, required: true },
  selected: { type: Boolean, default: false },
  hasFinal: { type: Boolean, default: false },
  dropTarget: { type: Boolean, default: false },   // 拖拽悬停目标高亮
  refSrc: { type: String, default: null },         // 参考图/资产图完整 URL（BoardCanvas 计算）
  candCount: { type: Number, default: 0 },         // 候选数（状态点）
})
const emit = defineEmits(['select'])

const store = inject('store')

// 代号 → 名称解析（store.assets 查 C/S 代号；未登记代号原样显示）
const charsText = computed(() => (props.row.chars || '').split(',')
  .map(c => c.trim()).filter(Boolean)
  .map(c => (store.assets[c] && store.assets[c].name) || c).join('、'))
const sceneText = computed(() => {
  const s = (props.row.scene || '').trim()
  if (!s) return ''
  return (store.assets[s] && store.assets[s].name) || s
})
const status = computed(() => props.hasFinal ? 'picked' : (props.candCount > 0 ? 'cands' : 'none'))
const statusTitle = computed(() => ({ picked: '已选', cands: `${props.candCount} 候选`, none: '无候选' })[status.value] || '')
</script>

<style scoped>
.shot-card { background: var(--panel2); border: 1px solid var(--line); border-radius: 10px;
  overflow: hidden; cursor: pointer; transition: border-color .12s, transform .12s, box-shadow .12s; }
.shot-card:hover { border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 4px 14px rgba(0,0,0,.25); }
.shot-card.selected { outline: 2px solid var(--accent); outline-offset: -1px; box-shadow: 0 4px 16px rgba(79,140,255,.16); }
.shot-card.has-final { box-shadow: inset 3px 0 0 var(--ok); }
.shot-card.has-final.selected { box-shadow: inset 3px 0 0 var(--ok), 0 4px 16px rgba(79,140,255,.16); }
.shot-card.drop-target { border-color: var(--warn); border-style: dashed; }
.thumb { width: 100%; height: 96px; background: #000; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-empty { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  color: var(--muted); font-size: 11px; background: var(--panel); }
.card-body { padding: 8px 10px 10px; }
.card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.shot-no { font-weight: 700; color: var(--accent); font-size: 14px; }
.shot-title { color: var(--muted); font-size: 12px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.final-badge { color: var(--ok); font-size: 12px; font-weight: 700; }
.dot { flex: none; width: 9px; height: 9px; border-radius: 50%; background: var(--muted); }
.dot.cands { background: var(--warn); }
.dot.picked { background: var(--ok); box-shadow: 0 0 0 2px rgba(89,201,125,.25); }
.meta-row { display: flex; gap: 8px; margin-bottom: 4px; }
.kv { flex: 1; min-width: 0; font-size: 11px; color: var(--fg); display: flex; gap: 4px; align-items: baseline;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kv b { color: var(--muted); font-weight: 600; flex: none; }
.dialogue { font-size: 11px; color: var(--fg); margin-top: 4px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.edit-hint { margin-top: 6px; font-size: 10px; color: var(--muted); border-top: 1px dashed var(--line);
  padding-top: 5px; }
</style>
