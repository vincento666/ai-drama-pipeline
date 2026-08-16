#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选自动质检（FR3）：ffmpeg 探针 + 首/尾帧抽帧 + 音轨检测 → REVIEW.md + JSON。

仅标准库 + ffmpeg（复用 config.yaml 的 compose.ffmpeg；无 ffmpeg 时优雅降级）。
对每个候选（shots/.candidates/shot_XX_YY.mp4）产出：
  - 时长 / 分辨率 / 帧率 / 是否含音轨（ffmpeg -i 探针，解析 stderr）
  - 首帧 / 尾帧亮度（1x1 灰度 rawvideo，纯 Python 读 1 字节，无需 PIL）
  - 首/尾帧缩略图（320px PNG，写入 shots/.review/，供 REVIEW.md 与前端展示）
  - 标记 flags 与判定 verdict（ok / warn / reject），供 Agent 自动淘汰明显废片

用法：
  python scripts/review.py <项目> --episode 1
  python scripts/review.py <项目> --episode 1 --json     # 输出 JSON（供 API/Agent）
  python scripts/review.py <项目> --episode 1 --dry-run
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from common import episode_dir, load_config
from gen_storyboard import load_storyboard, parse_dur

SHOT_FILE_RE = re.compile(r"^shot_(\d{2})_(\d{2})\.mp4$")
DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
RES_RE = re.compile(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b")
FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
AUDIO_RE = re.compile(r"\bAudio:\s*([^,\n]+)")

BLACK_LUMA = 12      # 低于此值视为纯黑帧
WHITE_LUMA = 243     # 高于此值视为纯白帧
DUR_LO = 0.7         # 时长下限系数（相对分镜目标时长）
DUR_HI = 1.3         # 时长上限系数


def _ffmpeg(cfg):
    exe = cfg.get_path("compose.ffmpeg", "ffmpeg")
    if isinstance(exe, str) and exe.strip().startswith("#"):
        exe = "ffmpeg"
    import shutil
    if shutil.which(exe) is None and not Path(exe).exists():
        return None
    return exe


def probe(ffmpeg, video):
    """ffmpeg -i 探针：返回 {duration,width,height,fps,audio,audio_desc,video_codec,error}。"""
    info = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0,
            "audio": False, "audio_desc": "", "video_codec": "", "error": ""}
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video)],
                              capture_output=True, text=True, timeout=60)
        txt = proc.stderr or proc.stdout
    except Exception as ex:
        info["error"] = str(ex)
        return info
    m = DUR_RE.search(txt)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = RES_RE.search(txt)
    if m:
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    m = FPS_RE.search(txt)
    if m:
        info["fps"] = float(m.group(1))
    m = AUDIO_RE.search(txt)
    if m:
        info["audio"] = True
        info["audio_desc"] = m.group(1).strip()
    m = re.search(r"Video:\s*([^,\s]+)", txt)
    if m:
        info["video_codec"] = m.group(1)
    if "Video:" not in txt:
        info["error"] = "无视频流"
    return info


def frame_luma(ffmpeg, video, at_end=False):
    """抽 1 帧缩成 1x1 灰度，返回亮度 0-255（纯 Python 读 1 字节）。"""
    seek = ["-sseof", "-0.05"] if at_end else ["-ss", "0"]
    cmd = ([ffmpeg, "-hide_banner", "-loglevel", "error"] + seek +
           ["-i", str(video), "-frames:v", "1", "-vf", "scale=1:1,format=gray",
            "-f", "rawvideo", "-"])
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        return proc.stdout[0] if proc.stdout else None
    except Exception:
        return None


def extract_thumb(ffmpeg, video, dest, at_end=False):
    seek = ["-sseof", "-0.05"] if at_end else ["-ss", "0"]
    cmd = ([ffmpeg, "-hide_banner", "-loglevel", "error", "-y"] + seek +
           ["-i", str(video), "-frames:v", "1", "-vf", "scale=320:-1", str(dest)])
    try:
        subprocess.run(cmd, capture_output=True, timeout=60)
        return dest.exists()
    except Exception:
        return False


def _flags(rec):
    flags = []
    if rec.get("error"):
        flags.append("probe_error")
    if not rec.get("audio"):
        flags.append("no_audio")
    if rec.get("first_luma") is not None and rec["first_luma"] < BLACK_LUMA:
        flags.append("black_first")
    if rec.get("first_luma") is not None and rec["first_luma"] > WHITE_LUMA:
        flags.append("white_first")
    if rec.get("last_luma") is not None and rec["last_luma"] < BLACK_LUMA:
        flags.append("black_last")
    if rec.get("last_luma") is not None and rec["last_luma"] > WHITE_LUMA:
        flags.append("white_last")
    target = rec.get("target_dur", 5.0)
    if rec.get("duration") and target:
        if rec["duration"] < target * DUR_LO:
            flags.append("short")
        elif rec["duration"] > target * DUR_HI:
            flags.append("long")
    elif rec.get("duration") == 0 and not rec.get("error"):
        flags.append("empty")
    return flags


