<template>
  <div class="compose-view">
    <ComposeTrack />
  </div>
</template>

<script setup>
// 成片视图（spec 11 §11 映射；P6b 升级）：ComposeTrack = 成片编排台
// （已选片段横条 + 拖拽重排 + 顺序持久化 + 按序拼接 + 成片预览）迁入。
import ComposeTrack from './ComposeTrack.vue'
</script>

<style scoped>
.compose-view { max-width: 1160px; padding: 4px 8px 16px; }
</style>
