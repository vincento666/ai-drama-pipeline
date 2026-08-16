<template>
  <main class="canvas" ref="canvasEl" @scroll.passive="onScroll">
    <!-- 剧本已收进左侧板（TopBar「剧本」按钮）；美术泳道默认折叠保留 -->
    <LaneShell lane-key="art" title="② 美术设定"><ArtPanel /></LaneShell>

    <!-- 创作台主视觉：资产条 + 分镜时间轴 + 成片轨 -->
    <AssetStrip />
    <BoardCanvas />
    <ComposeTrack />
  </main>
</template>

<script setup>
import { ref, inject } from 'vue'
import LaneShell from './LaneShell.vue'
import ArtPanel from './ArtPanel.vue'
import AssetStrip from './AssetStrip.vue'
import ComposeTrack from './ComposeTrack.vue'
import BoardCanvas from './board/BoardCanvas.vue'

const store = inject('store')
const canvasEl = ref(null)

const SECTIONS = ['art', 'assets', 'board', 'compose']
// 滚动侦测：最后一个越过视口顶部的分区 = 当前分区（驱动 TopBar 锚点高亮）
function onScroll() {
  const el = canvasEl.value
  if (!el) return
  let current = 'assets'
  for (const key of SECTIONS) {
    const sec = document.getElementById('lane-' + key)
    if (sec && sec.offsetTop - el.scrollTop <= 96) current = key
  }
  store.activeLane.value = current
}
</script>

<style scoped>
.canvas { flex: 1; min-width: 0; overflow-y: auto; position: relative; }
</style>
