#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成片拼接：按分镜顺序用 ffmpeg 把 shots/ 里的视频拼成 成片.mp4。仅标准库。"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from common import episode_dir


def shot_sort_key(path: Path):
    """从文件名提取序号排序：shot_03 / S01_02 / 003 均可。"""
    m = re.search(r"(\d{1,3})", path.stem)
    return int(m.group(1)) if m else 0


def find_shots(shots_dir: Path):
    exts = (".mp4", ".mov", ".mkv", ".webm", ".avi")
    files = [f for f in shots_dir.iterdir() if f.suffix.lower() in exts]
    files.sort(key=shot_sort_key)
    return files


def build_concat_list(files, list_path: Path):
    lines = ["file '%s'" % f.resolve().as_posix() for f in files]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list_path


def compose(shots_dir: Path, out_path: Path, ffmpeg: str = "ffmpeg", fps: int = 24,
            dry_run: bool = False, order=None):
    """按镜号顺序拼接：order 为镜号数组（如 [1,3,2]）时按序取 shots/shot_XX.mp4；
    order 为 None → 按文件名排序（默认分镜行顺序）。"""
    if order is not None:
        files = []
        for n in order:
            f = shots_dir / ("shot_%02d.mp4" % int(n))
            if f.exists():
                files.append(f)
        if not files:
            print("[警告] %s 里没有与 order 匹配的视频文件" % shots_dir)
            return False
    else:
        files = find_shots(shots_dir)
    if not files:
        print("[警告] %s 里没有视频文件（.mp4/.mov/.mkv/.webm）" % shots_dir)
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_path.with_suffix(".concat.txt")
    build_concat_list(files, list_file)

    if shutil.which(ffmpeg) is None:
        print("[警告] 未找到 ffmpeg，请先安装：brew install ffmpeg / apt install ffmpeg")
        print("拼接清单已生成（可直接用剪映导入代替）：%s" % list_file)
        print("待拼接：%s" % "  →  ".join(f.name for f in files))
        return False

    if dry_run:
        print("[DRY-RUN] ffmpeg -f concat -safe 0 -i %s -c copy -r %d %s"
              % (list_file.name, fps, out_path.name))
        print("[DRY-RUN] 待拼接 %d 段：%s" % (len(files),
                                            "  →  ".join(f.name for f in files)))
        return True

    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
           "-c", "copy", "-r", str(fps), str(out_path)]
    print("[运行] " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr[-2000:])
        print("[失败] 拼接出错（编码不一致时用 -c copy 会失败，可改 -c:v libx264 -c:a aac）")
        return False
    print("[OK] 成片已生成: %s（%.1f MB）"
          % (out_path, out_path.stat().st_size / 1024 / 1024))
    return True


def main():
    ap = argparse.ArgumentParser(description="ffmpeg 拼接成片")
    ap.add_argument("project", help="项目名（output/ 下）")
    ap.add_argument("--episode", type=int, default=1, help="集号")
    ap.add_argument("--shots", default="", help="shots 目录（默认 <project>/E<episode>/shots）")
    ap.add_argument("--out", default="", help="输出文件（默认 <project>/E<episode>/成片.mp4）")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    e_dir = episode_dir(args.project, args.episode)
    shots_dir = Path(args.shots) if args.shots else (e_dir / "shots")
    out_path = Path(args.out) if args.out else (e_dir / "成片.mp4")
    ok = compose(shots_dir, out_path, ffmpeg=args.ffmpeg, fps=args.fps,
                 dry_run=args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
