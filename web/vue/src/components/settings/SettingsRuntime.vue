<template>
  <div class="sr">
    <h3>③ Harness 运行设置</h3>

    <div class="ctx-card">
      <div class="ctx-row">
        <label>上下文压缩阈值
          <input type="number" min="1000" step="1000" v-model.number="contextLimit" />
        </label>
        <span class="hint">会话上下文超过该 token 阈值 → 摘要压缩（保存 → PUT agent.context_limit）</span>
      </div>
      <div class="ctx-foot">
        <button class="primary" :disabled="savingCtx" @click="saveCtx">
          {{ savingCtx ? '保存中…' : '保存阈值' }}</button>
        <span v-if="ctxMsg" class="saved" :class="ctxErr ? 'bad' : 'ok'">{{ ctxMsg }}</span>
      </div>
    </div>

    <!-- P6c ②：ComfyUI 工作流（config workflow 段，GET/PUT /api/workflows） -->
    <div class="wf-card">
      <h4>ComfyUI 工作流（/api/workflows）</h4>
      <p class="hint">模式决定抽卡工作流来源：内置 = render 内置构造器（H3 T2VA/I2VA/Ref2VA）；模板 = ComfyUI 导出 JSON + config 注入映射（render.resolve_workflow 分派）。</p>
      <div class="wf-row">
        <label class="wf-radio">
          <input type="radio" value="builtin" v-model="wfMode" /> 内置（builtin）
        </label>
        <label class="wf-radio">
          <input type="radio" value="template" v-model="wfMode" /> 模板（template）
        </label>
        <select v-if="wfMode === 'template'" v-model="wfTemplate" class="wf-select mono"
          :disabled="!wfAvailable.length">
          <option v-for="t in wfAvailable" :key="t.name" :value="t.path">{{ t.name }}</option>
          <option v-if="!wfAvailable.length" value="">（无可用模板）</option>
        </select>
        <button class="ghost" :disabled="wfLoading" @click="loadWf">
          {{ wfLoading ? '加载中…' : '刷新模板列表' }}</button>
      </div>
      <div class="wf-row hint">
        <span>模板 JSON 放入 config eco.sources 目录（如 ComfyUI/workflows/…）即出现在上方列表。</span>
        <span v-if="wfStatus" class="mono wf-status">当前：{{ wfStatus }}</span>
      </div>
      <div class="ctx-foot">
        <button class="primary" :disabled="wfSaving" @click="saveWf">
          {{ wfSaving ? '保存中…' : '保存工作流模式' }}</button>
        <span v-if="wfMsg" class="saved" :class="wfErr ? 'bad' : 'ok'">{{ wfMsg }}</span>
      </div>
    </div>

    <!-- P7b ④：素材生成引擎（/api/engines，scan/adapt/register/delete 只增不改） -->
    <div class="wf-card">
      <h4>素材生成引擎（/api/engines）</h4>
      <p class="hint">外部引擎能力收敛为 refimg（美术参考）/ storyframe（分镜帧）/ video（视频抽卡）。
        引擎注册表写 config.local.json engines 段；未配置引擎时抽卡走内置构造器（行为与现状一致）。
        「扫描工作流」→ 能力识别 → 「AI 分析对接」生成映射草案（不写入）→ 「确认注册」落库。</p>
      <div class="wf-row">
        <button class="ghost" :disabled="engLoading" @click="loadEngines">
          {{ engLoading ? '加载中…' : '刷新引擎' }}</button>
        <button class="ghost" :disabled="scanning" @click="scanWf">
          {{ scanning ? '扫描中…' : '扫描工作流' }}</button>
        <span class="hint">{{ engines.length }} 引擎 / {{ scanned.length }} 工作流</span>
      </div>
      <div v-if="engMsg" class="skill-msg" :class="engErr ? 'bad' : 'ok'">{{ engMsg }}</div>

      <div v-if="engines.length" class="eco-group">
        <h5>已注册引擎</h5>
        <div v-for="e in engines" :key="e.id" class="eco-item">
          <span class="eco-dot" :class="e.changed ? 'bad' : 'ok'">{{ e.changed ? '⚠' : '✓' }}</span>
          <span class="eco-name">{{ e.name }}</span>
          <span class="eco-desc">{{ e.kind }} · {{ e.provider }}<template v-if="e.builtin"> · 内置兜底</template></span>
          <span class="eco-path mono" :title="e.workflow || e.note || ''">
            {{ (e.workflow || e.note || '').slice(0, 46) }}</span>
          <span class="eco-actions">
            <button v-if="!e.builtin" class="mini" @click="removeEngine(e)">删除</button>
          </span>
        </div>
      </div>

      <div v-if="scanned.length" class="eco-group">
        <h5>扫描到的工作流（能力识别）</h5>
        <div v-for="it in scanned" :key="it.path" class="eco-item">
          <span class="eco-name">{{ it.name }}</span>
          <span class="eco-desc cap" :title="it.summary">{{ it.summary || '—' }}</span>
          <span class="eco-desc">{{ capText(it.capability) }}</span>
          <span class="eco-actions">
            <select v-model="it.kind" class="wf-select mini-sel">
              <option v-for="k in it.capKinds" :key="k" :value="k">{{ k }}</option>
            </select>
            <button class="mini" :disabled="busy === it.path" @click="adapt(it)">
              {{ busy === it.path ? '分析中…' : 'AI 分析对接' }}</button>
          </span>
        </div>
      </div>

      <div v-if="draft" class="draft-box">
        <h5>映射草案：{{ draft.name }}（kind={{ draft.kind }} · {{ draft.mode }}）</h5>
        <p class="hint">{{ draft.summary }}</p>
        <table class="draft-table">
          <tr v-for="(slot, p) in draft.mapping" :key="p">
            <td class="mono draft-param">{{ p }}</td>
            <td class="mono draft-slot">{{ slot }}</td>
            <td class="draft-note">{{ (draft.notes && draft.notes[p]) || '' }}</td>
          </tr>
          <tr v-if="draft.unclassified && draft.unclassified.length">
            <td colspan="3" class="draft-un">未命中槽：{{ draft.unclassified.join('、') }}（规则+LLM 均未兜底）</td>
          </tr>
        </table>
        <div class="skill-row">
          <input v-model="draftName" class="skill-input mono" placeholder="引擎名称（缺省 = 工作流文件名）" />
          <button class="primary" :disabled="regBusy" @click="confirmRegister">
            {{ regBusy ? '注册中…' : '确认注册' }}</button>
          <button class="ghost" @click="draft = null">取消</button>
        </div>
      </div>
    </div>

    <h4>Skill 管理（/api/eco）</h4>
    <p class="hint">ComfyUI 插件与 H3 skill 生态（scripts/eco.py）+ 本地 .agents/skills/ 目录</p>
    <div class="eco-tools">
      <button class="ghost" :disabled="loading" @click="loadEco">{{ loading ? '加载中…' : '刷新清单' }}</button>
      <button class="ghost" :disabled="refreshing" @click="refresh">
        {{ refreshing ? '发现中…' : '重新发现生态源' }}</button>
      <span class="hint">{{ items.length }} 项</span>
    </div>
    <div v-if="ecoError" class="eco-err">{{ ecoError }}</div>

    <div v-for="g in groups" :key="g.key" class="eco-group">
      <h5>{{ g.label }}（{{ g.items.length }}）</h5>
      <div v-for="it in g.items" :key="it.id" class="eco-item">
        <span class="eco-dot" :class="it.installed ? 'ok' : 'bad'">{{ it.installed ? '✓' : '✗' }}</span>
        <span class="eco-name">{{ it.name }}</span>
        <span class="eco-desc" :title="it.desc">{{ it.desc || '—' }}</span>
        <span v-if="it.path" class="eco-path mono" :title="it.path">{{ it.path }}</span>
        <span class="eco-actions">
          <button v-if="!it.installed" class="mini" :disabled="busy === it.id" @click="install(it)">
            {{ busy === it.id ? '…' : '安装' }}</button>
          <button v-if="it.type === 'plugin'" class="mini" :disabled="busy === it.id" @click="check(it)">
            {{ busy === it.id ? '…' : '检查' }}</button>
        </span>
      </div>
      <div v-if="!g.items.length" class="eco-empty">无</div>
    </div>

    <div v-if="lastOutput" class="eco-out">
      <div class="eco-out-head">
        <span>操作输出（只读）</span>
        <button class="mini" @click="lastOutput = ''">清除</button>
      </div>
      <pre class="mono">{{ lastOutput }}</pre>
    </div>

    <!-- P6d ④：Skill 管理增强 —— 从 GitHub 安装 / 创建 skill（POST /api/skills/install|create，只增不改） -->
    <div class="skill-card">
      <h4>Skill 安装 / 创建（/api/skills）</h4>
      <p class="hint">安装 = api+raw 链路拉取 GitHub 仓库（同步，60s 超时，断点续传）；创建 = LLM 按 skill-create 规范生成 SKILL.md（约 120s）。装/建完后重新加载 agent 或新会话生效。</p>
      <div class="skill-row">
        <input v-model="instUrl" class="skill-input mono" placeholder="https://github.com/owner/repo[/tree/ref][/子目录]" />
        <input v-model="instOnly" class="skill-input skill-only" placeholder="子目录（可选，如 skills/h3-prompt-writing）" />
        <button class="ghost" :disabled="instBusy" @click="installSkill">
          {{ instBusy ? '安装中…' : '从 GitHub 安装' }}</button>
      </div>
      <div class="skill-row">
        <input v-model="createName" class="skill-input skill-name" placeholder="skill 名称（小写连字符，如 shot-review）" />
        <input v-model="createDesc" class="skill-input" placeholder="描述（含触发词，如 分镜审校工具，抽卡后逐镜质检）" />
        <button class="ghost" :disabled="createBusy" @click="createSkill">
          {{ createBusy ? '生成中…' : '创建 skill' }}</button>
      </div>
      <div v-if="skillMsg" class="skill-msg" :class="skillErr ? 'bad' : 'ok'">{{ skillMsg }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, inject } from 'vue'
