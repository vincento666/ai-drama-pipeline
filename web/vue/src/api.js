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

// ACP 交互对话（spec 11，多轮同会话，工作区=项目目录）：POST {project, text} → {job, status}
export const postAgentChat = (project, text) => api('/api/agent-chat', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project, text }),
})
// 对话 job 轮询：GET /api/agent-chat/status/<job> → {status, message, lines:[流式行], reply, session_id}
export const getAgentChatStatus = (job) => api(`/api/agent-chat/status/${enc(job)}`)

// Agent 设置：GET → {ok, agent:{default,max_rounds,audit,adapters}, lhh:{available,source,...}}；
// PUT {agent} 保存到 config.local.json（覆盖 config.yaml 的 agent 段）
export const getConfigAgent = () => api('/api/config-agent')
export const putConfigAgent = (agent) => api('/api/config-agent', {
  method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent }),
})

// 创作简报回写：PUT /api/brief/<项目> {brief} → {ok, path}
export const putBrief = (p, brief) => api(`/api/brief/${enc(p)}`, {
  method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ brief }),
})

// ============ P2 会话（docs/11 §7，新增封装，不改现有） ============
// 会话列表：GET /api/sessions?project=<项目> → {sessions:[{id,title,archived,running,updated}]}
export const getSessions = (project) => api(`/api/sessions?project=${enc(project)}`)
// 新建会话：POST /api/sessions {project, title?} → {ok, session}
export const postSession = (project, title = '') => api('/api/sessions', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project, title }),
})
// 删除会话（含 events 文件）：DELETE /api/sessions/<id> → {ok, session_id}
export const deleteSession = (id) => api(`/api/sessions/${enc(id)}`, { method: 'DELETE' })
// 会话消息：GET /api/sessions/<id>/messages → {session_id, messages:[{role,text,ts,meta}]}
export const getSessionMessages = (id) => api(`/api/sessions/${enc(id)}/messages`)
// 会话任务队列：GET /api/sessions/<id>/tasks → {session_id, tasks:[{id,title,kind,status,summary,updated}]}
export const getSessionTasks = (id) => api(`/api/sessions/${enc(id)}/tasks`)
// 审计事件（倒序）：GET /api/sessions/<id>/events?limit=&offset=&kind=&status= → {session_id, events, total}
export const getSessionEvents = (id, limit = 200, offset = 0, kind = '', status = '') =>
  api(`/api/sessions/${enc(id)}/events?limit=${limit}&offset=${offset}`
    + (kind ? `&kind=${enc(kind)}` : '') + (status ? `&status=${enc(status)}` : ''))
// 发消息（manager 异步执行）：POST /api/sessions/<id>/chat {text, episode?} → {ok, session_id, task_id}
export const postSessionChat = (id, text, episode = 1) => api(`/api/sessions/${enc(id)}/chat`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ text, episode }),
})

// ============ P3 SSE 实时通道（docs/11 §9.1，新增封装，不改现有） ============
// EventSource 连接 URL：GET /api/events?project=&episode=（text/event-stream，15s 心跳，按 project 过滤）
// 事件：rev {rev,episode} / job {id,status,progress,message,meta} /
//       trace {session_id,task_id,event} / session.msg {session_id,task_id,chunk} / doc.diff {doc,summary,episode?}
export const eventsUrl = (project, episode) =>
  `/api/events?project=${enc(project)}&episode=${episode}`

// ============ P4 设置页（docs/11 §6，新增封装，不改现有） ============
// 生态清单：GET /api/eco?action=list|check&name=<id> → {ok, items:[{id,type,name,installed,path?,desc?}], output?}
// action=list 默认；action=check 需 name（生态 id），附带 {output}（ComfyUI 节点注册探测）
export const getEco = (action = 'list', name = '') =>
  api(`/api/eco?action=${enc(action)}${name ? `&name=${enc(name)}` : ''}`)
// 生态操作：POST /api/eco {action:install|check|refresh, name?} → {ok, output, error?}
export const postEco = (action, name = '') => api('/api/eco', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ action, name }),
})
// 适配器连通性测试：POST /api/config-agent/test {adapter?} → {ok, output, lhh?}
// adapter=kimi/codex/claude/dsh 跑 --version 探测；不传或 lhh → harness 整体检测
export const testAdapter = (adapter = '') => api('/api/config-agent/test', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ adapter }),
})

// ============ P6c 设置页（docs/13 §3 ②③，新增封装，不改现有） ============
// ComfyUI 工作流：GET → {ok, mode, template, available:[{name,path,mtime}], desc}
// mode = builtin（内置构造器）| template（模板 + 注入映射，render.resolve_workflow 分派）
export const getWorkflows = () => api('/api/workflows')
// 保存工作流模式：PUT /api/workflows {mode, template?} → {ok, workflow:{mode, template}}
// template 为空/缺省 → 视为 builtin；写 config.local.json 的 workflow 段
export const putWorkflows = (mode, template = '') => api('/api/workflows', {
  method: 'PUT', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ mode, template }),
})
// 通用配置段（白名单 image|workflow|h3|comfyui）：GET /api/config-section?section=X → {ok, section, value}
export const getConfigSection = (section) => api(`/api/config-section?section=${enc(section)}`)
// 保存配置段：PUT /api/config-section {section, value} → 写 config.local.json 该段覆盖（深合并）
export const putConfigSection = (section, value) => api('/api/config-section', {
  method: 'PUT', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ section, value }),
})

