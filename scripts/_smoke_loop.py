#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LHH 自动 Loop 冒烟：内置 Manager（LLM 决策）→ 内置执行 → Auditor 验证，单轮。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, "scripts")
import agentbridge  # noqa: E402
import common       # noqa: E402


def main():
    project = "smoke"
    goal = "给 smoke 项目的 E01 分镜补充镜 1 的灯光细节：在 E01/分镜.md 中把镜 1 的灯光列改为 深夜油灯暖光。"
    # Manager 用内置 LLM 决策下一步；Executor 用 kimi（外部 harness，工作区=项目目录）；
    # Auditor 用默认 rev 校验（文件变化即通过）
    start = time.time()
    adapter = agentbridge.get_adapter("kimi")
    calls = {"n": 0}

    def decide(g, s):
        calls["n"] += 1
        t = agentbridge._decide_next(project, g, s)
        print("decide #%d → %r" % (calls["n"], t[:80]))
        return t

    lid, state = agentbridge.run_loop(project, goal, adapter=adapter, max_rounds=3,
                                      decide=decide)
    print("loop:", lid, "| rounds:", state["rounds"],
          "| verified:", state["verified"], "| evidence:", len(state["evidence"]))
    print("耗时: %.0fs" % (time.time() - start))
    d = common.project_dir(project) / "agent" / "loops" / lid
    for rd in sorted((d / "rounds").iterdir()) if (d / "rounds").exists() else []:
        print("--", rd.name)
        print((rd / "task.md").read_text(encoding="utf-8")[:300])


if __name__ == "__main__":
    main()
