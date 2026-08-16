<template>
  <div v-if="store.settingsOpen.value" class="settings-overlay" @click.self="close">
    <div class="settings-dialog" role="dialog" aria-modal="true" aria-label="设置">
      <header class="dialog-head">
        <span class="dialog-title">⚙ 设置</span>
        <span class="dialog-sub">全局唯一设置入口（docs/11 §6）</span>
        <button class="dialog-close" title="关闭（Esc）" @click="close">✕</button>
      </header>
      <div class="dialog-body">
        <nav class="settings-nav">
          <button v-for="t in TABS" :key="t.key" class="nav-item"
            :class="{ active: tab === t.key }" @click="tab = t.key">
            {{ t.label }}
          </button>
        </nav>
        <div class="settings-content">
          <SettingsProvider v-if="tab === 'provider'" />
          <SettingsHarness v-else-if="tab === 'harness'" />
          <SettingsRuntime v-else />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onBeforeUnmount, inject } from 'vue'
import SettingsProvider from './settings/SettingsProvider.vue'
import SettingsHarness from './settings/SettingsHarness.vue'
import SettingsRuntime from './settings/SettingsRuntime.vue'

// P4 设置页（docs/11 §6）：全屏遮罩居中对话框（720px，暗夜绿主题），左侧 3 子菜单导航，
// 右侧内容区由子组件承载（v-if 切换）。关闭：右上 ✕ / 点遮罩 / Esc。
const store = inject('store')
const TABS = [
  { key: 'provider', label: '① 本地 Model Provider' },
  { key: 'harness', label: '② 外部 Harness Agent' },
  { key: 'runtime', label: '③ Harness 运行设置' },
]
const tab = ref('provider')

function close() { store.settingsOpen.value = false }

function onKey(e) {
  if (e.key === 'Escape' && store.settingsOpen.value) close()
}
watch(() => store.settingsOpen.value, (open) => {
  if (open) { tab.value = 'provider'; window.addEventListener('keydown', onKey) }
  else window.removeEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.settings-overlay { position: fixed; inset: 0; z-index: 200;
  background: rgba(6, 14, 11, .72); backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center; }
.settings-dialog { width: 720px; max-width: 94vw; max-height: 84vh;
  display: flex; flex-direction: column; overflow: hidden;
  background: var(--panel); border: 1px solid rgba(52,211,153,.45);
  border-radius: 12px; box-shadow: 0 18px 60px rgba(0,0,0,.55); }
.dialog-head { flex: none; display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; background: var(--green-deep); border-bottom: 1px solid rgba(52,211,153,.3); }
.dialog-title { font-size: 14px; font-weight: 700; color: var(--green-soft); letter-spacing: .5px; }
.dialog-sub { font-size: 11px; color: var(--muted); }
.dialog-close { margin-left: auto; background: none; border: 1px solid var(--line);
  color: var(--muted); border-radius: 6px; width: 26px; height: 26px; cursor: pointer;
  font-size: 12px; }
.dialog-close:hover { color: var(--fg); border-color: var(--green); }
.dialog-body { flex: 1; min-height: 0; display: flex; }
.settings-nav { flex: none; width: 168px; display: flex; flex-direction: column; gap: 4px;
  padding: 12px 8px; background: var(--green-deep-2); border-right: 1px solid var(--line);
  overflow-y: auto; }
.nav-item { text-align: left; background: none; border: 1px solid transparent; border-radius: 6px;
  padding: 8px 10px; font-size: 12px; color: var(--muted); cursor: pointer; line-height: 1.5; }
.nav-item:hover { color: var(--fg); background: rgba(52,211,153,.08); }
.nav-item.active { color: var(--green-soft); background: rgba(52,211,153,.14);
  border-color: rgba(52,211,153,.4); }
.settings-content { flex: 1; min-width: 0; padding: 14px 16px; overflow-y: auto; }
</style>