import { getConfigAgent, putConfigAgent, getEco, postEco, getWorkflows, putWorkflows,
         postSkillInstall, postSkillCreate, getEngines, scanEngines, adaptEngine,
         registerEngine, deleteEngine } from '../../api'

// 设置页子菜单③（docs/11 §6.3）：上下文压缩阈值 + Skill 管理（/api/eco）。
// 阈值保存只 PUT {context_limit}（config.local.json 深合并，不覆盖适配器等其他 agent 字段）。
// P6c ②：加「ComfyUI 工作流」区块（GET/PUT /api/workflows，config workflow 段）。
const store = inject('store')
const DEFAULT_LIMIT = 20000

const contextLimit = ref(DEFAULT_LIMIT)
const savingCtx = ref(false)
const ctxMsg = ref('')
const ctxErr = ref(false)

// ComfyUI 工作流（P6c ②）
const wfMode = ref('builtin')
const wfTemplate = ref('')
const wfAvailable = ref([])
const wfLoading = ref(false)
const wfSaving = ref(false)
const wfMsg = ref('')
const wfErr = ref(false)
const wfStatus = ref('')

const items = ref([])
const loading = ref(false)
const refreshing = ref(false)
const busy = ref('')
const lastOutput = ref('')
const ecoError = ref('')

