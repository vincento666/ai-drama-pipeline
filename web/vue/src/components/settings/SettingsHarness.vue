<template>
  <div class="sh">
    <h3>② 外部 Harness Agent</h3>
    <p class="hint">LHH 官方仓库（vendor/longhorizon-harness submodule）自动检测：GET /api/config-agent → lhh</p>

    <div class="lhh-card" :class="lhh.available ? 'ok' : 'bad'">
      <div class="lhh-row">
        <span class="k">可用</span>
        <span class="v">
          <span class="mark" :class="lhh.available ? 'ok' : 'bad'">{{ lhh.available ? '✓' : '✗' }}</span>
          {{ lhh.available ? 'LHH 官方包已加载（' + (lhh.source || '') + '）' : (lhh.error || '未安装') }}
        </span>
      </div>
      <div class="lhh-row"><span class="k">来源</span><span class="v mono">{{ lhh.source || '—' }}</span></div>
      <div class="lhh-row"><span class="k">版本</span><span class="v mono">{{ lhh.version || '—' }}</span></div>
      <div class="lhh-row"><span class="k">dsh CLI</span>
        <span class="v">{{ lhh.dsh_cli ? '可用 ✓' : '不可用 ✗' }}</span></div>
      <div class="lhh-row"><span class="k">Windows 主循环</span><span class="v">{{ lhh.win_loop || '—' }}</span></div>
      <div class="lhh-row"><span class="k">同步</span><span class="v">{{ lhh.sync || '—' }}</span></div>
      <div class="lhh-row"><span class="k">复用组件</span>
        <span class="v">{{ (lhh.reused || []).join('、') || '—' }}</span></div>
    </div>

    <div class="sh-actions">
      <button class="ghost" :disabled="loading" @click="load">{{ loading ? '检测中…' : '重新检测' }}</button>
      <button class="ghost" :disabled="testing" @click="test">
        {{ testing ? '测试中…' : '可调用性测试' }}</button>
      <span class="hint test-hint">可调用性测试 = 无 adapter 名整体检测（lhh_status + 默认适配器）</span>
    </div>
    <div v-if="testOut" class="test-out mono" :class="testOk ? 'ok' : 'bad'">{{ testOut }}</div>

    <div v-if="!lhh.available" class="guide">
      <h4>安装 / 同步指引</h4>
      <p class="hint">LHH 官方仓库以 git submodule 挂载在 vendor/longhorizon-harness（纯逻辑复用，接口不变即同步）：</p>
      <pre class="mono">git submodule update --remote vendor/longhorizon-harness</pre>
      <p class="hint">或 <span class="mono">pip install lh-harness</span>（Windows 主循环由本项目 stdlib run_loop 驱动）</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { getConfigAgent, testAdapter } from '../../api'

// 设置页子菜单②（docs/11 §6.2）：LHH 自动检测结果 + 重新检测 + 可调用性测试 + 未安装指引。
const store = inject('store')
const lhh = ref({})
const loading = ref(false)
const testing = ref(false)
const testOut = ref('')
const testOk = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await getConfigAgent()
    lhh.value = r.lhh || {}
  } catch (e) { /* 桥不可达：保留旧结果 */ }
  loading.value = false
}
onMounted(load)

async function test() {
  if (testing.value) return
  testing.value = true
  testOut.value = ''
  try {
    const r = await testAdapter('')
    testOk.value = !!r.ok
    testOut.value = (r.output || (r.ok ? 'harness 可用' : 'harness 不可用')).slice(0, 500)
  } catch (e) {
    testOk.value = false
    testOut.value = '请求失败: ' + (e.message || '')
  }
  testing.value = false
}
</script>

<style scoped>
.sh { display: flex; flex-direction: column; gap: 14px; }
.sh h3 { margin-bottom: 2px; color: var(--green-soft); }
.lhh-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
  background: var(--panel2); }
.lhh-card.ok { border-color: rgba(52,211,153,.4); }
.lhh-card.bad { border-color: rgba(255,107,107,.4); }
.lhh-row { display: flex; gap: 10px; padding: 4px 0; font-size: 12px; align-items: baseline; }
.lhh-row .k { flex: none; width: 110px; color: var(--muted); }
.lhh-row .v { flex: 1; color: var(--fg); line-height: 1.6; }
.mark { font-weight: 700; margin-right: 4px; }
.mark.ok { color: var(--ok); }
.mark.bad { color: var(--danger); }
.mono { font-family: var(--mono); }
.sh-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ghost { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 12px; font-size: 12px; cursor: pointer; }
.ghost:hover:not(:disabled) { border-color: var(--green); color: var(--green-soft); }
.ghost:disabled { opacity: .5; cursor: default; }
.test-hint { flex-basis: 100%; }
.test-out { white-space: pre-wrap; word-break: break-all; font-size: 11px;
  border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px;
  background: rgba(0,0,0,.25); max-height: 180px; overflow-y: auto; }
.test-out.ok { color: var(--ok); border-color: rgba(52,211,153,.4); }
.test-out.bad { color: var(--danger); border-color: rgba(255,107,107,.4); }
.guide { border: 1px dashed var(--warn); border-radius: 8px; padding: 10px 12px; }
.guide h4 { font-size: 12px; color: var(--warn); margin-bottom: 6px; }
.guide pre { background: rgba(0,0,0,.3); border: 1px solid var(--line); border-radius: 6px;
  padding: 8px 10px; margin: 6px 0; font-size: 12px; overflow-x: auto; color: var(--green-soft); }
</style>
