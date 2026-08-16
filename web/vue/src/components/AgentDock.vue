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

      <!-- 模式：内置（agent-edit→patch）/ 外部委派（agentbridge 任务 + ACP 对话）/ 设置 -->
      <div class="dock-tabs">
        <button class="dtab" :class="{ on: mode === 'builtin' }" @click="mode = 'builtin'">内置</button>
        <button class="dtab" :class="{ on: mode === 'external' }" @click="mode = 'external'">外部委派</button>
        <button class="dtab" :class="{ on: mode === 'settings' }" @click="mode = 'settings'">设置</button>
      </div>

      <AgentPanel v-show="mode === 'builtin'" />

      <!-- 外部委派：子模式 [任务]（agentbridge transcript）/ [对话]（ACP 流式多轮） -->
      <div v-show="mode === 'external'" class="delegate">
        <div class="sub-tabs">
          <button class="stab" :class="{ on: extSub === 'task' }" @click="extSub = 'task'">任务模式</button>
          <button class="stab" :class="{ on: extSub === 'chat' }" @click="extSub = 'chat'">对话模式</button>
          <span v-if="extSub === 'chat' && chatSession" class="hint ses">会话 {{ chatSession }}</span>
        </div>

        <!-- 任务模式：harness 选择 + goal + job 轮询 + transcript 尾部流式 -->
        <template v-if="extSub === 'task'">
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
        </template>

        <!-- 对话模式：POST /api/agent-chat，2s 轮询拉新 lines 追加流式气泡，done 显示 reply -->
        <template v-else>
          <div ref="chatHist" class="dg-history">
            <p v-if="!chatLogs.length" class="hint dg-empty">ACP 交互对话：多轮同会话（后端按项目保持 session），
              工作区 = 项目目录。思考/工具调用行会流式出现在这里。</p>
            <div v-for="(m, i) in chatLogs" :key="i" class="msg" :class="[m.role, { err: m.err }]">{{ m.text }}</div>
            <div v-if="chatting" class="msg stream pending">…</div>
          </div>
          <div class="dg-input">
            <div class="dg-row">
              <span class="dg-status" :class="{ err: chatErr }">{{ chatStatus }}</span>
            </div>
            <textarea v-model="chatInput" rows="3" class="dg-goal" :disabled="chatting"
              placeholder="和 Agent 对话，如：现在的分镜节奏怎么样？哪里该加特写…"
              @keyup.ctrl.enter="sendChat"></textarea>
            <button class="primary" :disabled="chatting || !chatInput.trim()" @click="sendChat">
              {{ chatting ? '对话中…' : '发送（Ctrl+Enter）' }}
            </button>
          </div>
        </template>
      </div>

      <!-- 设置：Agent 配置（PUT /api/config-agent → config.local.json 覆盖）+ LHH 状态 -->
      <div v-show="mode === 'settings'" class="settings-pane">
        <div v-if="!cfgForm" class="hint set-loading">{{ cfgMsg || '读取中…' }}</div>
        <template v-else>
          <section class="set-sec">
            <h4>Agent 编排（config.yaml 的 agent 段）</h4>
            <div class="set-row">
              <span>默认适配器</span>
              <select v-model="cfgForm.default">
                <option v-for="k in adapterKeys" :key="k" :value="k">{{ k }}</option>
              </select>
            </div>
            <div class="set-row">
              <span>最大委派轮数</span>
              <input v-model="cfgForm.max_rounds" type="number" min="1" class="num" />
            </div>
            <div class="set-row">
              <span>Auditor 校验</span>
              <label class="chk"><input type="checkbox" v-model="cfgForm.auditEnabled" /> 启用</label>
            </div>
          </section>

          <section class="set-sec" v-for="k in adapterKeys" :key="k">
            <h4>适配器 · {{ k }}</h4>
            <div class="set-row"><span>cmd</span><input v-model="cfgForm.adapters[k].cmd" class="mono" /></div>
            <div class="set-row"><span>args</span><input v-model="cfgForm.adapters[k].args" class="mono" placeholder="空格分隔，如 -m kimi-code/k3-256k" /></div>
            <div class="set-row"><span>timeout(s)</span><input v-model="cfgForm.adapters[k].timeout" type="number" min="0" class="num" /></div>
            <div class="set-row"><span>skills_dir</span><input v-model="cfgForm.adapters[k].skills_dir" class="mono" placeholder="留空则不传 --skills-dir" /></div>
          </section>

          <div class="set-ops">
            <button class="primary" :disabled="cfgSaving" @click="saveCfg">{{ cfgSaving ? '保存中…' : '保存设置' }}</button>
            <button class="ghost" :disabled="cfgSaving" @click="loadCfg">重新读取</button>
            <span class="dg-status" :class="{ err: cfgErr }">{{ cfgMsg }}</span>
          </div>

          <section v-if="lhh" class="set-sec lhh">
            <h4>LHH（LongHorizon-Harness）状态</h4>
            <div class="set-row"><span>可用</span><b :class="lhh.available ? 'ok-t' : 'bad-t'">{{ lhh.available ? '✓' : '✗' }}</b></div>
            <div v-if="lhh.error" class="set-row"><span>错误</span><span class="mono dim">{{ lhh.error }}</span></div>
            <div class="set-row"><span>来源</span><span class="mono dim">{{ lhh.source }}</span></div>
            <div class="set-row"><span>版本</span><span class="mono dim">{{ lhh.version }}</span></div>
            <div class="set-row"><span>dsh_cli</span><b :class="lhh.dsh_cli ? 'ok-t' : 'bad-t'">{{ lhh.dsh_cli ? '✓' : '✗' }}</b></div>
            <div class="set-row"><span>win_loop</span><span class="dim">{{ lhh.win_loop }}</span></div>
            <div class="set-row"><span>sync</span><span class="mono dim">{{ lhh.sync }}</span></div>
            <div v-if="(lhh.reused || []).length" class="set-row"><span>复用</span><span class="dim">{{ lhh.reused.join('、') }}</span></div>
          </section>
        </template>
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
import { ref, computed, watch, inject, onMounted, nextTick } from 'vue'
import { api, enc, getFlowTemplates, postAgentTask, getAgentTask, refreshShotRef,
         postAgentChat, getAgentChatStatus, getConfigAgent, putConfigAgent } from '../api'
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

