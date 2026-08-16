<template>
  <div class="wall">
    <div class="render-ctl">
      <button @click="emit('render')" :disabled="rendering">抽卡</button>
      <select :value="shots" @change="emit('update:shots', Number($event.target.value))">
        <option :value="1">1 候选</option><option :value="2">2 候选</option><option :value="3">3 候选</option>
      </select>
      <select :value="mode" @change="emit('update:mode', $event.target.value)">
        <option value="quick">快速 ~9s/段</option>
        <option value="std">标准 ~48s/段</option>
      </select>
      <select :value="refCode" @change="emit('update:refCode', $event.target.value)">
        <option value="">无参考图</option>
        <option v-for="a in assets" :key="a.code" :value="a.code">{{ a.code }} {{ a.name }}</option>
      </select>
    </div>
    <div class="rstatus">{{ renderStatus }}</div>
    <div class="cmp-bar">
      <button class="mini" :class="{ on: cmpMode }" @click="emit('toggle-cmp')">{{ cmpMode ? '退出对比' : 'A/B 对比' }}</button>
      <span v-if="cmpMode" class="hint">点两个候选分别设为 A / B</span>
    </div>
    <div class="gallery">
      <div v-for="f in files" :key="f.name" class="cand"
           :class="{ cmpA: cmp[0] === f.name, cmpB: cmp[1] === f.name }"
           @click="emit('cand-click', f.name)">
        <video :src="`/video/${enc(project)}/${episode}/${f.name}`" muted loop preload="metadata" />
        <div class="cand-label">{{ f.name.replace(/\.mp4$/, '') }}
          <span v-if="review[f.name]" class="badge" :class="review[f.name].verdict">{{ verdictLabel(review[f.name].verdict) }}</span>
        </div>
      </div>
      <div v-if="!files.length" class="wall-empty">暂无候选，先抽卡</div>
    </div>
    <div v-if="pendingFile" class="pick-bar">
      <span class="mono">{{ pendingFile.replace(/\.mp4$/, '') }}</span>
      <input :value="note" @input="emit('update:note', $event.target.value)" placeholder="选中原因（供 Agent 复盘，可留空）" />
      <button @click="emit('confirm')">确认选中</button>
      <button class="ghost" @click="emit('cancel')">取消</button>
    </div>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import { enc } from '../../api'

defineProps({
  files: { type: Array, default: () => [] },
  review: { type: Object, default: () => ({}) },   // file → { verdict, ... }
  cmp: { type: Array, default: () => [] },
  cmpMode: { type: Boolean, default: false },
  rendering: { type: Boolean, default: false },
  renderStatus: { type: String, default: '' },
  pendingFile: { type: String, default: '' },
  assets: { type: Array, default: () => [] },       // 有图资产（Ref2VA 参考图下拉）
  shots: { type: Number, default: 2 },
  mode: { type: String, default: 'quick' },
  refCode: { type: String, default: '' },
  note: { type: String, default: '' },
})
const emit = defineEmits(['render', 'cand-click', 'toggle-cmp', 'confirm', 'cancel',
  'update:shots', 'update:mode', 'update:refCode', 'update:note'])

const store = inject('store')
const project = computed(() => store.project.value)
const episode = computed(() => store.episode.value)

function verdictLabel(v) { return { ok: '通过', warn: '复核', reject: '废片' }[v] || v }
</script>

<style scoped>
.render-ctl { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.render-ctl button { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 6px 12px; cursor: pointer; }
.render-ctl button:disabled { opacity: .4; cursor: default; }
.render-ctl select { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 4px 6px; }
.rstatus { font-size: 12px; color: var(--warn); margin-bottom: 6px; }
.cmp-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.cmp-bar .mini { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.cmp-bar .mini.on { border-color: var(--accent); color: var(--accent); }
.gallery { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.wall-empty { width: 100%; border: 1px dashed var(--line); border-radius: 6px; padding: 14px 10px;
  text-align: center; color: var(--muted); font-size: 12px; }
.cand { width: 120px; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; cursor: pointer; background: var(--panel2); }
.cand:hover { border-color: var(--accent); }
.cand video { width: 100%; height: 68px; object-fit: cover; display: block; background: #000; }
.cand-label { font-size: 11px; color: var(--muted); padding: 2px 4px; text-align: center; }
.cand.cmpA { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.cand.cmpB { border-color: var(--warn); box-shadow: 0 0 0 1px var(--warn); }
.badge { display: inline-block; margin-left: 4px; padding: 0 5px; border-radius: 8px; font-size: 10px; line-height: 1.5; }
.badge.ok { background: rgba(89,201,125,.18); color: var(--ok); }
.badge.warn { background: rgba(255,180,84,.18); color: var(--warn); }
.badge.reject { background: rgba(255,107,107,.18); color: var(--danger); }
.pick-bar { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; background: var(--panel2); border: 1px solid var(--accent); border-radius: 6px; padding: 8px; }
.pick-bar .mono { color: var(--accent); }
.pick-bar input { background: var(--panel); color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; font-size: 12px; }
.pick-bar button { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 12px; }
.pick-bar button.ghost { background: var(--panel); color: var(--muted); border: 1px solid var(--line); }
</style>
