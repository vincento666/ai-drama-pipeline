<template>
  <div class="agent-bar">
    <div class="ab-row">
      <span class="spark">✨</span>
      <input v-model="cmd" class="ab-input" :disabled="busy || executing"
        placeholder="给 Agent 下指令，如：把第 3 镜改成夜景、远景，重新抽卡…"
        @keyup.enter="send" />
      <button class="primary" :disabled="busy || executing || !cmd.trim()" @click="send">
        {{ busy ? '拆解中…' : '发送' }}
      </button>
    </div>

    <div v-if="plan" class="ab-plan">
      <div class="ab-plan-head">
        <span>动作清单（{{ plan.actions.length }} 步）</span>
        <span class="mono cmd">{{ plan.command }}</span>
      </div>
      <ol class="ab-actions">
        <li v-for="(a, i) in plan.actions" :key="i" :class="{ done: doneFlags[i], fail: failFlags[i] }">
          {{ labelOf(a) }}
        </li>
      </ol>
      <div class="ab-ops">
        <button class="primary" :disabled="executing" @click="execute">{{ executing ? '执行中…' : '执行' }}</button>
        <button class="ghost" :disabled="executing" @click="plan = null">取消</button>
        <span class="hint" :class="{ err: execErr }">{{ execMsg }}</span>
      </div>
    </div>
    <div v-if="error" class="ab-err">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, inject } from 'vue'
import { api, postAgentCommand, refreshShotRef } from '../api'

const store = inject('store')

const cmd = ref('')
const busy = ref(false)
const plan = ref(null)          // { ok, executed, command, actions:[{task, shot}] }
const error = ref('')
const executing = ref(false)
const doneFlags = ref([])
const failFlags = ref([])
const execMsg = ref('')
const execErr = ref(false)

const TASK_LABEL = {
  storyboard_gen: '从剧本生成分镜',
  shot_ref: '生成该镜参考图',
  draw: '重抽该镜候选',
  compose: '拼接成片',
}
function labelOf(a) {
  const base = TASK_LABEL[a.task] || a.task
  return a.shot != null ? `${base}（镜${a.shot}）` : base
}

async function send() {
  const text = cmd.value.trim()
  if (!text) return
  busy.value = true; error.value = ''; plan.value = null
  try {
    const r = await postAgentCommand(text)
    if (r.ok && (r.actions || []).length) {
      plan.value = r
      doneFlags.value = []; failFlags.value = []; execMsg.value = ''; execErr.value = false
    } else {
      error.value = '未能拆解出动作——试试「生成分镜」「重抽第 N 镜」「拼接成片」这类指令'
    }
  } catch (e) { error.value = '指令拆解失败: ' + e.message }
  busy.value = false
}

// 执行 = 前端按 task 调现有端点（后端 dry-run 只拆解不执行）
async function runAction(a) {
  const p = store.project.value, ep = store.episode.value
  if (a.task === 'storyboard_gen') {
    // 异步契约：POST 返回 job → 轮询至 done；error 时 reject → execute() 中断后续动作
    const r = await api('/api/storyboard-gen', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: p, episode: ep }) })
    if (!r.job) throw new Error('后端未返回任务号')
    await pollJob(r.job)
  } else if (a.task === 'shot_ref') {
    await refreshShotRef(p, ep, a.shot)
  } else if (a.task === 'draw') {
    const r = await api('/api/render', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: p, episode: ep, only: [a.shot], shots: 2,
        width: 512, height: 288, frames: 22, steps: 2 }) })
    await pollJob(r.job)
  } else if (a.task === 'compose') {
    const r = await api('/api/compose', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: p, episode: ep }) })
    if (!r.ok) throw new Error('拼接失败：检查每镜是否已选')
  } else {
    throw new Error('未知动作: ' + a.task)
  }
}

function pollJob(job) {
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const s = await api(`/api/render/status/${job}`)
        if (s.status === 'done') { clearInterval(timer); resolve(s) }
        else if (s.status === 'error') { clearInterval(timer); reject(new Error(s.message || '生成失败')) }
      } catch (e) { /* 轮询继续 */ }
    }, 4000)
  })
}

async function execute() {
  if (!plan.value || executing.value) return
  executing.value = true; execErr.value = false
  const flags = [], fails = []
  for (let i = 0; i < plan.value.actions.length; i++) {
    const a = plan.value.actions[i]
    execMsg.value = `执行中 ${i + 1}/${plan.value.actions.length}：${labelOf(a)}`
    try {
      await runAction(a)
      flags[i] = true
    } catch (e) {
      fails[i] = true
      execMsg.value = `第 ${i + 1} 步失败：${e.message}（后续步骤已跳过）`
      execErr.value = true
      break   // 流水线形态：一步失败不再继续，避免半成品状态扩大
    }
    doneFlags.value = [...flags]; failFlags.value = [...fails]
  }
  doneFlags.value = [...flags]; failFlags.value = [...fails]
  // 刷新画布：向导/档位 + 时间轴/成片轨数据
  await store.refreshWizard()
  await store.refreshEpisode()
  store.canvasTick.value++
  if (!execErr.value) { execMsg.value = '全部完成'; cmd.value = '' }
  executing.value = false
}
</script>

<style scoped>
.agent-bar { background: var(--panel); border-bottom: 1px solid var(--line); padding: 8px 16px; }
.ab-row { display: flex; align-items: center; gap: 10px; }
.spark { font-size: 15px; }
.ab-input { flex: 1; background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 8px; padding: 8px 12px; font-size: 13px; }
.ab-input:focus { border-color: var(--accent); outline: none; }
.primary { background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 8px 16px;
  cursor: pointer; font-size: 13px; }
.primary:disabled { background: var(--line); color: var(--muted); cursor: default; }
.ghost { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); border-radius: 8px;
  padding: 8px 14px; cursor: pointer; font-size: 13px; }
.ghost:disabled { opacity: .5; cursor: default; }

.ab-plan { margin-top: 8px; background: var(--panel2); border: 1px solid var(--line); border-radius: 8px;
  padding: 10px 12px; }
.ab-plan-head { display: flex; align-items: center; gap: 10px; font-size: 12px; margin-bottom: 6px; }
.ab-plan-head .cmd { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ab-actions { margin: 0 0 8px; padding-left: 22px; font-size: 13px; line-height: 1.9; }
.ab-actions li.done { color: var(--ok); }
.ab-actions li.fail { color: var(--danger); }
.ab-ops { display: flex; align-items: center; gap: 8px; }
.ab-ops .hint { font-size: 12px; color: var(--muted); }
.ab-ops .hint.err { color: var(--danger); }
.ab-err { margin-top: 6px; color: var(--danger); font-size: 12px; }
</style>
