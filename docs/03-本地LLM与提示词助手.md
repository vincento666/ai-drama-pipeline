# 03 · 本地 LLM 提示词助手（h3-studio）

## 为什么需要它

H3 **不吃自由文本**。MiniMax 线上管线有一个闭源的 `H3-Context-IR` 把普通描述改写成结构化 schema，只有 schema 才到达权重。ComfyUI 本地没有这个改写器——你输入什么它就生什么。
h3-studio 就是本地的开源替代：一个 ComfyUI 自定义节点 + 单页前端，用**本地 LLM** 把你的口语需求扩写成 H3 三段式提示词，并做格式校验/自纠错。

## 1. 安装 h3-studio

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/CharlesMod/h3-studio.git h3_studio
cd h3_studio
./scripts/fetch_corpus.sh    # 可选但推荐：下载 MiniMax 官方提示词指南做 few-shot
# 重启 ComfyUI
```

前端地址（无需单独起服务）：`http://127.0.0.1:8188/extensions/h3_studio/index.html`

## 2. 装一个 OpenAI 兼容的本地 LLM

h3-studio 的提示词助手需要一个 LLM 端点（三选一）：

| 方案 | 命令 | 说明 |
|---|---|---|
| Ollama（最省事） | `ollama serve`（默认 `127.0.0.1:11434`） | `ollama pull gemma4:26b-a4b` 等 |
| llama.cpp | `llama-server -m model.gguf --port 8080` | 端点默认 `127.0.0.1:8080` |
| LM Studio | 图形界面开 server | 同上 |

**选型建议（h3-studio 作者实测）**：MoE 模型最合适——`Gemma 4 26B-A4B` 只激活 4B 参数，专家放系统内存，显存只占 ~8GB，写提示词比稠密 12B 快约 3 倍。16GB 显卡上，H3(15.5GB) 和 12B LLM(14.7GB) 无法同驻，h3-studio 会自动做 **VRAM handoff**（生成时卸载 LLM，写提示词时卸载 H3）。

## 3. 配置端点

浏览器打开 h3-studio 页面 → 左侧 Endpoints 面板：

- **H3 / ComfyUI**：默认就是同源服务器，不用改
- **LLM**：`http://127.0.0.1:11434`（**不要带 /v1**，会自动追加 `/v1/chat/completions`）
- **Model**：留空自动探测；也可用环境变量 `H3_LLM_BASE` / `H3_LLM_MODEL` 强制

点 **Test** 确认两端连通。

## 4. 工作方式（人只需打字+挑片）

1. 输入口语 brief，如：`一个古装少女在竹林里舞剑，镜头缓慢推近，带点伤感`
2. 助手扩写成三段式 schema（`integrated_multimodal_description` + `overall_soundscape` + `non_diegetic_music`），**专有名词（人名/地名/导演/风格）自动钉住不被改写**
3. 校验失败时自动返回 LLM 自纠错，直到符合格式
4. 一键 Queue 生成；每段结果留在会话 filmstrip 里，点击可回放当时的提示词与参数

## 5. 人物一致性开关（Ref2VA）

- 上传**角色照片**（1-2 张）→ 自动切换到 Ref2VA checkpoint + 六段式参考 schema，`subject_definitions` 会**看到照片**来写（需要 LLM 端点开视觉投影，llama.cpp 加 `--mmproj`；没有则自动降级纯文本并提示）
- 上传**首帧/尾帧图** → 自动切 I2VA/L2VA/FL2VA，并把"画面与参考对齐"的提示行写好（携带到两位小数的时长，模型自己算总错）

## 6. 生产参数基线（社区实测，写入 config.yaml）

| 参数 | 建议 | 说明 |
|---|---|---|
| 分辨率 | 1024×576（8:5 质量甜点）；短剧竖屏 864×1536 | 眼睛细节与 token 网格相关，别用 864×480 出人脸 |
| 帧数 | 124（约 5s）；单段上限 360（15s） | 短剧单镜头 5-10s 为宜 |
| steps | 20（res_multistep + simple） | 低于 15 质量明显下降，25 提升有限 |
| 时长续接 | 生成时勾选/手动延帧 | 长镜头靠延长功能续接，不是一次生成 |

## 7. 注意

- h3-studio 的输出是**临时文件**：关标签页/六小时/再生成都会清掉，要保留必须点 Download 下载到 `assets/` 或 `output/`。
- 它写的是"编辑 diff"而不是整体重写，省 token；手改提示词框会清上下文。
- 若助手空白无返回：请求已禁用 thinking（`enable_thinking: false`），若仍空则调大 `promptwriter.py` 里的 `MAX_TOKENS`。
