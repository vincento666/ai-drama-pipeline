<template>
  <div class="panel script-panel">
    <p class="hint">粘贴小说/素材存为 小说.md；「一键 AI 编剧」自动产出事件图谱 → 故事骨架 → 逐集剧本 → 资产清单。
    有本地 LLM 直接生成；无 LLM 时输出 Agent 指令（发给外部 Agent 执行）。分步按钮用于单步重跑/细调。</p>

    <textarea v-model="novel" placeholder="粘贴小说原文或创作素材…（存为 小说.md）" rows="8" class="novel-box"></textarea>

    <!-- 主操作行 -->
    <div class="row">
      <button class="primary" @click="runAll" :disabled="busy">✨ 一键 AI 编剧</button>
      <button @click="saveNovel" :disabled="busy">保存小说</button>
      <span class="rstatus" :class="errCls">{{ status }}</span>
    </div>
    <!-- 分步（单步重跑/细调） -->
    <div class="row sub-row">
      <span class="hint">分步：</span>
      <button class="mini" @click="run('events')" :disabled="busy">事件</button>
      <button class="mini" @click="run('skeleton')" :disabled="busy">骨架</button>
      <button class="mini" @click="run('script')" :disabled="busy">剧本</button>
      <button class="mini" @click="run('assets')" :disabled="busy">资产</button>
    </div>

    <!-- 产物预览 -->
    <div class="tabs">
      <span class="hint tabs-label">预览：</span>
      <button v-for="k in tabs" :key="k.key" class="tab" :class="{ on: tab === k.key }" @click="tab = k.key">
        {{ k.label }}{{ k.count ? ` (${k.count})` : '' }}
      </button>
    </div>
    <pre class="mono box">{{ current }}</pre>

    <div v-if="result" class="ai-result">
      <h4>{{ result.title }}</h4>
      <p class="hint">{{ result.hint }}</p>
      <button v-if="result.instruction" @click="copy(result.instruction)">复制指令</button>
      <pre v-if="result.instruction" class="mono box">{{ result.instruction }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, inject } from 'vue'
import { api, enc } from '../api'

const store = inject('store')
const novel = ref('')
const creative = ref({ novel: '', events: '', skeleton: '', script: '', assets: '' })
const result = ref(null)
const status = ref('')
const errCls = ref('')
const busy = ref(false)
const tab = ref('events')

const MODES = { events: '事件图谱', skeleton: '故事骨架', script: '逐集剧本', assets: '资产清单' }
const FILE = { events: '小说事件.md', skeleton: '故事骨架.md', script: '剧本.md', assets: '资产清单.md' }
const tabs = [
  { key: 'events', label: '事件图谱', count: len('events') },
  { key: 'skeleton', label: '故事骨架', count: len('skeleton') },
  { key: 'script', label: '逐集剧本', count: len('script') },
  { key: 'assets', label: '资产清单', count: len('assets') },
]
function len(k) { return (creative.value[k] || '').length }

const current = computed(() => creative.value[tab.value] || '（暂无内容，点上方按钮生成）')

async function loadCreative() {
  if (!store.project.value) return
  try {
    const c = await api(`/api/creative/${enc(store.project.value)}`)
    creative.value = c
    if (c.novel && !novel.value.trim()) novel.value = c.novel
    status.value = c.script ? '已有 剧本.md（可审改）' : '尚未生成 剧本.md'
  } catch (e) { /* ignore */ }
}

async function saveNovel() {
  if (!novel.value.trim()) { status.value = '请先输入小说内容'; errCls.value = 'err'; return }
  try {
    const r = await api(`/api/novel/${enc(store.project.value)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ novel: novel.value }),
    })
    status.value = `小说已保存（${r.chars} 字）`; errCls.value = ''
  } catch (e) { status.value = '保存失败: ' + e.message; errCls.value = 'err' }
}

// 统一 job 轮询：running 时展示后端真实进度文案，终态返回整个状态对象
function pollJob(job, label) {
  return new Promise((resolve) => {
    const timer = setInterval(async () => {
      try {
        const s = await api(`/api/render/status/${job}`)
        if (s.status === 'running') { status.value = `${label}：${s.message || '执行中'}`; return }
        clearInterval(timer)
        resolve(s)
      } catch (e) { /* 继续轮询 */ }
    }, 3000)
  })
}

// 分步生成（新版契约）：POST 立即返回 {job, status, mode}；done 后 result 为结果对象
async function run(mode) {
  busy.value = true; result.value = null
  status.value = MODES[mode] + '：提交中…'; errCls.value = ''
  try {
    const r = await api(`/api/ai-write/${enc(store.project.value)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ novel: novel.value, title: store.project.value, mode }),
    })
    const s = await pollJob(r.job, MODES[mode])
    if (s.status === 'error') {
      status.value = MODES[mode] + ' 失败：' + (s.message || '任务错误'); errCls.value = 'err'
      return
    }
    const res = s.result || {}
    if (res.error) {
      status.value = MODES[mode] + ' 失败：' + res.error; errCls.value = 'err'
    } else if (r.mode === 'llm') {
      await loadCreative()
      status.value = MODES[mode] + ' 已生成并写入项目'
    } else {
      result.value = {
        title: MODES[mode] + ' Agent 指令',
        hint: `复制给任意 AI Agent，写入 output/${store.project.value}/${FILE[mode]}，然后刷新查看。`,
        instruction: res.instruction || '',
      }
      status.value = '无本地 LLM，已输出 Agent 指令'
    }
    await store.refreshWizard()
  } catch (e) {
    status.value = MODES[mode] + ' 失败：' + e.message; errCls.value = 'err'
  } finally {
    busy.value = false
  }
}

