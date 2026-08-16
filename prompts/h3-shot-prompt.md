# H3 单镜提示词生成规范（官方 MiniMax H3 Prompt Guide 本地化）

> 用途：**生成系统提示词**（当前）——渲染层按本规范把分镜行转成 H3 视频模型可直接消费的提示词。
> 未来迁移：本文件将转为 skill（`.agents/skills/htv-h3-prompt/SKILL.md`），供 LLM Agent 写 H3 提示词时加载。
> 源规范：`S:/Develop/AIGC/ComfyUI/workflows/20260811自动短剧/剧本转视频提示词生成指令.md`（官方结构 §3.3–3.5）。

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
  类型：Zoom In/Out、Push In/Pull Out、Pan Left/Right、Truck、Tilt、Pedestal、Arc、Tracking、Static、Shake、POV
- **环境与光照**：每镜开场建立环境细节+光源类型/色温（`set in/at <场景>，<灯光>`）。
- **人物**：`featuring <角色代号/名>`（外观锚定源：资产库；跨镜保持一致）。
- **对白**：说话者标注 `(S1)`，台词用 `<d>[Chinese] 原文</d>` 包裹，保留原文不翻译。
- 音效作为画面内动作声融入描述（`Sound of <sfx>`）。

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
