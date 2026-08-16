#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ComfyUI API 自动出片（HANDOFF 待办 #1）：逐镜提交 T2VA 工作流、批量抽候选、下载到 shots/。

用法：
  python scripts/pipeline.py render smoke --episode 1 --shots 2
  python scripts/render.py smoke --episode 1 --shots 2 --dry-run   # 只打印计划不提交

依赖：仅标准库（urllib）+ ComfyUI 已在 config.yaml 的 comfyui.base_url 运行。
模型名取自 config.yaml 的 h3: 节（与 ComfyUI 实际文件名一致）。
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from common import ConfigError, load_config, episode_dir, project_dir
from gen_storyboard import classify_audio, fmt_time, load_storyboard, parse_dur

FRAME_GRID = 17        # H3 原生帧网格 17n+5
FRAME_MIN = 22
FRAME_MAX = 360        # ~15s @24fps
AUDIO_SUFFIX = "-audio.mp4"  # VHS_VideoCombine 连音频时输出的文件名后缀
DEFAULT_TIMEOUT = 1800  # 单次 render 总超时（秒）


def snap_frames(seconds, fps=24):
    """时长(秒) → H3 原生网格帧数（17n+5，限幅 22..360）。"""
    n = max(1, round((seconds * fps - 5) / FRAME_GRID))
    return min(FRAME_MAX, max(FRAME_MIN, FRAME_GRID * n + 5))


def _camera_sentence(camera):
    """镜头运动三维度（类型+幅度+速度）自然英文句（官方 H3 规范）。"""
    c = (camera or "").strip().lower()
    mapping = [
        ("push in", "The camera pushes in with small amplitude at slow speed toward the subject."),
        ("push", "The camera pushes in toward the subject."),
        ("pull back", "The camera pulls out slowly from the subject."),
        ("pull", "The camera pulls out from the subject."),
        ("pan left", "The camera pans left slowly."),
        ("pan right", "The camera pans right slowly."),
        ("tilt up", "The camera tilts up slowly."),
        ("tilt down", "The camera tilts down slowly."),
        ("tracking", "The camera tracking follows the moving subject."),
        ("跟随", "The camera tracking follows the moving subject."),
        ("handheld", "The handheld camera sways slightly with natural shake."),
        ("手持", "The handheld camera sways slightly with natural shake."),
        ("orbit", "The camera arcs around the subject."),
        ("环绕", "The camera arcs around the subject."),
        ("crane", "The camera rises with a crane shot."),
        ("升降", "The camera rises with a crane shot."),
    ]
    for key, sent in mapping:
        if key in c:
            return sent
    return "The camera holds a static shot."  # 默认/static


def build_h3_shot(shot, shot_no, start_sec, style="", assets=None):
    """按官方 MiniMax H3 提示词规范生成单镜三段式（prompts/h3-shot-prompt.md）。

    integrated_multimodal_description / overall_soundscape / non_diegetic_music 缺一不可；
    镜头运动含类型+幅度+速度；对白 (S1)+<d>[Chinese]…</d>；无音效/BGM 写 N/A。
    """
    assets = assets or {}
    frame = shot.get("frame") or "medium"
    scene = shot.get("scene") or "the location"
    chars = shot.get("chars") or ""
    light = shot.get("light") or ""
    note = shot.get("note") or ""
    dialogue, sfx = classify_audio(shot.get("dialogue") or shot.get("sfx"))
    sfx = (sfx or "").strip()

    parts = ["[Shot %d%s] " % (shot_no,
                               " · %s" % fmt_time(start_sec) if shot_no > 1 else "")]
    parts.append("Live-action, cinematic, a %s shot of %s" % (frame, scene))
    if light:
        parts.append(", lit by %s" % light)
    parts.append(".")
    parts.append(" " + _camera_sentence(shot.get("camera")))
    if chars:
        names = []
        for code in [x.strip() for x in str(chars).split("、") if x.strip()]:
            code = code.split("/")[0].strip()
            nm = assets.get(code, {}).get("name", "")
            names.append("%s%s" % (code, ("(%s)" % nm) if nm else ""))
        parts.append(" Featuring %s." % " and ".join(names))
    if sfx:
        parts.append(" The sound of %s is heard in the scene." % sfx)
    if note:
        parts.append(" %s" % note)
    if dialogue:
        parts.append(" (S1) says: <d>[Chinese] %s</d>" % dialogue)
    desc = "".join(parts)

    # overall_soundscape：环境音 + 动作音 + 非语言人声；无则 N/A
    sc = []
    if sfx:
        sc.append("The sound of %s." % sfx)
    sc.append("Natural room tone consistent with the scene.")
    soundscape = " ".join(sc)

    # non_diegetic_music：风格/备注驱动 1-2 句；含 无BGM/静音/无配乐 → N/A
    low = ((style or "") + " " + (note or "")).lower()
    if ("无bgm" in low or "静音" in low or "无配乐" in low or "no music" in low
            or "无音乐" in low or "silent" in low or "静默" in low):
        music = "N/A"
    else:
        music = ("A subtle, emotion-driven score matching the drama of this shot, "
                 "rising and fading gently with the action. "
                 "No text, subtitles, logos or watermarks.")
    style_prefix = (style + ". ") if style else ""
    return ("integrated_multimodal_description: %s%s\n\n"
            "overall_soundscape: %s\n\n"
            "non_diegetic_music: %s"
            % (style_prefix, desc, soundscape, music))


