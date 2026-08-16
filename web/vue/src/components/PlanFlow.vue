<template>
  <section class="plan-flow">
    <h3>Agent 规划流</h3>
    <div v-for="s in steps" :key="s.key" class="pf-row" @click="go(s)">
      <span class="pf-st" :class="s.state">{{ ICON[s.state] }}</span>
      <span class="pf-label">{{ s.label }}</span>
      <span class="pf-sum">{{ s.summary }}</span>
    </div>
  </section>
</template>

<script setup>
import { computed, inject, nextTick } from 'vue'

const store = inject('store')

const ICON = { done: '✓', draft: '◐', none: '○' }

// 抽卡行状态：从 store.candCounts（候选目录聚合）推导 无/部分/全部镜有候选
const drawState = computed(() => {
  const total = store.shotCount.value
  if (!total) return { state: 'none', summary: '无分镜' }
  let withCands = 0
  for (let i = 1; i <= total; i++) if ((store.candCounts.value[i] || 0) > 0) withCands++
  if (!withCands) return { state: 'none', summary: '未抽卡' }
  if (withCands < total) return { state: 'draft', summary: `${withCands}/${total} 镜有候选` }
  return { state: 'done', summary: `${total} 镜均有候选` }
})

const steps = computed(() => {
  const ss = store.stageStates.value, sm = store.laneSummaries.value
  return [
    { key: 'script', label: '剧本分析', state: ss.script, summary: sm.script },
    { key: 'art', label: '美术设定', state: ss.art, summary: sm.art },
    { key: 'board', label: '分镜', state: ss.board, summary: sm.board },
    { key: 'draw', label: '抽卡', state: drawState.value.state, summary: drawState.value.summary },
    { key: 'compose', label: '成片', state: ss.compose, summary: sm.compose },
  ]
})

// 点击行滚动到对应画布区（剧本 → 打开左侧板；抽卡 → 分镜区）
function go(s) {
  if (s.key === 'script') { store.scriptOpen.value = true; return }
  const target = s.key === 'draw' ? 'board' : s.key
  if (target in store.laneOpen.value) store.laneOpen.value[target] = true
  nextTick(() => document.getElementById('lane-' + target)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}
</script>

<style scoped>
.plan-flow { flex: none; padding: 10px 12px; background: var(--panel); border-bottom: 1px solid var(--line); }
.plan-flow h3 { margin-bottom: 8px; }
.pf-row { display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 6px;
  cursor: pointer; font-size: 13px; }
.pf-row:hover { background: var(--panel2); }
.pf-st { width: 16px; text-align: center; font-size: 12px; }
.pf-st.done { color: var(--ok); }
.pf-st.draft { color: var(--warn); }
.pf-st.none { color: var(--muted); }
.pf-label { font-weight: 600; }
.pf-sum { margin-left: auto; color: var(--muted); font-size: 12px; }
</style>