// P7b ④：素材生成引擎（/api/engines）
const engines = ref([])
const scanned = ref([])
const engLoading = ref(false)
const scanning = ref(false)
const engMsg = ref('')
const engErr = ref(false)
const draft = ref(null)
const draftName = ref('')
const regBusy = ref(false)
const ENG_KIND_LABEL = { refimg: '参考图', storyframe: '分镜帧', video: '视频' }

function capText(cap) {
  if (!cap) return ''
  const ks = (cap.kinds || [])
    .map(k => `${ENG_KIND_LABEL[k.kind] || k.kind}(${Math.round((k.confidence || 0) * 100)}%)`)
    .join(' ')
  const feats = []
  if (cap.chain) feats.push('链式长视频')
  if (cap.ref_input) feats.push('参考输入')
  if (cap.audio) feats.push('音频')
  return [ks, feats.join('/')].filter(Boolean).join(' · ')
}

async function loadEngines() {
  engLoading.value = true
  try {
    const r = await getEngines()
    engines.value = r.engines || []
  } catch (e) {
    engMsg.value = '引擎加载失败: ' + (e.message || '')
    engErr.value = true
  }
  engLoading.value = false
}

async function scanWf() {
  scanning.value = true
  engMsg.value = ''
  engErr.value = false
  try {
    const r = await scanEngines()
    scanned.value = (r.items || []).map(it => {
      const tops = ((it.capability || {}).kinds || [])
      return { ...it, kind: tops.length ? tops[0].kind : 'video',
               capKinds: tops.map(k => k.kind) }
    })
  } catch (e) {
    engMsg.value = '扫描失败: ' + (e.message || '')
    engErr.value = true
  }
  scanning.value = false
}

