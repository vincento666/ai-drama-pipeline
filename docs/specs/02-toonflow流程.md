# 02 · Toonflow 流程参考

> 状态：规划中 · 对象：HBAI-Ltd/Toonflow-app（开源一站式 AI 短剧创作工具）
> 依据：官方 README + 社区深度解读（2026-08）

## 1. Toonflow 流程闭环

「策划 → 编剧 → 分镜 → 出片」：

1. 新建项目 → 导入原著（小说/文本）；
2. **章节事件提取（事件图谱）**：先分解长文本为事件，避免长文本丢信息；
3. **ScriptAgent**：故事骨架 / 改编策略 / 结构化剧本；
4. **ProductionAgent**：无限画布组织分镜 / 素材 / 视频节点，分镜图节点化精调；
5. 视频拼接导出成片。

三类模型可配（文本 LLM / 图片模型 / 视频模型 三开关）。官方 Demo：
Claude Opus 4.6（文本）+ GPT Image 2（图）+ Seedance 2.0（视频），约 2 分钟成片、成本约 ¥130。

## 2. 技术栈与许可

- Node.js 23 + TypeScript 5 + Express 5 + Socket.IO（后端端口 10588）
  + SQLite（better-sqlite3/knex）+ Vercel AI SDK + @huggingface/transformers（ONNX 本地推理）
  + Electron 40 桌面壳 + Sharp + Docker。
- 前端独立仓库 Toonflow-web（编译后放 `data/web`）。
- 许可：**Apache-2.0 + 补充商业协议**（分发 ≥2 个独立第三方需商业授权；
  ≤5 法人内部/学习/分账免费；v1.0.8 前 AGPL-3.0 不追溯）。→ 本项目 MIT 独立实现，仅参考流程设计。

## 3. 可参考点 → 本项目决策

| Toonflow 设计 | 本项目决策 |
|---|---|
| 事件图谱驱动改编（解长文本丢信息） | ✅ 已有 `小说事件.md`（ai_writer 四层链） |
| 结构化数据 SQLite + 二进制目录 | **保持 Markdown 文件为唯一事实源**（`分镜.md` 等，CONTEXT 已定）；SQLite 仅作未来索引缓存，不进事实源链 |
| 可编程供应商（TS 热更，Vercel AI SDK） | `config.yaml` + `llm.providers` 预设（deepseek/qwen/kimi/local，OpenAI 兼容）——配置即编程的轻量版 ✅ M0 |
| Skill Markdown 外置 + skillList.json | `.agents/skills/`（方法论 skill 已装）+ `prompts/` 模板目录 + 预留 `htv-pipeline` skill |
| 三层 Agent（决策/执行/监督） | 分阶段：M0 简单 Agent → M3 skill 化 + 质检监督（复用 review.py） |
| ONNX 本地向量记忆 | 轻量替代：章节/事件摘要 + 分镜上下文注入；向量检索为远期选配 |
| ScriptAgent / ProductionAgent 双工作台 | 现有 4 步创作向导 + CLI；M2 步骤面板演进 |

## 4. 数据组织对齐表

| Toonflow | 本项目（现状） |
|---|---|
| 项目/集/分镜结构化 + SQLite | `output/<项目>/E<n>/分镜.md` + 目录文件 |
| `data/oss` 二进制素材 | `output/<项目>/shots/` + `assets/` |
| `data/skills` 提示词 | `prompts/` + `.agents/skills/` |
| 设置中心供应商配置 | `config.yaml`（`llm.providers` + `comfyui` + `h3`） |

## 5. Out of Scope

Electron 桌面端（本项目走本地 Web + CLI）、SQLite 重构、ONNX 向量记忆、商业授权模型。
