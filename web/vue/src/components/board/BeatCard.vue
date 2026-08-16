<template>
  <div class="beat-card" :class="{ selected, 'drop-target': dropTarget }" :style="{ width: width + 'px' }" @click="emit('select')">
    <button class="redraw" :class="{ spinning: rendering }" title="重抽本镜" @click.stop="emit('redraw')">⟳</button>
    <div class="thumb">
      <img v-if="refImage" :src="refSrc" :alt="'镜' + (index + 1)" loading="lazy" />
      <div v-else class="thumb-empty">未出图</div>
    </div>
    <div class="meta">
      <b>镜{{ index + 1 }}</b>
      <span class="sub">{{ row.frame || '—' }} · {{ row.camera || '—' }} · {{ row.dur || 5 }}s</span>
    </div>
    <span class="dot" :class="status" :title="statusLabel"></span>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import { enc } from '../../api'

const props = defineProps({
  row: { type: Object, required: true },
  index: { type: Number, required: true },
  width: { type: Number, required: true },       // 卡宽 = 时长映射（min 120 / max 280，容器算好传入）
  refImage: { type: String, default: null },     // refs/shot_XX.png 文件名，null = 占位
  status: { type: String, default: 'none' },     // none 无候选 | cands 有候选 | picked 已选
  selected: { type: Boolean, default: false },
  rendering: { type: Boolean, default: false },
  dropTarget: { type: Boolean, default: false },   // 拖拽悬停目标高亮
})
const emit = defineEmits(['select', 'redraw'])

const store = inject('store')
const refSrc = computed(() => `/refs/${enc(store.project.value)}/${store.episode.value}/${props.refImage}`)
const statusLabel = computed(() => ({ none: '无候选', cands: '有候选', picked: '已选' }[props.status] || ''))
</script>

<style scoped>
.beat-card { position: relative; flex: none; background: var(--panel2); border: 1px solid var(--line);
  border-radius: 8px; overflow: hidden; cursor: pointer; transition: border-color .12s, transform .12s, box-shadow .12s; }
.beat-card:hover { border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 4px 14px rgba(0,0,0,.25); }
.beat-card.selected { outline: 2px solid var(--accent); outline-offset: -1px; }
.beat-card.drop-target { border-color: var(--warn); border-style: dashed; }
.thumb { width: 100%; height: 68px; background: #000; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-empty { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  color: var(--muted); font-size: 11px; background: var(--panel); }
.meta { display: flex; align-items: baseline; gap: 6px; padding: 5px 8px; font-size: 12px; }
.meta b { color: var(--accent); }
.meta .sub { color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dot { position: absolute; right: 6px; bottom: 6px; width: 9px; height: 9px; border-radius: 50%;
  background: var(--muted); }
.dot.cands { background: var(--warn); }
.dot.picked { background: var(--ok); box-shadow: 0 0 0 2px rgba(89,201,125,.25); }
.redraw { position: absolute; top: 4px; right: 4px; z-index: 2; width: 24px; height: 24px;
  border: none; border-radius: 6px; background: rgba(30,33,40,.85); color: var(--fg);
  cursor: pointer; font-size: 14px; line-height: 1; opacity: 0; transition: opacity .12s; }
.beat-card:hover .redraw { opacity: 1; }
.redraw:hover { color: var(--accent); }
.redraw.spinning { opacity: 1; animation: spin 1s linear infinite; color: var(--accent); }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
