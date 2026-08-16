# 12 · Agent 操作手册（FR8 · 本项目给 Agent 的接口契约）

> 版本：v1 · 2026-08-13
> 读者：通用 Agent（Reasonix / Codex / Claude 等，通过 CLI / HTTP API / MCP 调用）
> 目标：**零上下文交接**——一个新 Agent 仅凭本手册 + 命令行 `--help`，就能接管
> 「剧本 → 分段 → 分镜 → 资产 → 抽卡 → 质检 → 选片 → 拼接成片」全流程。

---

## 1. 角色与边界（先读这段）

你是**导演 Agent**，本项目是你的「场记 + 执行 + 摄影棚代理」，ComfyUI 是摄影棚，
剪映/ChatCut 是后期机房。

- **人定义框架**：剧本大纲、镜头脉络、叙事节奏、关键场面、审美偏好由人先给定；
- **你（Agent）在框架内打稿**：文本起草、分段、分镜字段、提示词、批量抽卡调度、
  质检初筛、素材规范化、成片串联；
- **你的产出永远是「草稿」**，由人审改后才定稿。不要替人做审美判断，只做批量与执行。

协作口诀：**人先画框，Agent 填框，人再审改打磨。**

---

## 2. 工作流总览（8 步，每步都有对应 CLI/API）

```
① 剧本  ② 分段  ③ 分镜  ④ 资产  ⑤ 抽卡  ⑥ 质检  ⑦ 选片  ⑧ 拼接
 小说.md   故事骨架.md  分镜.md   资产库   候选.mp4   REVIEW.md  selected-note.md  成片.mp4
```

| 步 | 输入 | 工具 | 产出 | 人做什么 |
|---|---|---|---|---|
| ① 剧本 | 小说/素材 | `ai_writer.py events/skeleton/script` 或 `POST /api/ai-write` | 小说事件.md → 故事骨架.md → 剧本.md | 审改文本 |
| ② 分段 | 故事骨架.md | 前端 / `ai_writer.storyboard_from_script` | 分集决策表 → 集 | 合并/拆分段 |
| ③ 分镜 | 剧本镜头序列 | `POST /api/storyboard-gen` 或 `gen_storyboard.py` | E<n>/分镜.md | 微调字段 |
| ④ 资产 | 剧本/分镜 | `asset_manager.py register/check` | assets/ + 角色圣经 | 提供定妆照 |
| ⑤ 抽卡 | 分镜.md | `render.py` / `POST /api/render` | shots/.candidates/shot_XX_YY.mp4 | 指定抽哪些镜/候选数 |
| ⑥ 质检 | 候选 | `review.py` / `GET /api/review` | REVIEW.md + 判定(ok/warn/reject) | 确认淘汰废片 |
| ⑦ 选片 | 候选 + 质检 | `POST /api/select` | shots/shot_XX.mp4 + selected-note.md | A/B 观感挑选 |
| ⑧ 拼接 | 选中片 | `compose.py` / `POST /api/compose` | E<n>/成片.mp4 | 进剪映精剪 |

**唯一事实源**：`分镜.md`（分镜表）+ `shots/`（素材目录）。
其它产物（提示词、REVIEW、concat 清单）均可从事实源重建，**可随时重跑**。

---

## 3. 目录与文件契约

```
output/<项目>/
├── 小说.md              原始素材（人粘贴）
├── 小说事件.md          事件图谱（①）
├── 故事骨架.md          故事核/人物小传/三幕/分集决策表（②，分段真相）
├── 剧本.md              逐集结构化剧本，每集含「## 集 N」+「镜头序列」（③）
├── 资产清单.md          角色/场景/道具表（④）
└── E<n>/
    ├── 分镜.md          markdown 表：镜号|景别|机位运动|时长|角色|场景|灯光|对白/音效|备注
    ├── prompts_h3.md    每镜 H3 三段式提示词（可重建）
    ├── REVIEW.md        候选质检报告（⑥，自动生成）
    ├── selected-note.md 选中原因表：镜号|选中文件|原因|时间（⑦，自动追加）
    ├── shots/           选中的规范化素材 shot_XX.mp4（⑧ 的输入）
    │   ├── .candidates/ 抽卡候选池 shot_XX_YY.mp4（⑤ 的产出）
    │   └── .review/     候选首/尾帧缩略图 shot_XX_YY_{first,last}.png
    └── 成片.mp4          拼接成片（⑧）
```

编号规范：资产 = `C/S/P/R` + 两位数字（C01/S01/P01/R01）；
分镜引用资产编号须已登记，否则 `verify` 报警。