async function adapt(it) {
  busy.value = it.path
  engMsg.value = ''
  engErr.value = false
  try {
    const r = await adaptEngine(it.path, it.kind)
    if (!r.ok) {
      engMsg.value = r.error || '分析失败'
      engErr.value = true
      return
    }
    draft.value = r.engine_draft
    draftName.value = draft.value.name || ''
  } catch (e) {
    engMsg.value = '分析失败: ' + (e.message || '')
    engErr.value = true
  }
  busy.value = ''
}

async function confirmRegister() {
  if (!draft.value) return
  regBusy.value = true
  engMsg.value = ''
  engErr.value = false
  try {
    const r = await registerEngine(draftName.value, draft.value.kind,
                                   draft.value.path, draft.value.mapping)
    if (r.ok) {
      engMsg.value = `已注册引擎：${r.engine.name}（${r.engine.id}）`
      engErr.value = false
      draft.value = null
      await loadEngines()
    } else {
      engMsg.value = '注册失败: ' + (r.error || '')
      engErr.value = true
    }
  } catch (e) {
    engMsg.value = '注册失败: ' + (e.message || '')
    engErr.value = true
  }
  regBusy.value = false
}

async function removeEngine(e) {
  if (!window.confirm(`删除引擎「${e.name}」？`)) return
  try {
    await deleteEngine(e.id)
    await loadEngines()
  } catch (err) {
    engMsg.value = '删除失败: ' + (err.message || '')
    engErr.value = true
  }
}

const GROUP_META = [
  { key: 'plugin', label: 'ComfyUI 插件' },
  { key: 'skill', label: 'Skills（本地 .agents/skills + H3 prompt skill）' },
  { key: 'h3', label: 'H3 工作流' },
]
// 分组（未安装在前），type 未知归入 skill
const groups = computed(() => {
  return GROUP_META.map(g => ({
    ...g,
    items: items.value
      .filter(it => (it.type === g.key))
      .sort((a, b) => Number(a.installed) - Number(b.installed)),
  }))
})

async function loadAgent() {
  try {
    const r = await getConfigAgent()
    const lim = Number((r.agent || {}).context_limit)
    contextLimit.value = Number.isFinite(lim) && lim > 0 ? lim : DEFAULT_LIMIT
  } catch (e) { /* 桥不可达：保持默认 */ }
}

async function loadEco() {
  loading.value = true
  ecoError.value = ''
  try {
    const r = await getEco('list')
    if (!r.ok) { ecoError.value = r.error || '清单获取失败' }
    items.value = r.items || []
  } catch (e) {
    ecoError.value = e.message || '请求失败'
    items.value = []
  }
  loading.value = false
}

async function saveCtx() {
  savingCtx.value = true
  ctxMsg.value = ''
  try {
    await putConfigAgent({ context_limit: Number(contextLimit.value) || DEFAULT_LIMIT })
    ctxMsg.value = '已保存'
    ctxErr.value = false
  } catch (e) {
    ctxMsg.value = '保存失败: ' + (e.message || '')
    ctxErr.value = true
  }
  savingCtx.value = false
}

async function install(it) {
  busy.value = it.id
  try {
    const r = await postEco('install', it.id)
    lastOutput.value = (r.output || '').trim() || (r.ok ? '完成' : '失败')
    await loadEco()
  } catch (e) {
    lastOutput.value = '请求失败: ' + (e.message || '')
  }
  busy.value = ''
}

async function check(it) {
  busy.value = it.id
  try {
    const r = await postEco('check', it.id)
    lastOutput.value = (r.output || '').trim() || (r.ok ? '节点已注册' : '节点未注册/无法连接')
  } catch (e) {
    lastOutput.value = '请求失败: ' + (e.message || '')
  }
  busy.value = ''
}

async function refresh() {
  refreshing.value = true
  try {
    const r = await postEco('refresh')
    lastOutput.value = (r.output || '').trim() || (r.ok ? '重新发现完成' : '失败')
    await loadEco()
  } catch (e) {
    lastOutput.value = '请求失败: ' + (e.message || '')
  }
  refreshing.value = false
}

