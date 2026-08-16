<template>
  <section class="session-rail" :class="{ collapsed }">
    <!-- 头部点击折叠/展开（P3.5 问题 8）：折叠时只显示标题行 + 会话计数 + 新建按钮 -->
    <div class="sr-head" @click="toggleCollapse">
      <h3>
        会话
        <span v-if="collapsed" class="sr-count" title="会话数量">{{ store.sessions.value.length }} 个会话</span>
        <span class="sr-fold" :title="collapsed ? '展开会话列表' : '收起会话列表'">{{ collapsed ? '▸' : '▾' }}</span>
      </h3>
      <button class="sr-new" title="新建会话（绑定当前项目）" @click.stop="onNew" :disabled="!store.project.value">＋ 新建会话</button>
    </div>

    <div v-show="!collapsed" class="sr-body">
      <!-- 空态：当前项目尚无会话（P7a：输入即自动新建会话） -->
      <div v-if="!store.sessions.value.length" class="sr-empty">
        <p class="sr-empty-title">尚无会话</p>
        <p class="hint">在下方对话里直接输入即自动新建会话（或点「＋ 新建会话」）——
          会话绑定当前项目，上下文与任务队列互不干扰。</p>
      </div>

      <!-- 会话列表（真数据：GET /api/sessions?project=；状态点 running 转圈） -->
      <div v-for="s in store.sessions.value" :key="s.id"
        class="sr-item" :class="{ active: s.id === store.selectedSessionId.value, archived: s.archived }"
        @click="onSelect(s)">
        <span class="sr-dot" :class="s.running ? 'running' : 'idle'"></span>
        <span class="sr-name" :title="s.title">{{ s.title }}</span>
        <span v-if="s.archived" class="sr-flag" title="已归档（超出每项目 50 会话上限）">归档</span>
        <button class="sr-del" title="删除会话" @click.stop="onDelete(s)">✕</button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { inject, onMounted, ref, watch } from 'vue'

// 左栏会话列表（spec 11 §3.2-1 + docs/11 §7）：P2 接真——
// 挂载/切项目时 GET /api/sessions；新建 POST；选中高亮；删除 DELETE（confirm）。
// P3.5 问题 8：头部点击折叠/展开（折叠态 = 标题行+计数+新建按钮，高度收缩到一行），
// localStorage 记忆（默认展开）。
const store = inject('store')

const COLLAPSE_KEY = 'sessionRailCollapsed'
const collapsed = ref(false)
try { collapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1' } catch (e) { /* 隐私模式忽略 */ }

function toggleCollapse() {
  collapsed.value = !collapsed.value
  try { localStorage.setItem(COLLAPSE_KEY, collapsed.value ? '1' : '0') } catch (e) { /* 隐私模式忽略 */ }
}

async function refresh() {
  if (!store.selectedSessionId.value
      || !store.sessions.value.some(s => s.id === store.selectedSessionId.value)) {
    store.selectSession(null)   // 切项目后旧选中失效
  }
  await store.loadSessions()
}

function onNew() {
  store.createSession()
}

function onSelect(s) {
  store.selectSession(s.id)
}

function onDelete(s) {
  if (!window.confirm(`删除会话「${s.title}」？消息与执行记录将一并删除。`)) return
  store.removeSession(s.id)
}

// 切项目 → 会话列表跟随过滤（spec 11 §3.1：会话隔离）
watch(() => store.project.value, refresh)
onMounted(refresh)
</script>

<style scoped>
.session-rail { flex: none; border-bottom: 1px solid var(--line); background: var(--green-bg); }
.sr-head { display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; cursor: pointer; user-select: none; }
.sr-head:hover h3 { color: var(--green); }
.sr-head h3 { margin-bottom: 0; font-size: 12px; color: var(--green-soft);
  letter-spacing: 1px; display: flex; align-items: center; gap: 6px; }
.sr-count { font-size: 11px; color: var(--muted); font-weight: 400; letter-spacing: 0; }
.sr-fold { font-size: 10px; color: var(--muted); }
.sr-new { background: var(--green-deep); color: var(--green-soft); border: 1px solid rgba(52,211,153,.4);
  border-radius: 6px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
.sr-new:hover { background: var(--green); color: #06281e; }
.sr-new:disabled { opacity: .5; cursor: not-allowed; }
.sr-body { padding: 4px 12px 10px; max-height: 40vh; overflow-y: auto; }
.session-rail.collapsed .sr-body { display: none; }
.sr-empty-title { font-size: 13px; color: var(--fg); margin-bottom: 2px; }
.sr-empty .hint { line-height: 1.7; }
.sr-item { display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 6px;
  font-size: 13px; cursor: pointer; border: 1px solid transparent; }
.sr-item:hover { background: var(--panel2); }
.sr-item.active { background: var(--green-deep); border-color: rgba(52,211,153,.45); }
.sr-item.archived { opacity: .6; }
.sr-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.sr-dot.idle { background: var(--muted); }
.sr-dot.running { background: var(--green); box-shadow: 0 0 0 2px rgba(52,211,153,.25);
  animation: sr-pulse 1.2s ease-in-out infinite; }
@keyframes sr-pulse { 50% { box-shadow: 0 0 0 4px rgba(52,211,153,.12); } }
.sr-name { flex: 1; min-width: 0; color: var(--fg); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.sr-item.active .sr-name { color: var(--green-soft); }
.sr-flag { flex: none; font-size: 10px; color: var(--muted); border: 1px solid var(--line);
  border-radius: 4px; padding: 0 4px; line-height: 1.6; }
.sr-del { flex: none; visibility: hidden; background: none; border: none; color: var(--muted);
  font-size: 11px; cursor: pointer; padding: 0 2px; }
.sr-item:hover .sr-del { visibility: visible; }
.sr-del:hover { color: var(--danger); }
</style>