def _verdict(flags):
    hard = {"probe_error", "no_audio", "black_first", "black_last",
            "white_first", "white_last", "empty"}
    warn = {"short", "long"}
    if flags & hard:
        return "reject"
    if flags & warn:
        return "warn"
    return "ok"


def review_episode(project, episode, cfg=None, dry_run=False):
    """扫描候选 → 逐条质检 → REVIEW.md + JSON。返回 {episode, generated, shots:[...]}。"""
    cfg = cfg or load_config()
    ffmpeg = _ffmpeg(cfg)
    e_dir = episode_dir(project, episode)
    cand_dir = e_dir / "shots" / ".candidates"
    review_dir = e_dir / "shots" / ".review"
    sb = e_dir / "分镜.md"
    targets = {}
    if sb.exists():
        for i, s in enumerate(load_storyboard(sb), 1):
            targets[i] = parse_dur(s.get("dur"))
    files = sorted(cand_dir.iterdir()) if cand_dir.exists() else []
    shots_map = {}   # shot_no -> [rec, ...]
    for f in files:
        m = SHOT_FILE_RE.match(f.name)
        if not m:
            continue
        shot_no, cand_no = int(m.group(1)), int(m.group(2))
        rec = {"file": f.name, "shot": shot_no, "candidate": cand_no,
               "target_dur": targets.get(shot_no, 5.0)}
        if not ffmpeg:
            rec.update({"error": "ffmpeg 不可用", "duration": 0, "width": 0,
                        "height": 0, "fps": 0, "audio": False, "audio_desc": "",
                        "first_luma": None, "last_luma": None})
        else:
            rec.update(probe(ffmpeg, f))
            if not rec.get("error"):
                rec["first_luma"] = frame_luma(ffmpeg, f)
                rec["last_luma"] = frame_luma(ffmpeg, f, at_end=True)
                if not dry_run:
                    review_dir.mkdir(parents=True, exist_ok=True)
                    base = f.stem
                    rec["first_thumb"] = (base + "_first.png")
                    rec["last_thumb"] = (base + "_last.png")
                    extract_thumb(ffmpeg, f, review_dir / rec["first_thumb"])
                    extract_thumb(ffmpeg, f, review_dir / rec["last_thumb"],
                                  at_end=True)
        rec["flags"] = _flags(rec)
        rec["verdict"] = _verdict(set(rec["flags"]))
        shots_map.setdefault(shot_no, []).append(rec)

    result = {"episode": episode,
              "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
              "ffmpeg": bool(ffmpeg),
              "shots": [{"shot": k, "target_dur": targets.get(k, 5.0),
                         "candidates": v} for k, v in sorted(shots_map.items())]}
    if not dry_run:
        _write_md(e_dir, result)
    return result


def _write_md(e_dir, result):
    lines = ["# E%02d 候选质检报告（REVIEW）" % result["episode"],
             "> 由 scripts/review.py 自动生成 · %s" % result["generated"],
             "> 判定：ok=通过 warn=需人工复核 reject=废片（可自动淘汰）",
             "",
             "| 镜号 | 候选 | 文件 | 时长 | 分辨率 | 帧率 | 音轨 | 首帧 | 尾帧 | 标记 | 判定 |",
             "|------|------|------|------|--------|------|------|------|------|------|------|"]
    for g in result["shots"]:
        for c in g["candidates"]:
            dur = "%.2fs" % c.get("duration", 0) if c.get("duration") else "-"
            res = "%sx%s" % (c.get("width", 0), c.get("height", 0)) if c.get("width") else "-"
            fps = ("%g" % c.get("fps", 0)) if c.get("fps") else "-"
            audio = "✓" if c.get("audio") else "✗"
            fl = str(c.get("first_luma")) if c.get("first_luma") is not None else "-"
            ll = str(c.get("last_luma")) if c.get("last_luma") is not None else "-"
            flags = ",".join(c.get("flags", [])) or "-"
            lines.append("| %d | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                         % (g["shot"], c["candidate"], c["file"], dur, res, fps,
                            audio, fl, ll, flags, c["verdict"]))
    (e_dir / "REVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="候选自动质检（FR3）")
    ap.add_argument("project")
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    result = review_episode(a.project, a.episode, dry_run=a.dry_run)
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return
    # 文本摘要
    total = sum(len(g["candidates"]) for g in result["shots"])
    rej = sum(1 for g in result["shots"] for c in g["candidates"] if c["verdict"] == "reject")
    warn = sum(1 for g in result["shots"] for c in g["candidates"] if c["verdict"] == "warn")
    print("== 质检结果 E%02d：%d 候选（通过 %d / 复核 %d / 废片 %d）=="
          % (result["episode"], total, total - rej - warn, warn, rej))
    if not result["ffmpeg"]:
        print("[警告] 未找到 ffmpeg，质检仅能标记文件存在性")
    for g in result["shots"]:
        for c in g["candidates"]:
            print("  镜%02d 候选%d %-20s %-6s [%s]"
                  % (g["shot"], c["candidate"], c["file"], c["verdict"],
                     ",".join(c["flags"]) or "-"))


if __name__ == "__main__":
    main()
