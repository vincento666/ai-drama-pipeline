<template>
  <div v-if="open" class="dock-mask" @click.self="emit('close')">
    <aside class="agent-dock">
      <div class="dock-head">
        <h2>✨ Agent 对话窗 <span class="sub">推进 · 委派 · 所改即所得</span></h2>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <!-- 流程推进卡（GET /api/flow-templates；按 mode 分派） -->
      <div class="flow-cards">
        <button v-for="t in templates" :key="t.key" class="fcard" :class="t.mode"
          :disabled="cardBusy" :title="t.goal || t.hint || ''" @click="runCard(t)">
          {{ t.label }}
        </button>
      </div>
      <div v-if="cardState.text" class="card-status" :class="cardState.cls">{{ cardState.text }}</div>

      <!-- 模式：内置（agent-edit→patch）/ 外部委派（agentbridge transcript） -->
      <div class="dock-tabs">
        <button class="dtab" :class="{ on: mode === 'builtin' }" @click="mode = 'builtin'">内置</button>
        <button class="dtab" :class="{ on: mode === 'external' }" @click="mode = 'external'">外部委派</button>
      </div>

      <AgentPanel v-show="mode === 'builtin'" />

      <!-- 外部委派：harness 选择 + goal + job 轮询 + transcript 尾部流式 -->
      <div v-show="mode === 'external'" class="delegate">
        <div ref="dgHist" class="dg-history">
          <p v-if="!dgLogs.length" class="hint dg-empty">选择外部 harness，输入目标后委派。外部 agent 的工作区 = 项目目录，
            可直接改 剧本/分镜/参考图提示词 或调 CLI；文件改动经 rev 轮询自动回显画布。</p>
          <div v-for="(m, i) in dgLogs" :key="i" class="msg" :class="[m.role, { err: m.err }]">{{ m.text }}</div>
          <div v-if="transcript.length" class="dg-transcript mono">
            <div class="tr-head">transcript · {{ taskId }}（{{ transcript.length }} 行）</div>
            <div v-for="(l, i) in transcript" :key="i" class="tr-line">{{ l }}</div>
          </div>
        </div>
        <div class="dg-input">
          <div class="dg-row">
            <span class="hint">harness</span>
            <select v-model="agentName" :disabled="delegating">
              <option value="kimi">kimi</option>
              <option value="codex">codex</option>
              <option value="claude">claude</option>
              <option value="dsh">dsh</option>
            </select>
            <span class="dg-status" :class="{ err: dgErr }">{{ dgStatus }}</span>
          </div>
          <textarea v-model="goal" rows="3" class="dg-goal" :disabled="delegating"
            placeholder="委派目标，如：通读 分镜.md，把夜景镜的对白收紧，改完总结改动…"></textarea>
          <button class="primary" :disabled="delegating || !goal.trim()" @click="delegate">
            {{ delegating ? '执行中…' : `委派 ${agentName}` }}
          </button>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup>
// 统一 Agent 侧边对话窗（spec 10 片 D）：
// - 流程推进卡：job 类（aiwrite/storyboard/draw/compose）提交对应端点并轮询；
//   builtin 类 onboard 跳剧本侧板、shotref 逐镜 POST /api/shot-ref；external 类 polish 把 goal 填入委派框。
// - 内置模式：复用 AgentPanel（agent-edit → 变更清单勾选 → patch 写盘）。
// - 外部委派：POST /api/agent-task → job 轮询；拿到 task_id 后每 3s 拉 transcript 尾部（流式），
//   done 后经 GET /api/agent-task/<项目>/<task_id> 拉全量显示。
// 注意：当前后端在任务完成后才把 task_id 写进 job（run_task 阻塞），故流式拉取在后端提前暴露 task_id 前
// 实际表现为完成后一次性显示；前端逻辑已按流式写好，契约一旦提前即可生效。
import { ref, inject, onMounted, nextTick } from 'vue'
import { api, enc, getFlowTemplates, postAgentTask, getAgentTask, refreshShotRef } from '../api'
import AgentPanel from './AgentPanel.vue'

defineProps({ open: Boolean })
const emit = defineEmits(['close'])
const store = inject('store')

// ---------- 流程推进卡 ----------
const templates = ref([])
const cardBusy = ref(false)
const cardState = ref({ key: '', text: '', cls: '' })

onMounted(async () => {
  try { templates.value = (await getFlowTemplates()).templates || [] } catch (e) { /* 桥不可达时静默 */ }
})

