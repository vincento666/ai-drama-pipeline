<template>
  <div class="panel script-panel">
    <!-- P6b：AI 入口唯一化——删「一键 AI 编剧」+ 分步按钮；AI 生成/修改一律在左侧对话栏说一句话 -->
    <p class="hint">AI 生成/修改请在左侧对话栏说一句话；此处可直接编辑小说/剧本（保存后作为后续分镜的真理源）。</p>

    <textarea v-model="novel" placeholder="粘贴小说原文或创作素材…（存为 小说.md）" rows="8" class="novel-box"></textarea>

    <!-- 主操作行：唯一操作 = 编辑小说正文并保存 -->
    <div class="row">
      <button class="primary" @click="saveNovel" :disabled="saving">{{ saving ? '保存中…' : '保存小说' }}</button>
      <span class="rstatus" :class="errCls">{{ status }}</span>
    </div>

    <!-- 产物预览（只读 tabs，P5 行级 diff 高亮：doc.diff 后新增行绿色 3s 渐隐，删除行红标） -->
    <div class="tabs">
      <span class="hint tabs-label">产物预览（只读）：</span>
      <button v-for="k in tabs" :key="k.key" class="tab" :class="{ on: tab === k.key }" @click="tab = k.key">
        {{ k.label }}{{ k.count ? ` (${k.count})` : '' }}
      </button>
    </div>
    <div v-if="currentLines.length" class="mono box diff-body">
      <div v-for="(line, i) in currentLines" :key="i" class="dline" :class="diffCls(tab, i)">{{ line || ' ' }}</div>
    </div>
    <pre v-else class="mono box">{{ current }}</pre>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, inject } from 'vue'
import { api, enc } from '../api'
import { lineDiff, docKeyOf } from '../lib/diff'

// 剧本视图内容（spec 11 §11 映射；P6b 收敛）：小说 textarea（唯一编辑操作）+ 保存 +
// 产物预览 tabs（事件/骨架/剧本/资产，只读）+ P5 行级 diff 高亮 + 版本历史（在 ScriptView）。
// 一键/分步 AI 编剧按钮已删除——AI 唯一入口 = 左栏对话（docs/12 §3 ①）。
const store = inject('store')
const novel = ref('')
const creative = ref({ novel: '', events: '', skeleton: '', script: '', assets: '' })
const status = ref('')
const errCls = ref('')
const saving = ref(false)
const tab = ref('events')

// P5：行级 diff 高亮状态——diffState[tabKey] = { added: Set<行号>, removed: Set<行号> }
// prevTexts[tabKey] = 上次加载的文本（diff 基线；creativeTick/rev 刷新后与新文本比对）
const diffState = ref({})
const prevTexts = {}
const DIFF_TAB_MAP = { script: ['events', 'skeleton', 'script'], assets: ['assets'] }

const tabs = [
  { key: 'events', label: '事件图谱', count: len('events') },
  { key: 'skeleton', label: '故事骨架', count: len('skeleton') },
  { key: 'script', label: '逐集剧本', count: len('script') },
  { key: 'assets', label: '资产清单', count: len('assets') },
]
function len(k) { return (creative.value[k] || '').length }

const current = computed(() => creative.value[tab.value] || '（暂无内容，可在左侧对话栏让 AI 生成）')
const currentLines = computed(() => String(current.value).split('\n'))

// P5：某行是否高亮（added 绿 / removed 红；CSS 动画 3s 渐隐，类可保留无害）
function diffCls(k, idx) {
  const st = diffState.value[k]
  if (!st) return ''
  const n = idx + 1
  if (st.added.has(n)) return 'diff-add'
  if (st.removed.has(n)) return 'diff-del'
  return ''
}

async function loadCreative() {
  if (!store.project.value) return
  try {
    const c = await api(`/api/creative/${enc(store.project.value)}`)
    creative.value = c
    if (c.novel && !novel.value.trim()) novel.value = c.novel
    status.value = c.script ? '已有 剧本.md（可审改）' : '尚未生成 剧本.md'
    // P5：doc.diff 对应本视图文档 → 与上次内容比对，产出本次行级高亮（新增行绿标 3s 渐隐）
    const doc = store.lastDocDiff.value && docKeyOf(store.lastDocDiff.value.doc)
    if (doc && DIFF_TAB_MAP[doc]) {
      const next = { ...diffState.value }
      for (const k of DIFF_TAB_MAP[doc]) {
        const old = prevTexts[k]
        const neu = c[k] || ''
        if (old != null && old !== '' && old !== neu) {
          const { added, removed } = lineDiff(old, neu)
          next[k] = { added: new Set(added), removed: new Set(removed) }
        }
      }
      diffState.value = next
    }
    for (const k of Object.keys(c)) prevTexts[k] = c[k] || ''
  } catch (e) { /* ignore */ }
}

async function saveNovel() {
  if (!novel.value.trim()) { status.value = '请先输入小说内容'; errCls.value = 'err'; return }
  saving.value = true
  try {
    const r = await api(`/api/novel/${enc(store.project.value)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ novel: novel.value }),
    })
    status.value = `小说已保存（${r.chars} 字）`; errCls.value = ''
  } catch (e) { status.value = '保存失败: ' + e.message; errCls.value = 'err' }
  finally { saving.value = false }
}

onMounted(loadCreative)
watch(() => store.project.value, loadCreative)
watch(() => store.creativeTick.value, loadCreative)   // rev watcher：外部改动剧本四块/简报时自动回显（视图打开期间）
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
.row button:disabled { background: var(--line); color: var(--muted); cursor: default; }
.rstatus { font-size: 12px; color: var(--warn); }
.rstatus.err { color: var(--danger); }
.tabs { display: flex; gap: 6px; margin: 8px 0; align-items: center; flex-wrap: wrap; }
.tabs-label { flex: none; }
.tab { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 12px; }
.tab.on { border-color: var(--accent); color: var(--accent); }
.box { background: var(--panel2); border: 1px solid var(--line); border-radius: 8px;
  padding: 10px; white-space: pre-wrap; word-break: break-all; max-height: 360px; overflow-y: auto; }
/* P5：diff 行级高亮——新增行绿色背景 3s 渐隐（spec 11 §10），删除行红色短标 */
.diff-body { padding: 6px 10px; }
.dline { min-height: 1.5em; line-height: 1.6; white-space: pre-wrap; word-break: break-all; }
.dline.diff-add { border-radius: 3px; animation: diffFadeAdd 3s ease forwards; }
.dline.diff-del { border-radius: 3px; animation: diffFadeDel 3s ease forwards; }
@keyframes diffFadeAdd {
  0% { background-color: rgba(52, 211, 153, .38); }
  100% { background-color: transparent; }
}
@keyframes diffFadeDel {
  0% { background-color: rgba(255, 99, 99, .28); }
  100% { background-color: transparent; }
}
</style>
