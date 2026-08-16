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
      <!-- P6b：角色 = C 类资产下拉（多选逗号分隔，存储保持代号列表字符串）；自由输入兜底 -->
      <label>角色
        <template v-if="cAssets.length">
          <select :value="''" @change="onAddChar($event)">
            <option value="" disabled>＋ 添加角色（资产）…</option>
            <option v-for="a in cAssets" :key="a.code" :value="a.code">{{ a.code }} {{ a.name }}</option>
            <option value="__custom__">＋ 自定义…</option>
          </select>
        </template>
        <span v-else class="asset-empty" title="前往「美术·资产」登记角色" @click="goArt">暂无角色资产——去「美术·资产」登记 →</span>
        <div v-if="charList.length" class="chips">
          <span v-for="c in charList" :key="c" class="chip" :title="charName(c)">
            {{ charName(c) }}<button class="chip-x" title="移除" @click="removeChar(c)">✕</button>
          </span>
        </div>
        <input v-if="charCustom" v-model="charCustomText" @input="emit('dirty')"
          @keydown.enter="commitCharCustom" @blur="commitCharCustom"
          placeholder="输入资产代号或自由文本，回车确认" class="custom-in" />
      </label>
      <!-- P6b：场景 = S 类资产下拉（单选）；自由输入兜底 -->
      <label>场景
        <template v-if="sAssets.length">
          <select :value="row.scene" @change="onScene($event)">
            <option value="" disabled>选择场景（资产）…</option>
            <option v-for="a in sAssets" :key="a.code" :value="a.code">{{ a.code }} {{ a.name }}</option>
            <option value="__custom__">＋ 自定义…</option>
          </select>
        </template>
        <span v-else class="asset-empty" title="前往「美术·资产」登记场景" @click="goArt">暂无场景资产——去「美术·资产」登记 →</span>
        <input v-if="sceneCustom" v-model="sceneCustomText" @input="emit('dirty')"
          @keydown.enter="commitSceneCustom" @blur="commitSceneCustom"
          placeholder="输入资产代号或自由文本，回车确认" class="custom-in" />
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
import { ref, computed, inject } from 'vue'

// 分镜 9 字段编辑区（镜号/备注在卡头），检查器 shot 态使用（P6b：网格卡已只读摘要化，不再内嵌编辑）。
// 角色/场景 = 资产下拉（C/S 类，代号+名称），含「自定义…」自由输入兜底；存储格式保持现状
// （chars="C01,C02" 逗号分隔代号列表、scene="S01" 代号），与后端分镜行契约零改动。
const props = defineProps({
  row: { type: Object, required: true },   // 直接就地编辑 store.boardRows 元素（沿用原行为）
  vocab: { type: Object, default: () => ({ frames: [], cameras: [] }) },
})
const emit = defineEmits(['dirty'])

const store = inject('store')

// P7a：「添加素材」入口——无资产时点击提示文案直接切到 美术·资产 视图（文案引导，不新做页面）
function goArt() { if (store.view) store.view.value = 'art' }

// store.assets 为纯对象（非响应式），借用 assetsWithImg（响应式，资产重载时更新）做联动触发
const cAssets = computed(() => {
  void store.assetsWithImg.value
  return Object.values(store.assets).filter(a => a.type === 'C').sort((x, y) => (x.code < y.code ? -1 : 1))
})
const sAssets = computed(() => {
  void store.assetsWithImg.value
  return Object.values(store.assets).filter(a => a.type === 'S').sort((x, y) => (x.code < y.code ? -1 : 1))
})

// ---- 角色：多选（逗号分隔代号列表） ----
const charList = computed(() => (props.row.chars || '').split(',').map(s => s.trim()).filter(Boolean))
function charName(c) {
  const a = store.assets[c]
  return a ? `${a.code} ${a.name}` : c
}
const charCustom = ref(false)
const charCustomText = ref('')
function onAddChar(e) {
  const v = e.target.value
  if (v === '__custom__') { charCustom.value = true; return }
  if (v && !charList.value.includes(v)) props.row.chars = [...charList.value, v].join(',')
  emit('dirty')
}
function removeChar(c) {
  props.row.chars = charList.value.filter(x => x !== c).join(',')
  emit('dirty')
}
function commitCharCustom() {
  const v = charCustomText.value.trim()
  if (v && !charList.value.includes(v)) props.row.chars = [...charList.value, v].join(',')
  charCustom.value = false; charCustomText.value = ''
  emit('dirty')
}

// ---- 场景：单选 ----
const sceneCustom = ref(false)
const sceneCustomText = ref('')
function onScene(e) {
  const v = e.target.value
  if (v === '__custom__') { sceneCustom.value = true; return }
  props.row.scene = v
  emit('dirty')
}
function commitSceneCustom() {
  const v = sceneCustomText.value.trim()
  if (v) props.row.scene = v
  sceneCustom.value = false; sceneCustomText.value = ''
  emit('dirty')
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
.asset-empty { font-size: 11px; color: var(--warn); line-height: 1.5; padding: 2px 0; }
.asset-empty { cursor: pointer; text-decoration: underline dotted; }
.asset-empty:hover { color: var(--accent); }
.chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px; }
.chip { display: inline-flex; align-items: center; gap: 3px; background: rgba(79,140,255,.14);
  border: 1px solid rgba(79,140,255,.4); color: var(--accent); border-radius: 10px;
  padding: 1px 4px 1px 7px; font-size: 11px; }
.chip-x { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 10px; padding: 0 2px; }
.chip-x:hover { color: var(--danger); }
.custom-in { margin-top: 2px; }
</style>