**品味/记忆层（读它，但改它需人确认）**：
```
profile/taste.md            品味档案（风格/镜头/对白/避免项/用户声明）
profile/selection_log.jsonl 每次选片记录 {chosen, rejected, note}
profile/diffs/ + stats.json 草稿→定稿 diff 与修改率趋势（自动化率指标）
```

---

## 4. CLI 契约（标准库，`python <script> ...`）

> 所有脚本在 `scripts/` 下，从项目根运行。Windows 用 `python`，POSIX 用 `python3`。
> 退出码 0=成功，非 0=失败（可脚本化判断）。

### 4.1 编排 `pipeline.py`
```bash
python scripts/pipeline.py init <项目> --episodes 6      # 建目录 + 骨架
python scripts/pipeline.py run <项目> --episode 1 --dry-run   # 只预览
python scripts/pipeline.py run <项目> --episode 1 --yes       # 免确认执行
python scripts/pipeline.py storyboard <项目> --episode 1      # 分镜→prompts_h3.md
python scripts/pipeline.py verify <项目> --episode 1          # 校验（视频数/资产登记）
python scripts/pipeline.py compose <项目> --episode 1         # ffmpeg 拼接
```

### 4.2 抽卡 `render.py`（真实提交 ComfyUI）
```bash
python scripts/render.py <项目> --episode 1 --shots 3 --dry-run
python scripts/render.py <项目> --episode 1 --shots 3 --only 1,3        # 只渲染 1/3 镜
python scripts/render.py <项目> --episode 1 --image 首帧图.png          # I2VA（首帧）
python scripts/render.py <项目> --episode 1 --ref-image ref_C01.png     # Ref2VA（人物一致性）
# 关键参数：--width/--height/--frames/--steps/--seed/--timeout
```
产出在 `E<n>/shots/.candidates/`，**不直接进 shots/**（需经选片规范化）。

### 4.3 质检 `review.py`（FR3）
```bash
python scripts/review.py <项目> --episode 1           # 生成 REVIEW.md + 缩略图
python scripts/review.py <项目> --episode 1 --json    # JSON（给 Agent 结构化消费）
python scripts/review.py <项目> --episode 1 --dry-run
```
判定：`ok`=通过 / `warn`=需人工复核 / `reject`=废片（可自动淘汰）。
`reject` 的硬条件：无音轨、首/尾帧纯黑/纯白、探针失败、空文件。

### 4.4 资产 `asset_manager.py`
```bash
python scripts/asset_manager.py register C01 --name 林冲 --image 定妆照.png
python scripts/asset_manager.py list / check / manifest
```

### 4.5 提示词 `gen_storyboard.py`
```bash
python scripts/gen_storyboard.py <分镜.md> --format h3 --style "水墨风"
```

### 4.6 AI 编剧 `ai_writer.py`（双模式）
```bash
python scripts/ai_writer.py events|skeleton|script|assets <项目>
# 配置了 LLM（config.yaml llm_base）→ 直接生成；否则输出 Agent 指令（你照做写文件）
python scripts/ai_writer.py check    # 探测 LLM 是否可用
```

### 4.7 生态 `eco.py` / 品味 `taste.py`
```bash
python scripts/eco.py list / install <id> / check <id>
python scripts/taste.py stats / extract
python scripts/taste.py log-select --project X --episode 1 --shot 1 --chosen shot_01_02.mp4 --rejected shot_01_01.mp4,shot_01_03.mp4 --note "构图好"
```

---

## 5. HTTP API 契约（`web/server.py`，默认 127.0.0.1:8189，可 `--port`）

启动：`python web/server.py [--port 18889]`。所有 API 返回 JSON，非 2xx 带 `{"error": ...}`。

| 方法 | 路径 | 请求体 | 说明 |
|---|---|---|---|
| GET | `/api/projects` | — | 项目列表 |
| GET | `/api/project/<name>` | — | 分段树（acts）+ 集列表 |
| GET | `/api/project/<n>/episode/<ep>/storyboard` | — | 分镜表 {header, rows} |
| PUT | 同上 | `{rows, header}` | 保存分镜（全量重写，唯一事实源） |
| GET | `/api/assets` / `/api/vocab` | — | 资产 / 景别·运镜词表 |
| GET | `/api/prompt/<n>/<ep>/<shot>` | — | 单镜 H3 三段式提示词 |
| POST | `/api/render` | `{project,episode,only:[..],shots,width,height,frames,steps,seed,ref,image}` | 起后台抽卡任务 → `{job}` |
| GET | `/api/render/status/<job>` / `/api/jobs` | — | 任务状态 / 全局队列 |
| GET | `/api/candidates/<n>/<ep>/<shot>` | — | 某镜候选 `{files:[{name,size}]}` |
| GET | `/api/review/<n>/<ep>` | — | 质检报告（带缓存） |
| POST | `/api/review` | `{project,episode}` | 强制重新质检 |
| POST | `/api/select` | `{project,episode,shot,file,note?}` | 选中候选→规范化 shot_XX.mp4，note 写入 selected-note.md |
| GET | `/api/selection-notes/<n>/<ep>` | — | 选中原因记录 |
| POST | `/api/compose` | `{project,episode}` | 拼接成片 |
| GET | `/api/episode-status/<n>/<ep>` | — | 选中状态 / 成片状态 |
| GET | `/api/wizard/<n>` | — | 创作向导 7 步状态 |
| POST | `/api/novel/<n>` | `{novel}` | 保存小说源 |
| POST | `/api/ai-write/<n>` | `{novel,title,mode}` | AI 编剧（mode=events/skeleton/script/assets） |
| POST | `/api/storyboard-gen` | `{project,episode}` | 剧本镜头序列 → 分镜.md |
| GET | `/api/taste` | — | 品味默认值（前端插入行 + Agent 读取） |
| GET | `/video/<n>/<ep>/<file>` | — | 视频流（支持 Range） |
| GET | `/review-img/<n>/<ep>/<file>` | — | 质检缩略图 |

---

## 6. 端到端示例（Agent 照抄可跑通）

```bash
# 0. 干跑验证链路（不调模型）
python scripts/pipeline.py run demo --episode 1 --dry-run

# 1. 剧本：有 LLM 就一键，无 LLM 就用 Agent 指令（会打印出来）
python scripts/ai_writer.py events demo
python scripts/ai_writer.py skeleton demo
python scripts/ai_writer.py script demo
python scripts/ai_writer.py assets demo

# 2. 资产登记（把资产清单里的 C/S/P 逐条登记）
python scripts/asset_manager.py register C01 --name 林冲

# 3. 分镜（剧本镜头序列 → 分镜.md）
python scripts/pipeline.py storyboard demo --episode 1

# 4. 抽卡（ComfyUI 需运行，模型名与 config.yaml 一致）
python scripts/pipeline.py render demo --episode 1 --shots 3

# 5. 质检（自动出 REVIEW.md，废片标记 reject）
python scripts/review.py demo --episode 1

# 6. 选片（把中选候选规范化，可选原因）
#    CLI 无单镜选片命令时用 API：POST /api/select {project:"demo",episode:1,shot:1,file:"shot_01_02.mp4",note:"构图好"}

# 7. 校验 + 拼接
python scripts/pipeline.py verify demo --episode 1
python scripts/pipeline.py compose demo --episode 1
```

---

## 7. 品味学习与质检的消费方式

- **生成前**：读 `profile/taste.md`（用户声明 > 镜头偏好 > 避免项）→ 注入剧本/分镜默认值/提示词 style；
- **选片时**：读 `GET /api/review` 的 `verdict`，先淘汰 `reject`，再把 `warn` 列出给用户复核；
  你选中某片时，把对比结论写进 `note`（如"构图好但口型差"）→ 沉淀进 selection_log；
- **周期性**：`python scripts/taste.py stats` 看修改率趋势（下降 = 自动化率提升），
  结合 `profile/diffs/` 归纳「用户连续修改 2 次以上」的模式，**以 [Agent 提炼] 标注写入
  taste.md，等用户点头转正**；
- **禁忌**：不要把你的偏好写进 taste.md；没有用户修改/选择证据时不要编造品味。

---

## 8. 幂等与可恢复（重要）

1. `分镜.md` 是唯一事实源——前端/CLI 保存都是全量重写，**重跑不会产生孤儿状态**；
2. `shots/.candidates/` 抽卡可反复覆盖（同名 `shot_XX_YY.mp4`）；
3. 选中 `shot_XX.mp4` 只是从候选**复制**，候选不删，可重新选；
4. `REVIEW.md` / `prompts_h3.md` / `成片.concat.txt` 均可从事实源重建；
5. 中断后：`verify` 看缺什么 → 补 → `compose` 续作。

---

## 9. 安全与约定

- 项目名/文件名须匹配 `^[A-Za-z0-9_\-\u4e00-\u9fff]+$`（防路径穿越，桥已校验）；
- 桥默认绑定 127.0.0.1，单机本地使用；
- H3 权重遵循 MiniMax H3 Community License（商用需确认条款）。

---

*配套：docs/00-08 实施手册、docs/09 前端设计、docs/10 PRD、docs/11 战略定稿。*
