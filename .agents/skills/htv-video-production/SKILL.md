---
name: htv-video-production
description: AI 短剧制作全流程操作手册（剧本→美术·资产→分镜→抽卡→选片→成片）。外部 harness agent 操作本项目、推进创作流程、查询看板状态或校验验收时使用本 skill；工作区=项目目录（output/<project>/），可直接读写项目文档、运行 scripts/cli.py。
---

# AI 短剧制作全流程操作手册

## 项目定位

本项目是 **AI 短剧/漫剧流水线**：一句话想法（或小说素材）→ 从零编剧 → 美术·资产 → 分镜 → 抽卡（ComfyUI H3 视频生成）→ 质检 → 选片 → 拼接成片。人机双驱动：对话窗（内置）+ 外部 agent（改文件/调 CLI）均可推进；事实源文件变化即回显到看板。

你（外部 harness agent）被委派时的角色 = **执行者**：工作区是项目目录，改文件、跑 CLI，改完无需额外通知（rev 自动回显）。

## 工作区与文件约定

工作区 = `output/<project>/`（下文路径均相对项目目录；脚本命令从**仓库根**运行，从项目目录运行时把 `scripts/` 换成 `../scripts/`）。

| 文件 | 内容 | 谁写 |
|---|---|---|
| `创作简报.md` | 风格/卖点/人物锚点（一致性锚点，链式生成必读） | AI 访谈 / 从零编剧① |
| `小说.md` | 原始素材（3000-6000 字，从零编剧② 或粘贴） | 从零编剧 / 用户 |
| `小说事件.md` | 事件图谱（5-12 事件） | 链式编剧① |
| `故事骨架.md` | 故事核/人物小传/三幕/分集决策表 | 链式编剧② |
| `剧本.md` | 逐集剧本，每集含**镜头序列**（格式见「写盘规范」） | 链式编剧③ |
| `资产清单.md` | 角色/场景/道具表（C/S/P + 两位数字） | 链式编剧④ |
| `E{NN}/分镜.md` | 分镜表，列：镜号/景别/运镜/时长/角色/场景/灯光/对白/备注 | 拆分镜（LLM/解析器） |
| `E{NN}/shots/` | **已选片**：`shot_XX.mp4`（选中成片，拼接输入） | 选片 |
| `E{NN}/shots/.candidates/` | 抽卡候选池：`shot_XX_NN.mp4`（未选，不参与拼接） | 抽卡 |
| `E{NN}/refs/` | 参考图 + `shot_XX.prompt.md`（逐镜提示词） | 参考图任务 |
| `E{NN}/成片.mp4` | 拼接产物（验收目标） | 拼接 |

`E{NN}` = `E01`/`E02`…（两位集号）。资产库在仓库根 `assets/`（characters/scenes/props），跨项目共享。

## 制作流程步骤

每步给出 输入 → 动作 → 输出 → 完成判据。

1. **从零编剧（对话驱动）**：用户在对话窗说「写一个关于 X 的短剧」→ 后端从零编剧 ① 创作简报 → ② 小说素材 → 链式编剧 ①事件图谱 ②故事骨架 ③剧本 ④资产清单。无小说时不再要求先粘贴素材；对话里直接粘贴 ≥200 字素材则直写 `小说.md`。完成判据：`剧本.md` 与 `资产清单.md` 非空。
2. **拆分镜**：输入 `剧本.md` 的镜头序列 → LLM 优先（`python scripts/cli.py agent generate storyboard_from_script --in payload.json`，payload 形如 `{"script_text": "<剧本全文>", "style": "<风格前缀>"}`），失败回退解析器 → 输出 `E{NN}/分镜.md`（严格表格列格式）。完成判据：分镜表可解析且非空。
3. **资产登记**：按 `资产清单.md` 把角色/场景/道具登记到 `assets/`（`C01`/`S01`/`P01` 代号，名称+描述）。完成判据：分镜引用的每个代号都有登记。
4. **抽卡**：ComfyUI 需在线 → `python scripts/pipeline.py render <project> --episode 1 --shots N`（每镜 N 个候选，默认参数见 config `generate:` 段）→ 候选落 `E{NN}/shots/.candidates/`。完成判据：每镜至少 1 个候选 mp4。
5. **质检**：`python scripts/review.py <project> --episode 1`（自动检查时长/黑场/静音等，输出 `E{NN}/review.md`）。
6. **选片**：把选中的候选复制为 `E{NN}/shots/shot_XX.mp4`（镜号与分镜一致）。完成判据：`shots/*.mp4` 数量 ≥ 分镜镜数。
7. **拼接成片**：`python scripts/compose.py <project> --episode 1`（ffmpeg 按镜号拼 `E{NN}/成片.mp4`）。完成判据：成片存在。

## CLI 工具表

命令从仓库根运行；`<project>` 为项目名（output/ 下的目录名）。

