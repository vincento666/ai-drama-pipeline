<template>
  <div class="agent-panel">
    <!-- 会话历史（本地数组，不持久化；v-show 挂载，切 Tab 不丢） -->
    <div ref="histEl" class="ap-history">
      <p v-if="!msgs.length" class="hint ap-empty">用自然语言改画布内容，如「把镜3的灯光改为夜景」。
        解析出的变更先预览、勾选确认后才写盘；写盘后画布即时回显。</p>
      <div v-for="(m, i) in msgs" :key="i" class="msg" :class="[m.role, { err: m.err }]">{{ m.text }}</div>

      <!-- 变更清单预览（可勾选，应用后才写盘） -->
      <div v-if="pending.length" class="ap-changes">
        <div class="ap-ch-head">变更清单（勾选后应用）</div>
        <label v-for="(p, i) in pending" :key="i" class="ap-ch-row" :class="{ off: !p.checked }">
          <input type="checkbox" v-model="p.checked" />
          <span class="mono">{{ descOf(p.c) }}</span>
        </label>
        <div class="ap-ch-ops">
          <button class="primary" :disabled="applying || !checkedCount" @click="apply">
            {{ applying ? '应用中…' : `应用变更（${checkedCount}）` }}
          </button>
          <button class="ghost" :disabled="applying" @click="pending = []">丢弃</button>
        </div>
      </div>

      <!-- 应用结果（逐条） -->
      <div v-if="result" class="ap-result">
        <div v-for="(a, i) in result.applied" :key="'a' + i" class="ap-line ok">✓ {{ a.summary || descOfApplied(a) }}</div>
        <div v-for="(e, i) in result.errors" :key="'e' + i" class="ap-line bad">✗ {{ e.op }}：{{ e.error }}</div>
      </div>
    </div>

    <!-- 输入行 -->
    <div class="ap-input-row">
      <input v-model="input" class="ap-input" :disabled="busy"
        placeholder="把镜3的灯光改为夜景…" @keyup.enter="send" />
      <button class="primary" :disabled="busy || !input.trim()" @click="send">{{ busy ? '解析中…' : '发送' }}</button>
    </div>
  </div>
</template>

<script setup>
// Agent 会话工作台（spec 09 P2，所改即所得）：
// 发送 → POST /api/agent-edit {text} → {ok, changes:[{op, ...}]}（dry-run 解析，不写盘）
// 应用 → POST /api/patch {project, episode, changes} → {ok, applied, errors}（逐条写盘）
// 回显：canvasTick++ 触发 BoardCanvas.loadAll / ComposeTrack.load，refreshWizard 同步泳道头档位。
// 会话历史为本地数组，不持久化。
import { ref, computed, inject, nextTick } from 'vue'
import { postAgentEdit, postPatch } from '../api'

const store = inject('store')
const msgs = ref([])          // {role:'user'|'agent', text, err?}
const pending = ref([])       // 待应用变更 [{c: change, checked}]
const result = ref(null)      // 最近一次应用结果 {applied, errors}
const input = ref('')
const busy = ref(false)       // agent-edit 解析中
const applying = ref(false)   // patch 应用中
const histEl = ref(null)

const FIELD_LABEL = { shot: '镜号', frame: '景别', camera: '运镜', dur: '时长', chars: '角色', scene: '场景', light: '灯光', dialogue: '对白', note: '备注' }
const BLOCK_LABEL = { novel: '小说', events: '事件图谱', skeleton: '故事骨架', script: '剧本', assets: '资产清单', brief: '创作简报' }

const checkedCount = computed(() => pending.value.filter(p => p.checked).length)

function shotNo(n) { return String(n).padStart(2, '0') }
function descOf(c) {
  if (c.op === 'shot') return `镜${shotNo(c.shot)} ${FIELD_LABEL[c.field] || c.field} → ${c.value}`
  if (c.op === 'script') return `${BLOCK_LABEL[c.block] || c.block} 整块替换（${(c.text || '').length} 字）`
  if (c.op === 'ref') {
    const t = c.text || ''
    return `镜${shotNo(c.shot)} 参考图提示词 → ${t.slice(0, 20)}${t.length > 20 ? '…' : ''}`
  }
  return c.op || '未知操作'
}
// applied 项当前无 op/summary 字段，按形状判断（{shot,field,value} / {block,chars} / {shot,chars}）；
// 后端补上 summary 后优先用 summary（模板里 a.summary || …）
function descOfApplied(a) {
  if (a.field) return `镜${shotNo(a.shot)} ${FIELD_LABEL[a.field] || a.field} → ${a.value}`
  if (a.block) return `${BLOCK_LABEL[a.block] || a.block} 已替换（${a.chars} 字）`
  if (a.shot != null) return `镜${shotNo(a.shot)} 参考图提示词已替换（${a.chars} 字）`
  return '已应用'
}

