# 02 · 安装 ComfyUI + MiniMax H3（生成引擎）

> 以下命令在**生成引擎机器**上执行（本机或云 GPU）。全部基于开源官方通道。

## 1. 安装 ComfyUI

ComfyUI 0.30.0+ 已**原生内置 H3 节点**（`MiniMaxH3ImageToVideo`、`MiniMaxH3ReferenceToVideo`、`EmptyMiniMaxH3LatentAV`、`MiniMaxH3SigmaShift` 等），无需额外装主节点包。

```bash
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI

# 创建虚拟环境（推荐 uv，快）
uv venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt

# 启动（16GB 卡建议加 --use-sage-attention；注意：见下方警告）
python main.py --listen 0.0.0.0 --port 8188
```

浏览器打开 `http://<机器IP>:8188` 即见 ComfyUI。

### ⚠️ SageAttention 警告（H3 专属坑，先记住）

h3-studio 实测：**SageAttention 会毁掉 H3 的高频细节**（眼睛等小特征糊成"旋涡"）。H3 的注意力带 QK-RMSNorm + 部分 RoPE，int8 量化扛不住。
- 若发现面部细节糊：**去掉 `--use-sage-attention`**；
- 或给 `comfy/ldm/minimax/model.py` 的调用加一行 `low_precision_attention=False`（会随 git pull 被还原，改后别急着 pull）；
- 千万别用 SageAttention 2（纯噪声）。

## 2. 安装 H3 节点包（官方）

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Comfy-Org/ComfyUI-MiniMaxH3.git
# 重启 ComfyUI 即可加载节点
```

## 3. 下载 H3 权重

权重在 HuggingFace `Comfy-Org/MiniMax-H3`（国内可用 ModelScope 镜像）。放入对应目录：

| 文件 | 放入目录 |
|---|---|
| `minimax_h3_*_nvfp4.safetensors`（扩散模型，T2V/I2V/FL2V 共用） | `ComfyUI/models/diffusion_models/` |
| `minimax_h3_ref2va_*.safetensors`（引用生视频专用，人物一致性） | `ComfyUI/models/diffusion_models/` |
| `minimax_h3_video_vae_fp16.safetensors`（视频 VAE） | `ComfyUI/models/vae/` |
| `minimax_h3_audio_vae_fp32.safetensors`（音频 VAE） | `ComfyUI/models/vae/` |
| `qwen3vl_32b_minimax_h3.safetensors`（文本编码器） | `ComfyUI/models/text_encoders/` |

下载示例（HF CLI 或浏览器）：

```bash
# 用 huggingface-cli 下载到当前目录后手工移动
huggingface-cli download Comfy-Org/MiniMax-H3 --include "*.safetensors" --local-dir ./h3_weights
```

> 文件名与 `config.yaml` 的 `h3:` 节保持一致。**Ref2VA 用单独 checkpoint**，别拿 FL2V 的模型跑引用生视频（会静默失败：能出片但完全不锁角色）。
>
> 验证权重（h3-studio 提供脚本，可查社区被改过的 .safetensors）：
> ```bash
> cd ComfyUI/custom_nodes/h3_studio && ./scripts/verify_models.sh /path/to/ComfyUI
> ```

## 4. 首次冒烟测试

1. ComfyUI 默认自带 H3 示例工作流（Workflow 菜单或拖入 `custom_nodes/ComfyUI-MiniMaxH3/*.json`）。
2. 若无，从 [ai-models-lab/minimax-h3](https://github.com/ai-models-lab/minimax-h3) 或 minimaxh3.run 导出一份 T2V 工作流 JSON，拖进 ComfyUI。
3. 填提示词（H3 三段式，见 `05-提示词模板.md`），点 Queue。

**通过标准**：`output/video/` 出现带声音的 MP4。若无声，检查是否**两个 VAE 都接了 CreateVideo**（视频 VAE + 音频 VAE 缺一即静音）。

## 5. 常见问题速查

| 症状 | 处理 |
|---|---|
| 找不到 H3 节点 | ComfyUI < 0.30，升级；或节点没装进 `custom_nodes/` |
| CUDA OOM | 降到 864×480 + 124 帧；确认显卡上没有 LLM/浏览器占显存；1344×768 在 16GB 卡峰值 ~15.6GB 会炸 |
| 视频无声 | 两个 VAE 都要接 CreateVideo |
| 出片但角色不像 | 检查是否误用 FL2V 权重跑 Ref2VA；参考节点输入必须是 `ref_images.ref_image_0` 点命名（裸名会被静默忽略） |
| 面部糊 | 去掉 SageAttention / 提到 1024×576+ / 用近景（眼睛在 864×480 中景只占 ~0.28 token，物理上无法精细） |
| 输出无字幕/logo | H3 无 negative prompt，把排除项写进描述末尾："No text, subtitles, logos or watermarks of any kind." |
