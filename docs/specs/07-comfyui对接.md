# 07 · ComfyUI 对接（启动 + 工作流配置模式）

> 状态：进行中 · 目标：抽卡真实跑通（本机 ComfyUI + H3）+ 工作流对接方式定案

## 1. RHTV 怎么做（参考）

RHTV/RunningHub 的工作流是**云端托管**：
1. 用户在 RunningHub 平台（ComfyUI 节点编辑器）**可视化搭建**工作流；
2. 发布为可调用应用/API（有参数面板：prompt/比例/时长/参考图等）；
3. RHTV Agent 画布按任务类型**自动选工作流 + 填参数**提交执行，结果回填画布。

结论：RHTV = **可视化搭一次 → 参数化调用**。用户不碰节点，但也改不了引擎内部——它给你的是"参数表单"。

## 2. 本项目的对接模式（本地化对应）

与 RHTV 同构，落地为**两种模式共存**（`config.yaml` 的 `workflow.mode` 切换）：

| 模式 | 工作流来源 | 参数来源 | 适用 |
|---|---|---|---|
| `builtin`（默认） | 程序内置 H3 API 工作流构造器（render.py build_workflow，已冒烟实测） | config 的 h3 模型名 + generate 参数 | 开箱即用，零配置 |
| `template`（新增） | **可视化导出**：ComfyUI 原生 UI 搭好 → Export(API/UI) → JSON 文件放本地 | `workflow.mapping`：业务参数 → 节点槽位映射 | 换社区工作流不改代码；对齐 RHTV「可视化搭 + 参数调用」 |

**模板模式流程**：
1. 浏览器开 `http://127.0.0.1:9288`（ComfyUI 原生 UI）搭/改工作流；
2. `Save (API Format)` 导出 JSON 到本机目录（如 eco.sources 里已有的 20260811自动短剧/H3 工作流）；
3. `config.yaml` 声明 `workflow.template` 路径 + `workflow.mapping`（业务参数 → `节点id.inputs.槽位`）；
4. 程序：加载模板 → 注入参数 → POST /prompt → 轮询 history → 取产物。

**为什么不是"纯可视化配置"**：程序里写死的是**参数注入映射**而不是节点逻辑；节点逻辑永远在 ComfyUI 侧可视化管理——这是和 RHTV 一样的边界（我们不重造 ComfyUI 的编辑器）。

## 3. 契约

```yaml
workflow:
  mode: builtin          # builtin | template
  template: S:/Develop/AIGC/ComfyUI/workflows/video_minimax_h3_t2v.json
  mapping:               # 业务参数 → 模板节点槽位（node_id.inputs.param）
    prompt: 6.inputs.prompt
    width: 6.inputs.width
    height: 6.inputs.height
    frames: 6.inputs.length
    seed: 8.inputs.noise_seed
    image: 0.inputs.image          # 可选：I2VA 首帧
    ref_image: 20.inputs.image     # 可选：Ref2VA
    prefix: 12.inputs.filename_prefix
```

seam（测试只打这些）：
- `render.ui_to_api(wf_ui)` — UI 格式 → API 格式（widget_values→inputs，去 _meta）
- `render.load_template(path)` — 读 JSON（UI 或 API 格式均可，UI 自动转换）
- `render.inject_params(wf, mapping, params)` — 槽位注入；映射缺槽位 → ValueError
- `render.resolve_workflow(cfg, **params)` — 按 mode 分派；template 缺失 → ConfigError

## 4. 启动方式（本机 portable）

```
cd S:\Develop\AIGC\ComfyUI\ComfyUI_windows_portable
.\python_embeded\python.exe -s ComfyUI\main.py --port 9288 --listen 127.0.0.1
```
探测：`GET http://127.0.0.1:9288/system_stats`。抽卡经 `POST /api/render`（Web 桥）或 CLI。
