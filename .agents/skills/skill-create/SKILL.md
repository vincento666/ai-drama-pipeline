---
name: skill-create
description: 安装已有 skill 或制作新 skill（本项目 .agents/skills/ 目录规范）。Use when installing a skill from a GitHub URL into .agents/skills/, creating a new skill (SKILL.md) from a description, listing installed skills, or validating a skill's frontmatter. 触发词：安装skill / 安装技能 / 创建skill / 制作skill / 列出skill / skill 管理。
compatibility: 供外部 harness agent（kimi/codex/claude/dsh 外派时）与内置 manager（agent_manager skill 分支）按同一规范操作；工具化入口 = scripts/skill_mgr.py（list_skills / install_from_url / create_skill），仅标准库。
---

# skill-create：安装 / 制作 skill（.agents/skills/ 规范）

本项目把"可复用的任务指令"封装为 **skill**，落地在仓库根 `.agents/skills/<name>/` 目录（如
`.agents/skills/h3-prompt-writing/`、`.agents/skills/htv-h3-prompt/`）。harness 扫描该目录并
按 `SKILL.md` 的 frontmatter 描述识别每个 skill。本 skill 定义"装 skill / 做 skill"的统一操作规范。

## What is a skill

一个 skill = 一个目录 + 一个 `SKILL.md`（必需）+ 可选 `references/`（参考资料，被 SKILL.md 引用）：

```
.agents/skills/<name>/
├── SKILL.md            # 必需：frontmatter + 分节正文（agent 实际执行的指令）
├── references/         # 可选：大块参考（官方指南原文等），SKILL.md 里用相对路径引用
└── agents/             # 可选：第三方 UI 元数据（如 openai.yaml），不影响 harness 识别
```

skill 与普通文档的区别：**description 是触发指针**——harness 只凭 description 判断何时加载
SKILL.md，正文才是加载后执行的内容（参考 .agents/skills/writing-for-agents/SKILL.md 的
pointer/body 分层思想）。

## Frontmatter 规范（必需字段）

SKILL.md 必须以 `---` 段开头（YAML 子集，参照 h3-prompt-writing 与 writing-for-agents）：

```yaml
---
name: <小写连字符名>            # 如 h3-prompt-writing；目录名保持一致
description: <一句话用途 + 何时使用 + 触发词>   # harness 靠它决定何时调用，必须含触发词
compatibility: <可选：适用环境/限制说明>        # h3-prompt-writing 有此字段，writing-for-agents 可无
---
```

- `name`：小写字母/数字开头，仅 `[a-z0-9-]`（如 `h3-prompt-writing`）。
- `description`：**含触发词**——写明"何时用"（如"Use when rewriting multimodal requests…"）
  与"不要何时用"，让 harness 能精准匹配；中英均可，但触发词要覆盖用户的自然语言说法。
- `compatibility`（可选）：适用 agent/环境约束（如"仅标准库""不依赖外部 API"）。

正文风格（对齐 writing-for-agents）：分节（What / When to use / Steps / Output / 校验）、
**可操作步骤**（每步有完成判据）、避免废话与空话（"be thorough" 类 no-op 删掉）、
环境能查到的不重复写（看 SKILL-MECHANICS.md / SKILL.md 的目录即环境）。

## 安装已有 skill（从 GitHub）

工具化入口：`python scripts/install_github_repo.py <owner/repo> <target_dir> [ref] [--only <子目录>]`
（skill_mgr.install_from_url 内部即调它的 install_repo，api.github.com trees + raw 批量拉取，
**不 git clone**——github.com 直连/codeload 不通，只有 api+raw 链路可用）。

```bash
# 安装仓库根下的整个 skill
python scripts/install_github_repo.py T8mars/minimax-h3-prompt-skill-T8 .agents/skills/minimax-h3-prompt-skill-T8 main

# 只装仓库子目录（--only），目标目录名 = 子目录末段（本仓库 MiniMax-H3 官方 skill 的装法）
python scripts/install_github_repo.py MiniMax-AI/MiniMax-H3 .agents/skills/h3-prompt-writing main --only skills/h3-prompt-writing
```

- `--only <子目录>`：只拉取该子目录下文件，且目标目录 = 子目录末段（去掉仓库前缀层级）。
- 断点续传：目标已存在且非空 → 自动跳过；中断后重跑同一命令即可续传。
- 装完校验：SKILL.md 存在 + frontmatter 合法（`validate_skill_file`：name + description 非空）。

## 制作新 skill（LLM 生成 SKILL.md）

1. 定名：`<name>` 小写连字符（如 `shot-review`），目录 = `.agents/skills/<name>/`。
2. 写描述：一句话 + 触发词（**用户在对话里怎么说、harness 何时该调用**）。
3. 生成 SKILL.md：内置 manager 说「创建 skill <名> <描述>」→ skill_mgr.create_skill 用 LLM
   按本规范生成；外部 agent 也可自己写（同样遵循 frontmatter + 分节正文规范）。
   要求：正文可操作（步骤+完成判据）、避免废话、中英描述均可、大块参考下沉到 references/。
4. 校验：
   - frontmatter 合法：`---` 段 + `name:` + `description:` 非空；
   - description 含触发词（能覆盖用户自然语言）；
   - 目录结构 = SKILL.md + 可选 references/。
5. 生效：装/建完成后需**重新加载 agent 或新会话**才被 harness 识别（manager 会提示）。

## 工具化入口（skill_mgr.py，仅标准库）

- `list_skills()` → `[{name, description, path}]`（GET /api/skills）
- `install_from_url(url, only=None)` → 解析 GitHub URL → install_repo → frontmatter 校验
  → `{ok, name, target, files, errors, frontmatter}`
- `create_skill(name, description, content=None)` → LLM 生成（系统提示词=本规范）→ 写盘 → 校验
  → `{ok, name, path, error?}`
- 内置 manager 的 skill 分支（意图含 安装skill/安装技能/创建skill/制作skill/制作技能/列出skill）
  即调上述函数，事件回执注明「已安装 skill：xxx（N 文件，frontmatter ✓）」/「已创建 skill：xxx」。
