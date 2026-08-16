<template>
  <header class="topbar">
    <div class="brand">AI 短剧流水线 <span class="tag">创作画布</span></div>
    <label>项目
      <select :value="store.project.value" @change="onProject">
        <option v-for="p in store.projects.value" :key="p" :value="p">{{ p }}</option>
      </select>
    </label>
    <label>集
      <select :value="store.episode.value" @change="onEpisode">
        <option v-for="n in store.episodes.value" :key="n" :value="n">E{{ String(n).padStart(2, '0') }}</option>
      </select>
    </label>
    <nav class="anchors">
      <button v-for="a in ANCHORS" :key="a.key" class="ghost anchor"
        :class="{ on: store.activeLane.value === a.key }" @click="goLane(a.key)">{{ a.label }}</button>
    </nav>
    <span class="status" :class="store.statusCls.value">{{ store.status.value }}</span>
    <button class="ghost" :class="{ active: store.scriptOpen.value }" @click="store.scriptOpen.value = true">剧本</button>
    <button class="ghost" :class="{ active: store.agentOpen.value }" @click="store.agentOpen.value = !store.agentOpen.value">Agent</button>
    <button class="ghost" :class="{ active: store.jobsOpen.value }" @click="store.jobsOpen.value = !store.jobsOpen.value">任务队列</button>
    <button class="primary" :disabled="!store.dirty.value" @click="store.saveBoard()">保存分镜</button>
  </header>
</template>

<script setup>
import { inject, nextTick } from 'vue'

const store = inject('store')

const ANCHORS = [
  { key: 'assets', label: '资产' },
  { key: 'board', label: '分镜' },
  { key: 'compose', label: '成片' },
]

function onProject(e) {
  store.project.value = e.target.value
  store.onProjectChange()
}
function onEpisode(e) {
  store.episode.value = Number(e.target.value)
  store.onEpisodeChange()
}
function goLane(key) {
  if (key in store.laneOpen.value) store.laneOpen.value[key] = true   // 折叠的泳道先展开再滚动
  nextTick(() => document.getElementById('lane-' + key)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}
</script>

<style scoped>
.anchors { display: flex; gap: 4px; }
.anchor { font-size: 12px !important; padding: 5px 10px !important; }
.anchor.on { border-color: var(--accent) !important; color: var(--accent) !important; }
</style>
