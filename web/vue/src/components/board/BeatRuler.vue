<template>
  <div class="beat-ruler" :style="{ width: totalWidth + 'px' }">
    <div v-for="(t, i) in ticks" :key="i" class="tick" :style="{ left: t.left + 'px' }">
      <span class="tick-label">{{ t.label }}</span>
    </div>
  </div>
</template>

<script setup>
// 刻度尺：在每个卡边界标累计秒数（0s/5s/10s…），与卡片行同宽同滚动容器，天然对齐
defineProps({
  ticks: { type: Array, default: () => [] },       // [{ left: px, label: '5s' }]
  totalWidth: { type: Number, default: 0 },
})
</script>

<style scoped>
.beat-ruler { position: relative; height: 20px; margin-bottom: 4px; flex: none;
  border-bottom: 1px solid var(--line); }
.tick { position: absolute; top: 0; bottom: 0; border-left: 1px solid var(--line); }
.tick-label { position: absolute; top: 2px; left: 3px; font-size: 10px; color: var(--muted);
  font-family: var(--mono); white-space: nowrap; }
</style>