// ComfyUI 工作流（P6c ②）：GET /api/workflows → 模式 + 可用模板清单
async function loadWf() {
  wfLoading.value = true
  try {
    const r = await getWorkflows()
    wfMode.value = r.mode === 'template' ? 'template' : 'builtin'
    wfTemplate.value = r.template || ''
    wfAvailable.value = r.available || []
    wfStatus.value = r.mode === 'template'
      ? (r.template ? `template：${r.template}` : 'template（未选模板）')
      : 'builtin（内置构造器）'
  } catch (e) {
    wfMsg.value = '加载失败: ' + (e.message || '')
    wfErr.value = true
  }
  wfLoading.value = false
}

// 保存：PUT /api/workflows {mode, template} → 写 config.local.json workflow 段
async function saveWf() {
  wfSaving.value = true
  wfMsg.value = ''
  try {
    const r = await putWorkflows(wfMode.value, wfTemplate.value)
    const w = r.workflow || {}
    wfMode.value = w.mode === 'template' ? 'template' : 'builtin'
    wfTemplate.value = w.template || ''
    wfStatus.value = w.mode === 'template' ? `template：${w.template}` : 'builtin（内置构造器）'
    wfMsg.value = '已保存（config.local.json workflow 段）'
    wfErr.value = false
  } catch (e) {
    wfMsg.value = '保存失败: ' + (e.message || '')
    wfErr.value = true
  }
  wfSaving.value = false
}

// P6d ④：从 GitHub 安装 skill（POST /api/skills/install，同步 + 60s 超时）
const instUrl = ref('')
const instOnly = ref('')
const instBusy = ref(false)
const createName = ref('')
const createDesc = ref('')
const createBusy = ref(false)
const skillMsg = ref('')
const skillErr = ref(false)

async function installSkill() {
  if (!instUrl.value.trim()) {
    skillMsg.value = '请输入 GitHub URL'
    skillErr.value = true
    return
  }
  instBusy.value = true
  skillMsg.value = ''
  try {
    const r = await postSkillInstall(instUrl.value.trim(), instOnly.value.trim())
    if (r.ok) {
      skillMsg.value = `已安装 skill：${r.name}（${r.files} 文件，frontmatter ${r.frontmatter || '✓'}）`
      skillErr.value = false
    } else {
      skillMsg.value = `安装未完成：${r.error || '未知原因'}`
      skillErr.value = true
    }
  } catch (e) {
    skillMsg.value = '请求失败: ' + (e.message || '')
    skillErr.value = true
  }
  instBusy.value = false
  await loadEco()          // 清单自动刷新（skill 组出现新项）
}

async function createSkill() {
  if (!createName.value.trim() || !createDesc.value.trim()) {
    skillMsg.value = '名称与描述都不能为空'
    skillErr.value = true
    return
  }
  createBusy.value = true
  skillMsg.value = ''
  try {
    const r = await postSkillCreate(createName.value.trim(), createDesc.value.trim())
    if (r.ok) {
      skillMsg.value = `已创建 skill：${r.name}（${r.path}）`
      skillErr.value = false
      createName.value = ''
      createDesc.value = ''
    } else {
      skillMsg.value = `创建失败：${r.error || '未知原因'}`
      skillErr.value = true
    }
  } catch (e) {
    skillMsg.value = '请求失败: ' + (e.message || '')
    skillErr.value = true
  }
  createBusy.value = false
  await loadEco()
}

onMounted(() => { loadAgent(); loadEco(); loadWf(); loadEngines() })
</script>

<style scoped>
.sr { display: flex; flex-direction: column; gap: 14px; }
.sr h3 { margin-bottom: 2px; color: var(--green-soft); }
.sr h4 { font-size: 12px; color: var(--muted); letter-spacing: .5px; margin-bottom: 2px; }
.sr h5 { font-size: 12px; color: var(--green-soft); margin: 8px 0 4px; }
.ctx-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
  background: rgba(14,59,46,.18); display: flex; flex-direction: column; gap: 8px; }
.wf-card { border: 1px solid rgba(52,211,153,.35); border-radius: 8px; padding: 10px 12px;
  background: rgba(14,59,46,.12); display: flex; flex-direction: column; gap: 8px; }
.wf-card h4 { font-size: 12px; color: var(--green-soft); letter-spacing: .5px; margin: 0; }
.wf-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.wf-radio { display: flex; align-items: center; gap: 4px; color: var(--fg); font-size: 12px;
  cursor: pointer; }
