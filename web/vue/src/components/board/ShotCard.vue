<template>
  <div class="shot-card" :class="{ selected, 'has-final': hasFinal, 'drop-target': dropTarget }" @click="emit('select')">
    <div class="card-head">
      <span class="shot-no">镜 {{ index + 1 }}</span>
      <span class="shot-title">{{ row.note || '' }}</span>
      <span v-if="hasFinal" class="final-badge">✓ 已选</span>
    </div>
    <ShotFields :row="row" :vocab="vocab" @dirty="emit('dirty')" />
  </div>
</template>

<script setup>
import ShotFields from './ShotFields.vue'

defineProps({
  row: { type: Object, required: true },   // 直接就地编辑 rows 数组元素（沿用原 BoardView 行为）
  index: { type: Number, required: true },
  selected: { type: Boolean, default: false },
  hasFinal: { type: Boolean, default: false },
  dropTarget: { type: Boolean, default: false },   // 拖拽悬停目标高亮
  vocab: { type: Object, default: () => ({ frames: [], cameras: [] }) },
})
const emit = defineEmits(['select', 'dirty'])
</script>

<style scoped>
.shot-card { background: var(--panel2); border: 1px solid var(--line); border-radius: 10px;
  padding: 10px; cursor: pointer; transition: border-color .12s, transform .12s, box-shadow .12s; }
.shot-card:hover { border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 4px 14px rgba(0,0,0,.25); }
.shot-card.selected { outline: 2px solid var(--accent); outline-offset: -1px; box-shadow: 0 4px 16px rgba(79,140,255,.16); }
.shot-card.has-final { box-shadow: inset 3px 0 0 var(--ok); }
.shot-card.has-final.selected { box-shadow: inset 3px 0 0 var(--ok), 0 4px 16px rgba(79,140,255,.16); }
.shot-card.drop-target { border-color: var(--warn); border-style: dashed; }
.card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
.shot-no { font-weight: 700; color: var(--accent); font-size: 14px; }
.shot-title { color: var(--muted); font-size: 12px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.final-badge { color: var(--ok); font-size: 12px; font-weight: 700; }
</style>
