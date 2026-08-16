<template>
  <nav class="stage-nav">
    <div v-for="(v, i) in VIEWS" :key="v.key" class="sn-row" :class="{ on: store.view.value === v.key }"
      :title="'切换到' + v.label" @click="store.view.value = v.key">
      <span class="sn-dot" :class="dotOf(v.key)"></span>
      <span class="sn-label">{{ i + 1 }} {{ v.label }}</span>
      <span class="sn-sum">{{ store.laneSummaries.value[v.key] || '' }}</span>
    </div>
  </nav>
</template>

<script setup>
import { inject } from 'vue'
import { VIEWS, dotClassOf } from '../store'

// 右栏阶段导航锚点（spec 11 §5-1）：4 项，点击切换中栏视图；状态点 灰=未开始 / 蓝=进行中 / 绿=完成。
// 吸收原 PlanFlow 的状态职责（stageStates 推导），PlanFlow.vue 已删除。
const store = inject('store')

function dotOf(key) {
  return dotClassOf(store.stageStates.value[key] || 'none')
}
</script>

<style scoped>
.stage-nav { flex: none; padding: 10px 12px; border-bottom: 1px solid var(--line);
  background: var(--panel); }
.sn-row { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px;
  cursor: pointer; font-size: 13px; }
.sn-row:hover { background: var(--panel2); }
.sn-row.on { background: var(--green-deep); box-shadow: inset 2px 0 0 var(--green); }
.sn-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.sn-dot.none { background: var(--muted); }        /* 未开始 灰 */
.sn-dot.active { background: var(--accent); box-shadow: 0 0 0 2px rgba(79,140,255,.25); }  /* 进行中 蓝 */
.sn-dot.done { background: var(--green); box-shadow: 0 0 0 2px rgba(52,211,153,.25); }     /* 完成 绿 */
.sn-label { font-weight: 600; color: var(--fg); }
.sn-row.on .sn-label { color: var(--green-soft); }
.sn-sum { margin-left: auto; color: var(--muted); font-size: 11px; max-width: 52%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sn-row.on .sn-sum { color: rgba(167,243,208,.7); }
</style>
