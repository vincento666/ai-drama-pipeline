# 09 · 统一 Agent 侧边对话窗（连接外部 harness · 工作区=项目目录 · 改文档即回显）

> 状态：v2（2026-08 用户定案）· 取代分散的 4 个 agent 触点
> 一句话：**一个全高侧边对话窗** = 统一 agent 入口；可切「内置 Agent / 外部 harness（kimi/codex/claude/dsh）」；
> 外部 harness 的**工作区 = 项目目录**（output/<项目>/），它直接改项目文档；
> 后端监视事实源变化 → 前端轮询 rev → **展示层自动刷新**（所改即所得，无需手动操作）。

## 1. 目标形态

```
┌ 侧边对话窗（右侧全高，420px，可开合）────────────────┐
│ ✨ HTV Agent                                     │
│ ┌ 会话流（多轮）────────────────────────────────┐ │
│ │ 用户：用 kimi 把第 3 镜灯光改成夜景并检查全镜   │ │
│ │ ▶ 委派 kimi（工作区: output/smoke）            │ │
│ │ ▶ kimi transcript…（流式）                    │ │
│ │ ▶ Auditor 校验 ✓ 已写盘 → 展示层自动刷新       │ │
│ │ 用户：内置：把镜1对白改为「爷爷吃。」            │ │
│ │ ▶ 变更清单 [应用]（本地规则解析）               │ │
│ └───────────────────────────────────────────────┘ │
│ 模式: [内置] [外部 harness ▾ kimi/codex/claude/dsh] │
│ 输入框 [发送]                                    │
└──────────────────────────────────────────────────┘
```

## 2. 三通道统一（原 4 触点收敛）

| 原触点 | 去向 |
|---|---|
| AgentBar 指令条 | 并入对话窗（内置模式：本地解析轻动作/变更） |
| Agent 工作台 Tab（spec 09 P2） | 并入对话窗（变更清单/应用逻辑原样迁移） |
| agentbridge CLI 外部任务 | 对话窗「外部 harness」模式（web 端委派，工作区=项目目录） |
| OnboardPanel 访谈 | 保留（生成前流程，对话窗可一键跳转） |

## 3. 机制

### 3.1 外部 harness 委派（工作区 = 项目目录）

```
POST /api/agent-task {project, goal, agent?, context?}
  → 后台线程：cwd = output/<项目>/；adapter = kimi/codex/claude/dsh（CLI 非交互）
  → run_task（transcript 全程留痕 agent/tasks/）→ Auditor 校验（文件可解析）→ 写 result
GET /api/agent-task/<project>/<task_id>  → {status, transcript 尾部, result}
```
- 默认上下文 = **项目文档摘要**（简报 + 剧本字数 + 分镜 N 镜 + 资产数 + 当前集分镜表）；
- 外部 agent 直接读写项目目录里的文档（它就是"在改文件"）。

### 3.2 改文档即回显（rev 轮询，零长连接）

- `GET /api/canvas/<project>/<ep>` 新增 **`rev`** 字段：事实源文件（剧本四块+简报+分镜+refs+资产 registry/图片）mtime 摘要；
- 前端全局 watcher：每 5s 轮询 rev → 变化 → `loadAll + refreshCreative + refreshWizard + assetsWithImg` 全量刷新展示层；
- 覆盖来源：外部 harness 直接改文件、/api/patch 写盘、访谈简报、资产删除等——**统一走 rev 这一个信号**。

### 3.3 内置模式

- 本地解析（parse_edit_action / parse_command）→ 变更清单 → 应用（/api/patch）→ rev 变化 → 回显。

## 4. 分片

| 片 | 内容 | 状态 |
|---|---|---|
| P1 写盘核心 + agent-edit/patch 端点 | ✅ 完成（13 测试，冒烟通过） |
| P2 会话工作台（右栏 Tab） | ✅ 完成（AgentPanel，62 modules）——将迁入侧边对话窗 |
| **P3 统一侧边对话窗** | 全高侧栏 + 内置/外部模式切换 + 委派/transcript 流式 + 会话持久化（项目 agent/conversations.jsonl） | 🔵 本轮 |
| **P4 自动回显 watcher** | canvas rev + 前端 5s 轮询全量刷新 | 🔵 本轮 |
| P5 旧触点收敛 | AgentBar 弱化为快捷入口；Agent Tab 并入侧栏 | 随 P3 |

## 5. 不做

- 不做 SSE/WebSocket（轮询 rev 足够且零依赖）；外部 harness 会话级 `-c` 续聊留 v2（本轮每次委派 = 新会话）。
