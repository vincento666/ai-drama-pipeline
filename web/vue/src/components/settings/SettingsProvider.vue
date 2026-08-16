<template>
  <div class="sp">
    <h3>① 本地 Model Provider</h3>
    <p class="hint">外部 harness agent 适配器设置（保存 → PUT /api/config-agent 写入 config.local.json，不修改 config.yaml）</p>

    <div class="sp-row top">
      <label>默认适配器
        <select v-model="form.default">
          <option v-for="n in adapterNames" :key="n" :value="n">{{ n }}</option>
        </select>
      </label>
      <label>最大委派轮数
        <input type="number" min="1" max="50" v-model.number="form.max_rounds" />
      </label>
      <label class="audit">
        <input type="checkbox" v-model="form.auditEnabled" /> Auditor 校验
      </label>
    </div>

    <div v-for="name in adapterNames" :key="name" class="adapter">
      <div class="adapter-head">
        <span class="adapter-name mono">{{ name }}</span>
        <button class="ghost" :disabled="testing === name" @click="test(name)">
          {{ testing === name ? '测试中…' : '测试连通' }}
        </button>
        <span v-if="results[name]" class="test-result" :class="results[name].ok ? 'ok' : 'bad'"
          :title="results[name].out">
          {{ results[name].ok ? '✓' : '✕' }} {{ results[name].out }}
        </span>
      </div>
      <div class="adapter-fields">
        <label>cmd <input v-model="form.adapters[name].cmd" class="mono" /></label>
        <label>args <input v-model="form.adapters[name].args" class="mono"
          placeholder="空格分隔，保存时转数组" /></label>
        <label>timeout(s) <input type="number" min="5" v-model.number="form.adapters[name].timeout" /></label>
        <label>skills_dir <input v-model="form.adapters[name].skills_dir" class="mono" /></label>
      </div>
    </div>

    <!-- P6c ①：生图 Provider（config image 段，OpenAI 兼容 images/generations） -->
    <div class="imgsec">
      <h4>生图 Provider（config.local.json 的 image 段）</h4>
      <p class="hint">对话「给角色C01生成参考图」/ 资产注入时使用；未配置则生图不可用。保存 → PUT /api/config-section（写 config.local.json，立即生效，出图时读取）。</p>
      <div class="img-fields">
        <label>provider
          <input v-model="imgForm.provider" class="mono" placeholder="展示用，如 siliconflow" /></label>
        <label>base
          <input v-model="imgForm.base" class="mono" placeholder="https://api.example.com/v1" /></label>
        <label>model
          <input v-model="imgForm.model" class="mono" placeholder="gpt-image-1 / flux-dev" /></label>
        <label>api_key
          <input v-model="imgForm.api_key" class="mono" type="password" placeholder="sk-xxx" /></label>
      </div>
      <div class="img-foot">
        <button class="primary" :disabled="savingImg" @click="saveImage">
          {{ savingImg ? '保存中…' : '保存生图配置' }}</button>
        <span class="hint">v1 仅保存：抽卡/出图时生效；连通性「测试」留待接入真实生图 API 后补充。</span>
        <span v-if="imgMsg" class="saved" :class="imgErr ? 'bad' : 'ok'">{{ imgMsg }}</span>
      </div>
    </div>

    <div class="sp-foot">
      <button class="primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存设置' }}</button>
      <span v-if="savedMsg" class="saved" :class="savedErr ? 'bad' : 'ok'">{{ savedMsg }}</span>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, computed, onMounted, inject } from 'vue'
import { getConfigAgent, putConfigAgent, testAdapter, getConfigSection, putConfigSection } from '../../api'

// 设置页子菜单①（docs/11 §6.1）：适配器列表编辑 + 测试连通 + 默认/轮数/Auditor + 保存。
// args 在 UI 以空格分隔字符串编辑，保存时 split 转数组（与 GET 归一化后的数组互转）。
// P6c ①：加「生图 Provider」区块（config image 段，PUT /api/config-section；v1 只保存不测试）。
const store = inject('store')
const FALLBACK_NAMES = ['kimi', 'codex', 'claude', 'dsh']

const form = reactive({
  default: 'kimi', max_rounds: 8, auditEnabled: true, adapters: {},
})
const imgForm = reactive({ provider: '', base: '', model: '', api_key: '' })
const adapterNames = computed(() => Object.keys(form.adapters).length ? Object.keys(form.adapters) : FALLBACK_NAMES)
const results = reactive({})
const testing = ref('')
const saving = ref(false)
const savedMsg = ref('')
const savedErr = ref(false)
const savingImg = ref(false)
const imgMsg = ref('')
const imgErr = ref(false)

// 适配器配置 → 表单（args 数组 → 空格字符串；缺失字段补默认）
function seedFromAgent(agent = {}) {
  form.default = agent.default || 'kimi'
  form.max_rounds = Number(agent.max_rounds) || 8
  form.auditEnabled = !!(agent.audit && agent.audit.enabled !== false)
  const ads = (agent.adapters && typeof agent.adapters === 'object') ? agent.adapters : {}
  for (const name of Object.keys(ads).length ? Object.keys(ads) : FALLBACK_NAMES) {
    const a = ads[name] || {}
    form.adapters[name] = {
      cmd: a.cmd || name,
      args: Array.isArray(a.args) ? (a.args || []).join(' ')
           : String(a.args || '').trim(),
      timeout: Number(a.timeout) || 1800,
      skills_dir: a.skills_dir || '',
    }
  }
}

