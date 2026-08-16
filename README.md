# AI 短剧/漫剧本地生产流水线（ComfyUI + MiniMax H3 + 资产库）

一套**本地、开源、可自动化**的 AI 短剧/漫剧生产工作流骨架：剧本 → 资产 → 分镜 → 视频 → 剪辑成片。
参考业界主流方法论（资产先行 / 关键帧驱动 / 批量抽卡-人工挑选）与开源项目（h3-studio、minimax-h3-hub、Seedance2-Storyboard-Generator、Koma Studio）设计。

**人只做判断与组织，机器做批量生成。** 每个环节都有人工决策点（见 `docs/08-人机协作判断点.md`）。

> **新规划（2026-08，SDD+TDD 开发中）**：本项目对标 RunningHub **RHTV** 做本地化 HTV
> （剧本 → 分镜 → **分镜参考图** → 抽卡 → 成片，画布式、每步可编辑），流程参考 **Toonflow-app**；
> 新增**简单生成 Agent**（DeepSeek/Qwen/Kimi/本地 可配置）与 **CLI/harness 接口预留**。
> 规划与各模块 spec 见 `docs/specs/00-规划总览.md`。

## 架构总览

```
┌────────────────────────────────────────────────────────────────┐
│  人工决策层         剧本/素材/分镜/生成结果 全部由人确认          │
├────────────────────────────────────────────────────────────────┤
│  编排层    scripts/pipeline.py（干跑预览 → 逐环节执行）          │
├────────────────────────────────────────────────────────────────┤
│  资产层    assets/{characters,scenes,props,refs}  C/S/P 编号规范 │
│            assets/bible/ 角色圣经（角色一致性锚点）              │
├────────────────────────────────────────────────────────────────┤
│  提示词层  prompts/  H3 三段式 + Seedance 时间轴 + 角色圣经模板   │
├────────────────────────────────────────────────────────────────┤
│  生成层    ComfyUI 0.30+ + ComfyUI-MiniMaxH3 节点 + H3 权重      │
│            h3-studio（本地 LLM 写结构化提示词 + 引用生视频）      │
├────────────────────────────────────────────────────────────────┤
│  成片层    scripts/compose.py → ffmpeg 拼接 / 剪映草稿           │
└────────────────────────────────────────────────────────────────┘
```

## 快速开始（三步）

```bash
# 1. 阅读实施手册（按顺序）
docs/00-实施总览.md   → 硬件决策
docs/01-环境与硬件.md → 装机
docs/02-ComfyUI与H3安装.md → 生成引擎

# 2. 干跑一遍流水线（不真正调用模型，验证链路）
python3 scripts/pipeline.py --dry-run --episode 1

# 3. 开始第一个项目
python3 scripts/pipeline.py init my-drama      # 初始化项目目录
python3 scripts/asset_manager.py register C01  # 登记角色资产

# 4. 自动抽卡出片（需 ComfyUI 运行中，模型名与 config.yaml 一致）
python3 scripts/pipeline.py render my-drama --episode 1 --shots 3   # 每镜 3 个候选
python3 scripts/pipeline.py render my-drama --episode 1 --only 1,3  # 只渲染 1/3 镜
python3 scripts/pipeline.py render my-drama --episode 1 --ref-image ref_C01.png  # Ref2VA 人物一致性
# 人工从 shots/shot_XX_YY.mp4 挑片，其余删除后：
python3 scripts/review.py my-drama --episode 1                     # 自动质检：REVIEW.md + 首/尾帧 + 音轨/废片判定
python3 scripts/pipeline.py verify my-drama --episode 1
python3 scripts/pipeline.py compose my-drama --episode 1            # 拼成成片.mp4

# 5. 创作前端（端到端：剧本分段 → 分镜管理 → 抽卡选片 → 拼接成片）
python web/server.py [--port 18889]                                 # 打开 http://127.0.0.1:18889（Vue 前端 web/dist；8188/8189 被系统临时限制时换高位端口）
#   前端重构建（改了 web/vue/src 后）：cd web/vue && npm run build
python scripts/eco.py list                                             # 生态对接层：列出 H3 skill/插件安装状态
python scripts/eco.py install motion-context                           # 一键安装外部插件（跨镜连续等）
#   顶部 4 步创作向导（对标 RHSTORY 主干）：①剧本（一键 AI 编剧：小说→事件→骨架→剧本→资产）→
#   ②美术设定（角色定妆照/场景图/整体风格，资产先行）→③分镜（卡片式，每镜景别/运镜/对白）→④成片。
#   分镜卡片点选 → 右栏“抽卡/选片”缩略图墙（带质检徽标：通过/复核/废片 + A/B 并排对比 + 选中原因录入）
#   数据仍是 output/<项目>/E<n>/分镜.md + shots/；shots/ 顶层 = 每镜选中的素材(shot_XX.mp4)；
#   shots/.candidates/ = 抽卡候选池；REVIEW.md + selected-note.md 记录质检与选片原因

# 6. 简单 Agent 与统一 CLI（provider 可配：DeepSeek / Qwen / Kimi / 本地 Ollama）
python scripts/cli.py agent chat "写一个都市逆袭短剧的三镜开场分镜" --json
python scripts/cli.py agent generate storyboard_from_script --in payload.json --json   # 任务模板生成（payload: script_text/style）
#   config.yaml → llm.provider 切换 deepseek/qwen/kimi/local；llm.providers 填各自 base/model/api_key
#   CLI 退出码契约（外部 harness agent 依据）：0 成功 / 2 参数错 / 3 配置错 / 4 上游错误
#   规划与 spec：docs/specs/00-规划总览.md；测试：python -m unittest scripts.test_agent scripts.test_cli scripts.test_core
```

