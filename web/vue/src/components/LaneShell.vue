<template>
  <section class="lane" :id="'lane-' + laneKey">
    <header class="lane-head" @click="toggle">
      <span class="fold">{{ open ? '▾' : '▸' }}</span>
      <h2>{{ title }}</h2>
      <span class="pill" :class="state">{{ STATE_LABEL[state] }}</span>
      <span class="summary">{{ summary }}</span>
      <span class="ops" @click.stop><slot name="ops" /></span>
    </header>
    <div v-show="open" class="lane-body"><slot /></div>
  </section>
</template>

<script setup>
import { computed, inject } from 'vue'

const props = defineProps({
  laneKey: { type: String, required: true },   // script | art | board | compose
  title: { type: String, required: true },
})

const store = inject('store')
const STATE_LABEL = { done: '● 完成', draft: '◐ 草稿', none: '○ 无' }

const open = computed(() => store.laneOpen.value[props.laneKey] !== false)
const state = computed(() => store.stageStates.value[props.laneKey] || 'none')
const summary = computed(() => store.laneSummaries.value[props.laneKey] || '')

function toggle() { store.laneOpen.value[props.laneKey] = !open.value }
</script>

<style scoped>
.lane { border-bottom: 1px solid var(--line); }
.lane-head { display: flex; align-items: center; gap: 10px; padding: 10px 16px; cursor: pointer;
  user-select: none; background: var(--panel); position: sticky; top: 0; z-index: 5; }
.lane-head:hover { background: var(--panel2); }
.fold { color: var(--muted); width: 14px; }
.lane-head h2 { font-size: 14px; font-weight: 700; }
.pill { font-size: 11px; padding: 0 8px; border-radius: 8px; line-height: 1.7; }
.pill.done { color: var(--ok); background: rgba(89,201,125,.15); }
.pill.draft { color: var(--warn); background: rgba(255,180,84,.15); }
.pill.none { color: var(--muted); background: var(--panel2); }
.summary { color: var(--muted); font-size: 12px; }
.ops { margin-left: auto; display: flex; gap: 8px; }
.lane-body { padding: 4px 8px 14px; }
</style>
