<template>
  <div class="wall">
    <div class="render-ctl">
      <!-- P6b：抽卡按钮 disabled = 分镜提示词未生成（硬前置，docs/12 §4 4e） -->
      <button @click="emit('render')" :disabled="rendering || !hasPrompt"
        :title="!hasPrompt ? '先生成分镜提示词' : ''">抽卡</button>
      <!-- P7a：参数收敛——仅候选数可选；时长由分镜行 dur 派生、质量走 config generate 段（docs/12 §5） -->
      <select :value="shots" @change="emit('update:shots', Number($event.target.value))">
        <option :value="1">1 候选</option><option :value="2">2 候选</option><option :value="3">3 候选</option>
      </select>
      <span class="hint">质量参数：由分镜卡（时长）+ config 默认生成；如需新参数请在分镜卡内新增</span>
    </div>
    <div class="rstatus" :class="{ warn: !hasPrompt }">
      {{ !hasPrompt ? '⚠ 先生成分镜提示词，再抽卡' : renderStatus }}
    </div>
    <div class="cmp-bar">
      <button class="mini" :class="{ on: cmpMode }" @click="emit('toggle-cmp')">{{ cmpMode ? '退出对比' : 'A/B 对比' }}</button>
      <span v-if="cmpMode" class="hint">点两个候选分别设为 A / B</span>
    </div>
    <div class="gallery">
      <!-- P6b：候选点击 → 播放试看（overlay 大图播放），选中 = 播放层内显式「确认选中」 -->
      <div v-for="f in files" :key="f.name" class="cand"
           :class="{ cmpA: cmp[0] === f.name, cmpB: cmp[1] === f.name }"
           @click="openPlay(f.name)">
        <video :src="`/video/${enc(project)}/${episode}/${f.name}`" muted loop preload="metadata" />
        <span class="play-badge">▶ 试看</span>
        <div class="cand-label">{{ f.name.replace(/\.mp4$/, '') }}
          <span v-if="review[f.name]" class="badge" :class="review[f.name].verdict">{{ verdictLabel(review[f.name].verdict) }}</span>
        </div>
      </div>
      <div v-if="!files.length" class="wall-empty">暂无候选，先抽卡</div>
    </div>

    <!-- 播放试看层（大图播放 controls autoplay loop；「确认选中」显式选片） -->
    <div v-if="playing" class="play-overlay" @click.self="playing = ''">
      <div class="play-box">
        <div class="play-head">
          <span class="mono">{{ playing.replace(/\.mp4$/, '') }}</span>
          <button class="x" title="关闭" @click="playing = ''">✕</button>
        </div>
        <video :src="`/video/${enc(project)}/${episode}/${playing}`" controls autoplay loop playsinline />
        <div class="play-foot">
          <input :value="note" @input="emit('update:note', $event.target.value)"
            placeholder="选中原因（供 Agent 复盘，可留空）" />
          <button class="primary" @click="confirmPlay">确认选中</button>
          <button class="ghost" @click="playing = ''">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, inject } from 'vue'
import { enc } from '../../api'

const props = defineProps({
  files: { type: Array, default: () => [] },
  review: { type: Object, default: () => ({}) },   // file → { verdict, ... }
  cmp: { type: Array, default: () => [] },
  cmpMode: { type: Boolean, default: false },
  rendering: { type: Boolean, default: false },
  renderStatus: { type: String, default: '' },
  hasPrompt: { type: Boolean, default: false },     // 分镜提示词已生成（抽卡硬前置）
  shots: { type: Number, default: 2 },
  note: { type: String, default: '' },
})
const emit = defineEmits(['render', 'cand-click', 'toggle-cmp', 'confirm',
  'update:shots', 'update:note'])

const store = inject('store')
const project = computed(() => store.project.value)
const episode = computed(() => store.episode.value)

// 播放试看层状态（点击候选 → 打开；「确认选中」→ emit('confirm', file)）
const playing = ref('')
function openPlay(file) {
  if (props.cmpMode) emit('cand-click', file)   // A/B 模式：点候选 = 设定 A/B
  else playing.value = file
}
function confirmPlay() {
  const f = playing.value
  playing.value = ''
  emit('confirm', f)
}

function verdictLabel(v) { return { ok: '通过', warn: '复核', reject: '废片' }[v] || v }
</script>

<style scoped>
.render-ctl { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; align-items: center; }
.render-ctl button { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 6px 12px; cursor: pointer; }
.render-ctl button:disabled { opacity: .4; cursor: default; }
.render-ctl select { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 4px 6px; }
.render-ctl .hint { font-size: 11px; color: var(--muted); }
.rstatus { font-size: 12px; color: var(--warn); margin-bottom: 4px; }
.rstatus.warn { color: var(--danger); }
.cmp-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.cmp-bar .mini { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.cmp-bar .mini.on { border-color: var(--accent); color: var(--accent); }
.gallery { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.wall-empty { width: 100%; border: 1px dashed var(--line); border-radius: 6px; padding: 14px 10px;
  text-align: center; color: var(--muted); font-size: 12px; }
.cand { position: relative; width: 120px; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; cursor: pointer; background: var(--panel2); }
.cand:hover { border-color: var(--accent); }
.cand video { width: 100%; height: 68px; object-fit: cover; display: block; background: #000; }
.play-badge { position: absolute; top: 4px; left: 4px; z-index: 1; background: rgba(0,0,0,.65);
  color: #fff; font-size: 10px; border-radius: 4px; padding: 1px 5px; pointer-events: none; }
.cand-label { font-size: 11px; color: var(--muted); padding: 2px 4px; text-align: center; }
.cand.cmpA { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.cand.cmpB { border-color: var(--warn); box-shadow: 0 0 0 1px var(--warn); }
.badge { display: inline-block; margin-left: 4px; padding: 0 5px; border-radius: 8px; font-size: 10px; line-height: 1.5; }
.badge.ok { background: rgba(89,201,125,.18); color: var(--ok); }
.badge.warn { background: rgba(255,180,84,.18); color: var(--warn); }
.badge.reject { background: rgba(255,107,107,.18); color: var(--danger); }

/* ---- 播放试看层 ---- */
.play-overlay { position: fixed; inset: 0; z-index: 200; background: rgba(8, 10, 14, .82);
  display: flex; align-items: center; justify-content: center; padding: 24px; }
.play-box { width: min(720px, 92vw); background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; overflow: hidden; box-shadow: 0 12px 40px rgba(0,0,0,.5); }
.play-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--line); }
.play-head .mono { flex: 1; color: var(--accent); font-size: 12px; }
.play-head .x { background: var(--panel2); color: var(--muted); border: 1px solid var(--line); border-radius: 6px;
  padding: 2px 8px; cursor: pointer; font-size: 12px; }
.play-head .x:hover { color: var(--fg); border-color: var(--accent); }
.play-box video { width: 100%; max-height: 62vh; background: #000; display: block; }
.play-foot { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--line); }
.play-foot input { flex: 1; background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 7px 10px; font-size: 12px; }
.play-foot button { border-radius: 6px; padding: 7px 16px; font-size: 12px; cursor: pointer; border: none; }
.play-foot .primary { background: var(--accent); color: #fff; }
.play-foot .ghost { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); }
</style>
