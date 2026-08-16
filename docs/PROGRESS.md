# PROGRESS · 进度看板（DSH 管理，每轮更新）

> 分工：**Kimi K3-256k** = 前端 UI/UX 视觉理解与实现（web/vue/src）｜**DSH** = PRD/spec 规划、进度管理、后端（scripts/ + web/server.py）、验收与联调
> 联调契约：`web/KIMI-BRIEF.md`；Kimi 会话：`session_d113e911-ad9d-41fb-b9ed-787ab332d277`（kimi -r 恢复）

## 1. 里程碑

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 基础与 agent | provider 预设 + agent.py + cli.py + 测试基座 | ✅ 完成（真实 API 冒烟通过） |
| M1 分镜参考图 | 提示词存储层 + API + 出图 | ✅ 提示词链路完成；F9 出图 = 选片首帧晋升（已实现，无需 ComfyUI 出图任务） |
| M2 HTV 画布 | 对标 RHTV 画布重构 | ✅ v3 创作台画布 R0-R4 全部交付（Kimi 前端 + DSH 后端契约），DSH 逐片复验；待浏览器人工走查（http://127.0.0.1:18999，冒烟项目 smoke） |
| M3 harness 集成 | htv-pipeline skill + CLI 契约完善 | ⬜ 未开始 |

## 2. 前端切片（Kimi）

### 阶段 A：地基（已完成 ✅）

| 切片 | 内容 | 状态 | 验收（DSH） |
|---|---|---|---|
| 0 设计说明 | 线框/组件树/API 映射/取舍 | ✅ | 3 个未决问题已答复 |
| 1 布局壳 | store.js + TopBar + StepBar + JobDrawer + App.vue | ✅ | build 复验通过 |
| 2 分镜卡 | BoardCanvas + ActTree + ShotCard 拆分 | ✅ | build 复验通过（30 modules） |
| 3 参考图墙 | ShotInspector + ShotRefPanel + CandidateWall + ABCompare | ✅ | /refs 静态 200；shot-ref 端到端 |
| 4 状态接入 | ComposePanel 选中原因 + StepBar 联动 + 走查 | ✅ | build 复验通过 |
| 5 视觉打磨 | 空态/药丸/卡片质感/逐镜覆盖判定 | ✅ | build 复验通过（38 modules） |

### 阶段 B：画布 v2 重设计（spec 06 · 进行中 🔵）

| 切片 | 内容 | 状态 | 验收 |
|---|---|---|---|
| R0 设计稿 | Kimi 搜 RHTV 真实素材 → v2 线框/交互/组件映射（只出稿） | ✅ 交付 | DSH 验收通过；3 个未决问题已答复（2 个后端契约已实现） |
| R1 画布骨架 | store 扩展 + 泳道壳 + 锚点 + Inspector 常驻壳 | ✅ 交付 | build 复验通过（44 modules）；v3 修正：长页泳道退为次要，主视觉转创作台 |
| R2 画布主视觉 | 时间轴大画布（BeatCard/BeatRuler）+ 资产条 + 成片轨 + Inspector asset 态 | ✅ 交付 | DSH 复验 build（50 modules）+ index/js/canvas 全 200；**可见质变落地** |
| R3 检查器保真 | ShotFields 共用 + 重抽联动 + 路径/定位收尾 | ✅ 交付 | DSH 复验 build（52 modules）；双编辑入口同源 ref 闭环核对通过 |
| R4 Agent 驱动 + 侧板 | AgentBar 指令条联调 + PlanFlow 规划流 + 剧本侧板抽屉 | ✅ 交付 | DSH 复验 build（58 modules）+ index/js 200；F19 AgentBar 端到端（dry-run→执行→画布刷新） |
| R5 视觉打磨 | 播放头/动效/细节（可选收尾） | ⬜ 待定 | — |

