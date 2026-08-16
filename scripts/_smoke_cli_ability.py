#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部 agent CLI 能力实测：委派 kimi 在工作区（项目目录）运行 cli.py。"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:18999"


def api(path, payload=None, timeout=30):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    goal = ("你的工作区是当前目录（项目目录）。请执行命令：python ../scripts/cli.py agent-list smoke "
            "（注意当前目录下运行，脚本在上级 scripts 目录），把命令输出报告给我，"
            "并说明你是否成功执行了该命令（能执行命令请回复「CLI 可用」）。")
    r = api("/api/agent-task", {"project": "smoke", "goal": goal, "agent": "kimi"})
    print("job:", r["job"])
    deadline = time.time() + 480
    while time.time() < deadline:
        s = api("/api/render/status/" + r["job"])
        if s["status"] in ("done", "error"):
            break
        time.sleep(6)
    print("job:", s["status"], "|", s.get("message"))
    tid = s.get("task_id", "")
    if tid:
        t = api("/api/agent-task/smoke/" + tid)
        print("transcript 尾 6 行:")
        for line in t["transcript"][-6:]:
            print("  ", line[:160])
        res = t.get("result") or {}
        print("summary 尾 400 字:", (res.get("summary") or "")[-400:])


if __name__ == "__main__":
    main()