// ---------- ACP 对话模式（spec 11）：多轮同会话，lines 流式追加为气泡 ----------
const extSub = ref('task')       // 外部 Tab 子模式：task 任务 / chat 对话
const chatLogs = ref([])         // {role:'user'|'agent'|'stream', text, err?}（本地数组，不持久化）
const chatInput = ref('')
const chatting = ref(false)
const chatSession = ref('')
const chatStatus = ref('')
const chatErr = ref(false)
const chatHist = ref(null)

async function chatScroll() {
  await nextTick()
  if (chatHist.value) chatHist.value.scrollTop = chatHist.value.scrollHeight
}

async function sendChat() {
  const text = chatInput.value.trim()
  if (!text || chatting.value) return
  chatLogs.value.push({ role: 'user', text })
  chatInput.value = ''
  chatting.value = true; chatErr.value = false
  chatStatus.value = '对话中…'
  chatScroll()
  let streamIdx = -1             // 当前轮流式气泡在 chatLogs 里的下标（经数组代理改 text 保持响应式）
  try {
    const r = await postAgentChat(store.project.value, text)
    if (!r.job) throw new Error('后端未返回任务号')
    let cursor = 0
    const s = await new Promise((resolve, reject) => {
      const timer = setInterval(async () => {
        try {
          const st = await getAgentChatStatus(r.job)
          const lines = st.lines || []
          if (lines.length > cursor) {           // 追加新行到流式气泡（思考/工具调用可见）
            const fresh = lines.slice(cursor).join('\n')
            cursor = lines.length
            if (streamIdx < 0) { chatLogs.value.push({ role: 'stream', text: fresh }); streamIdx = chatLogs.value.length - 1 }
            else chatLogs.value[streamIdx].text += '\n' + fresh
            chatScroll()
          }
          if (st.session_id) chatSession.value = st.session_id
          if (st.status === 'done') { clearInterval(timer); resolve(st) }
          else if (st.status === 'error') { clearInterval(timer); reject(new Error(st.message || '对话失败')) }
          else if (st.message) chatStatus.value = st.message
        } catch (e) { /* 轮询继续 */ }
      }, 2000)
    })
    if (s.reply) chatLogs.value.push({ role: 'agent', text: s.reply })
    chatStatus.value = ''
    // 对话可能改了文件：rev watcher 5s 内兜底，这里主动刷新一次
    store.canvasTick.value++
    store.creativeTick.value++
    store.refreshWizard()
    store.refreshEpisode()
  } catch (e) {
    chatLogs.value.push({ role: 'agent', text: '对话失败：' + e.message, err: true })
    chatStatus.value = '对话失败'; chatErr.value = true
  } finally {
    chatting.value = false
    chatScroll()
  }
}

// ---------- Agent 设置（GET/PUT /api/config-agent） ----------
const cfgForm = ref(null)        // { default, max_rounds, auditEnabled, adapters:{k:{cmd,args(str),timeout,skills_dir}} }
const cfgRaw = ref(null)         // 原始 agent 对象（保存时保留未编辑键）
const lhh = ref(null)
const cfgMsg = ref('')
const cfgErr = ref(false)
const cfgSaving = ref(false)
const adapterKeys = computed(() => Object.keys((cfgForm.value || {}).adapters || {}))

