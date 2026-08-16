<template>
  <div class="panel art-panel">
    <h2>② 美术设定 <span class="sub">先锁定角色/场景/风格，再分镜</span></h2>
    <p class="hint">对标 RHSTORY 的「美术设定」：先定角色定妆照、场景图与整体视觉风格，
      分镜与抽卡时引用这些资产，保证跨镜头一致性（Ref2VA 参考图来源）。</p>

    <div class="style-bar">
      <span class="label">整体风格</span>
      <span class="style-text">{{ taste.style || '（未设置 → 在 config.yaml 的 project.style_prefix 配置）' }}</span>
      <span v-if="taste.defaults.frame" class="chip">默认景别 {{ taste.defaults.frame }}</span>
      <span v-if="taste.defaults.camera" class="chip">默认运镜 {{ taste.defaults.camera }}</span>
    </div>

    <!-- 上传/登记资产 -->
    <div class="upload-bar">
      <span class="label">新增资产</span>
      <select v-model="upType">
        <option value="C">角色 C</option><option value="S">场景 S</option>
        <option value="P">道具 P</option><option value="R">参考 R</option>
      </select>
      <input v-model="upCode" class="code" :placeholder="nextCode" />
      <input v-model="upName" class="name" placeholder="名称（如 林冲）" />
      <label class="file-btn">
        {{ upFile ? upFile.name : '选图片' }}
        <input type="file" accept="image/*" @change="onFile" hidden />
      </label>
      <button class="primary" :disabled="uploading" @click="upload">{{ uploading ? '上传中…' : '登记/上传' }}</button>
    </div>

    <section v-for="g in groups" :key="g.key" class="art-sec">
      <h3>{{ g.title }} <span class="count">{{ g.items.length }}</span></h3>
      <div v-if="!g.items.length" class="empty">暂无{{ g.type }}资产（用上方上传，或 CLI 登记）</div>
      <div class="asset-grid">
        <div v-for="a in g.items" :key="a.code" class="asset-card" :class="{ noimg: !a.image }">
          <button class="del" title="删除资产" @click.stop="removeAsset(a)">✕</button>
          <img v-if="a.image" :src="`/asset-img/${a.code}`" :alt="a.name" loading="lazy" />
          <div v-else class="placeholder">{{ a.code }}</div>
          <div class="asset-meta">
            <b>{{ a.code }}</b> <span class="nm">{{ a.name }}</span>
            <span v-if="a.bible" class="tag">圣经</span>
            <span v-if="a.image" class="tag ok">图</span>
          </div>
        </div>
      </div>
    </section>

    <div class="hint foot">
      角色圣经：<code>assets/bible/C01_林冲.md</code>（生成含该角色的镜头前必读，做一致性锚点）。
      有图资产可在分镜抽卡时选为 Ref2VA 参考图（人物一致性）。
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, inject } from 'vue'
import { api, deleteAsset } from '../api'

const store = inject('store')
const assets = ref([])
const taste = ref({ style: '', defaults: {}, avoid: [] })
const upType = ref('C')
const upCode = ref('')
const upName = ref('')
const upFile = ref(null)
const uploading = ref(false)

const GROUPS = [
  { key: 'C', title: '角色', type: '角色' },
  { key: 'S', title: '场景', type: '场景' },
  { key: 'P', title: '道具', type: '道具' },
  { key: 'R', title: '风格参考', type: '风格参考' },
]
const groups = computed(() => GROUPS.map(g => ({
  ...g, items: assets.value.filter(a => a.type === g.key),
})))
const nextCode = computed(() => {
  const codes = assets.value.filter(a => a.type === upType.value).map(a => parseInt(a.code.slice(1), 10))
  const n = (codes.length ? Math.max(...codes) : 0) + 1
  return upType.value + String(n).padStart(2, '0')
})

function onFile(e) { upFile.value = e.target.files[0] || null }

async function removeAsset(a) {
  if (!window.confirm(`确认删除资产 ${a.code} ${a.name}？登记痕迹与图片将一并移除。`)) return
  try {
    await deleteAsset(a.code)
    store.setStatus('资产已删除：' + a.code, 'ok')
    await load()
  } catch (e) { store.setStatus('删除失败: ' + e.message, 'err') }
}

