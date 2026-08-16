<template>
  <div class="chat-input">
    <textarea class="ci-box" rows="2" ref="box"
      :disabled="!canSend"
      :placeholder="placeholder"
      v-model="draft"
      @keydown="onKeydown"></textarea>
    <div class="ci-foot">
      <span class="hint">Ctrl+Enter 发送 · 全站唯一 AI 入口</span>
      <button class="ci-send" :disabled="!canSend" @click="send">{{ sending ? '执行中…' : '发送' }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, ref, watch } from 'vue'
import { postSessionChat, getSessionMessages } from '../api'

// 左栏唯一自然语言入口（spec 11 §3.2-3 + docs/11 §7）：P2 接真——
// 发送 → 乐观插入 user 气泡 → POST /api/sessions/<id>/chat → P3 改 SSE 驱动：
//   SSE 活着 → session.msg 事件驱动（beginStream → chunk 累积 → 空 chunk 收尾）；
//   SSE 断开 → 回退 2s 轮询 messages，直到本回合 assistant 回复出现（或超时 120s）。
const store = inject('store')
const box = ref(null)
const draft = ref('')
const sending = ref(false)
let pollTimer = null
let pollCtx = null            // { sid, taskId }
let startDeadline = 0

// P7a：无会话时输入框也可用——发送时若未选中会话则先自动新建（POST /api/sessions → 选中）
const canSend = computed(() =>
  !!store.project.value && !sending.value && !store.chatBusy.value)

const placeholder = computed(() => {
  if (!store.selectedSessionId.value) return '输入即自动新建会话…'
  if (sending.value) return '正在执行，请稍候…'
  return '在对话里输入创作指令…'
})

function onKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); send() }
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  pollCtx = null
  sending.value = false
  store.clearStream()           // 轮询兜底完成时也清流式/实时记录（P3）
  store.loadSessionTasks()      // 刷新右栏任务 + chatBusy
  store.sessionTick.value++
}

function startPolling(sid, taskId) {
  stopPolling()                 // 停旧表（含清流式，随后重开）
  pollCtx = { sid, taskId }
  startDeadline = Date.now() + 120000
  const tick = async () => {
    if (!pollCtx || pollCtx.sid !== store.selectedSessionId.value) { stopPolling(); return }
    try {
      const r = await getSessionMessages(pollCtx.sid)
      store.sessionMessages.value = r.messages || []
      const done = (r.messages || []).some(m =>
        m.role === 'assistant' && m.meta && m.meta.task_id === pollCtx.taskId)
      if (done || Date.now() > startDeadline) { stopPolling(); return }
    } catch (e) { stopPolling(); return }
  }
  tick()                        // 立即首拉（比等 2s 快）
  pollTimer = setInterval(tick, 2000)
}

// P3：SSE 断开（错误期/未连接）→ 回退轮询；回合完成（streamTaskId 清空）→ 停表
watch(() => store.sseAlive.value, (alive) => {
  if (!alive && pollCtx) startPolling(pollCtx.sid, pollCtx.taskId)
})
watch(() => store.streamTaskId.value, (tid) => {
  if (!tid && sending.value) stopPolling()
})

async function send() {
  const text = draft.value.trim()
  if (!text || !canSend.value) return
  sending.value = true
  // P7a：无选中会话 → 先自动新建并选中（createSession 内部 await selectSession，
  // 返回后 selectedSessionId/sessionMessages 已就绪，再发消息）
  let sid = store.selectedSessionId.value
  if (!sid) {
    const s = await store.createSession()
    if (!s) { sending.value = false; return }   // 无项目或新建失败（store 已 setStatus 报错）
    sid = s.id
  }
  // 乐观插入 user 气泡（随后以服务端消息整体替换）
  store.sessionMessages.value.push({ role: 'user', text, ts: Date.now() / 1000, meta: {} })
  draft.value = ''

  let taskId = null
  try {
    const r = await postSessionChat(sid, text, store.episode.value)
    taskId = r.task_id
  } catch (e) {
    store.setStatus('发送失败: ' + e.message, 'err')
    stopPolling()
    store.loadSessionMessages()
    return
  }
  store.beginStream(taskId)     // P3：进入流式（session.msg chunk 累积）
  store.loadSessionTasks()      // 让右栏立刻看到 running 任务
  if (!store.sseAlive.value) startPolling(sid, taskId)   // SSE 断开 → 轮询兜底
}
</script>

<style scoped>
.chat-input { flex: none; border-top: 1px solid var(--line); padding: 8px 10px 10px;
  background: var(--green-bg); }
.ci-box { width: 100%; background: var(--panel2); color: var(--fg);
  border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 13px;
  line-height: 1.6; resize: none; font-family: inherit; }
.ci-box:disabled { opacity: .75; cursor: not-allowed; }
.ci-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }
.ci-send { background: var(--green-deep); color: var(--green-soft); border: 1px solid rgba(52,211,153,.4);
  border-radius: 6px; padding: 5px 16px; font-size: 13px; cursor: pointer; }
.ci-send:hover:not(:disabled) { background: var(--green); color: #06281e; }
.ci-send:disabled { opacity: .5; cursor: not-allowed; }
</style>
