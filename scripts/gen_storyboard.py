#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分镜 → 提示词：解析分镜 markdown 表格/CSV，生成 H3 三段式 或 Seedance 时间轴提示词。

分镜表字段（markdown 表格列名可中英混用）：
镜号 | 景别 | 机位运动 | 时长 | 角色 | 场景 | 灯光 | 对白/音效 | 备注

输出两种格式：
  h3       本地 ComfyUI（integrated_multimodal_description / overall_soundscape / non_diegetic_music）
  seedance 云端即梦（时间轴格式）
"""
import argparse
import csv
import io
import re
import sys
from pathlib import Path

# 列名别名 → 标准字段
COL_ALIASES = {
    "镜号": "shot", "shot": "shot", "no": "shot",
    "景别": "frame", "framing": "frame", "镜头类型": "frame",
    "机位运动": "camera", "camera": "camera", "运镜": "camera",
    "时长": "dur", "duration": "dur", "dur": "dur",
    "角色": "chars", "actors": "chars",
    "场景": "scene", "location": "scene",
    "灯光": "light", "lighting": "light",
    "对白": "dialogue", "对白/音效": "dialogue", "dialogue": "dialogue",
    "音效": "sfx", "sfx": "sfx",
    "备注": "note", "note": "note",
}

CAMERA_VOCAB = ["push in", "pull back", "pan left", "pan right", "tilt up",
                "tilt down", "tracking", "crane up", "crane down", "handheld",
                "orbit", "static", "推近", "拉远", "左摇", "右摇", "上摇",
                "下摇", "跟随", "环绕", "手持", "固定", "升降", "俯冲"]

FRAME_VOCAB = ["extreme wide", "wide", "medium-wide", "medium", "medium close-up",
               "close-up", "extreme close-up", "远景", "全景", "中景", "近景",
               "特写", "大特写"]


def parse_markdown_table(text):
    """解析 markdown 表格 → list[dict]。"""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue  # 分隔行
        rows.append(cells)
    if not rows:
        raise ValueError("未找到 markdown 表格")
    headers = [COL_ALIASES.get(c, c) for c in rows[0]]
    data = []
    for cells in rows[1:]:
        if len(cells) < len(headers):
            cells += [""] * (len(headers) - len(cells))
        data.append(dict(zip(headers, cells)))
    return data


def parse_csv_text(text):
    rd = csv.DictReader(io.StringIO(text))
    return [{COL_ALIASES.get(k, k): (v or "") for k, v in row.items()} for row in rd]


def load_storyboard(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        return parse_csv_text(text)
    return parse_markdown_table(text)


def fmt_time(seconds):
    m, s = divmod(int(seconds), 60)
    return "%02d:%02d" % (m, s)


def norm_camera(v):
    v = (v or "").strip()
    if not v:
        return "static camera"
    for w in CAMERA_VOCAB:
        if w in v:
            return v
    return v + " camera" if v else "static camera"


def classify_audio(v):
    """把'对白/音效'列分成对白和音效：'对白：xxx'→dialogue；'音效/环境音/配乐：xxx'→sfx；无前缀默认对白。"""
    v = (v or "").strip()
    if not v:
        return "", ""
    for prefix in ("音效：", "环境音：", "配乐：", "音效:", "环境音:", "配乐:"):
        if v.startswith(prefix):
            return "", v[len(prefix):].strip()
    if v.startswith("对白：") or v.startswith("对白:"):
        return v.split("：", 1)[-1].split(":", 1)[-1].strip(), ""
    return v, ""


def parse_dur(v, default=5.0):
    """时长解析（容错）：'4s'/'4秒'/'4' → 4.0；'3-6' → 取首数；无效/空 → default。"""
    m = re.search(r"\d+(?:\.\d+)?", str(v or "").strip())
    return float(m.group(0)) if m else default


def article(word):
    return "an" if word.startswith(("extreme", "e")) else "a"


def shot_h3(shot, shot_no, start_sec):
    frame = shot.get("frame") or "medium"
    camera = norm_camera(shot.get("camera"))
    scene = shot.get("scene") or "the location"
    chars = shot.get("chars") or ""
    light = shot.get("light") or ""
    dialogue, sfx = classify_audio(shot.get("dialogue") or shot.get("sfx"))
    note = shot.get("note") or ""

    parts = ["[Shot %d%s] " % (shot_no,
                               " · %s" % fmt_time(start_sec) if shot_no > 1 else "")]
    parts.append("Live-action, cinematic, %s %s shot" % (article(frame), frame))
    parts.append(" with %s camera movement" % camera)
    if light:
        parts.append(", %s lighting" % light)
    if chars:
        parts.append(", featuring %s" % chars)
    parts.append(", set in/at %s" % scene)
    if note:
        parts.append(". %s" % note)
    desc = "".join(parts).rstrip(". ") + "."

    if sfx:
        desc += " Sound of %s." % sfx
    if dialogue:
        desc += " A character speaks: <d>[Chinese] %s</d>." % dialogue
    return desc


def gen_h3(shots, style_prefix=""):
    desc_lines = []
    t = 0
    for i, shot in enumerate(shots, 1):
        desc_lines.append(shot_h3(shot, i, t))
        t += parse_dur(shot.get("dur"))
    desc = " ".join(desc_lines)

    sfx_parts = []
    for shot in shots:
        sfx = shot.get("sfx") or ""
        if sfx and sfx not in sfx_parts:
            sfx_parts.append(sfx)
    soundscape = ("Ambient sound consistent with the scene. "
                  + (" ".join(sfx_parts) if sfx_parts else "Natural room tone."))

    style = (style_prefix + ". ") if style_prefix else ""
    prompt = "integrated_multimodal_description: %s%s\n\n" % (style, desc)
    prompt += "overall_soundscape: %s\n\n" % soundscape
    prompt += ("non_diegetic_music: A subtle, emotion-driven score that matches the "
               "drama of each shot and fades gently at the end. "
               "No text, subtitles, logos or watermarks of any kind.")
    return prompt


def gen_seedance(shots, style_prefix=""):
    lines = [style_prefix or "写实电影风格，9:16竖屏"]
    t = 0
    for i, shot in enumerate(shots, 1):
        dur = parse_dur(shot.get("dur"))
        seg = "%d-%d秒画面：%s，%s" % (t, t + dur,
                                        shot.get("note") or shot.get("frame") or "镜头",
                                        shot.get("camera") or "固定镜头")
        lines.append(seg)
        t += dur
    lines.append("")
    lines.append("【声音】" + ("；".join(s.get("sfx") for s in shots if s.get("sfx"))
                             or "与画面匹配的配乐与音效"))
    dialogs = [s.get("dialogue") for s in shots if s.get("dialogue")]
    if dialogs:
        lines.append("【对白】" + "；".join(dialogs))
    lines.append("【参考】@图片1 角色，@图片2 场景（按素材清单替换）")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="分镜 → H3/Seedance 提示词")
    ap.add_argument("storyboard", help="分镜文件（markdown 表格或 CSV）")
    ap.add_argument("--format", choices=["h3", "seedance"], default="h3")
    ap.add_argument("--out", default="", help="输出文件（默认 stdout）")
    ap.add_argument("--style", default="",
                    help="统一风格前缀，如 'Chinese ink wash painting style'")
    args = ap.parse_args()

    shots = load_storyboard(args.storyboard)
    if not shots:
        sys.exit("分镜为空或格式无法解析")
    if args.format == "h3":
        prompt = gen_h3(shots, args.style)
    else:
        prompt = gen_seedance(shots, args.style)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(prompt + "\n", encoding="utf-8")
        print("[OK] 已生成 %s 提示词（%d 镜）→ %s" % (args.format, len(shots), args.out))
    else:
        print(prompt)


if __name__ == "__main__":
    main()
