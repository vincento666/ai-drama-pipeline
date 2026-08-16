---
name: htv-h3-prompt
description: 官方 MiniMax H3 镜头提示词三段式规范（integrated_multimodal_description / overall_soundscape / non_diegetic_music）。生成 H3 兼容镜头提示词、写/改参考图提示词（E{NN}/refs/*.prompt.md）、或为 ComfyUI 抽卡构造提示词时使用本 skill；生成入口 = scripts/render.py 的 build_h3_shot。
---

# H3 单镜提示词生成规范（官方 MiniMax H3 Prompt Guide 本地化）

生成入口：`scripts/render.py` 的 `build_h3_shot(shot, shot_no, start_sec, style, assets)` —— 按本规范把分镜行转成 H3 视频模型可直接消费的三段式提示词（`shot_prompt()` 为其别名）。手工编写/修改提示词时同样遵循本规范。

## LLM 反推增强（P6c，scripts/h3_prompt_enhance.py）

配置开关 `h3.prompt_enhance`：`rule`（默认，规则组装 = build_h3_shot）| `llm`（LLM 反推，失败自动回退 rule）。
`llm` 模式下，prompt 分支（对话「生成/刷新分镜提示词」）与 `POST /api/shot-ref`（Inspector 生成/刷新）走
`h3_prompt_enhance.enhance(shot, shot_no, start_sec, style, assets, desc, cfg)`，事件回执注明「LLM 反推」/「规则组装」。

### 输入输出契约（「用户描述 → 反推专业分镜提示词」）

- **输入** = 分镜行字段（景别/运镜/时长/角色/场景/灯光/对白音效/备注）+ 资产名/描述（外观锚定源，跨镜不得换词）+ 全局风格（config project.style_prefix）+ 用户附加描述（desc，如「画面要赛博朋克夜雨」，最高优先级）。
- **输出** = H3 三段式英文提示词（`integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`，缺一不可），可直接投喂 ComfyUI MiniMaxH3AudioConditioningT8。
- **校验与回退**：输出必须含三个段锚点，缺段补 `N/A`；LLM 调用失败或输出无法识别 → 回退 `build_h3_shot`（rule 模式），调用方以返回值 mode（`llm`/`rule`）写回执。

### LLM 反推公式与结构锚点（enhance 系统提示词内置，外部 agent 手写同款）

1. **主体+动作**：画面核心 = 主体（角色代号，外观锚定资产描述）+ 动作 + 场景环境（set in/at <场景>）。
2. **场景环境+光影色调**：每镜开场建立环境细节 + 光源类型/色温（lit by <光源>），并入全局风格色调。
3. **镜头运镜**：每镜只有一个主运镜（类型+幅度+速度的自然英文句），如 `The camera pushes in with small amplitude at slow speed toward the subject.`；严禁堆叠。
4. **视觉风格**：全局风格 <style> 作为风格锚点并入。
5. **画质约束**：结尾统一加 `High quality, sharp focus, filmic grade.`
6. **对白**：说话者标注 `(S1)`，台词用 `<d>[Chinese] 原文</d>` 包裹，保留原文不翻译。
7. **音效**：作为画面内动作声融入描述（`Sound of <sfx>`）；无音效写 `N/A`。
8. **参考锁定细节**：从分镜行与资产描述提取 **3-5 条受保护细节**（角色外观/道具/场景标志物）明确写出，保证跨镜一致性（对齐 docs/13 §1.1 一致性手段：参考锁定 3-5 个受保护细节）。
9. **用户附加描述**：与分镜行冲突时以用户描述为准。

### 引用来源

- 官方 MiniMax H3 Prompt Guide（本地化沉淀为本文件 §输出三段式 与 §气闸缓冲法）
- T8 提示词 skill：https://github.com/T8mars/minimax-h3-prompt-skill-T8
- T8 ComfyUI 提示词增强器（enhance 思路参考）：https://github.com/T8mars/comfyui-minimax-h3-prompt-enhancer-T8

## 输出三段式（缺一不可）

```
integrated_multimodal_description: [Shot 1] Live-action, cinematic, ...
overall_soundscape: ...
non_diegetic_music: ...
```

### 1. integrated_multimodal_description

- 开场：`[Shot 1] Live-action, cinematic, <景别> shot <画面核心>`
- **镜头运动**（类型+幅度+速度，自然英文句，非标签堆叠）：
  `The camera pushes in with small amplitude at slow speed toward the subject.`
  类型：Zoom In/Out、Push In/Pull Out、Pan Left/Right、Truck、Tilt、Pedestal、Arc、Tracking、Static、Shake、POV；幅度 `with small/large amplitude`、速度 `at slow/fast speed`（中等幅度与正常速度通常省略）。
- **环境与光照**：每镜开场建立环境细节+光源类型/色温（`set in/at <场景>，<灯光>`）。
- **人物**：`featuring <角色代号/名>`（外观锚定源：资产库；跨镜保持一致，同一人物不得换词）。
- **对白**：说话者标注 `(S1)`，台词用 `<d>[Chinese] 原文</d>` 包裹，保留原文不翻译。
- 音效作为画面内动作声融入描述（`Sound of <sfx>`）。
- 多镜头：首镜无时间戳 `[Shot 1]`，后续 `[Shot 2] At 00:02.500, the camera cuts to...`（时间轴格式 `At hh:mm:ss.mmm`）。
- 场内可见文字用英文双引号包裹并保留原文（如 `"天海集团"`）。

### 2. overall_soundscape

- 1–4 句英文：环境音 + 物理动作音 + 非语言人声（呼吸/沉默）。
- 不重复对白与 BGM。无环境音写 `N/A`。

### 3. non_diegetic_music

- 1–3 句英文：乐器配置 / BPM / 节奏模式 / 动态（起落爆收）。
- 与上一镜的衔接说明（气闸缓冲：新镜开头保持上镜末构图约 2 秒+微小运动，再切新场景）。
- 无 BGM 写 `N/A`（分镜备注含「无BGM/静音/无配乐」时）。

## 气闸缓冲法（串联镜头防画面杂糅）

模型是叠加而非替换：上一镜结尾大特写，下一镜直接写全景会把两画面杂糅。
- 新镜开头不要同时要求延续和改变；保持上镜末构图约 2 秒（无对白），再切新场景。
- 缓冲期保持微小运动（呼吸/重心转移/视线改变），相机静止、演员微动。

## 与生成器的一致性

- `build_h3_shot` 的相机运动句由 `render._camera_sentence()` 映射（push in / pull back / pan / tilt / tracking / handheld / orbit / crane / static 等，未命中回退 static）。
- 对白/音效拆分由 `gen_storyboard.classify_audio()` 完成（`对白：`/`音效：`/`环境音：`前缀）。
- 无 BGM 判定：`build_h3_shot` 检查备注/风格文本含「无BGM/静音/无配乐/no music/silent」→ `non_diegetic_music: N/A`。
- 时长帧数：`render.snap_frames()` 把秒数映射到 H3 原生帧网格（17n+5，限幅 22..360）。
