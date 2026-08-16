#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分镜参考图（Shot ref）存储层（M1，spec: docs/specs/01-htv对标.md §3）。

事实源：E<n>/refs/ 目录
  shot_XX.prompt.md        参考图提示词（文本）
  shot_XX.png|jpg|jpeg|webp 参考图（图片，生成侧产出）
公共 seam：save_ref_prompt / load_ref_prompt / list_refs / shot_ref_payload。
仅标准库。
"""
import re
from pathlib import Path

import common
import gen_storyboard

PROMPT_RE = re.compile(r"^shot_(\d{2})\.prompt\.md$")
IMAGE_RE = re.compile(r"^shot_(\d{2})\.(png|jpe?g|webp)$")


def ref_dir(project, episode):
    d = common.episode_dir(project, episode) / "refs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_ref_prompt(project, episode, shot, text):
    """保存某镜参考图提示词 → shot_XX.prompt.md，返回路径。"""
    p = ref_dir(project, episode) / ("shot_%02d.prompt.md" % int(shot))
    p.write_text(text, encoding="utf-8")
    return p


def load_ref_prompt(project, episode, shot):
    """读取某镜参考图提示词；无则返回空串。"""
    p = common.episode_dir(project, episode) / "refs" / ("shot_%02d.prompt.md" % int(shot))
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def list_refs(project, episode):
    """扫描 refs/ → [{shot, prompt, image}]，按镜号排序；prompt/image 可缺省。"""
    d = common.episode_dir(project, episode) / "refs"
    rows = {}
    if d.exists():
        for f in sorted(d.iterdir()):
            m = PROMPT_RE.match(f.name)
            if m:
                n = int(m.group(1))
                row = rows.setdefault(n, {"shot": n, "prompt": "", "image": None})
                row["prompt"] = f.read_text(encoding="utf-8", errors="ignore")
                continue
            m = IMAGE_RE.match(f.name.lower())
            if m:
                n = int(m.group(1))
                row = rows.setdefault(n, {"shot": n, "prompt": "", "image": None})
                row["image"] = f.name
    return [rows[k] for k in sorted(rows)]


def shot_ref_payload(row, style=""):
    """分镜行 dict（gen_storyboard 字段）→ agent.shot_ref 任务的 payload。"""
    dlg, sfx = gen_storyboard.classify_audio(row.get("dialogue", ""))
    action = dlg or sfx or row.get("note", "")
    line = "镜%s｜场景%s｜景别%s｜运镜%s｜角色%s｜内容：%s" % (
        row.get("shot", "?"), row.get("scene", ""), row.get("frame", ""),
        row.get("camera", ""), row.get("chars", ""), action)
    return {"shot": line, "style": style or ""}


def promote_first_frame(project, episode, shot, src):
    """F9：把候选首帧（质检抽帧 PNG）晋升为参考图 refs/shot_XX.png。

    src 不存在 → FileNotFoundError；返回目标路径。
    """
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError("首帧不存在: %s" % src)
    dest = ref_dir(project, episode) / ("shot_%02d.png" % int(shot))
    dest.write_bytes(src.read_bytes())
    return dest


def first_frame_candidate(project, episode, candidate_file):
    """选中文件名 shot_03_02.mp4 → 对应质检首帧 shots/.review/shot_03_02_first.png。"""
    stem = Path(candidate_file).stem
    return common.episode_dir(project, episode) / "shots" / ".review" / (stem + "_first.png")
