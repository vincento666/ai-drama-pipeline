<template>
  <div class="evt-trace" :class="{ open, live }">
    <!-- 默认折叠为单行标题：暗夜绿 + 流光动画（background-clip:text 渐变扫光） -->
    <button v-if="!headless" class="evt-head" @click="open = !open" :title="open ? '收起任务轨迹' : '展开任务轨迹'">
      <span class="evt-dot" :class="headDot"></span>
      <span class="evt-title">{{ showTitle }}</span>
      <span v-if="merged.length" class="evt-count">{{ doneCount }}/{{ merged.length }}</span>
      <span class="evt-fold">{{ open ? '▾' : '▸' }}</span>
    </button>

    <!-- 展开：垂直时间线，每行 = [状态图标] 事件标题 + 回执摘要 -->
    <div v-if="open || headless" ref="listEl" class="evt-list">
      <div v-for="it in rows" :key="it._key" class="evt-row" :class="'st-' + it.status">
        <span class="evt-icon" :class="it.status" :title="STATUS_TIP[it.status] || it.status"></span>
        <span class="evt-kind" :class="'k-' + it.kind">{{ KIND_LABEL[it.kind] || it.kind }}</span>
        <span class="evt-row-title">{{ it.title }}</span>
        <span v-if="it.summary" class="evt-summary">{{ it.summary }}</span>
      </div>
      <div v-if="!merged.length" class="evt-empty">无执行记录</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'

// 垂直事件进度条（spec 09 §9.2 + docs/11 §9.2）。P3 接真（SSE trace 驱动实时追加/更新）：
// props 接口向后兼容（P1 items/title/collapsed 不变），新增可选 live（实时模式）：
//   live = true 时折叠态标题显示「执行中：<当前 subtask>」（有 running 行时）、
//   展开列表自动滚动到底（max-height 内滚动）。
// P3.5 问题 2/5：items 按 (kind|title)（有 id 用 id）去重合并——
//   同一键先 running 后终态 → 只显示终态行（状态/摘要用最新）；只有 running 无终态
//   → 显示 running（转圈）；终态不被后来的 running 覆盖；顺序 = 首次出现顺序。
//   新增可选 headless（只渲染列表，无头部；ThinkingTrace 思考中折叠块展开态复用）。
// props 接口：
//   items: [{ id?, kind, title, status, summary }]
//     kind   ∈ subtask | command | search | tool | patch（事件类型 label）
//     status ∈ running | success | error | skip（状态图标：转圈 / ✓ / ✕ / –）
//   title: 折叠态单行标题（默认「任务轨迹」）；collapsed: 默认折叠；live: 实时模式
const props = defineProps({
  items: { type: Array, default: () => [] },
  title: { type: String, default: '任务轨迹' },
  collapsed: { type: Boolean, default: true },
  live: { type: Boolean, default: false },
  headless: { type: Boolean, default: false },
})

const open = ref(!props.collapsed)   // 默认按 collapsed 折叠；点标题可展开/收起

const STATUS_TIP = { running: '执行中', success: '成功', error: '失败', skip: '跳过' }
const KIND_LABEL = { subtask: '子任务', command: '命令', search: '搜索', tool: '工具', patch: '写盘' }

// 去重合并键：有 id 用 id，无 id 用 kind|title
const keyOf = (it) => (it.id != null ? String(it.id) : `${it.kind}|${it.title}`)

const merged = computed(() => {
  const map = new Map()
  for (const it of props.items || []) {
    const key = keyOf(it)
    const prev = map.get(key)
    if (!prev) map.set(key, { ...it, _key: key })
    else if (prev.status === 'running' || it.status !== 'running') {
      // running 被任何后续覆盖（running→终态 / running→running）；终态不被 running 降级
      map.set(key, { ...it, _key: key })
    }
  }
  return [...map.values()]
})

// 展开顺序 = 首次出现顺序（Map 保序）；行即合并结果
const rows = computed(() => merged.value)

