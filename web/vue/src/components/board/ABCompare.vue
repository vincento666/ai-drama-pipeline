<template>
  <div class="compare">
    <div class="cmp-col">
      <video :src="`/video/${enc(project)}/${episode}/${cmp[0]}`" muted autoplay loop playsinline />
      <button @click="emit('choose', cmp[0])">选 A：{{ cmp[0].replace(/\.mp4$/, '') }}</button>
    </div>
    <div class="cmp-col">
      <video :src="`/video/${enc(project)}/${episode}/${cmp[1]}`" muted autoplay loop playsinline />
      <button @click="emit('choose', cmp[1])">选 B：{{ cmp[1].replace(/\.mp4$/, '') }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed, inject } from 'vue'
import { enc } from '../../api'

defineProps({ cmp: { type: Array, required: true } })   // 恰好 2 个候选文件名
const emit = defineEmits(['choose'])

const store = inject('store')
const project = computed(() => store.project.value)
const episode = computed(() => store.episode.value)
</script>

<style scoped>
.compare { display: flex; gap: 8px; margin-bottom: 10px; }
.cmp-col { flex: 1; min-width: 0; }
.cmp-col video { width: 100%; height: 96px; object-fit: cover; background: #000; border-radius: 6px; display: block; }
.cmp-col button { width: 100%; margin-top: 4px; background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 5px 0; font-size: 12px; cursor: pointer; }
</style>