async function load() {
  try {
    const r = await getConfigAgent()
    seedFromAgent(r.agent || {})
  } catch (e) { /* 桥不可达：保持默认表单 */ }
  try {
    const r = await getConfigSection('image')
    const v = r.value || {}
    imgForm.provider = v.provider || ''
    imgForm.base = v.base || ''
    imgForm.model = v.model || ''
    imgForm.api_key = v.api_key || ''
  } catch (e) { /* image 段未配置：保持空表单 */ }
}
onMounted(load)

async function test(name) {
  if (testing.value) return
  testing.value = name
  results[name] = { ok: false, out: '测试中…' }
  try {
    const r = await testAdapter(name)
    results[name] = { ok: !!r.ok, out: (r.output || (r.ok ? '连通' : '失败')).replace(/\s+/g, ' ').slice(0, 90) }
  } catch (e) {
    results[name] = { ok: false, out: e.message || '请求失败' }
  }
  testing.value = ''
}

async function save() {
  saving.value = true
  savedMsg.value = ''
  try {
    const adapters = {}
    for (const name of adapterNames.value) {
      const a = form.adapters[name]
      const argStr = String(a.args || '').trim()
      adapters[name] = {
        cmd: (a.cmd || name).trim(),
        args: argStr ? argStr.split(/\s+/) : [],
        timeout: Number(a.timeout) || 1800,
        skills_dir: String(a.skills_dir || '').trim(),
      }
    }
    const agent = {
      default: form.default,
      max_rounds: Number(form.max_rounds) || 8,
      audit: { enabled: !!form.auditEnabled },
      adapters,
    }
    await putConfigAgent(agent)
    savedMsg.value = '已保存（config.local.json）'
    savedErr.value = false
  } catch (e) {
    savedMsg.value = '保存失败: ' + (e.message || '')
    savedErr.value = true
  }
  saving.value = false
}

// 生图配置保存：PUT /api/config-section（image 段，深合并写 config.local.json，立即生效）
async function saveImage() {
  savingImg.value = true
  imgMsg.value = ''
  try {
    await putConfigSection('image', {
      provider: imgForm.provider.trim(),
      base: imgForm.base.trim(),
      model: imgForm.model.trim(),
      api_key: imgForm.api_key.trim(),
    })
    imgMsg.value = '已保存，抽卡/出图时生效'
    imgErr.value = false
  } catch (e) {
    imgMsg.value = '保存失败: ' + (e.message || '')
    imgErr.value = true
  }
  savingImg.value = false
}
</script>

<style scoped>
.sp { display: flex; flex-direction: column; gap: 14px; }
.sp h3 { margin-bottom: 2px; color: var(--green-soft); }
.sp-row { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.sp-row label { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; }
.sp-row input[type="number"] { width: 72px; }
.audit input { accent-color: var(--green); }
.sp input, .sp select {
  background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 8px; font-size: 13px;
}
.sp input:focus, .sp select:focus { outline: none; border-color: var(--green); }
.adapter { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
  background: rgba(14,59,46,.18); }
.adapter-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.adapter-name { font-weight: 700; color: var(--green); font-size: 13px; }
.ghost { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.ghost:hover:not(:disabled) { border-color: var(--green); color: var(--green-soft); }
.ghost:disabled { opacity: .5; cursor: default; }
.test-result { font-size: 11px; max-width: 46%; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.test-result.ok { color: var(--ok); }
.test-result.bad { color: var(--danger); }
.adapter-fields { display: grid; grid-template-columns: 1fr 2fr 1fr 1.4fr; gap: 8px; }
.adapter-fields label { display: flex; flex-direction: column; gap: 4px; color: var(--muted);
  font-size: 11px; min-width: 0; }
.adapter-fields input { width: 100%; font-size: 12px; padding: 4px 6px; }
.imgsec { border: 1px solid rgba(52,211,153,.35); border-radius: 8px; padding: 10px 12px;
  background: rgba(14,59,46,.12); display: flex; flex-direction: column; gap: 8px; }
.imgsec h4 { font-size: 12px; color: var(--green-soft); letter-spacing: .5px; margin: 0; }
.imgsec .hint { font-size: 11px; color: var(--muted); margin: 0; }
.img-fields { display: grid; grid-template-columns: 1fr 1.6fr 1.2fr 1.6fr; gap: 8px; }
.img-fields label { display: flex; flex-direction: column; gap: 4px; color: var(--muted);
  font-size: 11px; min-width: 0; }
.img-fields input { width: 100%; font-size: 12px; padding: 4px 6px; }
.img-foot { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.mono { font-family: var(--mono); }
.sp-foot { display: flex; align-items: center; gap: 12px; }
.primary { background: var(--green); color: #06281e; border: none; border-radius: 6px;
  padding: 7px 20px; font-size: 13px; font-weight: 600; cursor: pointer; }
.primary:hover:not(:disabled) { background: var(--green-soft); }
.primary:disabled { opacity: .6; cursor: default; }
.saved { font-size: 12px; }
.saved.ok { color: var(--ok); }
.saved.bad { color: var(--danger); }
</style>
