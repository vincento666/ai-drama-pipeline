#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流写盘核心（spec: docs/specs/09-agent工作台.md P1）。

agent 产出 → 结构化变更 → 写入工作流事实源（分镜.md / 剧本四块+简报 / 参考图提示词），
UI 因 store 响应式刷新即时回显（所改即所得）。仅标准库。
"""
import re

import ai_writer
import common
import gen_storyboard
import refs


# ============ 分镜行写盘 ============

def _read_board(project, episode):
    """读 分镜.md → (header_lines, rows)。表头 = 首个 | 行之前的文本行。"""
    p = common.episode_dir(project, episode) / "分镜.md"
    if not p.exists():
        raise ValueError("缺分镜.md（先生成分镜）")
    lines = p.read_text(encoding="utf-8").splitlines()
    header = []
    idx = 0
    while idx < len(lines) and not lines[idx].strip().startswith("|"):
        header.append(lines[idx])
        idx += 1
    body = lines[idx:]
    rows = gen_storyboard.parse_markdown_table("\n".join(body))
    return header, rows, p


def _write_board(header, rows, p):
    text = "\n".join(header).rstrip() + "\n" if header else ""
    # 复用 ai_writer._md 的表格序列化（列定义一致）
    cols = [("shot", "镜号"), ("frame", "景别"), ("camera", "机位运动"),
            ("dur", "时长"), ("chars", "角色"), ("scene", "场景"),
            ("light", "灯光"), ("dialogue", "对白/音效"), ("note", "备注")]
    lines = ["| " + " | ".join(c[1] for c in cols) + " |",
             "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(k, "") or "").strip() for k, _ in cols) + " |")
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n".join(lines) + "\n"
    p.write_text(text, encoding="utf-8")


def patch_shot(project, episode, shot, field, value):
    """改单镜单字段并写回 分镜.md。返回 {shot, field, value}。"""
    if field not in ("shot", "frame", "camera", "dur", "chars", "scene",
                     "light", "dialogue", "note"):
        raise ValueError("未知分镜字段: %s" % field)
    header, rows, p = _read_board(project, episode)
    target = next((r for r in rows if str(r.get("shot")) == str(int(shot))), None)
    if target is None:
        raise ValueError("分镜 %d 不存在" % int(shot))
    target[field] = str(value)
    _write_board(header, rows, p)
    return {"shot": int(shot), "field": field, "value": str(value)}


# ============ 剧本/简报写盘 ============

_BLOCKS = {
    "novel": (ai_writer.write_novel, ai_writer.NOVEL_FILE),
    "events": (ai_writer.write_events, ai_writer.EVENTS_FILE),
    "skeleton": (ai_writer.write_skeleton, ai_writer.SKELETON_FILE),
    "script": (ai_writer.write_script, ai_writer.SCRIPT_FILE),
    "assets": (ai_writer.write_assets, ai_writer.ASSETS_FILE),
    "brief": (ai_writer.write_brief, ai_writer.BRIEF_FILE),
}


def patch_script_block(project, block, text):
    """整块替换剧本四块/简报。返回 {block, chars}。"""
    if block not in _BLOCKS:
        raise ValueError("未知剧本块: %s（可用: %s）" % (block, ", ".join(sorted(_BLOCKS))))
    writer, _fname = _BLOCKS[block]
    writer(project, text)
    return {"block": block, "chars": len(text)}


# ============ 参考图提示词写盘 ============

def patch_ref_prompt(project, episode, shot, text):
    """替换某镜参考图提示词。返回 {shot, chars}。"""
    refs.save_ref_prompt(project, episode, int(shot), text)
    return {"shot": int(shot), "chars": len(text)}


# ============ 自然语言 → 结构化变更（规则版 v1） ============

_FIELD_MAP = {"对白": "dialogue", "灯光": "light", "景别": "frame", "运镜": "camera",
              "时长": "dur", "角色": "chars", "场景": "scene", "备注": "note"}


def parse_edit_action(text):
    """自然语言 → 变更清单（v1 规则版：镜N + 字段 + 改为/改成/设为）。

    例：把镜3的灯光改为夜景 → [{op:shot, shot:3, field:light, value:夜景}]
    """
    t = (text or "").strip()
    m = re.search(
        r"(?:第\s*(\d+)\s*镜|镜\s*(\d+)).*?"
        r"(对白|灯光|景别|运镜|时长|角色|场景|备注)"
        r"\s*(?:改为|改成|设为)\s*[:：]?\s*(.+)$", t)
    if not m:
        return []
    shot = int(m.group(1) or m.group(2))
    field = _FIELD_MAP[m.group(3)]
    value = m.group(4).strip().strip("「」『』\"'")
    if not value:
        return []
    return [{"op": "shot", "shot": shot, "field": field, "value": value}]


# ============ 批量应用 ============

def _summarize(op, item):
    if op == "shot":
        return "镜%02d %s → %s" % (item["shot"], item["field"], item["value"])
    if op == "script":
        return "%s 整块替换（%d 字）" % (item["block"], item["chars"])
    if op == "ref":
        return "镜%02d 参考图提示词替换（%d 字）" % (item["shot"], item["chars"])
    return op


def apply_patch(project, changes, episode=1):
    """逐条应用变更清单 → {applied: [...], errors: [...]}。applied 项带 op+summary（前端契约）。"""
    applied, errors = [], []
    for ch in changes or []:
        op = ch.get("op")
        try:
            if op == "shot":
                item = patch_shot(project, episode, ch["shot"], ch["field"], ch["value"])
                applied.append({"op": op, **item, "summary": _summarize(op, item)})
            elif op == "script":
                item = patch_script_block(project, ch["block"], ch["text"])
                applied.append({"op": op, **item, "summary": _summarize(op, item)})
            elif op == "ref":
                item = patch_ref_prompt(project, episode, ch["shot"], ch["text"])
                applied.append({"op": op, **item, "summary": _summarize(op, item)})
            else:
                errors.append({"op": op, "error": "未知操作"})
        except Exception as ex:
            errors.append({"op": op, "error": str(ex)})
    return {"applied": applied, "errors": errors}