async function loadCfg() {
  cfgMsg.value = ''; cfgErr.value = false
  try {
    const r = await getConfigAgent()
    lhh.value = r.lhh || null
    const a = r.agent || {}
    cfgRaw.value = a
    const adapters = {}
    for (const [k, v] of Object.entries(a.adapters || {})) {
      adapters[k] = { cmd: v.cmd || '', args: (v.args || []).join(' '),
                      timeout: v.timeout ?? '', skills_dir: v.skills_dir || '' }
    }
    cfgForm.value = { default: a.default || 'kimi', max_rounds: a.max_rounds ?? 8,
                      auditEnabled: !!(a.audit && a.audit.enabled), adapters }
  } catch (e) { cfgMsg.value = '读取失败：' + e.message; cfgErr.value = true }
}

async function saveCfg() {
  if (!cfgForm.value || cfgSaving.value) return
  cfgSaving.value = true; cfgMsg.value = ''; cfgErr.value = false
  try {
    const adapters = {}
    for (const [k, v] of Object.entries(cfgForm.value.adapters)) {
      const to = Number(v.timeout)
      adapters[k] = {
        cmd: v.cmd.trim(),
        args: (v.args || '').split(/\s+/).filter(Boolean),
        ...(to > 0 ? { timeout: to } : {}),        // 非法/留空则不写，由 config.yaml 原值兜底
        ...(v.skills_dir.trim() ? { skills_dir: v.skills_dir.trim() } : {}),
      }
    }
    const raw = cfgRaw.value || {}
    const agent = { ...raw, default: cfgForm.value.default,
                    max_rounds: Number(cfgForm.value.max_rounds) || 8,
                    audit: { ...(raw.audit || {}), enabled: cfgForm.value.auditEnabled },
                    adapters }
    await putConfigAgent(agent)
    cfgMsg.value = '已保存到 config.local.json（覆盖 config.yaml 的 agent 段）；对后续新建任务/会话生效'
  } catch (e) { cfgMsg.value = '保存失败：' + e.message; cfgErr.value = true }
  finally { cfgSaving.value = false }
}

// 设置 Tab 首次打开时懒加载
watch(mode, (m) => { if (m === 'settings' && !cfgForm.value) loadCfg() })
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

/* 外部 Tab 子模式切换（任务/对话） */
.sub-tabs { flex: none; display: flex; align-items: center; gap: 6px; padding: 8px 12px 0; }
.stab { background: var(--panel2); color: var(--muted); border: 1px solid var(--line); border-radius: 6px;
  padding: 3px 12px; font-size: 12px; cursor: pointer; }
.stab.on { color: var(--accent); border-color: var(--accent); }
.sub-tabs .ses { margin-left: auto; }

/* 对话模式流式气泡（思考/工具调用行） */
.msg.stream { background: none; border: 1px dashed var(--line); color: var(--muted);
  font-family: var(--mono); font-size: 11px; line-height: 1.5; }
.msg.stream.pending { text-align: center; border: none; }

/* 设置面板 */
.settings-pane { flex: 1; min-height: 0; overflow-y: auto; background: var(--panel); padding: 12px; }
.set-loading { padding: 4px; }
.set-sec { margin-bottom: 14px; background: var(--panel2); border: 1px solid var(--line);
  border-radius: 8px; padding: 10px 12px; }
.set-sec h4 { font-size: 12px; color: var(--accent); margin-bottom: 8px; }
.set-row { display: flex; align-items: center; gap: 10px; padding: 4px 0; font-size: 12px; }
.set-row > span:first-child { width: 76px; flex: none; color: var(--muted); }
.set-row input:not([type=checkbox]), .set-row select { flex: 1; background: var(--panel); color: var(--fg);
  border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font-size: 12px; }
.set-row input.num { flex: 0 0 90px; }
.set-row input:focus, .set-row select:focus { border-color: var(--accent); outline: none; }
.set-row .chk { display: flex; align-items: center; gap: 6px; }
.set-row .chk input { accent-color: var(--accent); }
.set-row .dim { color: var(--muted); word-break: break-all; }
.set-row .ok-t { color: var(--ok); }
.set-row .bad-t { color: var(--danger); }
.set-ops { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; }
.set-ops .primary { width: auto; }
.set-ops .ghost { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 8px; padding: 7px 12px; cursor: pointer; font-size: 12px; }
.lhh .set-row > span:first-child { width: 56px; }
</style>
