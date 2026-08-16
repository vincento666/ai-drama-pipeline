export async function api(path, opts = {}) {
  const resp = await fetch(path, opts)
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status))
  return data
}

export const enc = encodeURIComponent

// 分镜参考图（Shot ref）：提示词读取/刷新；图片经 GET /refs/<name>/<ep>/<file> 静态访问
export const getShotRef = (p, ep, shot) => api(`/api/shot-ref/${enc(p)}/${ep}/${shot}`)
export const refreshShotRef = (p, ep, shot) => api(`/api/shot-ref/${enc(p)}/${ep}/${shot}`, { method: 'POST' })

// AgentBar 指令拆解（dry-run）：{command} → { ok, executed, command, actions:[{task, shot}] }
export const postAgentCommand = (command) => api('/api/agent-command', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command }),
})

// 删除资产：DELETE /api/asset/<编号> → { ok, code, removed }
export const deleteAsset = (code) => api(`/api/asset/${enc(code)}`, { method: 'DELETE' })

// AI 访谈（一站式生成第一步）：{description, answers:[{q,a}], want} → want=questions 得 {ok, questions[]}；want=brief 得 {ok, brief, path}
export const postOnboard = (p, body) => api(`/api/onboard/${enc(p)}`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

// Agent 会话工作台（spec 09）：自然语言 → 变更清单（dry-run 解析，不写盘；无法解析时 changes 为空数组）
export const postAgentEdit = (text) => api('/api/agent-edit', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
})
// 应用变更清单：{project, episode, changes} 逐条写盘 → {ok, applied, errors}
export const postPatch = (project, episode, changes) => api('/api/patch', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ project, episode, changes }),
})

// 流程推进卡（spec 10）：GET → {ok, templates:[{key,label,mode,goal?,hint?,endpoint?}]}，mode = builtin/job/external
export const getFlowTemplates = () => api('/api/flow-templates')

// 外部委派（agentbridge）：{project, goal, agent, context} → {job, status}；轮询 /api/render/status/<job>
export const postAgentTask = (project, goal, agent, context = '') => api('/api/agent-task', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ project, goal, agent, context }),
})
// 委派任务详情：GET /api/agent-task/<项目>/<task_id> → {status, transcript:[行], result}
export const getAgentTask = (project, taskId) => api(`/api/agent-task/${enc(project)}/${enc(taskId)}`)
