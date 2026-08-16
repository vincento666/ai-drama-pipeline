// 全局 store：App 创建并 provide，各面板 inject 使用。
// 键名与原 App.vue 内嵌 store 保持一致（project/episode/wizard/view/dirty/…），子组件零改动。
import { ref, computed } from 'vue'
import { api, enc } from './api'

export const STAGES = [
  { key: 'script', label: '剧本' },
  { key: 'art', label: '美术设定' },
  { key: 'board', label: '分镜' },
  { key: 'compose', label: '成片' },
]

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

  return {
    projects, project, episode, episodes, wizard, jobsOpen,
    selection, laneOpen, activeLane, timelineMode, assetsWithImg,
    boardRows, vocab, lastRedrawn, scriptOpen, agentOpen, canvasTick, creativeTick, candCounts,
    status, statusCls, dirty, assets, tasteDefaults, epStatus, shotCount,
    pickedShots, coveredCount, stageStates, laneSummaries,
    setStatus, reloadAssets, refreshWizard, refreshEpisode,
    onProjectChange, onEpisodeChange, saveBoard, init,
  }
}
