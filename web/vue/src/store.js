// 全局 store：App 创建并 provide，各面板 inject 使用。
// 键名与原 App.vue 内嵌 store 保持一致（project/episode/wizard/view/dirty/…），子组件零改动。
import { ref, computed, watch } from 'vue'
import { api, enc, getSessions, postSession, deleteSession,
         getSessionMessages, getSessionTasks, eventsUrl } from './api'

export const STAGES = [
  { key: 'script', label: '剧本' },
  { key: 'art', label: '美术设定' },
  { key: 'board', label: '分镜' },
  { key: 'compose', label: '成片' },
]

// 中栏视图（P1 三栏壳）：右栏 StageNav 锚点 ↔ 中栏一次显示一个视图
export const VIEWS = [
  { key: 'script', label: '剧本' },
  { key: 'art', label: '美术·资产' },
  { key: 'board', label: '分镜' },
  { key: 'compose', label: '成片' },
]

// 三档状态 → 状态点 class（StageNav / 右栏窄条共用）：done=完成(绿) draft=进行中(蓝) none=未开始(灰)
export const dotClassOf = (state) => (state === 'done' ? 'done' : state === 'draft' ? 'active' : 'none')

export function createStore() {
  const projects = ref([])
  const project = ref('')
  const episode = ref(1)
  const episodes = ref([])
  const wizard = ref({ steps: [] })
  const jobsOpen = ref(false)
  const scriptOpen = ref(false)      // 剧本侧板（左抽屉）开关
  const agentOpen = ref(false)       // Agent 对话窗（右侧滑出，spec 10）开关
  const canvasTick = ref(0)          // 画布数据刷新信号（AgentBar 执行后 ++，BoardCanvas/ComposeTrack 监听重载）
  const creativeTick = ref(0)        // 剧本四块/简报刷新信号（rev watcher 置位，ScriptPanel 监听 loadCreative）
  const candCounts = ref({})         // 镜号 → 候选数（BoardCanvas 写，节拍卡状态点/PlanFlow 抽卡行共用）
  // v2 画布状态（view 已退役：单画布不再切视图）
  const selection = ref(null)        // 当前选中对象 { type:'shot'|'asset'|'script', id } | null
  const laneOpen = ref({ script: false, art: false })   // 剧本/美术泳道默认折叠（一行摘要）
  const activeLane = ref('assets')   // 滚动侦测到的当前分区（锚点高亮）
  const timelineMode = ref('timeline')   // ③分镜视图：timeline（默认）| grid
  const assetsWithImg = ref([])      // 有图资产（BoardCanvas 挂载时填充，Inspector 复用）
  // 分镜数据共享（BoardCanvas 写入；Inspector 的 ShotFields 编辑同一引用，保存链路不变）
  const boardRows = ref([])
  const vocab = ref({ frames: [], cameras: [] })
  const lastRedrawn = ref(null)      // 最近完成卡级重抽的镜号（ShotInspector 据此联动刷新候选墙）
  const status = ref('加载中…')
  const statusCls = ref('')
  const dirty = ref(false)
  const assets = {}                // BoardCanvas/ArtPanel 挂载时填充：{ C01: {...} }
  const tasteDefaults = {}         // BoardCanvas 挂载时填充：{ frame, camera, dur }
  // 步骤三档状态推导所需数据
  const epStatus = ref({ selected: [], composed: false })
  const shotCount = ref(0)
  let rowsCache = null             // saveBoard 兜底实现用的分镜缓存
  // ---- P1 三栏壳状态（只增不改：新增壳状态，不动现有逻辑） ----
  const view = ref('script')        // 中栏当前视图 key：script | art | board | compose
  // ---- P4 设置页（docs/11 §6，只增）：顶栏 ⚙ 打开 SettingsDialog ----
  const settingsOpen = ref(false)   // 设置对话框开关（TopBar 齿轮置 true，Dialog 内关闭置 false）
  function clampW(v, lo, hi) { return Math.min(hi, Math.max(lo, Math.round(v))) }
  function loadW(key, def, lo, hi) {
    try { const n = Number(localStorage.getItem(key)); return Number.isFinite(n) && n > 0 ? clampW(n, lo, hi) : def } catch (e) { return def }
  }
  const leftW = ref(loadW('leftW', 360, 280, 640))        // 左栏 AI 宽度（280–640）
  const rightW = ref(loadW('rightW', 300, 240, 480))      // 右栏状态栏宽度（240–480）
  const rightCollapsed = ref(0)     // 右栏折叠态：0=展开 | 1=24px 窄条 | 2=完全隐藏
  watch(leftW, (v) => { leftW.value = clampW(v, 280, 640); try { localStorage.setItem('leftW', String(leftW.value)) } catch (e) { /* 隐私模式忽略 */ } })
  watch(rightW, (v) => { rightW.value = clampW(v, 240, 480); try { localStorage.setItem('rightW', String(rightW.value)) } catch (e) { /* 隐私模式忽略 */ } })

  function setStatus(msg, cls) { status.value = msg; statusCls.value = cls || '' }

  // 资产列表重载（删除资产后调用；BoardCanvas/ArtPanel 挂载时也会各自填充）
  async function reloadAssets() {
    try {
      const a = await api('/api/assets')
      const map = Object.fromEntries((a.assets || []).map(x => [x.code, x]))
      for (const k of Object.keys(assets)) delete assets[k]
      Object.assign(assets, map)
      assetsWithImg.value = (a.assets || []).filter(x => x.image)
    } catch (e) { /* 桥不可达时静默 */ }
  }

  async function refreshWizard() {
    if (!project.value) return
    try {
      wizard.value = await api(`/api/wizard/${enc(project.value)}`)
    } catch (e) { /* 桥不可达时静默 */ }
  }

  // 拉取分镜行数 + 选中/成片状态（供泳道头状态丸/摘要推导；同时维护 rowsCache/dirty）
  async function refreshEpisode() {
    if (!project.value) return
    try {
      const [sb, st] = await Promise.all([
        api(`/api/project/${enc(project.value)}/episode/${episode.value}/storyboard`),
        api(`/api/episode-status/${enc(project.value)}/${episode.value}`),
      ])
      rowsCache = sb.rows || []
      shotCount.value = rowsCache.length
      epStatus.value = st
    } catch (e) {
      rowsCache = []
      shotCount.value = 0
      epStatus.value = { selected: [], composed: false }
    }
    dirty.value = false
  }

  async function onProjectChange() {
    const p = await api(`/api/project/${enc(project.value)}`)
    episodes.value = p.episodes || []
    if (episodes.value.length) episode.value = episodes.value[0]
    await Promise.all([refreshEpisode(), refreshWizard()])
  }

  async function onEpisodeChange() {
    await Promise.all([refreshEpisode(), refreshWizard()])
  }

  // 兜底实现；BoardCanvas 挂载后覆盖为其本地实现 saveNow
  async function saveBoard() {
    try {
      const rows = (rowsCache || []).map((r, i) => ({ ...r, shot: String(i + 1) }))
      await api(`/api/project/${enc(project.value)}/episode/${episode.value}/storyboard`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rows, header: [] }),
      })
      dirty.value = false
      setStatus('已保存', 'ok')
    } catch (e) { setStatus('保存失败: ' + e.message, 'err') }
  }

  // 已选镜号集合（从 selected 文件名 shot_XX.mp4 解析，逐镜覆盖判定用）
  const pickedShots = computed(() => {
    const s = new Set()
    for (const f of epStatus.value.selected || []) {
      const m = /shot_(\d+)\.mp4$/.exec(f || '')
      if (m) s.add(Number(m[1]))
    }
    return s
  })
  // 1..shotCount 范围内已被覆盖的镜数
  const coveredCount = computed(() => {
    let n = 0
    for (let i = 1; i <= shotCount.value; i++) if (pickedShots.value.has(i)) n++
    return n
  })

  // 步骤三档状态推导（wizard 无 state 字段，前端按契约推导）：
  // 剧本 done/none；美术 done/draft(有资产)/none；分镜 none(无行)/draft/done；成片 done/none
  const stageStates = computed(() => {
    const byKey = Object.fromEntries((wizard.value.steps || []).map(s => [s.key, s]))
    const assetCount = (byKey.assets && byKey.assets.count) || 0
    const boardDone = shotCount.value > 0 && coveredCount.value >= shotCount.value
    return {
      script: (byKey.script && byKey.script.done) ? 'done' : 'none',
      art: (byKey.assets && byKey.assets.done) ? 'done' : (assetCount > 0 ? 'draft' : 'none'),
      board: shotCount.value === 0 ? 'none' : (boardDone ? 'done' : 'draft'),
      compose: epStatus.value.composed ? 'done' : 'none',
    }
  })

  // 泳道头摘要行（LaneShell / Inspector 总览态共用）
  const laneSummaries = computed(() => {
    const byKey = Object.fromEntries((wizard.value.steps || []).map(s => [s.key, s]))
    const assetCount = (byKey.assets && byKey.assets.count) || 0
    return {
      script: (byKey.script && byKey.script.done) ? '已有 剧本.md' : '尚无剧本',
      art: assetCount ? `${assetCount} 项资产` : '暂无资产',
      board: shotCount.value ? `${shotCount.value} 镜 · 已选 ${coveredCount.value}/${shotCount.value}` : '暂无分镜',
      compose: epStatus.value.composed ? '成片已拼接' : (shotCount.value ? `已选 ${coveredCount.value}/${shotCount.value}` : '—'),
    }
  })

  async function init() {
    try {
      const proj = await api('/api/projects')
      projects.value = proj.projects || []
      if (projects.value.length) {
        project.value = projects.value[0]
        await onProjectChange()
        setStatus('就绪', 'ok')
      } else {
        setStatus('暂无项目', 'err')
      }
    } catch (e) { setStatus('加载失败: ' + e.message, 'err') }
  }

  // ============ P2 会话状态（只增：左栏会话列表 + 对话窗 + 右栏任务共享） ============
  const sessions = ref([])           // 当前项目会话列表 [{id,title,archived,running,updated}]
  const selectedSessionId = ref(null)
  const sessionMessages = ref([])    // 当前会话消息（ChatThread 渲染，ChatInput 轮询刷新）
  const sessionTasks = ref([])       // 当前会话任务（StatusPanel 渲染）
  const chatBusy = ref(false)        // 当前会话是否有运行中任务（发送禁用 / 状态点转圈）
  const sessionTick = ref(0)         // 会话数据版本号（切会话/回合完成时 ++，供组件联动）

  async function loadSessions() {
    if (!project.value) { sessions.value = []; return }
    try {
      const r = await getSessions(project.value)
      sessions.value = r.sessions || []
    } catch (e) { sessions.value = [] }
  }

  async function createSession(title = '') {
    if (!project.value) return null
    try {
      const r = await postSession(project.value, title)
      await loadSessions()
      await selectSession(r.session.id)
      return r.session
    } catch (e) { setStatus('新建会话失败: ' + e.message, 'err'); return null }
  }

  async function removeSession(id) {
    try {
      await deleteSession(id)
      if (selectedSessionId.value === id) {
        selectedSessionId.value = null
        sessionMessages.value = []
        sessionTasks.value = []
        chatBusy.value = false
      }
      await loadSessions()
      setStatus('会话已删除', 'ok')
    } catch (e) { setStatus('删除会话失败: ' + e.message, 'err') }
  }

  async function selectSession(id) {
    if (id !== selectedSessionId.value) clearStream()   // 切会话 → 清流式/实时记录（P3）
    selectedSessionId.value = id || null
    sessionTick.value++
    if (!id) { sessionMessages.value = []; sessionTasks.value = []; chatBusy.value = false; return }
    await Promise.all([loadSessionMessages(), loadSessionTasks()])
  }

  async function loadSessionMessages() {
    if (!selectedSessionId.value) { sessionMessages.value = []; return }
    try {
      const r = await getSessionMessages(selectedSessionId.value)
      sessionMessages.value = r.messages || []
    } catch (e) { /* 会话不存在时静默 */ }
  }

  async function loadSessionTasks() {
    if (!selectedSessionId.value) { sessionTasks.value = []; return }
    try {
      const r = await getSessionTasks(selectedSessionId.value)
      sessionTasks.value = r.tasks || []
      chatBusy.value = sessionTasks.value.some(t => t.status === 'running')
    } catch (e) { /* 会话不存在时静默 */ }
  }

  // ============ P3 SSE 实时通道（docs/11 §9.1，只增不改） ============
  // 事件分发：rev → 画布刷新链路（与 5s 轮询同函数）；job → 右栏任务实时；
  // trace → 当前会话 EventTrace 实时；session.msg → ChatThread 流式打字机；
  // doc.diff → 顶部 toast「AI 已更新 …」+ 对应视图刷新。断线由 EventSource 自动重连。
  const sseAlive = ref(false)           // SSE 连接存活（活着时 5s rev 轮询降级为兜底）
  const sseToast = ref(null)            // 顶部 toast：{ text, ts, doc }（doc.diff 触发，P5 加 doc 供撤销）
  const lastDocDiff = ref(null)         // P5 最近一次 doc.diff：{doc,label,summary,ts}（视图撤销条/版本历史数据源）
  const sseJobs = ref([])               // SSE job 事件快照（StatusPanel 合并展示）
  const liveEvents = ref([])            // 当前会话实时执行记录（EventTrace 数据源）
  const streamTaskId = ref(null)        // 正在流式输出的回合 task_id（null = 无）
  const streamText = ref('')            // session.msg chunk 累积文本（打字机渲染）
  let _es = null
  let _lastRev = null                   // SSE rev 基线（与 App.vue 轮询 lastRev 各自独立）

  function sseKey(ev) { return `${ev.kind}|${ev.title}` }

  // rev → 复用现有 canvasTick/creativeTick 刷新链路（与 pollRev 同函数，收到事件即刷）
  function applyRev(rev, episode) {
    if (episode != null && Number(episode) !== Number(episode.value)) return
    if (_lastRev == null) { _lastRev = rev; return }
    if (rev && rev !== _lastRev) {
      _lastRev = rev
      canvasTick.value++
      creativeTick.value++
      refreshWizard()
      refreshEpisode()
      reloadAssets()
    }
  }

  // doc.diff → toast + 对应视图刷新（分镜/成片 → 画布；剧本/资产等 → 创意区）
  // P5（只增）：兼容英文 doc key（board/compose → 画布；script/novel/brief/assets → 创意区，
  // 与 agent_manager 广播的中文标签并存），并记录 lastDocDiff 供视图撤销条/版本历史使用。
  function applyDocDiff({ doc, label, summary, episode }) {
    const d = doc || ''
    const boardish = d === '分镜' || d === '成片' || d === 'board' || d === 'compose'
    if (episode == null || Number(episode) === Number(episode.value)) {
      if (boardish) canvasTick.value++
      else creativeTick.value++
      refreshWizard()
      refreshEpisode()
    }
    sseToast.value = { text: `AI 已更新 ${label || d}：${summary || ''}`, doc: d, ts: Date.now() }
    lastDocDiff.value = { doc: d, label: label || d, summary: summary || '', ts: Date.now() }
  }

  // job → StatusPanel 任务列表实时更新（进度条/状态点，upsert 快照）
  function applyJob(job) {
    if (!job || !job.id) return
    const i = sseJobs.value.findIndex(j => j.id === job.id)
    if (i >= 0) sseJobs.value[i] = job
    else sseJobs.value.unshift(job)
  }

  // trace → 当前会话 EventTrace 实时追加/更新（running→转圈，success→✓ 同键替换）
  function applyTrace({ session_id, task_id, event }) {
    if (!event || session_id !== selectedSessionId.value) return
    if (streamTaskId.value && task_id && task_id !== streamTaskId.value) return
    const key = sseKey(event)
    const i = liveEvents.value.findIndex(e => sseKey(e) === key)
    if (i >= 0) liveEvents.value[i] = { ...liveEvents.value[i], ...event }
    else liveEvents.value.push({ ...event, id: event.ts + '-' + event.kind + '-' + event.title })
  }

  function clearStream() {
    streamTaskId.value = null
    streamText.value = ''
    liveEvents.value = []
  }

  // session.msg 收尾（空 chunk）：定格 → 以服务端正式消息为准刷新
  function finalizeStream() {
    clearStream()
    loadSessionMessages()
    loadSessionTasks()
    sessionTick.value++
  }

  // 发送后置为流式（ChatInput 调用；随后 session.msg chunk 累积）
  function beginStream(taskId) {
    streamTaskId.value = taskId || null
    streamText.value = ''
    liveEvents.value = []
  }

  function onSseEvent(name, data) {
    sseAlive.value = true
    if (name === 'rev') applyRev(data && data.rev, data && data.episode)
    else if (name === 'job') applyJob(data)
    else if (name === 'trace') applyTrace(data || {})
    else if (name === 'session.msg') {
      if (!data || data.session_id !== selectedSessionId.value) return
      if (streamTaskId.value && data.task_id && data.task_id !== streamTaskId.value) return
      if (data.chunk === '') finalizeStream()
      else if (data.chunk) streamText.value += data.chunk
    } else if (name === 'doc.diff') applyDocDiff(data || {})
  }

  // 连接 /api/events?project=&episode=（切项目/集时由 App.vue watch 触发断开重连）
  function connectSSE() {
    disconnectSSE()
    if (!project.value) return
    const p = project.value
    _lastRev = null
    try {
      _es = new EventSource(eventsUrl(p, episode.value))
    } catch (e) { sseAlive.value = false; return }
    _es.onopen = () => { sseAlive.value = true }
    _es.onerror = () => { sseAlive.value = false }      // EventSource 自动重连，错误期轮询兜底
    for (const n of ['rev', 'job', 'trace', 'session.msg', 'doc.diff']) {
      _es.addEventListener(n, (e) => {
        try { onSseEvent(n, JSON.parse(e.data)) } catch (err) { /* 忽略坏帧 */ }
      })
    }
  }

  function disconnectSSE() {
    if (_es) { _es.close(); _es = null }
    sseAlive.value = false
  }

  // P5：切项目/集 → 清掉上次 doc.diff 撤销条（避免跨项目误撤销）
  watch([project, episode], () => { lastDocDiff.value = null })

  return {
    projects, project, episode, episodes, wizard, jobsOpen,
    selection, laneOpen, activeLane, timelineMode, assetsWithImg,
    boardRows, vocab, lastRedrawn, scriptOpen, agentOpen, canvasTick, creativeTick, candCounts,
    status, statusCls, dirty, assets, tasteDefaults, epStatus, shotCount,
    pickedShots, coveredCount, stageStates, laneSummaries,
    view, leftW, rightW, rightCollapsed, settingsOpen,
    sessions, selectedSessionId, sessionMessages, sessionTasks, chatBusy, sessionTick,
    sseAlive, sseToast, sseJobs, liveEvents, streamTaskId, streamText, lastDocDiff,
    loadSessions, createSession, removeSession, selectSession,
    loadSessionMessages, loadSessionTasks,
    connectSSE, disconnectSSE, beginStream, clearStream, finalizeStream,
    setStatus, reloadAssets, refreshWizard, refreshEpisode,
    onProjectChange, onEpisodeChange, saveBoard, init,
  }
}