async function runAll() {
  busy.value = true; result.value = null
  status.value = '一键编剧：提交中…'; errCls.value = ''
  try {
    // 只在文本框有内容时才写回小说；否则使用项目里已有的 小说.md
    if (novel.value.trim()) {
      await api(`/api/novel/${enc(store.project.value)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ novel: novel.value }),
      })
    }
    const r = await api(`/api/ai-write-all/${enc(store.project.value)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ novel: novel.value.trim() ? novel.value : '', title: store.project.value }),
    })
    const s = await pollJob(r.job, '一键编剧')
    if (s.status === 'error') {
      status.value = '一键编剧失败：' + (s.message || '任务错误'); errCls.value = 'err'
      return
    }
    handleAiWriteResult(s.result || {})
  } catch (e) {
    status.value = '一键编剧失败：' + e.message; errCls.value = 'err'
  } finally {
    busy.value = false
    await loadCreative()
    await store.refreshWizard()
    store.refreshEpisode()   // 一键编剧可能已自动生成分镜，同步泳道头的分镜档位
    store.canvasTick.value++ // 联动时间轴/成片轨
  }
}

function handleAiWriteResult(r) {
  if (!r || !r.ok) { status.value = '生成失败：无有效结果'; errCls.value = 'err'; return }
  if (r.mode === 'llm') {
    status.value = r.board ? '一键编剧完成，分镜已自动生成' : '一键编剧完成：' + (r.done || []).join(' → ')
    errCls.value = ''
  } else {
    const inst = (r.instructions || []).join('\n\n' + '='.repeat(50) + '\n\n')
    result.value = {
      title: 'Agent 指令：用外部 Agent 生成完整剧本',
      hint: r.board
        ? `项目已有剧本，已自动生成分镜。若想用外部 Agent 重新写剧本，复制下方指令执行。`
        : `当前无本地 LLM。你可以：① 粘贴已有剧本到“逐集剧本”预览；② 或复制下方指令给任意 AI Agent 生成剧本。`,
      instruction: inst,
    }
    status.value = r.board ? '已用现有剧本自动生成分镜' : '无本地 LLM，且项目无剧本'
    errCls.value = r.board ? '' : 'err'
  }
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); status.value = '已复制' }
  catch (e) { status.value = '复制失败，请手动选择复制' }
}

// 暴露给 OnboardPanel（剧本侧板顶部）：「保存简报并一键生成」复用本条链路
defineExpose({ runAll, busy })

onMounted(loadCreative)
watch(() => store.project.value, loadCreative)
watch(() => store.creativeTick.value, loadCreative)   // rev watcher：外部改动剧本四块/简报时自动回显（侧板打开期间）
</script>

<style scoped>
.script-panel { max-width: 960px; }
.novel-box { width: 100%; background: var(--panel2); color: var(--fg);
  border: 1px solid var(--line); border-radius: 8px; padding: 10px;
  font-family: var(--mono); font-size: 13px; line-height: 1.6; margin-top: 8px; }
.row { display: flex; gap: 8px; align-items: center; margin: 10px 0; flex-wrap: wrap; }
.row button { background: var(--accent); color: #fff; border: none; border-radius: 6px;
  padding: 7px 14px; font-size: 13px; cursor: pointer; }
.row button.primary { background: var(--ok); font-weight: 700; padding: 8px 16px; }
.row button.mini { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); padding: 4px 10px; font-size: 12px; }
.row button:disabled { background: var(--line); color: var(--muted); }
.sub-row { margin-top: -4px; }
.rstatus { font-size: 12px; color: var(--warn); }
.rstatus.err { color: var(--danger); }
.tabs { display: flex; gap: 6px; margin: 8px 0; align-items: center; }
.tabs-label { flex: none; }
.tab { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 12px; }
.tab.on { border-color: var(--accent); color: var(--accent); }
.box { background: var(--panel2); border: 1px solid var(--line); border-radius: 8px;
  padding: 10px; white-space: pre-wrap; word-break: break-all; max-height: 360px; overflow-y: auto; }
.ai-result { margin-top: 12px; }
.ai-result h4 { color: var(--accent); margin-bottom: 6px; }
.ai-result button { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 12px; cursor: pointer; margin-bottom: 6px; }
</style>