// ============ P5 文档版本/回滚（docs/11 §10，新增封装，不改现有） ============
// doc ∈ script|board|assets|brief|novel|compose；数据落盘 profile/versions/<项目>/<doc>/
// 版本列表（倒序）：GET /api/docs/revs?project=&doc= → {ok, revs:[{rev,ts,source,note}]}
export const getDocRevs = (project, doc) =>
  api(`/api/docs/revs?project=${enc(project)}&doc=${enc(doc)}`)
// 恢复版本：POST /api/docs/revs/restore {project, doc, rev, episode?} → {ok, doc, rev, ts, summary}
// 后端先快照当前状态再写回目标版本，并广播 rev + doc.diff（前端现有刷新链路自动回显）
export const restoreDocRev = (project, doc, rev, episode = 1) => api('/api/docs/revs/restore', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ project, doc, rev, episode }),
})
// 当前 vs 指定版本的 diff：GET /api/docs/revs/diff?project=&doc=&rev= → {ok, diff, files:[{name,added,removed}]}
export const getDocDiff = (project, doc, rev, episode = 1) =>
  api(`/api/docs/revs/diff?project=${enc(project)}&doc=${enc(doc)}&rev=${rev}&episode=${episode}`)

// ============ P6b 成片编排台（docs/12 §4 ⑥，新增封装，不改现有） ============
// 成片轨顺序：GET /api/compose-order?project=&episode= → {ok, order:[镜号…]|null}
// order=null / 缺省 = 分镜行顺序；order=[1,3,2] 为拖拽后的镜号数组（1-based）
export const getComposeOrder = (project, episode) =>
  api(`/api/compose-order?project=${enc(project)}&episode=${episode}`)
// 保存成片轨顺序：PUT /api/compose-order {project, episode, order:[镜号…]|null} → {ok}
// order=null 恢复分镜行顺序；后端 /api/compose 自动读 compose.order.json 按序拼接（P6a 契约）
export const putComposeOrder = (project, episode, order) => api('/api/compose-order', {
  method: 'PUT', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ project, episode, order }),
})

// ============ P6d Skill 管理（docs/13 §2 + .agents/skills/skill-create，新增封装，不改现有） ============
// 本地 skill 清单：GET /api/skills → {ok, skills:[{name, description, path}]}
export const getSkills = () => api('/api/skills')
// 从 GitHub 安装：POST /api/skills/install {url, only?} → {ok, name, files, frontmatter?, errors?, error?}
// 同步安装（60s 超时）：超时返回部分结果（已拉取文件数）+ 断点续传提示
export const postSkillInstall = (url, only = '') => api('/api/skills/install', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ url, only: only || undefined }),
})
// 创建 skill：POST /api/skills/create {name, description} → {ok, name, path?, error?}
// LLM 按 skill-create 规范生成 SKILL.md（约 120s）→ 写盘 + frontmatter 校验
export const postSkillCreate = (name, description) => api('/api/skills/create', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name, description }),
})

// ============ P7b 素材生成引擎（docs/13 §3 P7b，新增封装，不改现有） ============
// 引擎注册表：GET /api/engines → {ok, engines:[内置 builtin 摘要 + 已注册], kinds:[{kind,label}]}
// 已注册引擎带 changed（工作流文件 hash 是否与注册时一致）
export const getEngines = () => api('/api/engines')
// 扫描工作流：POST /api/engines/scan {path?} → {ok, items:[{path,name,hash,capability,summary}]}
// path 缺省扫 config eco.sources 各目录 *.json；给定则单文件（可传绝对路径）
export const scanEngines = (path = '') => api('/api/engines/scan', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ path }),
})
// AI 分析对接：POST /api/engines/adapt {path, kind, desc?} → {ok, engine_draft:{kind,mapping,notes,unclassified}}
// 只生成草案（不写入），供确认注册；LLM 兜底失败静默回退规则结果
export const adaptEngine = (path, kind, desc = '') => api('/api/engines/adapt', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ path, kind, desc }),
})
// 确认注册：POST /api/engines/register {name, kind, path, mapping, note?} → {ok, engine, engines}
// 写 config.local.json engines 段（校验 mapping 槽位存在、path 可读、kind 合法）
export const registerEngine = (name, kind, path, mapping, note = '') => api('/api/engines/register', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name, kind, path, mapping, note }),
})
// 删除引擎：DELETE /api/engines/<id> → {ok, removed}
export const deleteEngine = (id) => api(`/api/engines/${enc(id)}`, { method: 'DELETE' })