### 阶段 C：前端重构（三栏壳 · 设计文档 docs/11-前端重构设计方案.md · 进行中 🔵）

| 切片 | 内容 | 状态 | 验收 |
|---|---|---|---|
| P0 设置 bug 修复 | common.py `[]` 解析为真列表 + server.py config-agent 类型归一化（args→list/timeout→int/enabled→bool） | ✅ | 实测 `args: []` → `[]`，TypeError 根除 |
| P1 三栏壳 | 顶栏极简 + 左 AI 栏（可拖 280–640px）+ 中栏四视图（剧本/美术·资产/分镜/成片）+ 右栏三态折叠（300px/24px 窄条/隐藏）+ EventTrace 垂直进度条组件（暗夜绿流光/mock）；删 8 旧组件（AgentBar/ScriptDrawer/OnboardPanel/JobDrawer/AgentDock/PlanFlow/CanvasView/LaneShell） | ✅ | build 66 modules + 冒烟全绿（kimi 交付）；待浏览器人工走查（http://127.0.0.1:18999） |
| P2 会话+manager | 会话 CRUD/chat/持久化（profile/sessions/）+ manager→executor→auditor 骨架 + 任务/事件落盘 | ⬜ 进行中 | — |
| P3 SSE 事件回显 | /api/events + EventTrace 接真 + 流式输出 + 审计日志（events.jsonl） | ✅ | 142 测试；smoke_accept 全绿（trace/msg/doc.diff/rev 实测到达） |
| P3.5 回显/轨迹修复 | 终态收尾器（无卡死 running）+ EventTrace 去重合并 + ThinkingTrace「思考中」折叠块 + 外派=tool 事件（agent 名/exit/transcript 回执）+ pollRev 10s 兜底（SSE 半死不锁死）+ Inspector 删画布总览 + SessionRail 折叠 | ✅ | pytest 142 / build 68 modules / smoke_accept 卡死 running=无（18999 真机复验） |
| P4a 从零编剧+skill 集 | 无小说自动「想法→创作简报→小说素材」+ `.agents/skills/htv-video-production` + `htv-h3-prompt` + build_project_summary 看板状态段 | ✅ | 165 测试；真实 LLM 冒烟（民国旗袍女特工 5.5 分钟全链，23 事件无卡死，小说/简报/剧本/分镜 7 镜落盘）；两 skill 被 harness 目录识别 |
| P4 设置页 | SettingsDialog 三子菜单（model provider+测试连通 / harness 检测+可调用测试 / 压缩阈值+skill 管理）+ /api/eco + /api/config-agent/test | ✅ | 165 测试（+test_eco 13）；76 modules；冒烟：eco 43 项含 htv skills、kimi 0.36.1 连通、lhh 检测 OK、context_limit 读写回 |
| P5 文档版本/diff/回滚 | doc_versions 快照/回滚/diff + 前端撤销条/版本历史/diff 高亮 + ai_writer 链式写入快照（P5.1 补） | ✅ | 165 测试；77 modules；冒烟：PUT storyboard→快照→改→回滚→rev/doc.diff 广播 PASS |
| P6a 后端 AI 全能力 | 7 新工具分支（asset/image-gen/prompt/select/restore/compose-order/settings）+ render 硬前置 403 + selected 幽灵过滤 + compose 按序 + patch reorder（交换镜） | ✅ | 224 测试；18997 冒烟全通（含「给角色C01生成参考图」引导、「交换镜1和镜2」生效） |
| P6b 前端工作流重构 | 删剧本 AI 按钮 + 角色/场景资产下拉 + 分镜提示词面板（空则禁抽卡）+ 候选播放试看+显式选中 + ShotCard 只读摘要 + 成片编排台（拖拽重排→compose-order） | ✅ | 77 modules；18999 联验：render 403/selected 过滤/order 全过 |
| P6c T8 融合+配置化 | h3_prompt_enhance LLM 反推（rule/llm 开关）+ /api/workflows 工作流配置化 + /api/config-section + 设置页生图 Provider/工作流区块 | ✅ | 241 测试；18997 冒烟：LLM 反推真对话「阴雨赛博朋克」三段式含描述元素 |
| P6d skill 工具化 | h3_prompt_enhance 自动加载已装 skill（h3-prompt-writing 官方公式优先）+ skill-create 元 skill + manager skill 分支 + /api/skills（list/install/create）+ 设置页③安装/创建入口；官方 h3-prompt-writing 已装；T8 enhancer 已装 ComfyUI custom_nodes | ✅ | 269 测试；build 77 modules；18999 终验：skills 40 项、workflows/eco 正常、主链路无回归 |
| P7a 验收修复 | 网格模式内容消失（顶层 ref 解包 .value TypeError，一行修复+全 SFC 扫描）+ 抽卡面板收敛（删模式/参考图下拉，参数全由分镜卡+config 派生；参考图自动关联只读展示）+ 无会话可直接输入自动建会话 | ✅ | build 77 modules；Node 仿真复现→修复验证；18996 冒烟全通；后端零改动 |
| P5 diff/回滚 | 文档版本 + 撤销 + 打磨 | ⬜ 待定 | — |

