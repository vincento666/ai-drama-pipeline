# 10 · Agent 编排架构（对齐 LongHorizon-Harness 组件与设置）

> 状态：规划中 · 目标：**核心创作流程由对话窗驱动**——agent（外部 harness）通过
> **修改文件 + 调用 CLI** 推进任务，UI 回显供人类微调；人机均可反复操作。
> 参考：AMAP-ML/LongHorizon-Harness（Loop Engineering / 三职责 / AgentAdapter / Environment）。

## 1. 组件映射（LHH → 本项目）

| LHH 组件 | 本项目实现 | 设置项（config.yaml `agent:`） |
|---|---|---|
| **AgentAdapter**（保留外部 agent 原生循环） | `agentbridge.AgentAdapter` / CLITaskAdapter / Kimi/Codex/Claude/Dsh | `agent.adapters.<name>.cmd/args/timeout/skills_dir` |
| **Environment**（执行环境） | `run_task(cwd=项目目录)` —— 外部 agent 工作区 = `output/<项目>/`，可读写项目文档 | `agent.workspace`（固定=项目目录） |
| **Manager**（状态与下一步） | `run_task`（单轮）+ **对话窗多轮委派**（人类在环的 Loop） | `agent.default`（默认适配器） |
| **Executor**（执行） | `adapter.execute`（CLI 非交互；`skills_dir` 使外部 agent 可加载本项目 skills） | `agent.adapters.*` |
| **Auditor**（真实依据） | `audit_file_exists` + 可扩展校验钩子（文件可解析/退出码） | `agent.audit.enabled` |
| **任务状态**（状态不漂移） | `output/<项目>/agent/tasks/<id>/`（goal/prompt/transcript/result/evidence） | 固定 |
| **Loop**（反复修改） | 对话窗 = 循环驱动器：目标+已验证状态 → 委派 → 验证 → 回显 → 继续 | `agent.max_rounds`（对话窗内限制） |

## 2. 设置项（config.yaml）

```yaml
agent:
  default: kimi                 # 对话窗「外部 harness」默认适配器
  max_rounds: 8                 # 单会话最多委派轮数（防失控）
  audit:
    enabled: true               # Auditor 校验开关
  adapters:
    kimi:   {cmd: kimi,   args: [-m, kimi-code/k3-256k, --output-format, text], timeout: 1800, skills_dir: .agents/skills}
    codex:  {cmd: codex,  args: [exec], timeout: 1800}
    claude: {cmd: claude, args: [], timeout: 1800}
    dsh:    {cmd: dsh,    args: [--profile, headless], timeout: 1800}
```

- `skills_dir`：非空则调用时加 `--skills-dir <项目根>/.agents/skills`（kimi 实测支持）——外部 agent 直接获得本项目全部 skills；
- 适配器 `available()` 缺失时对话窗提示安装/切换。

## 3. 创作流程推进（对话窗驱动，核心闭环）

**流程状态机**（事实源文件驱动，rev 回显）：访谈简报 → 剧本四块 → 分镜 → 参考图 → 抽卡候选 → 选片 → 成片。

**推进方式（两种，均可反复）**：

| 方式 | 机制 | 适用 |
|---|---|---|
| **内置推进**（本地端点/job） | 对话窗快捷卡：一键编剧 / AI 拆分镜 / 生成参考图 / 批量抽卡 / 拼接成片（现有端点 + job 轮询） | 确定性流程步骤 |
| **外部委派**（agentbridge） | 委派 kimi/codex/claude/dsh：**直接编辑项目文档** + **可运行 `python ../scripts/cli.py …`**（cli.py 是 harness 契约，L3）推进/精修 | 深度创作任务（精修剧本/分镜、批量改参考图提示词、质检建议落地） |

**外部 agent 的任务上下文**（build_project_summary）明确给出：
1. 工作区 = 项目目录，可读写 剧本.md/分镜.md/refs/资产；
2. 可运行 `python ../scripts/cli.py <命令>`（agent generate / agent chat / agent-run / storyboard-gen 等）推进或查询；
3. 改完文件后总结改动（UI 经 rev 轮询自动回显）。

## 4. 对话窗形态（前端）

```
侧边对话窗（全高，可开合）
├── 流程推进卡（阶段按钮：访谈/编剧/分镜/参考图/抽卡/成片 + 委派精修）
├── 会话流（内置解析变更 | 外部委派 transcript）
│    ├─ 委派 kimi（工作区=项目目录）… transcript 流式
│    └─ 完成 → Auditor 校验 → 已写盘 → rev 变化 → 展示层自动刷新
├── 模式：[内置] [外部 harness ▾] + skill 指示
└── 输入框
```

回显：全局 watcher 轮询 `/api/canvas` 的 `rev`（5s），变化即全量刷新（时间轴/剧本/资产/成片轨）。

## 5. 分片

| 片 | 内容 | 状态 |
|---|---|---|
| A 架构与设置 | spec 10 + config `agent:` 段 + agentbridge 读设置（args/skills_dir/timeout） | 🔵 本轮 |
| B 流程推进模板 | GET /api/flow-templates（阶段 goal 卡，内置/外部双模） | 🔵 本轮 |
| C 外部 CLI 能力实测 | 委派 kimi 运行 cli.py 验证「调 CLI 推进」成立 | 🔵 本轮 |
| D 统一对话窗前端 | 侧栏 + 推进卡 + 委派 transcript + rev watcher + 内置变更 | ⬜ 下片 |

## 6. 不做

- 不做 LHH 的桌面 GUI computer-use / OS 级环境（超出短剧流水线）；Environment 协议留扩展位；
- 不做 Manager/Executor/Auditor 分模型角色（v1 单适配器；角色映射为设置预留字段）。
