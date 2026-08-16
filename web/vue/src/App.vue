<template>
  <div class="shell">
    <TopBar />
    <AgentBar />
    <div class="canvas-row">
      <CanvasView />
      <Inspector />
    </div>
    <JobDrawer :open="jobsOpen" @close="store.jobsOpen.value = false" />
    <ScriptDrawer :open="scriptOpen" @close="store.scriptOpen.value = false" />
    <AgentDock :open="agentOpen" @close="store.agentOpen.value = false" />
  </div>
</template>

<script setup>
import { computed, onMounted, provide, watch } from 'vue'
import { createStore } from './store'
import { api, enc } from './api'
import TopBar from './components/TopBar.vue'
import AgentBar from './components/AgentBar.vue'
import CanvasView from './components/CanvasView.vue'
import Inspector from './components/Inspector.vue'
import JobDrawer from './components/JobDrawer.vue'
import ScriptDrawer from './components/ScriptDrawer.vue'
import AgentDock from './components/AgentDock.vue'

const store = createStore()
provide('store', store)
defineExpose({ store })

const jobsOpen = computed(() => store.jobsOpen.value)
const scriptOpen = computed(() => store.scriptOpen.value)
const agentOpen = computed(() => store.agentOpen.value)

onMounted(store.init)

// 全局自动回显 watcher（spec 10）：每 5s 轮询 /api/canvas 的 rev（事实源摘要），
// 变化即全量刷新展示层——任何来源的文件改动（外部 agent 写盘 / /api/patch / 访谈简报）都会自动回显。
let lastRev = null
async function pollRev() {
  if (!store.project.value) return
  try {
    const c = await api(`/api/canvas/${enc(store.project.value)}/${store.episode.value}`)
    if (lastRev == null) { lastRev = c.rev; return }
    if (c.rev && c.rev !== lastRev) {
      lastRev = c.rev
      store.canvasTick.value++        // BoardCanvas.loadAll / ComposeTrack.load
      store.creativeTick.value++      // ScriptPanel.loadCreative（剧本侧板打开时）
      store.refreshWizard()
      store.refreshEpisode()
      store.reloadAssets()            // 资产库也在 rev 摘要内
    }
  } catch (e) { /* 桥不可达时静默，下拍重试 */ }
}
// 切项目/集时重置基线，避免误报
watch([store.project, store.episode], () => { lastRev = null })
onMounted(() => { setInterval(pollRev, 5000) })
</script>

<style scoped>
.canvas-row { flex: 1; display: flex; min-height: 0; overflow: hidden; }
</style>
