# 08 · Agent Adapter 框架（外部 harness agent 执行机制）

> 状态：规划中 · 参考：AMAP-ML/**LongHorizon-Harness**（阿里开源，HF 周榜第一，2026-08）
> 定位：宿主 = 本产品（主循环 + 交互界面 + 状态存储 + 领域校验）；
> **执行 = 外部 harness agent**（kimi / codex / claude / dsh），通过轻量 Adapter 接入。

## 1. 对齐 LongHorizon-Harness 的核心机制

| LHH 机制 | 本项目落点 |
|---|---|
| **Loop Engineering**：目标+已验证状态 → 拆单步任务 → 全新上下文执行 → 真实验证 → 保存进度/记录失败证据 → 循环 | 任务状态机（Manager）+ 单轮执行（Executor）+ 确定性校验（Auditor） |
| **Manager（状态与下一步）** | `agentbridge.run_task`：从 goal + checkpoint 恢复，组装单步提示词 |
| **Executor（执行）** | `AgentAdapter.execute`：调外部 agent CLI（非交互 `-p`），全新上下文 |
| **Auditor（真实依据）** | 产物确定性校验：文件存在/格式解析/测试/exit code（不轻信 agent 自述） |
| **AgentAdapter 协议** | `scripts/agentbridge.py`：CLITaskAdapter 基类 + Kimi/Codex/Claude/Dsh 适配器 |
| **状态不漂移** | `output/<项目>/agent/tasks/<task_id>/`：goal.md / prompt.txt / transcript.jsonl / result.json / evidence.md |
| **上下文刷新后可续跑** | `cli.py agent-resume`（外部 agent `-c` 续会话 + checkpoint 重载） |
| **Web 工作台** | Agent 面板（下发任务 / 实时看外部 agent 输出 / 中断 / 续跑）——Kimi 前端切片 |

## 2. 架构

```
本产品（宿主，主循环+交互）
├── Manager   agentbridge.run_task(project, goal, context, adapter)
│             任务目录创建 → 组装 prompt（goal+context+领域提示）→ 派给 Executor → 记录 transcript → 写 result
├── Executor  AgentAdapter.execute(cwd, prompt_text, on_line)
│             CLI 适配器：kimi -p / codex exec / claude -p / dsh --profile headless -p
│             外部 agent 保留原生执行循环；宿主只在外层协调任务边界与状态
├── Auditor   校验执行产物（文件存在 / JSON 解析 / review.py 质检 / 退出码）
│             通过 → checkpoint 更新；失败 → evidence.md 记录，不记进度
└── 交互      cli.py agent-run / agent-resume / agent-list（--json 契约）
              Web Agent 面板（对话式下发、流式进度、审批/中断/续跑）
```

## 3. 状态目录契约

```
output/<项目>/agent/tasks/<task_id>/
  goal.md          原始目标 + 已验证状态（可被下一轮恢复）
  prompt.txt       发给外部 agent 的单步完整提示词
  transcript.jsonl 逐行 {ts, stream, line}（外部 agent 输出全程留痕）
  result.json      {ok, exit_code, summary, artifacts, audited_at}
  evidence.md      失败证据 / Auditor 记录（不记为进度）
```

## 4. Adapter 协议

```python
class AgentAdapter:
    name: str
    def available(self) -> bool                      # which <cli>
    def execute(self, cwd, prompt_text, on_line=None, timeout=1800) -> (exit_code, stdout)
    def resume_cmd(self, cwd) -> list[str]           # 续跑：kimi -c / codex --continue
```

| 适配器 | 命令（非交互） | 状态 |
|---|---|---|
| `kimi` | `kimi -p <prompt> -m kimi-code/k3-256k --output-format text` | ✅ 本机实测可用（0.36.1） |
| `codex` | `codex exec -p <prompt>`（占位模板） | 依赖 codex CLI |
| `claude` | `claude -p <prompt>`（占位模板） | 依赖 Claude Code |
| `dsh` | `dsh --profile headless -p <prompt>`（占位；对齐 LHH 的 DSH 接入方式） | 依赖 dsh CLI |

## 5. CLI 契约（harness agent 亦可调用）

```
cli.py agent-run <project> --goal "..." [--agent kimi] [--context FILE] [--json]   # 下发并等待单轮
cli.py agent-resume <project> <task_id> [--json]                                    # 续跑（-c + checkpoint）
cli.py agent-list <project> [--json]                                                # 任务列表+状态
```

## 6. 本产品内的领域用途（示例任务）

1. **剧本/分镜精修**：LLM 一键生成 → 外部 agent 深度润色（注入 创作简报 + H3 规范）→ Auditor 校验分镜表可解析；
2. **候选质量审查**：抽卡候选 → 外部 agent 看首帧/提示词给修改建议 → Auditor 用 review.py 复检；
3. **未来闭环**：外部 agent 通过 `cli.py`（L3 契约）直接驱动流水线——M3「harness 集成」的真正形态。

## 7. 不做（边界）

- 不复制外部 agent 的原生循环（它们各自维护）；宿主只做任务切分/状态/验证；
- 不做桌面 GUI computer-use（LHH 的 OS 层超出本地短剧流水线范围，预留 Environment 协议占位）；
- 三角色不拆模型（v1 单 adapter 单角色；角色分配留 v2）。