// job 轮询（3s），running 时把后端真实进度写到卡状态行
function pollJob(job, label) {
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const s = await api(`/api/render/status/${job}`)
        if (s.status === 'done') { clearInterval(timer); resolve(s) }
        else if (s.status === 'error') { clearInterval(timer); reject(new Error(s.message || '任务失败')) }
        else if (s.message) cardState.value = { key: cardState.value.key, text: `${label}：${s.message}`, cls: '' }
      } catch (e) { /* 轮询继续 */ }
    }, 3000)
  })
}

async function runCard(t) {
  if (t.key === 'onboard') { store.scriptOpen.value = true; return }
  if (t.key === 'polish') { mode.value = 'external'; goal.value = t.goal || ''; return }
  if (cardBusy.value) return
  const p = store.project.value, ep = store.episode.value
  const headers = { 'Content-Type': 'application/json' }
  cardBusy.value = true
  cardState.value = { key: t.key, text: `${t.label}：提交中…`, cls: '' }
  try {
    let doneText = ''
    if (t.key === 'shotref') {
      const n = store.shotCount.value
      if (!n) throw new Error('暂无分镜（先生成分镜）')
      for (let i = 1; i <= n; i++) {
        cardState.value = { key: t.key, text: `${t.label}：镜${i}/${n}`, cls: '' }
        await refreshShotRef(p, ep, i)
      }
    } else if (t.key === 'aiwrite') {
      const r = await api(`/api/ai-write-all/${enc(p)}`, { method: 'POST', headers, body: JSON.stringify({ novel: '', title: p }) })
      if (!r.job) throw new Error('后端未返回任务号')
      await pollJob(r.job, t.label)
    } else if (t.key === 'storyboard') {
      const r = await api('/api/storyboard-gen', { method: 'POST', headers, body: JSON.stringify({ project: p, episode: ep }) })
      if (!r.job) throw new Error('后端未返回任务号')
      const s = await pollJob(r.job, t.label)
      const m = (s.result || {}).method
      doneText = m ? `（${m === 'llm' ? 'AI 拆分' : '解析器提取'}）` : ''
    } else if (t.key === 'draw') {
      const r = await api('/api/render', { method: 'POST', headers, body: JSON.stringify({ project: p, episode: ep, shots: 2, width: 512, height: 288, frames: 22, steps: 2 }) })
      if (!r.job) throw new Error('后端未返回任务号')
      await pollJob(r.job, t.label)
    } else if (t.key === 'compose') {
      const r = await api('/api/compose', { method: 'POST', headers, body: JSON.stringify({ project: p, episode: ep }) })
      if (r.job) await pollJob(r.job, t.label)          // 兼容未来 job 化版本
      else if (r.ok === false) throw new Error('拼接失败：检查每镜是否已选')
    } else {
      throw new Error('该卡片暂未支持：' + t.key)
    }
    cardState.value = { key: t.key, text: `${t.label}：完成${doneText}`, cls: 'ok' }
    store.canvasTick.value++
    store.creativeTick.value++
    await store.refreshWizard()
    store.refreshEpisode()
  } catch (e) {
    cardState.value = { key: t.key, text: `${t.label} 失败：${e.message}`, cls: 'err' }
  } finally {
    cardBusy.value = false
  }
}

// ---------- 外部委派 ----------
const mode = ref('builtin')
const agentName = ref('kimi')
const goal = ref('')
const delegating = ref(false)
const dgStatus = ref('')
const dgErr = ref(false)
const dgLogs = ref([])         // 委派会话消息（本地数组，不持久化）
const transcript = ref([])     // 当前任务 transcript 行
const taskId = ref('')
const dgHist = ref(null)

async function dgScroll() {
  await nextTick()
  if (dgHist.value) dgHist.value.scrollTop = dgHist.value.scrollHeight
}

async function pullTranscript() {
  if (!taskId.value) return
  try {
    const t = await getAgentTask(store.project.value, taskId.value)
    transcript.value = t.transcript || []
    dgScroll()
  } catch (e) { /* 保留已有内容 */ }
}

