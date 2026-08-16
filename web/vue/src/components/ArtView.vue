<template>
  <div class="art-view">
    <ArtPanel />
    <AssetStrip />
  </div>
</template>

<script setup>
// 美术·资产视图（spec 11 §11 映射）：ArtPanel（资产登记/上传/删除/分组 + C/S/P/R 风格条）+ AssetStrip（资产预览条）迁入。
import ArtPanel from './ArtPanel.vue'
import AssetStrip from './AssetStrip.vue'
</script>

<style scoped>
.art-view { max-width: 1160px; padding: 4px 8px 16px; }
</style>
