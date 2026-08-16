<template>
  <section class="ref-panel">
    <div class="ref-head">
      <h3>参考图（Shot ref）</h3>
      <button class="mini" :disabled="busy" @click="emit('refresh')">
        {{ busy ? '生成中…' : (data.prompt ? '刷新提示词' : '生成提示词') }}
      </button>
    </div>
    <pre class="mono box">{{ data.prompt || '（暂无提示词，点「生成提示词」）' }}</pre>
    <img v-if="data.image" class="ref-img" :src="imgSrc" :alt="`shot_${String(data.shot || 0).padStart(2, '0')} 参考图`" />
    <div v-else class="ref-empty">尚未出图 <span class="hint">（选片后自动以该片首帧晋升为参考图）</span></div>
  </section>
</template>

<script setup>
import { computed, inject } from 'vue'
import { enc } from '../../api'

const props = defineProps({
  data: { type: Object, default: () => ({ shot: 0, prompt: '', image: null }) },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['refresh'])

const store = inject('store')
// 图片静态文件：GET /refs/<project>/<episode>/<file>（E<n>/refs/ 下）
const imgSrc = computed(() => `/refs/${enc(store.project.value)}/${store.episode.value}/${props.data.image}`)
</script>

<style scoped>
.ref-panel { margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
.ref-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.ref-head h3 { margin-bottom: 0; }
.mini { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.mini:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.mini:disabled { opacity: .4; cursor: default; }
.box { background: var(--panel2); border: 1px solid var(--line); border-radius: 6px; padding: 8px;
  white-space: pre-wrap; word-break: break-all; max-height: 120px; overflow-y: auto; margin-bottom: 8px; }
.ref-img { width: 100%; border-radius: 6px; border: 1px solid var(--line); display: block; background: #000; }
.ref-empty { border: 1px dashed var(--line); border-radius: 6px; padding: 18px 10px; text-align: center;
  color: var(--muted); font-size: 12px; }
</style>
