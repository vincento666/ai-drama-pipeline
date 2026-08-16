<template>
  <div class="th-trace" :class="{ open }">
    <!-- 思考中折叠块（P3.5 问题 5）：默认折叠，标题「思考中」+ 暗夜绿流光动画；
         折叠态显示最新一行（当前 running 事件标题+摘要，无 running 显示最近事件）；
         展开显示完整轨迹（复用 EventTrace，headless 只渲染列表）。 -->
    <button class="th-head" @click="open = !open" :title="open ? '收起思考过程' : '展开思考过程'">
      <span class="th-dot" :class="running ? 'running' : ''"></span>
      <span class="th-title">思考中</span>
      <span class="th-latest">{{ latestText }}</span>
      <span class="th-fold">{{ open ? '▾' : '▸' }}</span>
    </button>
    <div v-if="open" class="th-body">
      <EventTrace :items="items" title="思考中" :collapsed="false" :live="true" headless />
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import EventTrace from './EventTrace.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
})

const open = ref(false)   // 默认折叠

// 与 EventTrace 相同的去重键规则：有 id 用 id，否则 (kind|title)，终态覆盖 running
const keyOf = (it) => (it.id != null ? String(it.id) : `${it.kind}|${it.title}`)
const merged = computed(() => {
  const map = new Map()
  for (const it of props.items || []) {
    const key = keyOf(it)
    const prev = map.get(key)
    if (!prev) map.set(key, it)
    else if (prev.status === 'running' || it.status !== 'running') map.set(key, it)
  }
  return [...map.values()]
})

const running = computed(() => merged.value.some(i => i.status === 'running'))

// 折叠态最新一行：当前 running 事件（标题+摘要）；无 running 用最近事件（数组末位）
const latestText = computed(() => {
  const list = merged.value
  if (!list.length) return '（等待执行事件…）'
  const r = list.find(i => i.status === 'running') || list[list.length - 1]
  return (r.title || '') + (r.summary ? ' · ' + r.summary : '')
})
</script>

<style scoped>
.th-trace { border: 1px solid rgba(52,211,153,.35); border-radius: 8px;
  background: var(--green-deep-2); overflow: hidden; }
.th-head { width: 100%; display: flex; align-items: center; gap: 8px;
  background: none; border: none; cursor: pointer; padding: 6px 10px; text-align: left; }
.th-head:hover { background: rgba(52,211,153,.08); }
/* 暗夜绿 + 流光动画（复用 EventTrace 的 evt-title 渐变扫光） */
.th-title {
  flex: none; font-size: 12px; font-weight: 600;
  background: linear-gradient(100deg, var(--green-deep) 0%, var(--green) 30%,
    var(--green-soft) 50%, var(--green) 70%, var(--green-deep) 100%);
  background-size: 220% 100%;
  -webkit-background-clip: text; background-clip: text;
  color: transparent;
  animation: th-flow 2.8s linear infinite;
}
@keyframes th-flow { to { background-position: -220% 0; } }
.th-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: var(--muted); }
.th-dot.running { background: var(--green); box-shadow: 0 0 0 2px rgba(52,211,153,.25);
  animation: th-pulse 1.2s ease-in-out infinite; }
@keyframes th-pulse { 50% { box-shadow: 0 0 0 4px rgba(52,211,153,.12); } }
.th-latest { flex: 1; min-width: 0; font-size: 12px; color: var(--green-soft);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.th-fold { font-size: 11px; color: var(--muted); }
.th-body { border-top: 1px solid rgba(52,211,153,.2); padding: 6px 10px; }
.th-body :deep(.evt-trace) { border: none; background: none; }
</style>