.wf-radio input { accent-color: var(--green); }
.wf-select { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 8px; font-size: 12px; min-width: 220px; max-width: 320px; }
.wf-select:focus { outline: none; border-color: var(--green); }
.wf-status { color: var(--muted); font-size: 11px; }
.ctx-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ctx-row label { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
.ctx-row input {
  background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 8px; font-size: 13px; width: 130px;
}
.ctx-row input:focus { outline: none; border-color: var(--green); }
.ctx-foot { display: flex; align-items: center; gap: 10px; }
.primary { background: var(--green); color: #06281e; border: none; border-radius: 6px;
  padding: 6px 16px; font-size: 12px; font-weight: 600; cursor: pointer; }
.primary:hover:not(:disabled) { background: var(--green-soft); }
.primary:disabled { opacity: .6; cursor: default; }
.saved { font-size: 12px; }
.saved.ok { color: var(--ok); }
.saved.bad { color: var(--danger); }
.eco-tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ghost { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 12px; font-size: 12px; cursor: pointer; }
.ghost:hover:not(:disabled) { border-color: var(--green); color: var(--green-soft); }
.ghost:disabled { opacity: .5; cursor: default; }
.eco-err { color: var(--danger); font-size: 12px; }
.eco-group { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
.eco-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px;
  flex-wrap: wrap; }
.eco-dot { flex: none; font-weight: 700; }
.eco-dot.ok { color: var(--ok); }
.eco-dot.bad { color: var(--danger); }
.eco-name { flex: none; font-weight: 600; color: var(--fg); }
.eco-desc { flex: 1; min-width: 120px; color: var(--muted); font-size: 11px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.eco-path { flex: none; color: var(--muted); font-size: 10px; max-width: 240px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.eco-actions { flex: none; display: flex; gap: 6px; }
.mini { background: var(--panel2); color: var(--green-soft); border: 1px solid rgba(52,211,153,.35);
  border-radius: 5px; padding: 2px 8px; font-size: 11px; cursor: pointer; }
.mini:hover:not(:disabled) { background: var(--green-deep); }
.mini:disabled { opacity: .5; cursor: default; }
.eco-empty { color: var(--muted); font-size: 12px; padding: 4px 0; }
.mono { font-family: var(--mono); }
.eco-out { border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.eco-out-head { display: flex; justify-content: space-between; align-items: center;
  padding: 6px 10px; background: var(--panel2); font-size: 12px; color: var(--muted); }
.eco-out pre { white-space: pre-wrap; word-break: break-all; font-size: 11px; margin: 0;
  padding: 8px 10px; max-height: 200px; overflow-y: auto; background: rgba(0,0,0,.25);
  color: var(--green-soft); }
.skill-card { border: 1px solid rgba(52,211,153,.35); border-radius: 8px; padding: 10px 12px;
  background: rgba(14,59,46,.12); display: flex; flex-direction: column; gap: 8px; }
.skill-card h4 { font-size: 12px; color: var(--green-soft); letter-spacing: .5px; margin: 0; }
.skill-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.skill-input { flex: 1; min-width: 200px; background: var(--panel2); color: var(--fg);
  border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font-size: 12px; }
.skill-input:focus { outline: none; border-color: var(--green); }
.skill-input.skill-only { flex: .6; min-width: 160px; }
.skill-input.skill-name { flex: .6; min-width: 160px; }
.skill-msg { font-size: 12px; word-break: break-all; }
.skill-msg.ok { color: var(--ok); }
.skill-msg.bad { color: var(--danger); }
/* P7b ④：引擎区（扫描/草案/注册） */
.mini-sel { min-width: 96px; max-width: 110px; padding: 2px 6px; font-size: 11px; }
.cap { color: var(--green-soft); }
.draft-box { border: 1px solid rgba(52,211,153,.4); border-radius: 8px; padding: 10px 12px;
  background: rgba(14,59,46,.18); display: flex; flex-direction: column; gap: 8px; }
.draft-box h5 { font-size: 12px; color: var(--green-soft); margin: 0; }
.draft-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.draft-table td { padding: 4px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
.draft-param { font-weight: 600; color: var(--fg); white-space: nowrap; }
.draft-slot { color: var(--green-soft); white-space: nowrap; }
.draft-note { color: var(--muted); }
.draft-un { color: var(--danger); font-size: 11px; }
</style>
