#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""品味学习：采集 → 提炼 → 应用 → 度量 的自动化率优化闭环。

数据层（项目根 profile/）：
  profile/taste.md          品味档案（人维护 + Agent 提炼更新；生成时注入）
  profile/selection_log.jsonl  每次选片记录 {ts, project, episode, shot, chosen, rejected}
  profile/diffs/            分镜/剧本 草稿→定稿 的 diff 快照
  profile/stats.json        自动化率统计（修改率/选中率趋势）

用法：
  python scripts/taste.py init                    初始化 profile/ + taste.md 模板
  python scripts/taste.py stats                   输出自动化率统计
  python scripts/taste.py extract                 打印给 Agent 的品味提炼指引
  python scripts/taste.py log-select ...          记录一次选片（也可由 server 自动调）
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "profile"

TASTE_TEMPLATE = """# 品味档案（Taste Profile）

> 用途：生成剧本/分镜/提示词时注入，减少人工打磨量。
> 维护：**人工声明的偏好优先**；Agent 从 selection_log + diffs 提炼的新偏好，
> 需人确认后写入（避免 Agent 自我强化错误模式）。

## 风格基调（注入提示词 style）
（例：水墨风 + 动漫赛璐璐；整体色调偏暖；写实感弱）

## 镜头偏好（分镜默认值与建议）
- 默认景别: medium
- 默认运镜: static
- 偏好时长: 5
- 避免运镜: orbit, handheld
（值填英文词表；"默认景别/默认运镜/偏好时长"会被 /api/taste 读取为插入行的默认值）

## 对白风格
（例：对白简短口语化，<10 字；少用书面语；情绪靠动作不靠台词）

## 灯光/场景基调
（例：偏好 golden hour 暖光；少用夜景）

## 避免项（负面提示）
（例：避免镜头快速晃动；避免角色正脸大特写过长）

## 用户声明（人直接写，最高优先级）
（例：我不喜欢 X 风格；这个项目要 Y 氛围）
"""


def ensure_profile():
    PROFILE.mkdir(parents=True, exist_ok=True)
    (PROFILE / "diffs").mkdir(exist_ok=True)
    taste = PROFILE / "taste.md"
    if not taste.exists():
        taste.write_text(TASTE_TEMPLATE, encoding="utf-8")
        print("[OK] 已生成品味档案模板: %s" % taste)
    for f in ("selection_log.jsonl", "stats.json"):
        p = PROFILE / f
        if not p.exists():
            p.write_text("[]\n" if f.endswith("json") else "", encoding="utf-8")
    return PROFILE


