# CONTEXT.md — AI 短剧流水线领域词汇表

> 按 Matt Pocock `domain-modeling` skill 维护：本文件是项目唯一事实词汇表。
> 代码、文档、测试命名一律用这里的**规范词**；遇到模糊词先到这里对齐，再动手。
> 变更词汇 = 变更领域模型，须同步更新本文件（必要时写 `docs/adr/`）。

## 语言（Language）

**项目（Project）**
`output/<项目名>/` 目录。一个项目 = 一部剧的完整生产上下文。
_Avoid_：作品、工程、case

**集（Episode）**
`output/<项目>/E<n>/` 目录，一集 = 一段独立成片。
_Avoid_：章、期

**剧本（Script）**
`剧本.md`，逐集结构化剧本，每集含「## 集 N」+「镜头序列」。
_Avoid_：文案、台词本

**分镜（Shot）**
`E<n>/分镜.md` 里的一行（= 一个镜头），字段：镜号/景别/运镜/时长/角色/场景/灯光/对白/备注。
**分镜是唯一事实源（Source of Truth）**——CLI/前端都读写它。
_Avoid_：镜头卡、分镜格（UI 卡片只是 Shot 的视图，不是新概念）

**资产（Asset）**
`assets/` 下编号为 `C/S/P/R + 两位数字` 的资源（角色/场景/道具/风格参考），
含定妆照/场景图 + 登记痕迹（`.registry/`）+ 角色圣经（`bible/`）。
_Avoid_：素材（素材泛指一切文件，Asset 专指编号资产）

**美术设定（Art direction）**
先于分镜锁定的「整体风格 + 角色定妆照 + 场景图 + 色调」，是跨镜一致性的锚点。
_Avoid_：画风管理、风格设置（Art direction 是流程阶段，风格是其中一字段）

**抽卡（Draw）**
对一镜批量生成多个候选视频的动作（T2VA / I2VA / Ref2VA 三种模式）。
_Avoid_：生成、渲染（Render 是 ComfyUI 的技术动作，Draw 是业务动作）

**候选（Candidate）**
`shots/.candidates/shot_XX_YY.mp4`，抽卡产物（YY = 第几个候选）。
_Avoid_：备选、草稿

**选中（Selected）**
`shots/shot_XX.mp4`，人从候选里挑中的那一条（每镜一条）。选片即信号（进品味学习）。
_Avoid_：定稿、正片

**质检（Review）**
对候选跑 ffprobe/抽帧/音轨检测 → `REVIEW.md`，判定 `ok / warn / reject`。
_Avoid_：审核、QC 报告

**品味（Taste）**
`profile/` 下的偏好记忆：`taste.md`（偏好）+ `selection_log.jsonl`（选片）+ `diffs/`（修改 diff）。
_Avoid_：记忆、风格档案

**成片（Final cut）**
`E<n>/成片.mp4`，compose 按镜号拼接选中片的产物。
_Avoid_：正片、成品

**生成 Agent（Agent）**
`scripts/agent.py` 的最小生成内核：提示词 → 模型 API → 剧本/分镜等内容。
CLI 与 Web 前端都经它调模型；未来外部 harness agent 也经 CLI 调用它。
_Avoid_：助手、机器人、AI 助手

**模型提供商（Provider）**
`config.yaml` 的 `llm.providers` 预设：`deepseek` / `qwen` / `kimi` / `local`
（local = 本地 OpenAI 兼容服务，如 Ollama）。三要素：base/model/api_key。
_Avoid_：平台、渠道、厂商

**分镜参考图（Shot ref）**
每镜一张的视觉参考图（`E<n>/refs/shot_XX.png`）：角色/场景/风格一致性锚点，
也是抽卡首帧的输入源（M1 起）。**分镜卡 + Shot ref = 分镜环节的双产物**。
_Avoid_：分镜图、概念图（设定图属 Asset 侧）

**命令行接口（CLI）**
`scripts/cli.py` 统一入口：子命令 + `--json` + 退出码契约（0/2/3/4），
是外部 harness agent 的唯一入口。
_Avoid_：脚本、命令行工具集

**内置 skill（htv-pipeline）**
`.agents/skills/htv-pipeline/`（预留）：教外部 harness agent 用 CLI 操作本项目的说明书。
_Avoid_：插件（插件指 ComfyUI 侧）、工作流文件

## 关系（Relationships）

- 一个 **Project** 含多集 **Episode**
- 一集 **Episode** 含多镜 **Shot**（`分镜.md`）
- 一镜 **Shot** 经 **Draw** 产生多个 **Candidate**，人**选中**其一为 **Selected**
- 一镜 **Shot** 引用零到多个 **Asset**（角色/场景/道具）
- **Review** 对每个 **Candidate** 给判定；**Compose** 把每镜 **Selected** 拼成 **Final cut**
- **Taste** 采集「选/淘汰 + 草稿→定稿 diff」，反哺「默认分镜字段 + 提示词 style」

## 已消除的歧义（Flagged ambiguities）

- 「渲染」曾既指 ComfyUI 技术动作又指业务抽卡 → 定：**Render**=技术动作，**Draw**=业务抽卡。
- 「资产」曾与「素材」混用 → 定：**Asset**=编号资产，素材=泛指文件。
- 「分镜」曾既指文件又指单行 → 定：**分镜.md** 是文件，**Shot** 是单行；UI 卡片只是 Shot 的视图。
- 「9 步向导」已被 4 阶段取代 → 规范流程 = **剧本 → 美术设定 → 分镜 → 成片**。

## 测试接缝（Seams，TDD 约定）

seams 登记册 = `docs/specs/05-测试策略.md`（新增/变更 seam 必须先登记）。
既有 seams（测试只打这些公共边界，详见 `scripts/test_core.py`）：
- `review._flags/_verdict` — 质检判定（ok/warn/reject 的唯一出口）
- `gen_storyboard.parse_markdown_table / classify_audio / shot_h3` — 分镜解析与提示词
- `compose.shot_sort_key` — 拼接排序
- `common.validate_code / parse_yaml_subset` — 编号与配置解析
- `ai_writer.storyboard_from_script` — 剧本→分镜（按集过滤）
