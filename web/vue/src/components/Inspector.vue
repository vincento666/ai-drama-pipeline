<template>
  <aside class="inspector">
    <div class="insp-col">
      <!-- Agent 规划流：常驻右栏顶部 -->
      <PlanFlow />

      <!-- 选中条：显示当前对象路径，✕ 返回总览 -->
      <div v-if="sel" class="insp-bar">
        <span class="mono">{{ selPath }}</span>
        <button class="x" title="返回总览" @click="store.selection.value = null">✕</button>
      </div>

      <!-- shot 态：完整复用现有 ShotInspector（参考图/候选墙/A-B/选中原因/提示词） -->
      <ShotInspector v-if="shotSel" :key="shotSel.id" :shot="shotSel.id" :assets-with-img="store.assetsWithImg.value" />

      <!-- asset 态：资产详情 -->
      <div v-else-if="assetSel" class="panel asset-detail">
        <h3>资产 {{ assetSel.code }}</h3>
        <img class="ad-img" :src="`/asset-img/${assetSel.code}`" :alt="assetSel.name" />
        <div class="ad-row"><span>名称</span><b>{{ assetSel.name }}</b></div>
        <div class="ad-row"><span>类型</span><b>{{ TYPE_LABEL[assetSel.type] || assetSel.type }}</b></div>
        <div class="ad-row"><span>角色圣经</span><b :class="{ ok: assetSel.bible }">{{ assetSel.bible ? '✓ 已建' : '未建' }}</b></div>
        <p class="hint">抽卡时在「参考图」下拉选择该资产（Ref2VA 一致性锚点）。登记/上传在②美术设定泳道。</p>
        <button class="danger-btn" @click="removeAsset">删除该资产</button>
      </div>

      <!-- 总览态：四步状态 + 分镜进度 + 引导 -->
      <div v-else class="panel overview">
        <h3>画布总览</h3>
        <div class="ov-project mono">{{ store.project.value || '—' }} · E{{ String(store.episode.value).padStart(2, '0') }}</div>

        <div class="ov-list">
          <div v-for="(s, i) in STAGES" :key="s.key" class="ov-row" @click="goLane(s.key)">
            <span class="ov-label">{{ i + 1 }} {{ s.label }}</span>
            <span class="pill" :class="stageStates[s.key]">{{ STATE_LABEL[stageStates[s.key]] }}</span>
            <span class="ov-sum">{{ summaries[s.key] }}</span>
          </div>
        </div>

        <template v-if="store.shotCount.value > 0">
          <div class="bar"><i :style="{ width: pct + '%' }"></i></div>
          <div class="hint">分镜选片进度 {{ store.coveredCount.value }}/{{ store.shotCount.value }}</div>
        </template>

        <p class="hint ov-tip">点画布中的分镜卡或资产卡，在此编辑字段、参考图、抽卡与选片。</p>
      </div>
    </div>
  </aside>
</template>

<script setup>
// 右栏检查器（详情）。Agent 会话工作台已迁入统一对话窗 AgentDock（TopBar「Agent」按钮，spec 10）
import { computed, inject, nextTick } from 'vue'
import { STAGES } from '../store'
import { deleteAsset } from '../api'
import PlanFlow from './PlanFlow.vue'
import ShotInspector from './board/ShotInspector.vue'

const store = inject('store')

const STATE_LABEL = { done: '● 完成', draft: '◐ 草稿', none: '○ 无' }
const TYPE_LABEL = { C: '角色', S: '场景', P: '道具', R: '风格参考' }

const sel = computed(() => store.selection.value)
const shotSel = computed(() => sel.value && sel.value.type === 'shot' ? sel.value : null)
const assetSel = computed(() => {
  const s = sel.value
  if (!s || s.type !== 'asset') return null
  return store.assetsWithImg.value.find(a => a.code === s.id) || (store.assets || {})[s.id] || { code: s.id, name: '', type: s.id[0] }
})
const selPath = computed(() => {
  const s = sel.value
  if (!s) return ''
  if (s.type === 'shot') return `③分镜 / 镜${String(s.id + 1).padStart(2, '0')}`
  if (s.type === 'asset') return `资产条 / ${s.id}`
  return s.type
})
const stageStates = computed(() => store.stageStates.value)
const summaries = computed(() => store.laneSummaries.value)
const pct = computed(() => store.shotCount.value ? Math.round(100 * store.coveredCount.value / store.shotCount.value) : 0)

function goLane(key) {
  if (key === 'script') { store.scriptOpen.value = true; return }   // 剧本已收进左侧板
  if (key in store.laneOpen.value) store.laneOpen.value[key] = true
  nextTick(() => document.getElementById('lane-' + key)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

async function removeAsset() {
  const a = assetSel.value
  if (!a || !a.code) return
  if (!window.confirm(`确认删除资产 ${a.code} ${a.name || ''}？登记痕迹与图片将一并移除。`)) return
  try {
    await deleteAsset(a.code)
    store.setStatus('资产已删除：' + a.code, 'ok')
    store.selection.value = null
    await store.reloadAssets()
  } catch (e) { store.setStatus('删除失败: ' + e.message, 'err') }
}
</script>

<style scoped>
.inspector { width: 380px; flex: none; display: flex; min-height: 0; border-left: 1px solid var(--line); }
.insp-col { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
.insp-col > .panel, .insp-col > aside { flex: 1; min-height: 0; }
.insp-bar { display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 8px 12px; background: var(--panel); border-bottom: 1px solid var(--line); flex: none; }
.insp-bar .mono { color: var(--accent); font-size: 12px; }
.x { background: var(--panel2); color: var(--muted); border: 1px solid var(--line); border-radius: 6px;
  padding: 2px 8px; cursor: pointer; font-size: 12px; }
.x:hover { color: var(--fg); border-color: var(--accent); }

.asset-detail { overflow-y: auto; }
.ad-img { width: 100%; border-radius: 8px; border: 1px solid var(--line); background: #000;
  display: block; margin-bottom: 10px; }
.ad-row { display: flex; gap: 10px; font-size: 13px; padding: 5px 0; border-bottom: 1px dashed var(--line); }
.ad-row span { color: var(--muted); width: 64px; flex: none; }
.ad-row b.ok { color: var(--ok); }
.danger-btn { margin-top: 12px; background: none; color: var(--danger); border: 1px solid var(--danger);
  border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 12px; }
.danger-btn:hover { background: rgba(255,107,107,.12); }

.overview { overflow-y: auto; }
.ov-project { color: var(--accent); margin-bottom: 12px; }
.ov-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.ov-row { display: flex; align-items: center; gap: 8px; background: var(--panel2); border: 1px solid var(--line);
  border-radius: 6px; padding: 7px 10px; cursor: pointer; font-size: 13px; }
.ov-row:hover { border-color: var(--accent); }
.ov-label { font-weight: 600; }
.ov-sum { margin-left: auto; color: var(--muted); font-size: 12px; }
.pill { font-size: 11px; padding: 0 7px; border-radius: 8px; line-height: 1.7; }
.pill.done { color: var(--ok); background: rgba(89,201,125,.15); }
.pill.draft { color: var(--warn); background: rgba(255,180,84,.15); }
.pill.none { color: var(--muted); background: var(--panel); }
.bar { height: 6px; background: var(--panel2); border-radius: 3px; overflow: hidden; margin-bottom: 6px; }
.bar i { display: block; height: 100%; background: var(--ok); border-radius: 3px; transition: width .3s; }
.ov-tip { margin-top: 14px; }
</style>
