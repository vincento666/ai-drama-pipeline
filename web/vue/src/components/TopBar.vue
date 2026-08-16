<template>
  <header class="topbar">
    <button class="brand" title="回到剧本视图" @click="store.view.value = 'script'">
      AI 短剧流水线
    </button>
    <label>项目
      <select :value="store.project.value" @change="onProject">
        <option v-for="p in store.projects.value" :key="p" :value="p">{{ p }}</option>
      </select>
    </label>
    <label>集
      <select :value="store.episode.value" @change="onEpisode">
        <option v-for="n in store.episodes.value" :key="n" :value="n">E{{ String(n).padStart(2, '0') }}</option>
      </select>
    </label>
    <span class="spacer" />
    <!-- 保存：仅 dirty 时显示（全局唯一保存入口，保存分镜） -->
    <button v-if="store.dirty.value" class="primary save" @click="store.saveBoard()">保存</button>
    <!-- ⚙ 设置：P4 实现（打开 SettingsDialog 三子菜单，docs/11 §6） -->
    <button class="ghost gear" title="设置（本地 Provider / 外部 Harness / 运行设置）" @click="onSettings">⚙</button>
  </header>
</template>

<script setup>
// 极简顶栏（spec 11 §2）：品牌（点击回剧本视图）+ 项目/集 + 保存（仅 dirty）+ ⚙ 设置占位。
// 删除：锚点导航、剧本/Agent/任务队列按钮、状态文字（→ 右栏 StatusPanel）。
import { inject } from 'vue'

const store = inject('store')

function onProject(e) {
  store.project.value = e.target.value
  store.onProjectChange()
}
function onEpisode(e) {
  store.episode.value = Number(e.target.value)
  store.onEpisodeChange()
}
function onSettings() {
  store.settingsOpen.value = true
}
</script>

<style scoped>
.topbar { display: flex; align-items: center; gap: 14px; padding: 8px 16px;
  background: var(--panel); border-bottom: 1px solid var(--line); }
.brand { background: none; border: none; cursor: pointer; font-size: 14px; font-weight: 700;
  color: var(--green); letter-spacing: .5px; padding: 0; }
.brand:hover { color: var(--green-soft); }
.topbar label { color: var(--muted); display: flex; align-items: center; gap: 6px; font-size: 13px; }
.topbar select { background: var(--panel2); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 8px; min-width: 110px; font-size: 13px; }
.spacer { flex: 1; }
.save { background: var(--green); color: #06281e; border: none; border-radius: 6px;
  padding: 6px 18px; font-size: 13px; font-weight: 600; cursor: pointer; }
.save:hover { background: var(--green-soft); }
.gear { background: var(--panel2); color: var(--muted); border: 1px solid var(--line);
  border-radius: 6px; width: 32px; height: 32px; cursor: pointer; font-size: 14px; }
.gear:hover { color: var(--fg); border-color: var(--green); }
</style>