async function upload() {
  if (!upName.value.trim() && !upFile.value) { store.setStatus('请填写名称或选择图片', 'err'); return }
  uploading.value = true
  try {
    let b64 = ''
    if (upFile.value) {
      b64 = await new Promise((res, rej) => {
        const r = new FileReader()
        r.onload = () => res(r.result)
        r.onerror = rej
        r.readAsDataURL(upFile.value)
      })
    }
    const code = upCode.value.trim().toUpperCase() || nextCode.value
    await api('/api/asset', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, name: upName.value.trim() || code, image: b64, ext: (upFile.value ? (upFile.value.name.split('.').pop() || 'png') : 'png') }) })
    upCode.value = ''; upName.value = ''; upFile.value = null
    store.setStatus('资产已登记：' + code, 'ok')
    await load()
  } catch (e) { store.setStatus('上传失败: ' + e.message, 'err') }
  uploading.value = false
}

async function load() {
  try {
    const [a, t] = await Promise.all([api('/api/assets'), api('/api/taste')])
    assets.value = a.assets || []
    taste.value = t
    store.assets = Object.fromEntries((a.assets || []).map(x => [x.code, x]))
    store.assetsWithImg.value = (a.assets || []).filter(x => x.image)   // 同步资产条/检查器
  } catch (e) { store.setStatus('美术设定加载失败: ' + e.message, 'err') }
}

onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.art-panel { max-width: 1080px; }
.sub { font-size: 12px; color: var(--muted); font-weight: 400; text-transform: none; letter-spacing: 0; }
.style-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: var(--panel2); border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; }
.style-bar .label { color: var(--muted); font-size: 13px; }
.style-text { color: var(--accent); font-size: 13px; }
.chip { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 1px 10px; font-size: 12px; color: var(--muted); }

.upload-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  background: var(--panel); border: 1px dashed var(--line); border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; }
.upload-bar .label { color: var(--muted); font-size: 13px; }
.upload-bar select, .upload-bar input { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; font-size: 13px; }
.upload-bar .code { width: 70px; font-family: var(--mono); }
.upload-bar .name { width: 140px; }
.file-btn { background: var(--panel2); color: var(--fg); border: 1px solid var(--line); border-radius: 6px;
  padding: 6px 12px; cursor: pointer; font-size: 12px; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.upload-bar .primary { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 7px 14px; cursor: pointer; font-size: 13px; }
.upload-bar .primary:disabled { background: var(--line); }

.art-sec { margin-bottom: 18px; }
.art-sec h3 { display: flex; align-items: center; gap: 8px; }
.count { background: var(--panel2); color: var(--muted); border-radius: 10px; padding: 0 8px; font-size: 11px; }
.empty { color: var(--muted); font-size: 13px; padding: 8px 0; }
.asset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
.asset-card { background: var(--panel2); border: 1px solid var(--line); border-radius: 8px; overflow: hidden;
  position: relative; }
.asset-card .del { position: absolute; top: 4px; right: 4px; z-index: 2; width: 22px; height: 22px;
  border: none; border-radius: 6px; background: rgba(30,33,40,.85); color: var(--muted);
  cursor: pointer; font-size: 11px; line-height: 1; opacity: 0; transition: opacity .12s; }
.asset-card:hover .del { opacity: 1; }
.asset-card .del:hover { color: var(--danger); }
.asset-card img { width: 100%; height: 150px; object-fit: cover; display: block; background: #000; }
.asset-card .placeholder { width: 100%; height: 150px; display: flex; align-items: center; justify-content: center; color: var(--muted); background: var(--panel); font-family: var(--mono); }
.asset-meta { padding: 6px 8px; font-size: 12px; display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.asset-meta b { color: var(--accent); font-family: var(--mono); }
.asset-meta .nm { color: var(--fg); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag { font-size: 10px; padding: 0 6px; border-radius: 8px; background: var(--panel); color: var(--muted); }
.tag.ok { color: var(--ok); }
.foot { margin-top: 14px; }
code { font-family: var(--mono); background: var(--panel2); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
</style>