## 3. 后端（DSH）

| 项 | 状态 | 说明 |
|---|---|---|
| agent.py（provider 预设/chat/generate/parse_command） | ✅ | 23 测试 |
| cli.py（--json + 退出码契约） | ✅ | 14 测试 |
| ai_writer 迁移到 agent 薄兼容层 + 系统提示词 | ✅ | 委托测试 |
| common.parse_yaml_subset 引号剥离修复 | ✅ | TDD 修复 401 根因 |
| refs.py（Shot ref 存储层 + 首帧晋升 F9） | ✅ | 8 测试 |
| server.py：shot-ref / canvas 聚合 / agent-command / 资产删除 | ✅ | 端到端冒烟通过 |
| **真实 AI 整改**：单步编剧 job 化（真实进度）+ storyboard-gen LLM 优先（系统提示词+表格格式，失败回退解析器） | ✅ | 真实冒烟：小说→事件图谱生成成功（llm 模式）；llm_storyboard 4 测试 |
| asset_manager.remove_asset（CLI remove + DELETE API） | ✅ | 4 测试；种子 mock 数据已清理（仅留 C01_少年 真实图例） |
| 测试基线 | ✅ | **72 例全绿**：test_agent/test_cli/test_core/test_refs/test_assets |

## 4. 未决问题（闭环记录）

| # | 问题 | 答复/归属 | 状态 |
|---|---|---|---|
| Q1 | 参考图图片由谁生成 | DSH 后端补 POST 出图任务（F9）；前端先做 image:null 占位 | ✅ 已答复，F9 排队 |
| Q2 | wizard 是否加 state 三档 | 不加，前端推导（Kimi 方案） | ✅ 已答复 |
| Q3 | 已用接口是否稳定契约 | 确认稳定（均实现于 server.py） | ✅ 已答复 |
| Q4 | kimi -p 模式文件编辑权限 | 实测：`-p` 默认可写文件（不可组合 -y/--auto） | ✅ 已闭环 |

## 5. 联调环境备忘

