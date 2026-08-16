<template>
  <div class="shell">
    <TopBar />

    <!-- 三栏壳：左 AI 栏（可拖宽）｜ 中主工作区（单视图）｜ 右状态栏（可折叠） -->
    <div class="three-col">
      <!-- 左栏：AI（会话列表 + 对话窗 + 输入框） -->
      <aside class="left-col" :style="{ width: store.leftW.value + 'px' }">
        <SessionRail />
        <ChatThread />
        <ChatInput />
      </aside>
      <div class="resize-h left-h" title="拖拽调整左栏宽度（280–640px）"
        @mousedown="startDrag($event, 'left')" />

      <!-- 中栏：主工作区（视图标题 + 上下文动作 + 一次一个视图） -->
      <main class="main-col">
        <div class="view-head">
          <h2 class="view-title">{{ viewTitle }}</h2>
          <span class="view-sum">{{ viewSummary }}</span>
          <span class="spacer" />
          <!-- 分镜视图上下文动作：从剧本生成分镜（按钮自画布工具栏移入，唯一入口） -->
          <button v-if="store.view.value === 'board'" class="ghost" @click="genBoard">从剧本生成分镜</button>
        </div>
        <div class="view-body">
          <ScriptView v-if="store.view.value === 'script'" />
          <ArtView v-else-if="store.view.value === 'art'" />
          <BoardView v-else-if="store.view.value === 'board'" ref="boardView" />
          <ComposeView v-else />
        </div>
      </main>

      <!-- 右栏拖拽手柄（折叠按钮在手柄处；窄条态不可拖，宽度由折叠态决定） -->
      <div v-if="store.rightCollapsed.value !== 2" class="resize-h right-h"
        :title="store.rightCollapsed.value === 0 ? '拖拽调整右栏宽度' : ''"
        @mousedown="store.rightCollapsed.value === 0 && startDrag($event, 'right')">
        <button v-if="store.rightCollapsed.value === 0" class="collapse-btn"
          title="折叠右栏为 24px 窄条" @click.stop="store.rightCollapsed.value = 1">»</button>
      </div>

      <!-- 右栏：状态/导航（展开 300px / 窄条 24px / 隐藏 0） -->
      <aside v-if="store.rightCollapsed.value !== 2" class="right-col" :style="rightStyle">
        <template v-if="store.rightCollapsed.value === 0">
          <StageNav />
          <StatusPanel :active="true" />
        </template>
        <template v-else>
          <div class="right-strip" title="右栏已折叠">
            <div v-for="v in VIEWS" :key="v.key" class="strip-dot" :title="v.label"
              @click="store.view.value = v.key">
              <span class="sn-dot" :class="dotOf(v.key)"></span>
            </div>
            <button class="strip-btn" title="展开右栏" @click="store.rightCollapsed.value = 0">«</button>
            <button class="strip-btn" title="完全隐藏右栏" @click="store.rightCollapsed.value = 2">▷</button>
          </div>
        </template>
      </aside>

        <!-- 完全隐藏时的边缘恢复把手 -->
      <button v-if="store.rightCollapsed.value === 2" class="edge-tab" title="展开右栏（24px 窄条）"
        @click="store.rightCollapsed.value = 1">«</button>
    </div>

    <!-- P3/P5：AI 写盘 toast（doc.diff 事件，3.5s 自动消失；P5 加「撤销」动作——有版本可回滚时显示） -->
    <transition name="toast-fade">
      <div v-if="store.sseToast.value" class="sse-toast" :key="store.sseToast.value.ts">
        <span class="toast-text">{{ store.sseToast.value.text }}</span>
        <button v-if="toastCanUndo" class="toast-undo" :disabled="toastUndoing" @click="undoToast">
          {{ toastUndoing ? '撤销中…' : '撤销' }}
        </button>
      </div>
    </transition>

    <!-- P4：设置页（docs/11 §6，顶栏 ⚙ 打开；三子菜单 + /api/eco + 适配器测试） -->
    <SettingsDialog />
  </div>
</template>

<script setup>
import { computed, onMounted, provide, watch, ref } from 'vue'
import { createStore, VIEWS, dotClassOf } from './store'
import { api, enc, getDocRevs, restoreDocRev } from './api'
import { docKeyOf } from './lib/diff'
import TopBar from './components/TopBar.vue'
import SessionRail from './components/SessionRail.vue'
import ChatThread from './components/ChatThread.vue'
import ChatInput from './components/ChatInput.vue'
import StageNav from './components/StageNav.vue'
import StatusPanel from './components/StatusPanel.vue'
import ScriptView from './components/ScriptView.vue'
import ArtView from './components/ArtView.vue'
import BoardView from './components/BoardView.vue'
import ComposeView from './components/ComposeView.vue'
import SettingsDialog from './components/SettingsDialog.vue'

