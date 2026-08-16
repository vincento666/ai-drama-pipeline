<template>
  <div class="onboard">
    <div class="ob-head" @click="open = !open">
      <span class="ob-title">✨ AI 访谈 <span class="sub">一句话想法 → 追问 → 创作简报 → 一键生成</span></span>
      <span class="ob-right">
        <span v-if="hasBrief" class="badge-ok">✓ 已有创作简报</span>
        <span class="toggle">{{ open ? '▾ 收起' : '▸ 展开' }}</span>
      </span>
    </div>

    <div v-if="open" class="ob-body">
      <!-- 第一步：一句话想法 -->
      <template v-if="step === 'start'">
        <p v-if="hasBrief" class="hint warn">已有创作简报——重新访谈将覆盖项目里的 创作简报.md</p>
        <p v-else class="hint">没有小说素材也可以起步：说一句话想法，AI 追问几个关键问题后产出创作简报。</p>
        <textarea v-model="description" rows="2" class="ob-desc"
          placeholder="一句话想法，如：北宋镖局少东家卷入朝堂阴谋的复仇故事…"></textarea>
        <div class="ob-ops">
          <button class="primary" :disabled="busy || !description.trim()" @click="startInterview">
            {{ busy ? '提问生成中…' : (hasBrief ? '重新访谈' : '开始访谈') }}
          </button>
          <span class="rstatus" :class="errCls">{{ status }}</span>
        </div>
      </template>

      <!-- 第二步：追问（最多两轮） -->
      <template v-else-if="step === 'ask'">
        <p class="hint">第 {{ round }}/2 轮追问——回答越具体，简报越稳；也可以跳过直接出简报。</p>
        <div v-for="(qa, i) in answers" :key="'done' + i" class="qa done">
          <div class="q">Q{{ i + 1 }}：{{ qa.q }}</div>
          <div class="a">A：{{ qa.a || '（未答）' }}</div>
        </div>
        <div v-for="(q, i) in questions" :key="'q' + i" class="qa">
          <div class="q">Q{{ answers.length + i + 1 }}：{{ q }}</div>
          <input v-model="currentAnswers[i]" class="a-input" placeholder="你的回答…" />
        </div>
        <div class="ob-ops">
          <button class="primary" :disabled="busy" @click="submitAnswers">
            {{ busy ? '生成中…' : (round === 1 ? '提交，继续追问' : '提交并出简报') }}
          </button>
          <button class="ghost" :disabled="busy" @click="skipToBrief">跳过，直接出简报</button>
          <span class="rstatus" :class="errCls">{{ status }}</span>
        </div>
      </template>

      <!-- 第三步：创作简报（可编辑预览；内容由后端在生成时写入 创作简报.md） -->
      <template v-else>
        <p class="hint">创作简报已写入项目 创作简报.md，将作为后续编剧/分镜的一致性锚点。下方可编辑预览。</p>
        <textarea v-model="brief" rows="12" class="ob-brief mono" @input="briefDirty = true"></textarea>
        <p v-if="briefDirty" class="hint warn">已编辑（仅本地预览，未回写——暂无单独保存接口，一键生成仍用磁盘上的简报）</p>
        <div class="ob-ops">
          <button class="primary" :disabled="genBusy" @click="saveAndGenerate">保存简报并一键生成</button>
          <button class="ghost" @click="restart">重新访谈</button>
          <span class="rstatus" :class="errCls">{{ status }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
// AI 访谈（一站式生成第一步）：description → 最多两轮追问 → 创作简报
// 契约：POST /api/onboard/<项目> {description, answers:[{q,a}], want:'questions'|'brief'}
//   want=questions → {ok, questions:[str]}（同步返回，一轮 3-5 问）
//   want=brief     → {ok, brief, path}（后端已写入 创作简报.md）
// 已知边界：后端暂无「读取/回写简报」接口——存在性用 localStorage 标记（成功出简报后置位），
// 简报内容仅本次访谈会话内可见；预览区编辑不回写（见 dirty 提示）。
import { ref, computed, watch, inject, onMounted } from 'vue'
import { postOnboard } from '../api'

defineProps({ genBusy: { type: Boolean, default: false } })
const emit = defineEmits(['generate'])
const store = inject('store')

const open = ref(true)
const step = ref('start')        // start | ask | brief
const description = ref('')
const round = ref(1)
const questions = ref([])        // 当前轮追问
const currentAnswers = ref([])   // 当前轮各问的回答（输入中）
const answers = ref([])          // 累计已提交 [{q, a}]
const brief = ref('')
const briefDirty = ref(false)
const busy = ref(false)
const status = ref('')
const errCls = ref('')

const lsKey = computed(() => 'onboardBrief:' + store.project.value)
const hasBrief = computed(() => !!brief.value || !!localStorage.getItem(lsKey.value))
function markBriefed() { try { localStorage.setItem(lsKey.value, '1') } catch (e) { /* 隐私模式等忽略 */ } }

function restart() {
  step.value = 'start'; round.value = 1
  questions.value = []; currentAnswers.value = []; answers.value = []
  brief.value = ''; briefDirty.value = false; status.value = ''; errCls.value = ''
  // description 保留，便于在原想法上重新访谈
}

onMounted(() => { open.value = !localStorage.getItem(lsKey.value) })
watch(() => store.project.value, () => { restart(); open.value = !localStorage.getItem(lsKey.value) })

// 第一步：开始访谈 → 第一轮追问；模型未给出追问则直接出简报
async function startInterview() {
  answers.value = []
  busy.value = true; status.value = ''; errCls.value = ''
  let qs = null
  try {
    const r = await postOnboard(store.project.value,
      { description: description.value.trim(), answers: [], want: 'questions' })
    qs = r.questions || []
  } catch (e) { status.value = '访谈失败：' + e.message; errCls.value = 'err' }
  busy.value = false
  if (qs === null) return
  if (qs.length) {
    questions.value = qs
    currentAnswers.value = qs.map(() => '')
    round.value = 1
    step.value = 'ask'
  } else {
    await makeBrief()
  }
}

// 提交本轮回答：第一轮 → 带上全部问答再要一轮追问；第二轮（或模型不再追问）→ 出简报
async function submitAnswers() {
  questions.value.forEach((q, i) => answers.value.push({ q, a: (currentAnswers.value[i] || '').trim() }))
  if (round.value >= 2) { await makeBrief(); return }
  busy.value = true; status.value = ''; errCls.value = ''
  let qs = null
  try {
    const r = await postOnboard(store.project.value,
      { description: description.value.trim(), answers: answers.value, want: 'questions' })
    qs = r.questions || []
  } catch (e) { status.value = '追问失败：' + e.message; errCls.value = 'err' }
  busy.value = false
  if (qs === null) return
  if (qs.length) {
    questions.value = qs
    currentAnswers.value = qs.map(() => '')
    round.value = 2
  } else {
    await makeBrief()
  }
}

// 跳过追问，直接出简报（收进当前轮已填的回答）
function skipToBrief() {
  questions.value.forEach((q, i) => answers.value.push({ q, a: (currentAnswers.value[i] || '').trim() }))
  makeBrief()
}

// want=brief：后端生成并写入 创作简报.md
async function makeBrief() {
  busy.value = true; status.value = ''; errCls.value = ''
  try {
    const r = await postOnboard(store.project.value,
      { description: description.value.trim(), answers: answers.value, want: 'brief' })
    brief.value = r.brief || ''
    briefDirty.value = false
    markBriefed()
    step.value = 'brief'
    status.value = '创作简报已生成并写入项目'
  } catch (e) { status.value = '生成简报失败：' + e.message; errCls.value = 'err' }
  finally { busy.value = false }
}

// 「保存简报并一键生成」：简报已由后端落盘，这里触发现有一键 AI 编剧链路（ScriptPanel.runAll）
function saveAndGenerate() {
  emit('generate')
  status.value = '已触发一键 AI 编剧——进度与结果见下方编剧区'
  errCls.value = ''
}
</script>

<style scoped>
.onboard { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; margin: 8px 0 12px; }
.ob-head { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; cursor: pointer; }
.ob-title { font-size: 13px; font-weight: 600; }
.ob-title .sub { font-size: 12px; color: var(--muted); font-weight: 400; margin-left: 6px; }
.ob-right { display: flex; align-items: center; gap: 10px; }
.badge-ok { color: var(--ok); font-size: 12px; }
.toggle { color: var(--muted); font-size: 12px; }
.ob-body { padding: 0 12px 12px; }
.hint { color: var(--muted); font-size: 12px; margin: 4px 0 8px; }
.hint.warn { color: var(--warn); }
.ob-desc, .ob-brief { width: 100%; background: var(--panel2); color: var(--fg);
  border: 1px solid var(--line); border-radius: 8px; padding: 10px; font-size: 13px; line-height: 1.6; }
.ob-brief { font-family: var(--mono); }
.ob-desc:focus, .ob-brief:focus, .a-input:focus { border-color: var(--accent); outline: none; }
.qa { margin: 8px 0; }
.qa .q { font-size: 13px; margin-bottom: 4px; }
.qa.done { opacity: .65; }
.qa.done .a { font-size: 12px; color: var(--muted); }
.a-input { width: 100%; background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 7px 10px; font-size: 13px; }
.ob-ops { display: flex; gap: 8px; align-items: center; margin: 10px 0 2px; flex-wrap: wrap; }
.primary { background: var(--ok); color: #fff; border: none; border-radius: 6px; padding: 7px 14px;
  font-size: 13px; cursor: pointer; font-weight: 600; }
.primary:disabled { background: var(--line); color: var(--muted); font-weight: 400; }
.ghost { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); border-radius: 6px;
  padding: 7px 12px; font-size: 12px; cursor: pointer; }
.ghost:disabled { opacity: .5; cursor: default; }
.rstatus { font-size: 12px; color: var(--warn); }
.rstatus.err { color: var(--danger); }
</style>
