<template>
  <aside class="panel tree-panel">
    <h3>剧本分段</h3>
    <div v-for="(act, i) in acts" :key="act.title" class="act-node">
      <div class="act-title" @click="open[i] = !open[i]">
        <span class="toggle">{{ open[i] ? '▾' : '▸' }}</span>{{ act.title }}
      </div>
      <div v-if="open[i]" class="act-text mono">{{ act.text }}</div>
    </div>
    <p class="hint">按剧本.md 的“## 幕/集标题”自动分段；点击查看文本。</p>
  </aside>
</template>

<script setup>
import { ref } from 'vue'

defineProps({ acts: { type: Array, default: () => [] } })

// 展开状态本地管理（原 BoardView 把 open 挂在 act 对象上，效果相同）
const open = ref([])
</script>

<style scoped>
.tree-panel { width: 220px; flex: none; border-right: 1px solid var(--line); }
.act-node { margin-bottom: 6px; }
.act-title { cursor: pointer; padding: 4px 6px; border-radius: 6px; color: var(--accent); font-weight: 600; font-size: 13px; }
.act-title:hover { background: var(--panel2); }
.act-text { background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  padding: 8px; margin: 4px 0 8px; max-height: 120px; overflow-y: auto; }
.toggle { display: inline-block; width: 14px; color: var(--muted); }
</style>
