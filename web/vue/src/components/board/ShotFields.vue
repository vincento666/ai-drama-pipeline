<template>
  <div class="shot-fields">
    <div class="card-fields">
      <label>景别
        <select v-model="row.frame" @change="emit('dirty')">
          <option v-for="v in vocab.frames" :key="v" :value="v">{{ v }}</option>
        </select>
      </label>
      <label>运镜
        <select v-model="row.camera" @change="emit('dirty')">
          <option v-for="v in vocab.cameras" :key="v" :value="v">{{ v }}</option>
        </select>
      </label>
      <label>时长
        <input v-model="row.dur" @input="emit('dirty')" class="dur" />s
      </label>
    </div>
    <div class="card-fields">
      <label>角色
        <input v-model="row.chars" @input="emit('dirty')" :class="{ bad: badCodes(row.chars).length }" placeholder="C01" />
      </label>
      <label>场景
        <input v-model="row.scene" @input="emit('dirty')" placeholder="S01" />
      </label>
      <label>灯光
        <input v-model="row.light" @input="emit('dirty')" placeholder="golden hour" />
      </label>
    </div>
    <label class="f1">对白/音效
      <input v-model="row.dialogue" @input="emit('dirty')" placeholder="对白：这里发生了什么" />
    </label>
  </div>
</template>

<script setup>
import { inject } from 'vue'

// 分镜 9 字段编辑区（镜号/备注在卡头），网格 ShotCard 与检查器 shot 态共用
defineProps({
  row: { type: Object, required: true },   // 直接就地编辑 store.boardRows 元素（沿用原行为）
  vocab: { type: Object, default: () => ({ frames: [], cameras: [] }) },
})
const emit = defineEmits(['dirty'])

const store = inject('store')

function badCodes(chars) {
  return (chars || '').split(',').map(c => c.trim())
    .filter(c => /^[CSPR]\d{2}$/.test(c) && !(c in (store.assets || {})))
}
</script>

<style scoped>
.card-fields { display: flex; gap: 6px; margin-bottom: 6px; }
.card-fields label { flex: 1; display: flex; flex-direction: column; font-size: 11px; color: var(--muted); gap: 2px; }
.card-fields select, .card-fields input, .f1 input { background: var(--panel); color: var(--fg);
  border: 1px solid var(--line); border-radius: 6px; padding: 5px 7px; font-size: 13px; width: 100%; }
.card-fields .dur { width: 56px; }
.f1 { display: flex; flex-direction: column; font-size: 11px; color: var(--muted); gap: 2px; }
.f1 input { flex: 1; }
input.bad { color: var(--danger); border-color: var(--danger) !important; }
</style>