// ============ 三栏壳 ============
// App.vue = 壳（spec 11 §1）：顶栏极简 + 左 AI 栏（可拖宽 280–640）+ 中主工作区（单视图，右栏锚点切换）
// + 右状态栏（默认 300px，可折叠为 24px 窄条或 0）。抽屉/AgentBar/画布单页已全部移除。

const store = createStore()
provide('store', store)
defineExpose({ store })

const boardView = ref(null)
function genBoard() { boardView.value?.genFromScript() }

const viewMeta = computed(() => VIEWS.find(v => v.key === store.view.value) || VIEWS[0])
const viewTitle = computed(() => viewMeta.value.label)
const viewSummary = computed(() => store.laneSummaries.value[viewMeta.value.key] || '')

const rightStyle = computed(() => ({
  width: store.rightCollapsed.value === 0 ? store.rightW.value + 'px' : '24px',
}))
function dotOf(key) { return dotClassOf(store.stageStates.value[key] || 'none') }

// 拖拽调整栏宽（左 280–640 / 右 240–480，store watcher 内 clamp + localStorage 持久化）
function startDrag(e, side) {
  e.preventDefault()
  const rect = e.currentTarget.parentElement.getBoundingClientRect()
  const onMove = (ev) => {
    if (side === 'left') store.leftW.value = ev.clientX - rect.left
    else store.rightW.value = rect.right - ev.clientX
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

onMounted(store.init)

// ============ P3 SSE 实时通道（docs/11 §9.1） ============
// 切项目/集 → 断开重连 /api/events?project=&episode=（store.connectSSE 内部处理）；
// 事件分发在 store.onSseEvent：rev → 刷新链路 / job → 右栏 / trace → EventTrace /
// session.msg → 流式 / doc.diff → toast + 视图刷新。
watch([store.project, store.episode], () => { lastRev = null; store.connectSSE() })

// P3：doc.diff toast 3.5s 自动消失（仅清除同一次事件）
// P5：toast 扩展 {text, ts, doc}——doc 有版本可回滚时显示「撤销」按钮（调 restore 上一版本）
const toastCanUndo = ref(false)
const toastUndoing = ref(false)
const UNDOABLE_DOCS = ['script', 'board', 'assets', 'brief', 'novel']
watch(() => store.sseToast.value, async (t) => {
  toastCanUndo.value = false
  if (!t) return
  const key = docKeyOf(t.doc || '')
  if (UNDOABLE_DOCS.includes(key)) {
    try {
      const r = await getDocRevs(store.project.value, key)
      toastCanUndo.value = (r.revs || []).length > 0
    } catch (e) { toastCanUndo.value = false }
  }
  setTimeout(() => {
    if (store.sseToast.value && store.sseToast.value.ts === t.ts) store.sseToast.value = null
  }, 3500)
})
async function undoToast() {
  const t = store.sseToast.value
  if (!t) return
  const key = docKeyOf(t.doc || '')
  toastUndoing.value = true
  try {
    const r = await getDocRevs(store.project.value, key)
    const latest = (r.revs || [])[0]
    if (!latest) { store.setStatus('该文档暂无历史版本', 'err'); return }
    await restoreDocRev(store.project.value, key, latest.rev, store.episode.value)
    store.sseToast.value = null
    store.setStatus(`已撤销（回滚到 #${latest.rev}）`, 'ok')
  } catch (e) { store.setStatus('撤销失败: ' + e.message, 'err') }
  finally { toastUndoing.value = false }
}

// ============ 全局自动回显 watcher（spec 10，保留原逻辑） ============
// 每 5s 轮询 /api/canvas 的 rev（事实源摘要），变化即全量刷新展示层——
// 任何来源的文件改动（外部 agent 写盘 / /api/patch / 访谈简报）都会自动回显。
// P3：SSE 活着时轮询降级为兜底（rev 事件与轮询同函数，收到事件即刷）。
// P3.5 问题 6：轮询永不彻底停——SSE 存活时 10s 一次兜底，断开恢复 5s，
// 防 SSE 静默断流（连接在但事件不通）导致事件/轮询双失。
let lastRev = null
let lastPoll = 0
async function pollRev() {
  if (!store.project.value) return
  if (store.sseAlive.value && (Date.now() - lastPoll) < 10000) return
  lastPoll = Date.now()
  try {
    const c = await api(`/api/canvas/${enc(store.project.value)}/${store.episode.value}`)
    if (lastRev == null) { lastRev = c.rev; return }
    if (c.rev && c.rev !== lastRev) {
      lastRev = c.rev
      store.canvasTick.value++        // BoardCanvas.loadAll / ComposeTrack.load
      store.creativeTick.value++      // ScriptPanel.loadCreative
      store.refreshWizard()
      store.refreshEpisode()
      store.reloadAssets()            // 资产库也在 rev 摘要内
    }
  } catch (e) { /* 桥不可达时静默，下拍重试 */ }
}
// 切项目/集时重置基线，避免误报
onMounted(() => { setInterval(pollRev, 5000); store.connectSSE() })
</script>

<style scoped>
.three-col { flex: 1; display: flex; min-height: 0; overflow: hidden; position: relative; }

/* ---- 左栏 ---- */
.left-col { flex: none; display: flex; flex-direction: column; min-width: 0;
  border-right: 1px solid var(--line); background: var(--green-bg); }

/* ---- 拖拽手柄 ---- */
.resize-h { flex: none; width: 6px; cursor: col-resize; background: var(--panel);
  position: relative; z-index: 3; }
.resize-h:hover { background: var(--green-deep); }
.left-h { border-right: 1px solid var(--line); }
.right-h { border-left: 1px solid var(--line); }
.collapse-btn { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: 18px; height: 40px; border: 1px solid var(--line); border-radius: 4px;
  background: var(--panel2); color: var(--muted); font-size: 11px; cursor: pointer;
  opacity: 0; transition: opacity .12s; }
.resize-h:hover .collapse-btn { opacity: 1; }
.collapse-btn:hover { color: var(--green); border-color: var(--green); }

/* ---- 中栏 ---- */
.main-col { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
.view-head { flex: none; display: flex; align-items: center; gap: 10px;
  padding: 8px 16px; background: var(--panel); border-bottom: 1px solid var(--line); }
.view-title { margin-bottom: 0; font-size: 14px; font-weight: 700; color: var(--green-soft);
  text-transform: none; letter-spacing: .5px; }
.view-sum { font-size: 12px; color: var(--muted); }
.view-head .spacer { flex: 1; }
.view-head .ghost { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 12px; font-size: 12px; cursor: pointer; }
.view-head .ghost:hover { border-color: var(--green); color: var(--green-soft); }
.view-body { flex: 1; min-height: 0; overflow-y: auto; }

/* ---- 右栏 ---- */
.right-col { flex: none; display: flex; flex-direction: column; min-width: 0;
  border-left: 1px solid var(--line); background: var(--panel); }
.right-strip { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 10px;
  padding: 12px 0; }
.strip-dot { cursor: pointer; padding: 2px; }
.sn-dot { display: block; width: 9px; height: 9px; border-radius: 50%; }
.sn-dot.none { background: var(--muted); }
.sn-dot.active { background: var(--accent); box-shadow: 0 0 0 2px rgba(79,140,255,.25); }
.sn-dot.done { background: var(--green); box-shadow: 0 0 0 2px rgba(52,211,153,.25); }
.strip-btn { width: 20px; height: 20px; border: 1px solid var(--line); border-radius: 4px;
  background: var(--panel2); color: var(--muted); font-size: 10px; cursor: pointer; padding: 0; }
.strip-btn:hover { color: var(--green); border-color: var(--green); }

/* 完全隐藏时的边缘把手 */
.edge-tab { position: absolute; top: 50%; right: 0; transform: translateY(-50%);
  width: 16px; height: 44px; border: 1px solid var(--line); border-right: none;
  border-radius: 6px 0 0 6px; background: var(--panel2); color: var(--muted);
  font-size: 11px; cursor: pointer; z-index: 5; }
.edge-tab:hover { color: var(--green); border-color: var(--green); }

/* P3/P5：AI 写盘 toast（doc.diff）——顶部居中，暗夜绿边框 + 流光点缀；P5 加撤销动作按钮 */
.sse-toast { position: fixed; top: 52px; left: 50%; transform: translateX(-50%);
  z-index: 100; max-width: 70vw; background: var(--panel);
  border: 1px solid rgba(52,211,153,.55); border-left: 3px solid var(--green);
  color: var(--green-soft); font-size: 13px; line-height: 1.6;
  border-radius: 8px; padding: 8px 16px; box-shadow: 0 6px 24px rgba(0,0,0,.35);
  display: flex; align-items: center; gap: 10px; }
.toast-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.toast-undo { background: var(--green); color: #04281b; border: none; border-radius: 6px;
  padding: 4px 12px; font-size: 12px; font-weight: 700; cursor: pointer; flex: none; }
.toast-undo:disabled { opacity: .5; cursor: default; }
.toast-fade-enter-active, .toast-fade-leave-active { transition: opacity .25s, transform .25s; }
.toast-fade-enter-from, .toast-fade-leave-to { opacity: 0; transform: translate(-50%, -6px); }
</style>