| 命令 | 用途 |
|---|---|
| `python scripts/cli.py agent-run <project> --goal <目标> --agent kimi` | 下发单轮任务给外部 agent（Manager 单轮，流式 transcript） |
| `python scripts/cli.py agent-list <project>` | 列出项目 agent 任务与状态 |
| `python scripts/cli.py agent-resume <project> <task_id>` | 重跑任务 |
| `python scripts/cli.py agent-loop <project> --goal <目标> --agent kimi --audit storyboard,script,assets,composed` | LHH 自动循环（Manager 决策→执行→Auditor 业务验收） |
| `python scripts/cli.py agent generate <task> --in payload.json` | LLM 任务生成（storyboard_from_script / shot_ref / onboard_brief） |
| `python scripts/cli.py agent chat <提示词>` | 直接对话 |
| `python scripts/eco.py list` | 生态清单（ComfyUI 插件 / H3 skill / 工作流）+ 安装状态 |
| `python scripts/eco.py check <id>` | 验证插件节点是否在 ComfyUI 注册 |
| `python scripts/eco.py install <id>` | 安装插件/skill/工作流 |
| `python scripts/eco.py refresh` | 从生态源重新发现 zip/工作流/skill |

`agent-loop --audit` 的验收口径 = 业务 Auditor（见「验收」节）。

## ComfyUI 对接

- 地址：`config.yaml` → `comfyui.base_url`（当前 `http://127.0.0.1:9288`；**不要改 config.yaml**，运行期覆盖写 `config.local.json`）。
- 模型：`h3:` 段（diffusion_model / ref2va_model / video_vae / audio_vae / text_encoder / turbo_lora，须与 ComfyUI models 实际文件名一致）。
- 生成参数：`generate:` 段（width/height/frames/steps/seed；短剧竖屏用 864x1536）。
- 工作流双模式（`workflow.mode`）：
  - `builtin`（默认）：内置构造器 `scripts/render.py build_workflow`（T2VA / I2VA 首帧 / Ref2VA 参考图三态）。
  - `template`：可视化导出 JSON + `workflow.mapping` 把业务参数注入 `node_id.inputs.param`。
- 提交入口：`scripts/render.py render()`（逐镜提交 → 轮询 history → 下载带音频 mp4 到 `.candidates/`）。

## 写盘规范

- **分镜.md 严格列格式**：Markdown 表格，列序固定 `镜号 | 景别 | 运镜 | 时长 | 角色 | 场景 | 灯光 | 对白/音效 | 备注`；景别词表 wide/medium/close-up…，运镜词表 push in/pull back/pan/tracking/static…；`时长` 用秒数（如 `5`）。
- **AI 改动分镜走 workflow_patch 规则**：`镜N｜字段｜新值`（如「镜3｜灯光｜夜景」）→ 由 `scripts/workflow_patch.py` 落盘；不要直接重写整表（保留表头与未改行）。
- **资产代号**：`C`/`S`/`P` + 两位数字（C01/S01/P01…）；剧本镜头序列、分镜、资产清单三处代号必须一致。
- **剧本镜头序列格式**（每集 `**镜头序列：**` 下）：
  `- 镜N｜场景S01｜景别wide｜运镜push in｜角色C01｜<画面动作>｜<对白或音效>`
  每集 3-8 镜、单镜 3-6 秒。

## 回显机制

事实源文件（`小说.md`/`剧本.md`/`分镜.md`/`shots/`/`成片.mp4` 等）mtime 摘要 = `facts_rev`（`scripts/agentbridge.py`）→ SSE/轮询 → 看板自动刷新。**外部 agent 改完文件无需额外通知**，rev 变化即触发展示层刷新；如需让宿主知道"我做了什么"，在回复里总结改动即可。

## 验收

`agent-loop --audit storyboard,script,assets,composed` 的业务校验口径（`scripts/agentbridge.py` BUSINESS_AUDITS）：

| 键 | 判据 |
|---|---|
| `storyboard` | `E{NN}/分镜.md` 可解析且非空 |
| `script` | `剧本.md` 非空 |
| `assets` | 资产表可读、编号名称完整 |
| `composed` | `E{NN}/成片.mp4` 存在 |

全绿 = 该集可发布；任一失败按 `agent-loop` 证据落盘继续迭代。

## 注意事项

- **Windows 环境**：命令用 `python scripts/…`（不要用 `python3`）；路径含中文与空格时用引号包裹。
- **LLM**：用 `config.yaml` 的 `llm:` 段（provider=deepseek，`deepseek-v4-flash` 实测可用）；从零编剧/链式编剧/拆分镜都要 LLM 在线。
- **别改 config.yaml**：运行期覆盖写 `config.local.json`（设置界面同款机制）。
- **ComfyUI 未在线**时抽卡/质检/拼接会失败——先查 `comfyui.base_url` 配置与 `eco.py check` 节点注册。
- 分镜改动优先走 workflow_patch 规则而非整表重写；整表重写会丢表头注释与人工微调。