const doneCount = computed(() => merged.value.filter(i => i.status === 'success').length)
const headDot = computed(() => merged.value.some(i => i.status === 'running') ? 'running' : '')
// live 模式：有 running 行 → 折叠标题「执行中：<当前 subtask>」（流光动画沿用 P1 样式）
const showTitle = computed(() => {
  if (props.live) {
    const r = merged.value.find(i => i.status === 'running')
    if (r && r.title) return '执行中：' + r.title
  }
  return props.title
})

// live 模式：items 实时更新 → 自动滚动到底
const listEl = ref(null)
watch(() => props.items.length, async () => {
  if (!props.live) return
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
})
</script>

<style scoped>
.evt-trace { border: 1px solid var(--line); border-radius: 8px; background: var(--panel);
  overflow: hidden; }
.evt-head { width: 100%; display: flex; align-items: center; gap: 8px;
  background: none; border: none; cursor: pointer; padding: 6px 10px; text-align: left; }
.evt-head:hover { background: var(--panel2); }
/* 暗夜绿 + 流光动画：渐变扫光背景裁剪为文字 */
.evt-title {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 12px; font-weight: 600;
  background: linear-gradient(100deg, var(--green-deep) 0%, var(--green) 30%,
    var(--green-soft) 50%, var(--green) 70%, var(--green-deep) 100%);
  background-size: 220% 100%;
  -webkit-background-clip: text; background-clip: text;
  color: transparent;
  animation: evt-flow 2.8s linear infinite;
}
@keyframes evt-flow { to { background-position: -220% 0; } }
.evt-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: var(--muted); }
.evt-dot.running { background: var(--green); box-shadow: 0 0 0 2px rgba(52,211,153,.25);
  animation: evt-pulse 1.2s ease-in-out infinite; }
@keyframes evt-pulse { 50% { box-shadow: 0 0 0 4px rgba(52,211,153,.12); } }
.evt-count { font-size: 11px; color: var(--green); font-family: var(--mono); }
.evt-fold { font-size: 11px; color: var(--muted); }

/* 垂直时间线 */
.evt-list { border-top: 1px solid var(--line); padding: 4px 10px 8px; }
.evt-trace.live .evt-list { max-height: 240px; overflow-y: auto; }
.evt-row { display: flex; align-items: center; gap: 8px; padding: 4px 0;
  border-left: 1px solid var(--line); margin-left: 5px; padding-left: 12px; }
.evt-row:first-child { margin-top: 6px; }
.evt-icon { flex: none; width: 14px; height: 14px; text-align: center; font-size: 11px; line-height: 14px;
  border-radius: 50%; }
.evt-icon.success { color: var(--green); }
.evt-icon.success::before { content: '✓'; }
.evt-icon.error { color: var(--danger); }
.evt-icon.error::before { content: '✕'; }
.evt-icon.skip { color: var(--muted); }
.evt-icon.skip::before { content: '–'; }
/* running = 转圈动画（CSS 边框 spinner） */
.evt-icon.running { width: 12px; height: 12px; border: 2px solid rgba(52,211,153,.25);
  border-top-color: var(--green); border-radius: 50%; animation: spin .8s linear infinite;
  margin: 1px; }
@keyframes spin { to { transform: rotate(360deg); } }
.evt-kind { flex: none; font-size: 10px; color: var(--muted); border: 1px solid var(--line);
  border-radius: 4px; padding: 0 5px; line-height: 1.6; }
.evt-kind.k-subtask { color: var(--green); border-color: rgba(52,211,153,.35); }
.evt-kind.k-command { color: var(--accent); border-color: rgba(79,140,255,.35); }
.evt-kind.k-search { color: var(--warn); border-color: rgba(255,180,84,.35); }
.evt-kind.k-tool { color: #b48cff; border-color: rgba(180,140,255,.35); }
.evt-kind.k-patch { color: var(--ok); border-color: rgba(89,201,125,.35); }
.evt-row-title { flex: 1; min-width: 0; font-size: 12px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.evt-row.st-error .evt-row-title { color: var(--danger); }
.evt-row.st-skip .evt-row-title { color: var(--muted); }
.evt-summary { flex: none; max-width: 55%; font-size: 11px; color: var(--muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.evt-empty { color: var(--muted); font-size: 12px; padding: 8px 2px; }
</style>