- Web 服务：`python web/server.py --port 18999`（smoke 用，后台 job pwsh-17 运行中）
- 冒烟数据：`output/smoke/E01`（分镜.md + refs/shot_01.prompt.md）
- kimi：`C:\Users\vincento\.kimi-code\bin\kimi.exe` v0.36.1，模型 `kimi-code/k3-256k`，thinking effort=max（已改 config.toml）
- ComfyUI：**已上线**（**0.33.0**，`--enable-manager`，端口 9288，后台 job pwsh-41）；**稳定配置 = 动态显存开启（默认，INT8 32GB 必需）+ SolAttn 已禁用**（`--disable-dynamic-vram` 会 access violation，不可用）；抽卡 4 镜成功（shot_01~04 候选已产出）
- 崩溃排障记录：①aimdo 动态显存 hostbuf abort（偶发，发生在外来无效工作流插入时）②SolAttn Triton 编译失败（嵌入式 Python 缺 Python.h → 已禁用该节点）③`--disable-dynamic-vram` 下 INT8 加载 access violation（不可用，已回退）；另有来源不明的 `node #201/#211 无效工作流` 提交（疑为浏览器中 ComfyUI 标签页自动重放坏工作流，建议关闭多余 9288 标签页）
- 启动方式：`run_nvidia_gpu.bat` 已修正为 `--enable-manager --port 9288 --listen 127.0.0.1`（`--with-manager` 不存在）；后台直跑命令（bat 的 pause 会拖死后台任务树）；Manager 依赖安装自重启循环已通过清空 startup-scripts 解决
- 工作流对接双模式（spec 07）：builtin（内置 H3 构造器，本次抽卡实测）/ template（可视化导出 JSON + config mapping 注入，8 测试）
- **镜头提示词对齐官方 MiniMax H3 规范**（`prompts/h3-shot-prompt.md` = 生成系统提示词资源）：`render.build_h3_shot` 输出官方三段式（integrated_multimodal_description / overall_soundscape / non_diegetic_music），镜头运动含类型+幅度+速度、对白 (S1)+`<d>[Chinese]>`、无音效/BGM 写 N/A；预览接口 `shot_prompt_full` 委托同一实现（预览即所生成）；**TODO：后续将本资源转为 skill（`.agents/skills/htv-h3-prompt/SKILL.md`）**；测试基线 88 例全绿
- 抽卡 bug 修复：LLM 时长列 "4s" → parse_dur 容错（81 测试全绿）
- **LLM 预设（2026-08 更新）**：deepseek = `deepseek-v4-flash`（用户指定，一键 AI 编剧用；key/url 沿用 config 现有值），v4 flash 冒烟通过
- **链式真实生成已实测**（smoke 项目，v4 flash）：小说→事件图谱✅→故事骨架✅(1553字)→逐集剧本✅(3377字，含镜头序列)→资产清单✅(2057字)→**镜头分镜✅(method=llm，AI 拆分 10+ 镜)**；storyboard-gen 已 job 化，前端两处调用方已适配轮询契约

## 6. 里程碑状态（追加）