def shot_prompt(shot, shot_no, start_sec, style):
    """单镜 H3 三段式提示词（按官方规范，prompts/h3-shot-prompt.md）。"""
    return build_h3_shot(shot, shot_no, start_sec, style)


def build_workflow(cfg, prompt, width, height, frames, steps, seed, prefix, image=None, ref_image=None):
    """构造 H3 API 工作流（与实测通过的冒烟模板同构，模型名取自 config）。

    image 为 None → T2VA；给首帧图（ComfyUI/input 下）→ I2VA；
    ref_image 给参考图 → Ref2VA（人物一致性，用 ref2va 权重、不挂 turbo LoRA）。
    """
    h3 = cfg.get("h3", {})
    wf = {}
    if ref_image:  # Ref2VA：加载参考图（人物一致性）
        wf["20"] = {"class_type": "LoadImage", "inputs": {"image": ref_image}}
        unet_name = h3["ref2va_model"]
        has_lora = False   # Ref2VA 与 turbo LoRA 不完整兼容，不挂
    else:
        if image:  # I2VA：首帧图作为 exact frame 0
            wf["0"] = {"class_type": "LoadImage", "inputs": {"image": image}}
        unet_name = h3["diffusion_model"]
        has_lora = bool(h3.get("turbo_lora"))
    wf["1"] = {"class_type": "VAELoader",
               "inputs": {"vae_name": h3["video_vae"]}}
    wf["2"] = {"class_type": "VAELoader",
               "inputs": {"vae_name": h3["audio_vae"]}}
    wf["3"] = {"class_type": "CLIPLoader",
               "inputs": {"clip_name": h3["text_encoder"], "type": "minimax"}}
    wf["4"] = {"class_type": "UNETLoader",
               "inputs": {"unet_name": unet_name, "weight_dtype": "default"}}
    if has_lora:  # 量化基模用 bypass LoRA，避免 dtype 转换失败
        wf["5"] = {"class_type": "LoraLoaderBypassModelOnly",
                   "inputs": {"lora_name": h3["turbo_lora"], "strength_model": 1.0,
                              "model": ["4", 0]}}
        model_src = ["5", 0]
    else:
        model_src = ["4", 0]
    cond_inputs = {"prompt": prompt, "width": width, "height": height,
                   "length": frames,
                   "task_type": "Ref2VA" if ref_image else ("I2VA" if image else "T2VA"),
                   "audio_mode": "native", "audio_denoise_strength": 1.0,
                   "add_source_as_reference": False, "prompt_primary_audio_ordinal": 0,
                   "strict_prompt_tags": True, "ref_image_size": "match",
                   "reference_video_policy": "official_2_to_15s",
                   "clip": ["3", 0], "video_vae": ["1", 0], "audio_vae": ["2", 0]}
    if ref_image:
        cond_inputs["ref_image_0"] = ["20", 0]   # ComfyUI 0.31 autogrow 展开格式
    elif image:
        cond_inputs["first_frame"] = ["0", 0]
    wf["6"] = {"class_type": "MiniMaxH3AudioConditioningT8", "inputs": cond_inputs}
    wf["7"] = {"class_type": "MiniMaxH3DualClockSamplerT8",
               "inputs": {"steps": steps, "shift_video": 12.0, "shift_audio": 3.0,
                          "model": model_src, "av_latent": ["6", 1]}}
    wf["8"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}}
    wf["9"] = {"class_type": "BasicGuider",
               "inputs": {"model": ["7", 0], "conditioning": ["6", 0]}}
    wf["10"] = {"class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["8", 0], "guider": ["9", 0],
                           "sampler": ["7", 1], "sigmas": ["7", 2],
                           "latent_image": ["6", 1]}}
    wf["11"] = {"class_type": "MiniMaxH3AVDecodeT8",
                "inputs": {"av_latent": ["10", 0], "video_vae": ["1", 0],
                           "audio_vae": ["2", 0]}}
    wf["12"] = {"class_type": "VHS_VideoCombine",
                "inputs": {"frame_rate": 24, "loop_count": 0,
                           "filename_prefix": prefix, "format": "video/h264-mp4",
                           "pix_fmt": "yuv420p", "crf": 19, "save_metadata": True,
                           "trim_to_audio": False, "pingpong": False,
                           "save_output": True, "images": ["11", 0], "audio": ["11", 1]}}
    return wf


