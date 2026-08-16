# 04 · Harness 接口预留（CLI 契约 + 内置 skill）

> 状态：规划中 · 新增：`scripts/cli.py`（M0 骨架，M3 完善）· 预留：`.agents/skills/htv-pipeline/`
> 对应 `00-规划总览.md` 主线需求 3

## Problem Statement

未来版本要"内置 skill + harness agent 自动构建 HTV/视频制作工作流"；
前期就要给外部 harness agent（DeepSeek Harness、Claude Code 等）留一个**稳定、可脚本化**的入口，
而不是让 agent 直接啃内部脚本的参数细节。当前项目没有统一 CLI：入口散在
`pipeline.py / ai_writer.py / asset_manager.py / review.py / compose.py` 各自的 argparse。

## Solution

新增统一 CLI `scripts/cli.py`，作为 **L3 编排层唯一对外契约**；配套预留内置 skill
`htv-pipeline`（L5），内容是"怎么用 CLI 完成创作"的说明书（不复制业务逻辑）。

### CLI 契约（v1，M0 落地子命令，M1-M3 增量扩展）

```
python scripts/cli.py <command> [args] [--json] [--project NAME]
```

| 命令 | 职责 | 里程碑 |
|---|---|---|
| `agent chat "<prompt>"` | 提示词 → 模型生成（走 `agent.py`） | M0 |
| `agent generate <task> [--in FILE]` | 模板化生成：storyboard_from_script 等 | M0 |
| `storyboard <project> [--episode N]` | 剧本 → 分镜.md（复用 gen_storyboard） | M1 |
| `shot-ref <project> --episode N` | 分镜 → 参考图提示词/图片 | M1 |
| `pipeline render/review/compose ...` | 透传现有 pipeline 子流程 | M2 |
| `status <project>` | 项目进度摘要（JSON） | M3 |

规则：

- `--json`：所有输出（含错误）为单行/多行 JSON 到 stdout，供程序消费；无 `--json` 时保持人类可读文本；
- 退出码：`0` 成功；`2` 参数错；`3` 配置错；`4` 上游（模型/ComfyUI）错误——**harness agent 依此判断**；
- 输入大文本支持 `--in FILE` 或 stdin 管道，避免命令行长度限制；
- 命令实现只做**编排**：调 L1/L2 模块函数，不内嵌业务逻辑。

### 内置 skill 预留（L5，M3）

`.agents/skills/htv-pipeline/SKILL.md`：name `htv-pipeline`，描述触发场景（"用户要求生成短剧分镜/参考图/抽卡/成片"），
正文 = CLI 用法速查 + 项目领域词汇（CONTEXT.md）+ 常见工作流步骤。
外部 harness agent 加载它即可操作本项目，无需读全部源码。

### Python 模块级契约（harness agent 更细粒度调用）

`scripts/agent.py` 的函数接口（`chat` / `generate` / `resolve_provider`）即为 Python 级公共契约，
Web 服务（`web/server.py`）与 CLI 都通过它访问模型——三入口共用同一内核，避免三条实现。

## User Stories

1. 作为外部 harness agent，我想用一条 `cli.py agent generate ... --json` 命令拿到结构化结果与退出码，以便把它编排进自动工作流。
2. 作为外部 harness agent，我想加载 `htv-pipeline` skill 就能知道全套命令与领域词汇，以便少读源码、少猜。
3. 作为命令行用户，我想不加 `--json` 时看到可读的进度文本，以便日常手工操作。
4. 作为开发者，我想在 Web 服务里直接调 `agent.py`，以便前端与 CLI 行为一致。

## Implementation Decisions

- CLI 用标准库 `argparse`；`--json` 输出统一经 `cli.out_json(obj)` / `cli.fail(code, msg)` 收敛；
- 不引入子命令框架（保持零依赖）；
- `scripts/cli.py` 不 import Web 层（L3 不得依赖 L4）；
- 每新增子命令 = 一个新 spec 切片（垂直切片），并先在 `test_cli.py` 写失败测试。

## Testing Decisions（seams）

1. `cli.main(argv)` 返回 `(exit_code, output_text)`——**不**直接断言进程退出（可测性优先），入口薄壳 `if __name__` 才 sys.exit；
2. 各子命令的编排函数（如 `cmd_agent_generate(args) -> dict`）在 `test_cli.py` 用 mock 的 `agent.generate` 断言：参数映射、JSON 结构、错误码映射；
3. `--json` 输出结构用独立字面量断言（防同构复算的 tautological 测试）。

## Out of Scope

- M0 不实现 `pipeline/status` 等透传命令（M2/M3 再切）；
- 不实现 CLI 的交互式模式、配置文件生成向导；
- 不改 Web 前端（L4 属于 M2 spec）。

## Further Notes

- 与 `03-agent模块.md` 的退出码语义保持一致：`agent` 相关错误（上游模型）→ `4`。
- harness agent 概念定义见 `CONTEXT.md`（词汇表已收录）。
