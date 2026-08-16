<template>
  <div v-if="open" class="drawer-mask" @click.self="emit('close')">
    <aside class="drawer">
      <div class="drawer-head">
        <h2>任务队列 <span class="sub">全局 render job，打开时每 3 秒刷新</span></h2>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <table class="jobs">
        <thead>
          <tr><th>任务</th><th>项目</th><th>集</th><th>镜号</th><th>候选</th><th>模式</th><th>状态</th><th>耗时</th><th>消息</th></tr>
        </thead>
        <tbody>
          <tr v-if="!jobs.length"><td colspan="9" class="empty">暂无任务</td></tr>
          <tr v-for="j in jobs" :key="j.id">
            <td class="mono">{{ j.id }}</td>
            <td>{{ j.meta && j.meta.project || '-' }}</td>
            <td>{{ j.meta && j.meta.episode != null ? 'E' + String(j.meta.episode).padStart(2,'0') : '-' }}</td>
            <td>{{ j.meta && j.meta.only ? j.meta.only.join(',') : '全部' }}</td>
            <td>{{ j.meta && j.meta.shots || '-' }}</td>
            <td>{{ modeLabel(j.meta) }}</td>
            <td><span class="badge" :class="j.status">{{ statusLabel(j.status) }}</span></td>
            <td>{{ j.elapsed != null ? j.elapsed + 's' : '-' }}</td>
            <td class="msg">{{ j.message }}</td>
          </tr>
        </tbody>
      </table>
    </aside>
  </div>
</template>

<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { api } from '../api'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])

const jobs = ref([])
let timer = null

const MODES = { t2va: '文生', i2va: '图生', ref: '参考图', aiwrite: 'AI 编剧' }
function modeLabel(meta) {
  if (!meta) return '-'
  if (meta.type === 'aiwrite') return 'AI 编剧'
  return MODES[meta.mode] || meta.mode || '-'
}
const STATUS = { running: '运行中', done: '完成', error: '失败' }
function statusLabel(s) { return STATUS[s] || s }

async function refresh() {
  try {
    const r = await api('/api/jobs')
    jobs.value = r.jobs || []
  } catch (e) { /* 桥不可达时静默 */ }
}

// 仅在抽屉打开期间轮询（等价于原 JobPanel 仅在该视图挂载时轮询）
watch(() => props.open, (v) => {
  if (v) {
    refresh()
    timer = setInterval(refresh, 3000)
  } else if (timer) {
    clearInterval(timer)
    timer = null
  }
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.drawer-mask { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 40;
  display: flex; justify-content: flex-end; }
.drawer { width: min(760px, 62vw); background: var(--panel); border-left: 1px solid var(--line);
  padding: 14px; overflow-y: auto; box-shadow: -8px 0 24px rgba(0,0,0,.35); }
.drawer-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.drawer-head h2 { font-size: 15px; }
.sub { font-size: 12px; color: var(--muted); font-weight: 400; }
.close-btn { background: var(--panel2); color: var(--muted); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 13px; }
.close-btn:hover { color: var(--fg); border-color: var(--accent); }
table.jobs { width: 100%; border-collapse: collapse; font-size: 13px; }
table.jobs th, table.jobs td { border: 1px solid var(--line); padding: 5px 8px; text-align: left; }
table.jobs th { background: var(--panel2); color: var(--muted); }
.empty { text-align: center; color: var(--muted); padding: 20px; }
.badge { display: inline-block; padding: 1px 10px; border-radius: 10px; font-size: 12px; }
.badge.running { background: rgba(255,180,84,.18); color: var(--warn); }
.badge.done { background: rgba(89,201,125,.18); color: var(--ok); }
.badge.error { background: rgba(255,107,107,.18); color: var(--danger); }
.msg { color: var(--muted); font-size: 12px; }
.mono { font-family: var(--mono); font-size: 12px; }
</style>
