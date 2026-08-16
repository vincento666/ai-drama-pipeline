<template>
  <div class="chat-thread">
    <!-- 真数据消息流：user/assistant 气泡 + tool 消息内嵌 EventTrace（meta.events） -->
    <div v-if="messages.length" ref="listEl" class="ct-list">
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div v-if="m.text" class="msg-text">{{ m.text }}</div>
        <template v-if="m.role === 'tool'">
          <div class="tool-head">🧰 工具执行记录</div>
          <EventTrace v-if="m.meta && m.meta.events && m.meta.events.length"
            :items="m.meta.events" title="回合任务轨迹" />
          <p v-else class="tool-empty">（本回合无工具事件）</p>
        </template>
      </div>
      <!-- 思考中折叠块（P3.5 问题 5/7）：流式回合期间显示，默认折叠只看最新一行，
           展开看完整轨迹；liveEvents 变化时折叠态内容流式更新 -->
      <div v-if="thinkingActive" class="msg thinking-msg">
        <ThinkingTrace :items="store.liveEvents.value" />
      </div>

      <!-- 实时执行记录（P3.5 问题 2/6）：回合内唯一 live 气泡 = 普通 tool 样式，
           标题「回合任务轨迹」（与终态 tool 消息同构）；finalizeStream 后由
           messages 里的 tool 消息自然替换（liveEvents 已清空，无双份展示） -->
      <div v-if="store.liveEvents.value.length" class="msg tool live">
        <EventTrace :items="store.liveEvents.value" title="回合任务轨迹" :live="true" />
      </div>

      <!-- 流式回复（P3：session.msg chunk 累积打字机渲染；空 chunk 收尾后定格为正式消息） -->
      <div v-if="streaming" class="msg assistant stream">
        <span v-if="store.streamText.value" class="msg-text">{{ store.streamText.value }}</span>
        <span v-else class="typing-dots"><i></i><i></i><i></i></span>
      </div>

      <!-- 执行中占位（无流式文本时，如 SSE 断开回退轮询期间） -->
      <div v-if="busy && !streaming" class="msg assistant typing">
        <span class="typing-dots"><i></i><i></i><i></i></span>
      </div>
    </div>

    <!-- 空态：未选会话 / 无消息 -->
    <div v-else class="ct-body">
      <div class="ct-empty">
        <div class="ct-empty-icon">💬</div>
        <div class="ct-empty-title">{{ store.selectedSessionId.value ? '这个会话还没有消息' : '选择或新建一个会话' }}</div>
        <div class="ct-empty-sub">
          {{ store.selectedSessionId.value
            ? '在下方输入框说一句话想法，AI 将拆解任务、推进 剧本 → 美术·资产 → 分镜 → 成片。'
            : '在左侧「会话」栏选择或新建会话后，即可用自然语言驱动创作；执行结果实时反馈在右栏。' }}
        </div>
      </div>
      <div class="ct-suggest">
        <div class="ct-suggest-title">建议任务</div>
        <div class="suggest-cards">
          <div v-for="s in SUGGEST" :key="s" class="s-card">{{ s }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, ref, watch } from 'vue'
import EventTrace from './EventTrace.vue'
import ThinkingTrace from './ThinkingTrace.vue'

// 左栏对话窗消息流（spec 11 §3.2-2 + docs/11 §7）：P2 接真——
// 选中会话 → GET /api/sessions/<id>/messages 渲染；user/assistant 气泡；
// tool 消息渲染为内嵌 EventTrace（items 来自该条消息 meta.events，后端回合收尾写入）。
// P3.5：回合内只显示一个 live EventTrace（问题 6）+ 「思考中」折叠块（问题 7）。
const store = inject('store')

const messages = computed(() => store.sessionMessages.value)
const busy = computed(() => store.chatBusy.value)
const streaming = computed(() => !!store.streamTaskId.value)
// 思考中块：liveEvents 有 running 或正在流式时显示
const thinkingActive = computed(() =>
  store.liveEvents.value.length > 0 || !!store.streamTaskId.value)

// 新消息/新会话 → 自动滚到底部
const listEl = ref(null)
watch(messages, async () => {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}, { deep: true })
// P3：流式文本/实时执行记录变化 → 同样滚到底部（气泡不在 messages 内）
watch([() => store.streamText.value, () => store.liveEvents.value], async () => {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}, { deep: true })

const SUGGEST = ['✨ 生成分镜草稿', '✍️ 精修对白', '🎞 批量抽卡', '🧩 拼接成片']
</script>

<style scoped>
.chat-thread { flex: 1; min-height: 0; display: flex; flex-direction: column;
  background: var(--green-bg); }
.ct-list { flex: 1; overflow-y: auto; padding: 10px 12px; }

/* ---------- 空态 ---------- */
.ct-body { flex: 1; overflow-y: auto; padding: 14px 12px; }
.ct-empty { text-align: center; padding: 18px 8px 10px; }
.ct-empty-icon { font-size: 26px; margin-bottom: 8px; }
.ct-empty-title { font-size: 14px; font-weight: 600; color: var(--green-soft); margin-bottom: 6px; }
.ct-empty-sub { font-size: 12px; color: var(--muted); line-height: 1.8; max-width: 300px; margin: 0 auto; }

/* ---------- 建议卡（占位引导） ---------- */
.ct-suggest { margin: 14px 2px 10px; }
.ct-suggest-title { font-size: 11px; color: var(--muted); margin-bottom: 6px; letter-spacing: .5px; }
.suggest-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.s-card { background: var(--panel2); border: 1px solid var(--line); border-radius: 8px;
  padding: 8px 10px; font-size: 12px; color: var(--fg); cursor: default; }
.s-card:hover { border-color: rgba(52,211,153,.5); color: var(--green-soft); }

/* ---------- 气泡样式（user/assistant/tool） ---------- */
.msg { max-width: 94%; padding: 8px 10px; border-radius: 8px; font-size: 13px;
  line-height: 1.6; margin-bottom: 8px; white-space: pre-wrap; word-break: break-word; }
.msg.user { margin-left: auto; background: rgba(52,211,153,.12);
  border: 1px solid rgba(52,211,153,.45); }
.msg.assistant { background: var(--panel2); border: 1px solid var(--line); }
.msg.tool { background: var(--panel); border: 1px dashed var(--line);
  font-size: 12px; }
/* 思考中折叠块：无气泡壳，直接嵌在消息流里 */
.msg.thinking-msg { background: none; border: none; padding: 0 0 8px; max-width: 100%; }
.msg .msg-text { margin-bottom: 4px; }
.msg .msg-text:last-child { margin-bottom: 0; }
.msg.assistant .evt-trace { margin-top: 6px; }
.tool-head { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.tool-empty { font-size: 11px; color: var(--muted); margin: 2px 0; }

/* 执行中占位：三点呼吸 */
.msg.typing { width: fit-content; padding: 10px 14px; }
.typing-dots { display: inline-flex; gap: 4px; }
.typing-dots i { width: 6px; height: 6px; border-radius: 50%; background: var(--green);
  animation: td-bounce 1s ease-in-out infinite; }
.typing-dots i:nth-child(2) { animation-delay: .15s; }
.typing-dots i:nth-child(3) { animation-delay: .3s; }
@keyframes td-bounce { 0%, 60%, 100% { transform: translateY(0); opacity: .5; }
  30% { transform: translateY(-4px); opacity: 1; } }
</style>
