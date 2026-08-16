# KIMI-BRIEF · 前端联调简报（Kimi K3-256k ↔ DSH 后端协同开发）

> 分工：**Kimi = 前端设计与实现**（web/vue/src）；**DSH = 后端**（scripts/ + web/server.py）。
> 模型：kimi-code/k3-256k，max 思考。本文件是双方契约，改契约先改本文件。

## 1. 项目定位

本地化 HTV：对标 RunningHub RHTV 的 AI 短剧流水线（剧本 → 美术设定 → 分镜 → **分镜参考图** → 视频抽卡 → 成片），
画布式、每步可编辑、过程透明、不抽卡盲盒。领域词汇与事实源：见项目根 `CONTEXT.md`（务必先读）。

## 2. 技术约束（硬性）

1. 只允许修改 `web/vue/src/**`（Vue 3 `<script setup>`，Vite 构建；`web/index.html` 无功能）与 `web/vue/index.html`；
   **禁止改动** `scripts/**`、`web/server.py`、`config.yaml`、`web/dist/**`、`docs/**`、`assets/**`。
2. 不新增 npm 依赖（除非写清理由且我批准）；中文 UI；亮/暗色不限，先做一套。
3. 每片完成必须自检：`cd web/vue && npm run build` 通过（产物 web/dist 由我部署）。
4. 与后端交互只走 `web/vue/src/api.js` 的封装函数；需要新接口时按第 5 节契约调用并在回复里列出需求。
5. 保留现有能力：分镜卡编辑、抽卡/选片缩略图墙、质检徽标、A/B 对比、选中原因录入、任务队列、成片面板。

## 3. 现有前端盘点

- `src/App.vue`：顶栏（项目/集选择、状态、任务队列入口）+ 4 步向导导航 + 视图切换。
- `src/components/ScriptPanel.vue`：①剧本（小说导入 + AI 编剧）。
- `src/components/ArtPanel.vue`：②美术设定（资产 C/S/P 登记与定妆照）。
- `src/components/BoardView.vue`：③分镜（表格/卡片编辑 + 右栏候选墙）。
- `src/components/ComposePanel.vue`：④成片（选片检查 + 拼接）。
- `src/components/JobPanel.vue`：任务队列。
- `src/api.js`：`api` 封装（见下节函数），`enc()` 路径编码。

## 4. 后端 API 契约（现状，全部可用）

```
GET  /api/projects                         项目列表
GET  /api/project/<name>                   幕分段树 + 集列表
GET  /api/project/<name>/episode/<n>/storyboard   分镜表 JSON
PUT  /api/project/<name>/episode/<n>/storyboard   保存分镜表
GET  /api/assets /api/vocab                资产 / 词表
GET  /api/prompt/<name>/<ep>/<shot>        单镜完整 H3 三段式
POST /api/render                           起后台抽卡任务 {project,episode,only,shots,...}
GET  /api/render/status/<job>              抽卡任务状态
GET  /api/jobs                             全局任务队列
GET  /api/candidates/<name>/<ep>/<shot>    某镜候选视频列表
GET  /api/review/<name>/<ep>               候选自动质检报告（带缓存）
POST /api/review                          强制重新质检 {project,episode}
GET  /api/selection-notes/<name>/<ep>      选中原因记录
POST /api/select                           选中候选 → shot_XX.mp4
POST /api/compose                          拼接成片
GET  /api/episode-status/<name>/<ep>       选中状态 / 成片状态
GET  /api/wizard/<name>                    创作向导步骤状态
POST /api/novel/<name>                     保存小说源 {novel}
POST /api/ai-write/<name>                  AI 编剧 {novel,title}
GET  /video/<name>/<episode>/<file>        视频文件（Range 支持）
```

## 5. 新增契约（分镜参考图，由 DSH 后端实现，前端按此对接）

```
GET  /api/shot-ref/<name>/<ep>/<shot>      → {"shot": 3, "prompt": "…"|"", "image": "shot_03.png"|null}
POST /api/shot-ref/<name>/<ep>/<shot>      → 生成/刷新参考图提示词（后端调 LLM），保存 E<n>/refs/shot_XX.prompt.md，返回同上
GET  /refs/<name>/<episode>/<file>         → 参考图静态文件（E<n>/refs/ 下 PNG/JPG）
```

## 6. 设计目标（对标 RHTV，源自 docs/specs/01-htv对标.md）

- **步骤条**：①剧本 → ②美术设定 → ③分镜 → ④成片，每步显示产物状态（无/草稿/完成），点击进入该步；保留「每步可编辑」。
- **分镜卡**（③的核心）：卡片 = 一个 Shot 的视图（镜号/景别/运镜/时长/角色/场景/灯光/对白/备注），
  点选卡片 → 右栏显示该镜的「参考图 + 抽卡候选缩略图墙」。
- **参考图墙**（右栏）：Shot ref 提示词 + 参考图 + 生成按钮；候选墙带质检徽标（通过/复核/废片）、A/B 并排、选中原因录入。
- **过程透明**：生成任务进度可见（任务队列已有）；单镜失败只重跑单镜。
- 整体气质：**画布感**（工作区式布局），而非表单堆叠；响应式（≥1280px 优先桌面）。

## 7. 工作协议（分片）

1. **第一片（本次）**：只输出《HTV 画布设计说明》——布局线框（ASCII）、组件拆分树、每个组件用的 API、
   需新增/修改的后端接口清单、与现有 5 个组件的取舍（保留/重构/替换）。**不改代码**。
2. 我验收设计后，逐片让你实现（每片一个焦点：布局壳 → 分镜卡 → 参考图墙 → 状态接入 → 视觉打磨）。
3. 每片回复末尾给出：改动文件清单 + `npm run build` 结果 + 未决问题。
4. 遇到后端行为不符（非前端 bug）→ 记录到回复，由我修后端，不擅自绕过后端改逻辑。
