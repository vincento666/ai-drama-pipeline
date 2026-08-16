<template>
  <!-- P6b：分镜提示词面板（原 ShotRefPanel 改名/重构，docs/12 §4）——
       展示 refs/<shot>.prompt.md（GET shot-ref 的 prompt）+ 生成/刷新 + 镜内参考图缩略（选片首帧晋升保留）。
       P7a：参考图收敛为只读——自动关联该镜 chars/scene 资产（refAsset 由 ShotInspector 解析传入），
       不再提供手动下拉选择。提示词为空 → 抽卡按钮禁用（父组件 CandidateWall hasPrompt 联动）。 -->
  <section class="prompt-panel">
    <div class="pp-head">
      <h3>分镜提示词 · Shot {{ shot }}</h3>
      <button class="mini" :disabled="busy" @click="emit('refresh')">
        {{ busy ? '生成中…' : (data.prompt ? '刷新提示词' : '生成提示词') }}
      </button>
    </div>
    <pre class="mono box">{{ data.prompt || '（暂无提示词——点「生成提示词」；提示词为抽卡前置产物，未生成不可抽卡）' }}</pre>

    <!-- P7a：参考图（自动关联，只读）——由该镜角色/场景资产自动解析，唯一路径，不再手动选择 -->
    <div class="pp-ref-asset">
      <div class="pp-ref-label">参考图（自动关联）<span class="hint">由该镜角色/场景资产自动关联</span></div>
      <template v-if="refAsset && refAsset.image">
        <img class="ref-thumb" :src="`/asset-img/${refAsset.code}`" :alt="refAsset.name" />
        <span class="ref-meta"><b>{{ refAsset.code }}</b> {{ refAsset.name }}</span>
      </template>
      <div v-else class="ref-empty">该镜无关联资产图（角色/场景未登记带图资产，可不选参考图）</div>
    </div>

    <div v-if="data.image" class="pp-ref">
      <div class="pp-ref-label">镜内参考图<span class="hint">选片后以该片首帧晋升</span></div>
      <img class="ref-img" :src="imgSrc" :alt="`shot_${String(data.shot || 0).padStart(2, '0')} 参考图`" />
    </div>
    <div v-else class="ref-empty">尚无镜内参考图 <span class="hint">（选片后自动以该片首帧晋升为参考图）</span></div>
  </section>
</template>

<script setup>
import { computed, inject } from 'vue'
import { enc } from '../../api'

const props = defineProps({
  shot: { type: Number, default: 1 },               // 镜号（1-based，仅展示于标题）
  data: { type: Object, default: () => ({ shot: 0, prompt: '', image: null }) },
  busy: { type: Boolean, default: false },
  // P7a：自动关联的参考图资产（{code,name,image} | null）——ShotInspector 由 autoRefCode 解析
  refAsset: { type: Object, default: null },
})
const emit = defineEmits(['refresh'])

const store = inject('store')
// 图片静态文件：GET /refs/<project>/<episode>/<file>（E<n>/refs/ 下）
const imgSrc = computed(() => `/refs/${enc(store.project.value)}/${store.episode.value}/${props.data.image}`)
</script>

<style scoped>
.prompt-panel { margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
.pp-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.pp-head h3 { margin-bottom: 0; }
.mini { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.mini:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.mini:disabled { opacity: .4; cursor: default; }
.box { background: var(--panel2); border: 1px solid var(--line); border-radius: 6px; padding: 8px;
  white-space: pre-wrap; word-break: break-all; max-height: 150px; overflow-y: auto; margin-bottom: 8px; }
.pp-ref-asset, .pp-ref { margin-bottom: 8px; }
.pp-ref-label { font-size: 11px; color: var(--muted); margin-bottom: 4px; display: flex; align-items: baseline; gap: 6px; }
.pp-ref-label .hint { font-size: 10px; }
.ref-thumb { width: 64px; height: 64px; object-fit: cover; border-radius: 6px;
  border: 1px solid var(--line); display: inline-block; vertical-align: middle; background: #000; }
.ref-meta { margin-left: 8px; font-size: 12px; color: var(--fg); vertical-align: middle; }
.ref-meta b { color: var(--accent); }
.ref-img { width: 100%; border-radius: 6px; border: 1px solid var(--line); display: block; background: #000; }
.ref-empty { border: 1px dashed var(--line); border-radius: 6px; padding: 10px 8px;
  color: var(--muted); font-size: 12px; }
.ref-empty .hint { font-size: 10px; }
</style>
