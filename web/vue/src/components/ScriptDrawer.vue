<template>
  <div v-if="open" class="drawer-mask" @click.self="emit('close')">
    <aside class="drawer-l">
      <div class="drawer-head">
        <h2>剧本 <span class="sub">访谈 → 小说 → 事件 → 骨架 → 剧本 → 资产</span></h2>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>
      <div class="drawer-body">
        <OnboardPanel :gen-busy="!!(sp && sp.busy)" @generate="onGenerate" />
        <ScriptPanel ref="sp" />
      </div>
    </aside>
  </div>
</template>

<script setup>
// 剧本侧板（左抽屉）：顶部 OnboardPanel（AI 访谈）+ ScriptPanel 原逻辑（AI 编剧/分步/保存小说全部保留）
// 「保存简报并一键生成」经 ref 调 ScriptPanel.runAll，复用现有一键编剧链路（含轮询与状态展示）
import { ref } from 'vue'
import ScriptPanel from './ScriptPanel.vue'
import OnboardPanel from './OnboardPanel.vue'

defineProps({ open: Boolean })
const emit = defineEmits(['close'])

const sp = ref(null)
function onGenerate() { sp.value?.runAll() }
</script>

<style scoped>
.drawer-mask { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 40;
  display: flex; justify-content: flex-start; }
.drawer-l { width: min(860px, 62vw); background: var(--bg); border-right: 1px solid var(--line);
  display: flex; flex-direction: column; box-shadow: 8px 0 24px rgba(0,0,0,.35); }
.drawer-head { display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; background: var(--panel); border-bottom: 1px solid var(--line); flex: none; }
.drawer-head h2 { font-size: 15px; }
.sub { font-size: 12px; color: var(--muted); font-weight: 400; }
.close-btn { background: var(--panel2); color: var(--muted); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 13px; }
.close-btn:hover { color: var(--fg); border-color: var(--accent); }
.drawer-body { flex: 1; overflow-y: auto; padding: 4px 10px 14px; }
</style>