# ============ 工作流模板模式（spec: docs/specs/07-comfyui对接.md） ============

def ui_to_api(wf_ui):
    """ComfyUI 导出（UI 格式）→ API 格式：widgets_values 按 input_order 并入 inputs，去 _meta。"""
    out = {}
    for nid, node in (wf_ui or {}).items():
        node = dict(node)
        inputs = dict(node.get("inputs") or {})
        widgets = node.get("widgets_values") or []
        order = node.get("input_order") or []
        for name, value in zip(order, widgets):
            inputs[name] = value
        out[nid] = {"class_type": node["class_type"], "inputs": inputs}
    return out


def load_template(path):
    """读工作流 JSON；UI 格式自动转 API 格式。文件缺失 → ConfigError。"""
    p = Path(path)
    if not p.is_file():
        raise ConfigError("工作流模板不存在: %s" % path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if any("widgets_values" in (n or {}) for n in data.values()):
        data = ui_to_api(data)
    return data


def inject_params(wf, mapping, params):
    """按映射把业务参数注入槽位（node_id.inputs.param）；映射槽位缺失 → ValueError。"""
    out = {k: dict(v, inputs=dict(v.get("inputs") or {})) for k, v in wf.items()}
    for key, slot in (mapping or {}).items():
        if key not in params:
            continue
        parts = str(slot).split(".")
        if len(parts) != 3 or parts[1] != "inputs" or parts[0] not in out:
            raise ValueError("映射槽位无效: %s = %s" % (key, slot))
        out[parts[0]]["inputs"][parts[2]] = params[key]
    return out


def resolve_workflow(cfg, **params):
    """按 workflow.mode 分派：builtin → 内置构造器；template → 模板 + 注入映射。"""
    wf_cfg = cfg.get_path("workflow", {}) or {}
    if wf_cfg.get("mode") == "template":
        wf = load_template(wf_cfg.get("template", ""))
        return inject_params(wf, wf_cfg.get("mapping", {}), params)
    return build_workflow(cfg, params.get("prompt", ""), params.get("width", 1024),
                          params.get("height", 576), params.get("frames", 124),
                          params.get("steps", 20), params.get("seed", -1),
                          params.get("prefix", "shot"), params.get("image"),
                          params.get("ref_image"))


def api(url, payload=None, timeout=30):
    if payload is not None:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def submit(cfg, wf):
    return api(cfg.get_path("comfyui.base_url", "http://127.0.0.1:8188") + "/prompt",
               {"prompt": wf})


def render(project, episode, shots_per_shot=1, width=None, height=None,
           frames=None, steps=None, seed=1, only=None, dry_run=False,
           timeout=DEFAULT_TIMEOUT, image=None, ref_image=None):
    cfg = load_config()
    e_dir = episode_dir(project, episode)
    sb = e_dir / "分镜.md"
    if not sb.exists():
        print("[错误] 缺分镜文件: %s" % sb)
        return False
    shots = load_storyboard(sb)
    style = cfg.get_path("project.style_prefix", "")
    g = cfg.get("generate", {})
    width = width or int(g.get("width", 1024))
    height = height or int(g.get("height", 576))
    frames = frames or snap_frames(5)
    steps = steps or int(g.get("steps", 20))
    if only:
        wanted = {int(x) for x in str(only).split(",")}
        shots = [(i, s) for i, s in enumerate(shots, 1) if i in wanted]
    else:
        shots = [(i, s) for i, s in enumerate(shots, 1)]
    out_dir = e_dir / "shots" / ".candidates"   # 候选池（shots/ 顶层只放选中的 shot_XX.mp4）
    out_dir.mkdir(parents=True, exist_ok=True)

    # 逐镜构造任务清单
    tasks = []  # (镜号, 候选号, prompt, 帧数, seed, 输出名)
    t = 0
    for i, s in shots:
        dur = parse_dur(s.get("dur"))
        n_frames = snap_frames(dur)
        for k in range(1, shots_per_shot + 1):
            tasks.append((i, k, shot_prompt(s, i, t, style), n_frames,
                          seed + (i - 1) * shots_per_shot + (k - 1),
                          "shot_%02d_%02d" % (i, k)))
        t += dur

    if dry_run:
        mode = "I2VA（首帧 %s）" % image if image else "T2VA"
        print("== [DRY-RUN] %s E%02d 将提交 %d 个 %s 任务到 %s =="
              % (project, episode, len(tasks), mode,
                 cfg.get_path("comfyui.base_url", "http://127.0.0.1:8188")))
        for i, k, prompt, n_frames, sd, name in tasks:
            print("  镜 %02d 候选 %d: %s 帧=%d seed=%d → %s.mp4"
                  % (i, k, prompt.splitlines()[0][:70], n_frames, sd, name))
        print("[DRY-RUN] 结束：可去掉 --dry-run 正式提交。")
        return True

    base = cfg.get_path("comfyui.base_url", "http://127.0.0.1:8188")
    pending = {}  # prompt_id -> 输出名
    for i, k, prompt, n_frames, sd, name in tasks:
        wf = resolve_workflow(cfg, prompt=prompt, width=width, height=height,
                              frames=n_frames, steps=steps, seed=sd, prefix=name,
                              image=image, ref_image=ref_image)
        try:
            resp = submit(cfg, wf)
        except Exception as ex:
            print("[错误] 提交 镜%02d候选%d 失败: %s" % (i, k, ex))
            return False
        if resp.get("node_errors"):
            print("[错误] 节点校验失败 镜%02d候选%d: %s"
                  % (i, k, json.dumps(resp["node_errors"], ensure_ascii=False)[:400]))
            return False
        pid = resp["prompt_id"]
        pending[pid] = (i, k, name)
        print("[提交] 镜%02d 候选%d → %s" % (i, k, pid[:8]))

    # 轮询直到全部完成
    start = time.time()
    done = {}
    while pending:
        if time.time() - start > timeout:
            print("[错误] 超时 %ds，剩余 %d 个未完成" % (timeout, len(pending)))
            return False
        for pid in list(pending):
            try:
                hist = api(base + "/history/" + pid)
            except Exception:
                continue
            entry = hist.get(pid)
            if not entry:
                continue
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                print("[错误] 任务 %s 失败: %s" % (pid[:8],
                      json.dumps(entry.get("status", {}), ensure_ascii=False)[:300]))
                return False
            if status.get("completed") or status.get("status_str") == "success":
                i, k, name = pending.pop(pid)
                done[name] = entry
                print("[完成] 镜%02d 候选%d（%.0fs）" % (i, k, time.time() - start))
        if pending:
            time.sleep(10)

    # 下载带音频的视频到 shots/.candidates/
    for name, entry in done.items():
        outs = entry.get("outputs", {})
        src = None
        for o in outs.values():
            for g in o.get("gifs", []):
                if g.get("filename", "").endswith(AUDIO_SUFFIX):
                    src = g
        if src is None:
            print("[警告] %s 未找到带音频输出" % name)
            continue
        url = "%s/view?filename=%s&subfolder=%s&type=%s" % (
            base, urllib.request.quote(src["filename"]),
            urllib.request.quote(src.get("subfolder", "")), src.get("type", "output"))
        dest = out_dir / (name + ".mp4")
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
                f.write(r.read())
            print("[下载] %s（%.1fMB）" % (dest.name, dest.stat().st_size / 1e6))
        except Exception as ex:
            print("[警告] 下载 %s 失败: %s" % (dest.name, ex))
    print("[完成] 候选已就绪：%s（选中后自动规范化到 shots/shot_XX.mp4）" % out_dir)
    return True


def main():
    ap = argparse.ArgumentParser(description="ComfyUI API 自动出片")
    ap.add_argument("name")
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--shots", type=int, default=1, help="每镜候选数（抽卡批量）")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--frames", type=int)
    ap.add_argument("--steps", type=int)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--only", help="只渲染指定镜号，如 1,3")
    ap.add_argument("--image", help="首帧图文件名（ComfyUI/input 下），给出则走 I2VA")
    ap.add_argument("--ref-image", help="参考图文件名（ComfyUI/input 下），给出则走 Ref2VA（人物一致性）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    a = ap.parse_args()
    sys.exit(0 if render(a.name, a.episode, a.shots, a.width, a.height,
                         a.frames, a.steps, a.seed, a.only, a.dry_run,
                         a.timeout, a.image, a.ref_image) else 1)


if __name__ == "__main__":
    main()
