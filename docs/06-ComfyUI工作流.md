# 06 · ComfyUI 工作流（T2V / I2V / 首尾帧 / Ref2VA）

四条工作流对应四种生产场景。建议在 ComfyUI 里另存为模板，一条条验证通过后复用。

## 0. 前置

- ComfyUI 0.30+，H3 节点已加载（`02`）
- 权重按 `config.yaml` 的 `h3:` 节放好
- 先用 h3-studio 的前端（`03`）写提示词，工作流负责执行

## 1. T2V（文生视频）——铺底镜头

节点链：
```
EmptyMiniMaxH3LatentAV (width/height/frames/batch)
   ↓
CLIPTextEncode (positive = H3 三段式提示词) ──→ MiniMaxH3ModelSampling
   ↓
KSampler (steps=20, res_multistep + simple, cfg 用节点默认)
   ↓
VAEDecode (video_vae) ──→ CreateVideo
   ↓                    ↑
VAEDecodeAudio (audio_vae) ─┘   ← 两个 VAE 都必须接，否则无声
```
用于：环境镜头、过场、不需要角色锁定的戏。

## 2. I2V（图生视频）——首帧驱动

```
LoadImage (首帧图, 例如分镜图的某一格) ──→ MiniMaxH3ImageToVideo
                                              ↓
                           EmptyMiniMaxH3LatentAV (同尺寸) → 采样 → 双 VAE 解码 → CreateVideo
```
用于：从分镜图/宫格切出来的单格，直接动起来。
**注意**：首帧会被拉伸而非裁剪到目标分辨率——首帧图按目标画幅生成（如 864×1536），别硬缩。

## 3. FL2V（首尾帧插值）——关键帧驱动的核心

```
LoadImage (首帧) ──┐
                  ├──→ MiniMaxH3ImageToVideo (image_end 也接上)
LoadImage (尾帧) ──┘        ↓
             EmptyMiniMaxH3LatentAV → 采样 → 双 VAE → CreateVideo
```
用于：**"先画后动"**——分镜图决定镜头起止构图，模型只做中间插值。业界关键帧驱动方法论的标准落地。
建议用 `MiniMaxH3SigmaShift` 微调插值强度（默认即可）。

## 4. Ref2VA（引用生视频）——人物一致性主力

```
LoadImage (角色定妆照, 1-2 张) ──→ MiniMaxH3ReferenceToVideo (ref_images.ref_image_0/1)
                                        ↓
                EmptyMiniMaxH3LatentAV → 采样 → 双 VAE → CreateVideo
```
用于：任何**必须出现指定角色**的镜头（对白戏、特写戏）。

### ⚠️ 三个高频坑（h3-studio 实测总结）

1. **API 图里参考输入必须是点命名** `ref_images.ref_image_0`——裸名 `ref_image_0` 会被**静默忽略**：能出片、角色完全不像、不报错。手搓图小心。
2. **Ref2VA 用独立 checkpoint**（`minimax_h3_ref2va_*`），不是 FL2V 权重。用错了同上是"能出片但零相似度"。
3. **首尾帧与引用图不能混用**：Ref2VA 没有 keyframe 输入，同一工作流填了两类输入会互相清除。

## 5. 分辨率/时长策略（写进 config）

| 用途 | 分辨率 | 帧数 | 备注 |
|---|---|---|---|
| 横屏质量标杆 | 1024×576 | 124-360 | 8:5，token 网格 32×18 |
| 竖屏短剧 | 864×1536 | 124-240 | 9:16，注意显存（16GB 卡接近上限） |
| 快手式段子 | 1080×1920 谨慎 | ≤240 | 竖屏大分辨率 16GB 卡可能 OOM，先测 |
| 低配兜底 | 864×480 | 124 | 只建议非人脸镜头 |

## 6. 批量抽卡（省人力）

- ComfyUI 内置 **Queue 多次**（Queue Prompt 下拉）或 CLI `--run` 批处理
- 建议：同一分镜固定 seed 跑 3-5 个变体（抽卡），人只挑最好的一条
- 每批结果自动落在 `output/video/`，按时间戳区分；`pipeline.py` 会扫描这些文件做完整性校验（见 07）

## 7. 无字幕规则

成片字幕用剪辑阶段加（剪映/ffmpeg），H3 阶段一律提示词排除："No text, subtitles, logos or watermarks of any kind."——AI 生成的文字大概率错字。