async function scrollBottom() {
  await nextTick()
  if (histEl.value) histEl.value.scrollTop = histEl.value.scrollHeight
}

async function send() {
  const text = input.value.trim()
  if (!text || busy.value) return
  msgs.value.push({ role: 'user', text })
  input.value = ''
  busy.value = true; result.value = null
  try {
    const r = await postAgentEdit(text)
    const changes = r.changes || []
    if (!changes.length) {
      pending.value = []
      msgs.value.push({ role: 'agent', text: '未能解析出变更。试试更具体的说法，如：「把镜3的灯光改为夜景」「把镜2的对白改为……」' })
    } else {
      pending.value = changes.map(c => ({ c, checked: true }))
      msgs.value.push({ role: 'agent', text: `解析出 ${changes.length} 条变更，勾选确认后点「应用变更」写盘：` })
    }
  } catch (e) {
    msgs.value.push({ role: 'agent', text: '解析失败：' + e.message, err: true })
  } finally {
    busy.value = false
    scrollBottom()
  }
}

async function apply() {
  const changes = pending.value.filter(p => p.checked).map(p => p.c)
  if (!changes.length || applying.value) return
  applying.value = true
  try {
    const r = await postPatch(store.project.value, store.episode.value, changes)
    result.value = { applied: r.applied || [], errors: r.errors || [] }
    const okN = result.value.applied.length, errN = result.value.errors.length
    msgs.value.push({ role: 'agent', err: !okN && !!errN,
      text: errN ? `已应用 ${okN} 条，${errN} 条失败（见下方逐条结果）` : `已应用 ${okN} 条变更，画布已回显` })
    pending.value = []
    store.canvasTick.value++      // BoardCanvas.loadAll / ComposeTrack.load 监听重载
    await store.refreshWizard()   // 泳道头/总览档位同步
  } catch (e) {
    msgs.value.push({ role: 'agent', text: '应用失败：' + e.message, err: true })
  } finally {
    applying.value = false
    scrollBottom()
  }
}
</script>

<style scoped>
.agent-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; background: var(--panel); }
.ap-history { flex: 1; overflow-y: auto; padding: 10px 12px; }
.ap-empty { margin-top: 8px; line-height: 1.7; }
.msg { max-width: 94%; padding: 7px 10px; border-radius: 8px; font-size: 13px; line-height: 1.6;
  margin-bottom: 8px; white-space: pre-wrap; word-break: break-word; }
.msg.user { margin-left: auto; background: rgba(84,140,255,.15); border: 1px solid var(--accent); }
.msg.agent { background: var(--panel2); border: 1px solid var(--line); }
.msg.err { border-color: var(--danger); color: var(--danger); }
.ap-changes { background: var(--panel2); border: 1px solid var(--accent); border-radius: 8px;
  padding: 8px 10px; margin-bottom: 10px; }
.ap-ch-head { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.ap-ch-row { display: flex; gap: 8px; align-items: center; font-size: 12px; padding: 4px 0; cursor: pointer; }
.ap-ch-row input { accent-color: var(--accent); }
.ap-ch-row.off span { opacity: .45; text-decoration: line-through; }
.ap-ch-ops { display: flex; gap: 8px; margin-top: 8px; }
.ap-result { margin-bottom: 10px; font-size: 12px; }
.ap-line { padding: 2px 0; }
.ap-line.ok { color: var(--ok); }
.ap-line.bad { color: var(--danger); }
.ap-input-row { flex: none; display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--line); }
.ap-input { flex: 1; background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 8px; padding: 8px 12px; font-size: 13px; }
.ap-input:focus { border-color: var(--accent); outline: none; }
.primary { background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 8px 14px;
  cursor: pointer; font-size: 13px; }
.primary:disabled { background: var(--line); color: var(--muted); }
.ghost { background: var(--panel); color: var(--fg); border: 1px solid var(--line); border-radius: 8px;
  padding: 6px 12px; cursor: pointer; font-size: 12px; }
.ghost:disabled { opacity: .5; cursor: default; }
.hint { color: var(--muted); font-size: 12px; }
</style>