# ---------- 采集 ----------
def log_select(project, episode, shot, chosen, rejected=None, note=""):
    """记录一次选片（chosen 是选中的候选文件名，rejected 是未选候选列表）。"""
    ensure_profile()
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "project": project,
           "episode": episode, "shot": shot, "chosen": chosen,
           "rejected": rejected or [], "note": note}
    with open(PROFILE / "selection_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("[记录] 选片: 镜%s → %s（共 %d 候选）" % (shot, chosen, 1 + len(rec["rejected"])))
    return rec


def record_stats(event, data):
    """追加一条自动化率统计事件。"""
    ensure_profile()
    p = PROFILE / "stats.json"
    try:
        stats = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        stats = []
    stats.append({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **data})
    with open(p, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    return stats


def snapshot_and_diff(rel_path, text):
    """对 分镜.md/剧本.md 做快照；若与上一快照不同则写 diff 并统计修改率。

    rel_path: 相对项目根的路径（如 output/smoke/E01/分镜.md）。
    返回 (是否变化, 修改率 0~1)。
    """
    ensure_profile()
    snap_dir = PROFILE / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    import difflib
    name = rel_path.replace("/", "_").replace("\\", "_")
    snap = snap_dir / (name + ".txt")
    if snap.exists():
        old = snap.read_text(encoding="utf-8").splitlines(keepends=True)
        new = text.splitlines(keepends=True)
        diff = list(difflib.unified_diff(old, new, fromfile="草稿", tofile="定稿",
                                         lineterm="\n"))
        changed = [l for l in diff if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
        total = max(1, len(old) + len(new))
        ratio = len(changed) / total if total else 0
        if changed:
            diff_path = PROFILE / "diffs" / ("%s_%s.diff" % (time.strftime("%Y%m%d_%H%M%S"), name))
            diff_path.write_text("".join(diff), encoding="utf-8")
            record_stats("content_edit", {"path": rel_path, "changed_lines": len(changed),
                                          "total_lines": total, "edit_ratio": round(ratio, 3)})
            print("[快照] %s 修改 %d 行（修改率 %.1f%%）→ %s"
                  % (rel_path, len(changed), ratio * 100, diff_path))
            snap.write_text(text, encoding="utf-8")
            return True, ratio
        return False, 0.0
    snap.write_text(text, encoding="utf-8")
    print("[快照] %s 首次快照（基线）" % rel_path)
    return False, 0.0


# ---------- 度量 ----------
def show_stats():
    ensure_profile()
    p = PROFILE / "stats.json"
    try:
        stats = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        stats = []
    edits = [s for s in stats if s["event"] == "content_edit"]
    selects = [s for s in stats if s["event"] == "select"]
    print("== 品味学习统计 ==")
    print("内容修改事件: %d 次" % len(edits))
    if edits:
        recent = edits[-10:]
        avg = sum(e["edit_ratio"] for e in recent) / len(recent)
        print("最近 %d 次平均修改率: %.1f%%" % (len(recent), avg * 100))
        # 趋势：前一半 vs 后一半
        if len(edits) >= 4:
            half = len(edits) // 2
            early = sum(e["edit_ratio"] for e in edits[:half]) / half
            late = sum(e["edit_ratio"] for e in edits[half:]) / (len(edits) - half)
            trend = "下降（自动化率提升 ✓）" if late < early else "持平或上升"
            print("趋势: 早期 %.1f%% → 近期 %.1f%%（%s）" % (early * 100, late * 100, trend))
    sel_log = PROFILE / "selection_log.jsonl"
    if sel_log.exists():
        n = sum(1 for _ in sel_log.open(encoding="utf-8"))
        print("选片记录: %d 次" % n)
    return stats


# ---------- 提炼指引 ----------
EXTRACT_GUIDE = """== 品味提炼指引（给 Agent） ==

你（Agent）负责从用户的修改与选择中提炼品味，写入 profile/taste.md。步骤：

1. 读 profile/selection_log.jsonl：用户每镜选 A 淘汰 B，对比 A/B 的提示词差异
   （景别/运镜/灯光/对白风格），提炼"用户偏好哪种镜头语言"。
2. 读 profile/diffs/ 最新 diff：用户把 Agent 草稿改成了什么（改对白/改景别/改时长），
   这些改动就是品味信号；连续出现 2 次以上的改动模式 → 写入 taste.md 对应小节。
3. 与用户确认：新条目标注 [Agent 提炼]，由用户点头后转正；用户口头声明直接写
   "用户声明"小节（最高优先级）。
4. 更新后把 taste.md 摘要告诉用户，并说明注入点：
   - 剧本起草：Agent 按"风格基调/对白风格/节奏"起草
   - 分镜草稿：按"镜头偏好"填默认字段（前端插入行也读 /api/taste）
   - 提示词：style 扩展（config.style_prefix + taste 风格基调）
5. 周期性跑 `python scripts/taste.py stats` 看修改率是否下降（自动化率提升）。

禁忌：不要把你自己的偏好写进去；不要在没有用户修改证据时编造品味条目。
"""


def main():
    ap = argparse.ArgumentParser(description="品味学习：采集/度量/提炼")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="初始化 profile/ + taste.md 模板").set_defaults(
        fn=lambda a: ensure_profile())
    sub.add_parser("stats", help="输出自动化率统计").set_defaults(
        fn=lambda a: show_stats())
    sub.add_parser("extract", help="打印 Agent 品味提炼指引").set_defaults(
        fn=lambda a: print(EXTRACT_GUIDE))
    p = sub.add_parser("log-select", help="记录一次选片")
    p.add_argument("--project", required=True)
    p.add_argument("--episode", type=int, required=True)
    p.add_argument("--shot", type=int, required=True)
    p.add_argument("--chosen", required=True)
    p.add_argument("--rejected", default="", help="逗号分隔的未选候选")
    p.add_argument("--note", default="")
    p.set_defaults(fn=lambda a: log_select(a.project, a.episode, a.shot, a.chosen,
                                           [x for x in a.rejected.split(",") if x], a.note))
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
