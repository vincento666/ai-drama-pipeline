<template>
  <section class="asset-strip" id="lane-assets">
    <div class="strip-head">
      <h3>资产条</h3>
      <span class="hint">{{ assets.length }} 项带图资产 · 点卡在检查器查看 · 抽卡时可作 Ref2VA 参考图</span>
    </div>
    <div class="strip-scroll">
      <div v-for="a in assets" :key="a.code" class="asset-chip"
           :class="['t' + a.type, { on: selectedCode === a.code }]" @click="pick(a)">
        <img :src="`/asset-img/${a.code}`" :alt="a.name" loading="lazy" />
        <div class="chip-meta"><b>{{ a.code }}</b><span>{{ a.name }}</span></div>
      </div>
      <div v-if="!assets.length" class="strip-empty">暂无带图资产——展开上方「② 美术设定」登记</div>
    </div>
  </section>
</template>

<script setup>
import { computed, inject } from 'vue'

const store = inject('store')
// 带图资产（BoardCanvas/ArtPanel 挂载或上传后写入 store.assetsWithImg）
const assets = computed(() => store.assetsWithImg.value)
const selectedCode = computed(() => {
  const s = store.selection.value
  return s && s.type === 'asset' ? s.id : ''
})

function pick(a) {
  store.selection.value = { type: 'asset', id: a.code }
}
</script>

<style scoped>
.asset-strip { padding: 10px 16px 6px; border-bottom: 1px solid var(--line); }
.strip-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.strip-head h3 { margin-bottom: 0; }
.strip-scroll { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 6px; }
.asset-chip { flex: none; width: 132px; background: var(--panel2); border: 1px solid var(--line);
  border-left-width: 3px; border-radius: 8px; overflow: hidden; cursor: pointer; transition: border-color .12s; }
.asset-chip:hover { border-color: var(--accent); }
.asset-chip.on { outline: 2px solid var(--accent); outline-offset: -1px; }
/* C/S/P/R 分组色标（左边条） */
.asset-chip.tC { border-left-color: var(--accent); }
.asset-chip.tS { border-left-color: var(--ok); }
.asset-chip.tP { border-left-color: var(--warn); }
.asset-chip.tR { border-left-color: #b48cff; }
.asset-chip img { width: 100%; height: 72px; object-fit: cover; display: block; background: #000; }
.chip-meta { display: flex; align-items: center; gap: 6px; padding: 4px 8px; font-size: 12px; }
.chip-meta b { font-family: var(--mono); font-size: 11px; }
.chip-meta span { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.strip-empty { color: var(--muted); font-size: 12px; padding: 14px 12px; border: 1px dashed var(--line);
  border-radius: 8px; flex: none; align-self: center; }
</style>