async function delegate() {
  const g = goal.value.trim()
  if (!g || delegating.value) return
  delegating.value = true; dgErr.value = false
  transcript.value = []; taskId.value = ''
  dgLogs.value.push({ role: 'user', text: `[${agentName.value}] ${g}` })
  dgStatus.value = '提交委派中…'
  dgScroll()
  try {
    const r = await postAgentTask(store.project.value, g, agentName.value)
    if (!r.job) throw new Error('后端未返回任务号')
    const s = await new Promise((resolve, reject) => {
      const timer = setInterval(async () => {
        try {
          const st = await api(`/api/render/status/${r.job}`)
          const tid = st.task_id || (st.result && st.result.task_id)
          if (tid) { taskId.value = tid; pullTranscript() }   // 流式：每 3s 刷 transcript 尾部
          if (st.status === 'done') { clearInterval(timer); resolve(st) }
          else if (st.status === 'error') { clearInterval(timer); reject(new Error(st.message || '委派失败')) }
          else if (st.message) dgStatus.value = st.message
        } catch (e) { /* 轮询继续 */ }
      }, 3000)
    })
    const tid = s.task_id || (s.result && s.result.task_id) || taskId.value
    if (tid) { taskId.value = tid; await pullTranscript() }
    dgStatus.value = `任务 ${taskId.value || ''} 完成`
    dgLogs.value.push({ role: 'agent', text: `任务 ${taskId.value || ''} 执行完成（${agentName.value}），transcript 共 ${transcript.value.length} 行；文件改动经 rev 轮询自动回显。` })
    goal.value = ''
    store.canvasTick.value++
    store.creativeTick.value++
    await store.refreshWizard()
    store.refreshEpisode()
  } catch (e) {
    dgStatus.value = '委派失败：' + e.message; dgErr.value = true
    dgLogs.value.push({ role: 'agent', text: '委派失败：' + e.message, err: true })
  } finally {
    delegating.value = false
    dgScroll()
  }
}
</script>

<style scoped>
.dock-mask { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 40;
  display: flex; justify-content: flex-end; }
.agent-dock { width: min(420px, 92vw); background: var(--bg); border-left: 1px solid var(--line);
  display: flex; flex-direction: column; box-shadow: -8px 0 24px rgba(0,0,0,.35); }
.dock-head { display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; background: var(--panel); border-bottom: 1px solid var(--line); flex: none; }
.dock-head h2 { font-size: 15px; }
.sub { font-size: 12px; color: var(--muted); font-weight: 400; }
.close-btn { background: var(--panel2); color: var(--muted); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 13px; }
.close-btn:hover { color: var(--fg); border-color: var(--accent); }

.flow-cards { flex: none; display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 12px 6px; }
.fcard { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); border-radius: 6px;
  padding: 5px 10px; font-size: 12px; cursor: pointer; }
.fcard:hover { border-color: var(--accent); }
.fcard:disabled { opacity: .5; cursor: default; }
.fcard.job { border-left: 3px solid var(--accent); }
.fcard.builtin { border-left: 3px solid var(--ok); }
.fcard.external { border-left: 3px solid var(--warn); }
.card-status { flex: none; font-size: 12px; color: var(--muted); padding: 0 12px 6px; }
.card-status.ok { color: var(--ok); }
.card-status.err { color: var(--danger); }

.dock-tabs { flex: none; display: flex; background: var(--panel); border-bottom: 1px solid var(--line); }
.dtab { flex: 1; background: none; color: var(--muted); border: none; border-bottom: 2px solid transparent;
  padding: 7px 0; font-size: 12px; cursor: pointer; }
.dtab.on { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }

.delegate { flex: 1; min-height: 0; display: flex; flex-direction: column; background: var(--panel); }
.dg-history { flex: 1; overflow-y: auto; padding: 10px 12px; }
.dg-empty { margin-top: 8px; line-height: 1.7; }
.msg { max-width: 96%; padding: 7px 10px; border-radius: 8px; font-size: 13px; line-height: 1.6;
  margin-bottom: 8px; white-space: pre-wrap; word-break: break-word; }
.msg.user { margin-left: auto; background: rgba(84,140,255,.15); border: 1px solid var(--accent); }
.msg.agent { background: var(--panel2); border: 1px solid var(--line); }
.msg.err { border-color: var(--danger); color: var(--danger); }
.dg-transcript { background: var(--panel2); border: 1px solid var(--line); border-radius: 8px;
  padding: 8px 10px; font-size: 11px; line-height: 1.5; max-height: 320px; overflow-y: auto; }
.tr-head { color: var(--muted); margin-bottom: 4px; }
.tr-line { white-space: pre-wrap; word-break: break-word; }
.dg-input { flex: none; border-top: 1px solid var(--line); padding: 10px 12px; }
.dg-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.dg-row select { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 8px; font-size: 12px; }
.dg-status { font-size: 12px; color: var(--muted); }
.dg-status.err { color: var(--danger); }
.dg-goal { width: 100%; background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 8px; padding: 8px 10px; font-size: 13px; line-height: 1.6; margin-bottom: 8px; }
.dg-goal:focus { border-color: var(--accent); outline: none; }
.primary { background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 8px 14px;
  cursor: pointer; font-size: 13px; width: 100%; }
.primary:disabled { background: var(--line); color: var(--muted); }
.hint { color: var(--muted); font-size: 12px; }
</style>
