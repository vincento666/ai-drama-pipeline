# H3 三段式提示词模板（本地 ComfyUI / h3-studio）

> H3 不吃自由文本。本地必须用三段式 schema，字段顺序固定，空行分隔。
> 用 h3-studio 的提示词助手自动生成（docs/03），本模板用于手写/校对。

## 结构

```
integrated_multimodal_description: <逐镜头描述>

overall_soundscape: <环境音/拟音>

non_diegetic_music: <配乐>
```

## 逐镜头描述规则

- 第一个镜头：`[Shot 1]`（不带时间戳）
- 后续镜头：`[Shot 2 · 00:00:05]`（本镜头开始时间）
- 对白：`<d>[Chinese] 台词内容</d>`（语言标签必填）
- 说话人：在描述中标注 `(S1)`、`(S2)`
- 镜头词汇用封闭词表（见 docs/05），不要自由发挥
- 结尾可加排除句：`No text, subtitles, logos or watermarks of any kind.`

## 完整示例（抄改自 MiniMax 官方指南）

```
integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium-wide
shot frames a baker opening the shutters of a small street bakery before sunrise.
The camera pushes in with small amplitude at slow speed as the middle-aged baker
with a calm, slightly raspy voice (S1) places a fresh loaf on the wooden counter
and says: <d>[English] First batch of the morning.</d>

overall_soundscape: Wooden shutters scrape open over a quiet street as trays clink
softly inside the bakery. The doorbell rings once, followed by light footsteps.

non_diegetic_music: A soft acoustic-guitar pattern at a moderate tempo, joined by
sparse upright-bass notes and a gentle fade at the end.
```

## 三段式速填模板

```
integrated_multimodal_description: [Shot 1] Live-action, cinematic, a {景别}
shot frames {主体} in/at {场景}, with {机位运动} camera movement, {灯光}
lighting. {主体特征/动作} and says: <d>[Chinese] {对白}</d>.

overall_soundscape: {环境音}，{音效1}，{音效2}。

non_diegetic_music: {配乐风格} at a {节奏} tempo, matching the {情绪} mood,
with a gentle fade at the end.
```

## 常见坑

- 无 negative prompt：排除内容写进描述末尾散文句
- 无 guidance_scale：distilled 模型单遍前向，别调 cfg
- 上限 ~7000 字符，超长拆两段
- 别用 SageAttention 2（纯噪声）；面部细节优先 1024×576+