## 目录结构

```
ai-drama-pipeline/
├── README.md                本文件
├── config.yaml              全局配置（ComfyUI 地址 / LLM provider 预设 / H3 模型 / 路径）
├── docs/                    实施手册（01-08 按序阅读）
│   ├── 00-实施总览.md
│   ├── 01-环境与硬件.md
│   ├── 02-ComfyUI与H3安装.md
│   ├── 03-本地LLM与提示词助手.md
│   ├── 04-资产库管理.md
│   ├── 05-提示词模板.md
│   ├── 06-ComfyUI工作流.md
│   ├── 07-自动化编排.md
│   ├── 08-人机协作判断点.md
│   └── specs/                SDD 规划与模块 spec（对标 RHTV / Toonflow / agent / CLI / 测试）
├── assets/                 资产库（C=角色 S=场景 P=道具 R=参考）
│   ├── characters/  scenes/  props/  refs/  bible/
├── .agents/skills/          Agent skills（Matt Pocock 全套 35 + caveman；预留 htv-pipeline）
├── prompts/                提示词模板库（直接复制使用）
├── scripts/                编排脚本（Python3 标准库，无第三方依赖）
│   ├── agent.py            生成 Agent 内核（provider 预设 + 任务模板，seam 见 test_agent.py）
│   ├── cli.py              统一 CLI（--json + 退出码契约，harness agent 唯一入口）
│   ├── pipeline.py         主线编排：剧本→资产→分镜→生成→拼接
│   ├── asset_manager.py    资产登记 / 校验 / 清单生成
│   ├── gen_storyboard.py   分镜 → H3 / Seedance 提示词
│   ├── render.py           ComfyUI API 自动出片（逐镜抽候选）
│   ├── review.py           候选自动质检（FR3：ffprobe 探针 + 首/尾帧 + 音轨 → REVIEW.md）
│   ├── taste.py            品味学习（采集/度量/提炼，垂直记忆层）
│   ├── ai_writer.py        AI 编剧（事件图谱→骨架→剧本→资产；LLM 层委托 agent.py）
│   ├── eco.py              生态对接层（安装/加载外部 H3 skill/插件）
│   ├── compose.py          ffmpeg 拼接成片 + 文件检查
│   ├── test_core.py / test_agent.py / test_cli.py   单元测试（TDD，50 例）
├── tools/rtk/rtk.exe       Rust Token Killer v0.3.0（外部 agent 省 token 用）
└── output/                 按项目/集组织输出
```

## 环境要求（生成引擎侧，通常不是本机）

- **ComfyUI 0.30.0+**（H3 节点原生支持，更早版本没有 H3 节点）
- **H3 权重**（约 15.5GB NVFP4 量化 / 33B 全量需更多）：从 `Comfy-Org/MiniMax-H3` 下载
- **推荐 GPU**：16GB 显存可跑 NVFP4 量化（RTX 4080/5080 等）；8GB 需 GGUF 更深度量化
- **本地 LLM**（可选但强烈推荐）：Ollama / llama.cpp / LM Studio，用于 h3-studio 写结构化提示词
- 生成引擎可以跑在**另一台机器或云 GPU 实例**上，本机脚本只通过 HTTP 与 ComfyUI 通信

## 参考的开源项目

| 项目 | 用途 | 说明 |
|---|---|---|
| [RunningHub RHTV](https://rhtv.runninghub.ai/projects) | **对标对象** | 原生 AI 智能体无限画布；本项目的本地化对标分析见 `docs/specs/01-htv对标.md` |
| [HBAI-Ltd/Toonflow-app](https://github.com/HBAI-Ltd/Toonflow-app) | **流程参考** | 事件图谱→ScriptAgent→ProductionAgent；参考分析见 `docs/specs/02-toonflow流程.md` |
| [Comfy-Org/ComfyUI-MiniMaxH3](https://github.com/Comfy-Org/ComfyUI-MiniMaxH3) | H3 节点 | ComfyUI 0.30 内置 H3 支持 |
| [CharlesMod/h3-studio](https://github.com/CharlesMod/h3-studio) | 提示词助手前端 | 本地 LLM 自动写 H3 三段式提示词 + Ref2VA 人物一致性 |
| [ai-models-lab/minimax-h3](https://github.com/ai-models-lab/minimax-h3) | H3 知识库 | ComfyUI 工作流 JSON、VRAM 计算器、提示词库 |
| [liangdabiao/Seedance2-Storyboard-Generator](https://github.com/liangdabiao/Seedance2-Storyboard-Generator) | 剧本方法论 | 四幕剧本 + C/S/P 素材编号规范（本骨架沿用） |
| [M-JYuan/Koma](https://github.com/M-JYuan/Koma) | 本地桌面一站式 | 若不想用脚本，可直接用它管理剧本/资产/分镜/剪辑 |

## 许可证与注意

- 本骨架代码为 MIT，可自由使用/修改。
- **H3 模型权重**遵循 MiniMax H3 Community License（商用需确认条款）。
- 生成引擎侧需要独立显卡；本机（纯脚本层）无需 GPU。