| 里程碑 | 内容 | 状态 |
|---|---|---|
| **AI 访谈（一站式第一步）** | 追问（grill 风格）→ 创作简报 → 注入链式生成 | ✅ 后端 /api/onboard（追问+简报，真实冒烟）；前端 OnboardPanel（Kimi 交付，build 通过）；简报 GET/PUT 契约已补（/api/creative.brief + PUT /api/brief） |
| **Agent Adapter 框架（spec 08，对齐 LongHorizon-Harness）** | 宿主主循环 + 外部 harness agent 执行（kimi/codex/claude/dsh） | ✅ `agentbridge.py`（TaskStore + AgentAdapter + Kimi/Codex/Claude/Dsh 适配器 + Manager.run_task + Auditor）11 测试；`cli.py agent-run/resume/list`（--json 契约）；**真实冒烟**：kimi 审查 39 镜分镜 → transcript 158 行全程留痕 + result.json（3 条证据化建议） |
| **Agent 会话工作台（spec 09，所改即所得）** | 会话 → 变更清单 → 写盘 → 即时回显；统一 4 个 agent 触点 | ✅ P1 写盘核心 `workflow_patch.py`（patch_shot/script_block/ref_prompt + parse_edit_action + /api/agent-edit + /api/patch）13 测试，端到端冒烟（patch→分镜.md→canvas 回显）；✅ P2 前端 AgentPanel + Inspector 双 Tab（Kimi 交付，62 modules build）；P3 外部任务回写 / P4 布局整合 待续 |
| **Agent 编排架构（spec 10，对齐 LongHorizon-Harness）** | 统一侧边对话窗：推进卡 + 内置变更 + 外部 harness 委派（工作区=项目目录，改文件/调 CLI）+ rev 自动回显 | ✅ 组件：AgentAdapter（config 设置化 args/skills_dir/timeout）、Environment（cwd=项目目录）、Manager/Executor/Auditor、状态 agent/tasks/；设置：config `agent:` 段；推进模板 /api/flow-templates（7 卡）；**外部 agent 调 CLI 实测通过**（kimi 自主修正相对路径执行 cli.py）；**流式 transcript**（task_id 创建即暴露，实测 running 中可拉取）；前端：AgentDock 统一对话窗 + rev watcher（64 modules，Kimi 交付） |
| **ACP 交互式对话（spec 11，超出 LHH 范围但可达）** | 像原生 CLI 一样对话：多轮、流式、可中断；原生能力（skills/tools/搜索/读文件）全保留 | ✅ `AcpAdapter`（kimi acp stdio JSON-RPC：initialize/session/new[config: k3-256k+max+auto]/session/prompt 流式 chunk）；帧解析 6 单测；**真实冒烟**：HTTP 端点 /api/agent-chat（流式 lines + reply + 按项目常驻会话），两轮对话会话保持、读工作区文件成功；前端对话模式 UI 待切 |
| **LHH 自动 Loop（Manager→Executor→Auditor）** | 目标 → 内置 LLM Manager 决策下一步 → Executor（外部 adapter 或内置）单步执行 → Auditor（rev/文件校验）→ checkpoint/evidence → 继续/完成 | ✅ `run_loop`（状态机：decide/verify 可注入；状态落 agent/loops/<id>/；4 单测）；**真实冒烟**：kimi 执行改镜1灯光 → Auditor rev 校验通过，1 轮完成（57s）；内置 Manager 无外部 agent 时也能决策（判定无法推进则「完成」） |
| **LHH 官方仓库复用（模块化 + git pull 同步）** | 项目已 git init；`vendor/longhorizon-harness` = 官方 submodule（v0.1.5 af17ce8）；lhh.py vendor 优先导入，纯逻辑复用（DeepSeekHarnessAdapter/parse_audit_report/HarnessConfig…），Windows 限制已判定（manager.run 依赖 POSIX 原语→stdlib run_loop 驱动循环）；**同步 = git submodule update --remote（接口不变零改动）** | ✅ 实测 vendor 导入 + lhh_status |
| **业务 Auditor + 配置覆盖 + 前端补全（验收轮）** | 业务校验（分镜可解析/剧本非空/资产完整/成片存在，5 单测）；cli agent-loop（--audit 业务验收）；config.local.json 覆盖机制 + GET/PUT /api/config-agent（设置界面后端契约）；前端：AgentDock 对话模式（ACP 流式气泡）+ 设置面板（适配器/轮数/audit/LHH 状态）+ OnboardPanel 简报回写 + loadAll 选中态保持 | ✅ 全链路验收：4 镜选片→F9 参考图晋升（shot_01~04.png）→ 拼接成片 4MB；ACP 对话两轮会话保持；Loop 冒烟通过；前端 64 modules build；**测试基线 145 全绿** |
| **前端重构 P0+P1（设计文档 docs/11）** | P0 设置 bug 后端修复（`[]` 解析+类型归一化）；P1 三栏壳：左 AI 栏（会话/对话/输入骨架，可拖宽）/中栏四视图/右栏状态导航（三态折叠），EventTrace 暗夜绿流光垂直进度条组件，删 8 旧组件 | ✅ P0 实测通过；P1 build 66 modules + 冒烟全绿（kimi 交付）；P2 会话+manager 调度进行中 |
