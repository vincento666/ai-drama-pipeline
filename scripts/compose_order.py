#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成片顺序持久化（docs/12 §2 D1 / docs/13 §3 P6a 4，仅标准库）。

真理源：E{n}/compose.order.json（镜号数组，如 [1, 3, 2]）。
- 缺省顺序 = 分镜行顺序（compose.order.json 不存在 → read_order 返回 None）。
- PUT 写盘前校验：order 为镜号数组、元素唯一、范围为「现有分镜行镜号并集」。
- 前端成片编排台拖拽重排 → PUT /api/compose-order → POST /api/compose 按序拼接。

与 web/server.py（GET/PUT /api/compose-order、/api/compose）和
web/agent_manager.py（compose-order 工具分支）共用同一套函数。
"""
import json
import re
from pathlib import Path

import common
from gen_storyboard import load_storyboard


def order_path(project, episode):
    """E{n}/compose.order.json 路径。"""
    return common.episode_dir(project, episode) / "compose.order.json"


def storyboard_shot_numbers(project, episode):
    """当前分镜行镜号集合（int）。分镜缺失/解析失败 → 空集合。"""
    sb = common.episode_dir(project, episode) / "分镜.md"
    nums = set()
    if not sb.exists():
        return nums
    try:
        for row in load_storyboard(sb):
            try:
                nums.add(int(str(row.get("shot") or "").strip()))
            except (TypeError, ValueError):
                continue
    except Exception:
        nums = set()
    return nums


def validate_order(order, valid=None):
    """校验 order 为「正整数镜号数组、元素唯一、范围在 valid（若给）内」。

    返回 (ok, error)。valid 为 None/空集合时只校验正整数+唯一。
    """
    if not isinstance(order, list):
        return False, "order 必须是数组"
    if not order:
        return False, "order 不能为空"
    seen = set()
    for x in order:
        if isinstance(x, bool) or not isinstance(x, int):
            return False, "order 元素必须为整数镜号: %r" % (x,)
        if x <= 0:
            return False, "镜号必须为正整数: %r" % (x,)
        if x in seen:
            return False, "镜号重复: %d" % x
        seen.add(x)
    if valid:
        missing = [x for x in order if x not in valid]
        if missing:
            return False, "镜号超出当前分镜范围: %s（现有镜号: %s）" % (
                ",".join(map(str, sorted(missing))),
                ",".join(map(str, sorted(valid))) or "无")
    return True, ""


def read_order(project, episode):
    """读 E{n}/compose.order.json → 镜号数组；不存在/非法 → None（= 分镜行顺序）。"""
    p = order_path(project, episode)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    ok, _err = validate_order(data)
    return data if ok else None


def write_order(project, episode, order, valid=None):
    """校验并写盘 order → {ok, order, error?}；失败不写盘。"""
    ok, err = validate_order(order, valid)
    if not ok:
        return {"ok": False, "order": None, "error": err}
    if valid is None:
        valid = storyboard_shot_numbers(project, episode)
        ok2, err2 = validate_order(order, valid)
        if not ok2:
            return {"ok": False, "order": None, "error": err2}
    p = order_path(project, episode)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(order, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "order": order}


def clear_order(project, episode):
    """删除顺序覆盖（回到分镜行顺序）。返回是否删除成功。"""
    p = order_path(project, episode)
    if p.exists():
        try:
            p.unlink()
            return True
        except OSError:
            return False
    return False


def resolve_order(project, episode):
    """最终拼接顺序：compose.order.json（若有）→ 否则分镜行顺序。

    返回 (order_list, source)；order_list 为 int 镜号数组（分镜缺失 → 空表）。
    """
    o = read_order(project, episode)
    if o is not None:
        return o, "order"
    nums = sorted(storyboard_shot_numbers(project, episode))
    return nums, "storyboard"


def _parse_shot_no(tok):
    m = re.search(r"(\d+)", tok or "")
    return int(m.group(1)) if m else None


def apply_natural_order(project, episode, text, default_order=None):
    """从自然语言生成 order（manager compose-order 工具用）。

    支持：
      「把镜3放到镜1前面/后面」→ 3 插入 1 之前/之后
      「交换镜1和镜3」→ 交换位置（= 成片顺序交换）
      「恢复默认顺序」→ 清空覆盖
      「调整顺序为 3,1,2」→ 显式列表
    默认基准 = 分镜行顺序；返回 {ok, order|None, error?, action}。
    """
    t = (text or "").strip()
    if "恢复默认" in t or "回到默认" in t or "清除顺序" in t:
        if clear_order(project, episode):
            return {"ok": True, "order": None, "action": "clear"}
        return {"ok": True, "order": None, "action": "clear"}
    base = default_order if default_order is not None else sorted(
        storyboard_shot_numbers(project, episode))
    if not base:
        return {"ok": False, "order": None,
                "error": "无分镜行可排序（先拆分镜）"}
    # 「调整顺序为 3,1,2 / 顺序：3 1 2」
    m = re.search(r"(?:调整顺序|顺序)(?:为|改成|：|:)?\s*[为：: ]?\s*([\d\s,，、]+)", t)
    if m:
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
        if nums:
            ok, err = validate_order(nums, set(base))
            if not ok:
                return {"ok": False, "order": None, "error": err}
            write_order(project, episode, nums, valid=set(base))
            return {"ok": True, "order": nums, "action": "set"}
    # 「把镜A放到镜B前/后」
    m = re.search(r"把\s*镜\s*(\d+)\s*放\s*到\s*镜\s*(\d+)\s*([前后])", t)
    if m:
        a, b, pos = int(m.group(1)), int(m.group(2)), m.group(3)
        if a not in base or b not in base:
            return {"ok": False, "order": None,
                    "error": "镜号 %d/%d 不在当前分镜中" % (a, b)}
        order = [x for x in base if x != a]
        idx = order.index(b)
        order.insert(idx if pos == "前" else idx + 1, a)
        write_order(project, episode, order, valid=set(base))
        return {"ok": True, "order": order, "action": "move"}
    # 「交换镜A和镜B」
    m = re.search(r"交换\s*镜\s*(\d+)\s*和\s*镜\s*(\d+)", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a not in base or b not in base:
            return {"ok": False, "order": None,
                    "error": "镜号 %d/%d 不在当前分镜中" % (a, b)}
        order = list(base)
        ia, ib = order.index(a), order.index(b)
        order[ia], order[ib] = order[ib], order[ia]
        write_order(project, episode, order, valid=set(base))
        return {"ok": True, "order": order, "action": "swap"}
    return {"ok": False, "order": None,
            "error": "未识别出顺序指令：试试「把镜3放到镜1前面」「交换镜1和镜3」或「调整顺序为 3,1,2」"}
