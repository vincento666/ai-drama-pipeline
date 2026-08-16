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

# P5 文档版本快照（web/doc_versions.py，仅标准库）：apply_patch 是 /api/patch 与
# agent_manager._run_patch 两条写盘链路的单点，这里做“应用前快照”覆盖两路。
# 守卫式导入：doc_versions 在 web/ 下，scripts 上下文（单元测试/CLI）自动补路径；
# 导入失败（如 web 不可用）则快照静默跳过，绝不拖垮写盘主流程。
try:
    import doc_versions
except Exception:  # noqa: BLE001 —— 守卫导入：快照是附加能力
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _web = _Path(__file__).resolve().parent.parent / "web"
        if str(_web) not in _sys.path:
            _sys.path.insert(0, str(_web))
        import doc_versions
    except Exception:  # noqa: BLE001
        doc_versions = None


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


def reorder_shots(project, episode, action, a, b):
    """重排分镜行（镜号不变，仅表序变化）并写回 分镜.md。

    action ∈ swap（交换镜X和镜Y）/ move_before（把镜X移到镜Y前）/ move_after（移到镜Y后）。
    返回 {action, a, b, order}；镜号不存在抛 ValueError；a==b 为无操作（不写盘）。
    """
    header, rows, p = _read_board(project, episode)

    def _idx(n):
        return next((i for i, r in enumerate(rows)
                     if str(r.get("shot")) == str(int(n))), None)

    ia, ib = _idx(a), _idx(b)
    if ia is None or ib is None:
        raise ValueError("分镜 %d/%d 不存在" % (int(a), int(b)))
    if int(a) == int(b):
        return {"action": action, "a": int(a), "b": int(b),
                "order": [int(str(r.get("shot"))) for r in rows]}
    if action == "swap":
        rows[ia], rows[ib] = rows[ib], rows[ia]
    elif action in ("move_before", "move_after"):
        row = rows.pop(ia)
        # pop 后重新定位 b（索引可能已位移）
        ib2 = next((i for i, r in enumerate(rows)
                    if str(r.get("shot")) == str(int(b))), None)
        rows.insert(ib2 if action == "move_before" else ib2 + 1, row)
    else:
        raise ValueError("未知重排动作: %s" % action)
    _write_board(header, rows, p)
    return {"action": action, "a": int(a), "b": int(b),
            "order": [int(str(r.get("shot"))) for r in rows]}


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
    """自然语言 → 变更清单（v1 规则版）。

    例：把镜3的灯光改为夜景 → [{op:shot, shot:3, field:light, value:夜景}]
        交换镜1和镜2        → [{op:reorder, action:swap, a:1, b:2}]
        把镜3移到镜1前面    → [{op:reorder, action:move_before, a:3, b:1}]
    """
    t = (text or "").strip()
    m = re.search(r"交换\s*镜\s*(\d+)\s*和\s*镜\s*(\d+)", t)
    if m:
        return [{"op": "reorder", "action": "swap",
                 "a": int(m.group(1)), "b": int(m.group(2))}]
    m = re.search(r"把\s*镜\s*(\d+)\s*移\s*到\s*镜\s*(\d+)\s*([前后])", t)
    if m:
        return [{"op": "reorder",
                 "action": "move_before" if m.group(3) == "前" else "move_after",
                 "a": int(m.group(1)), "b": int(m.group(2))}]
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
    if op == "reorder":
        if item["action"] == "swap":
            return "交换镜%d和镜%d" % (item["a"], item["b"])
        return "把镜%d移到镜%d%s" % (item["a"], item["b"],
                                  "前" if item["action"] == "move_before" else "后")
    if op == "script":
        return "%s 整块替换（%d 字）" % (item["block"], item["chars"])
    if op == "ref":
        return "镜%02d 参考图提示词替换（%d 字）" % (item["shot"], item["chars"])
    return op


def apply_patch(project, changes, episode=1):
    """逐条应用变更清单 → {applied: [...], errors: [...]}。applied 项带 op+summary（前端契约）。

    P5：应用前按改动目标文件归类 doc 做快照（同批次同 doc 只快照一次），
    供前端 doc.diff 撤销（恢复上一版本）。快照失败静默（附加能力不阻塞写盘）。
    """
    applied, errors = [], []
    snap_done = set()

    def _snap(ch):
        if doc_versions is None:
            return
        doc = doc_versions.doc_of_change(ch)
        if doc is None:
            return
        key = (doc, episode)
        if key in snap_done:
            return
        snap_done.add(key)
        try:
            doc_versions.snapshot(project, doc, source="patch", episode=episode)
        except Exception:  # noqa: BLE001
            pass

    for ch in changes or []:
        op = ch.get("op")
        try:
            _snap(ch)
            if op == "shot":
                item = patch_shot(project, episode, ch["shot"], ch["field"], ch["value"])
                applied.append({"op": op, **item, "summary": _summarize(op, item)})
            elif op == "reorder":
                item = reorder_shots(project, episode, ch["action"], ch["a"], ch["b"])
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
