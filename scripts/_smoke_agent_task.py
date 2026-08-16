#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一对话窗委派冒烟：外部 harness(kimi) 直接改项目文档 → rev 变化 → canvas 回显。"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:18999"


def api(path, payload=None, method=None, timeout=30):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    before = api("/api/canvas/smoke/1")
    rev0 = before["rev"]
    print("rev 初始:", rev0)
    print("镜1 灯光:", before["storyboard"]["rows"][0]["light"])

    goal = ("请直接编辑本目录下 E01/分镜.md 文件：把镜号 1 那行的灯光列改为 深夜烛火微光。"
            "只改这一格，其余内容一律不动。改完回复确认。")
    r = api("/api/agent-task", {"project": "smoke", "goal": goal, "agent": "kimi"})
    print("委派 job:", r["job"])
    deadline = time.time() + 600
    while time.time() < deadline:
        s = api("/api/render/status/" + r["job"])
        if s["status"] in ("done", "error"):
            break
        time.sleep(6)
    print("job:", s["status"], s.get("message"))
    tid = s.get("task_id", "")
    if tid:
        t = api("/api/agent-task/smoke/" + tid)
        print("task:", t["status"], "| transcript 行数:", len(t["transcript"]))
        print("transcript 尾 3 行:")
        for line in t["transcript"][-3:]:
            print("  ", line[:120])
    after = api("/api/canvas/smoke/1")
    rev1 = after["rev"]
    print("rev 变化:", rev0 != rev1)
    print("镜1 灯光 now:", after["storyboard"]["rows"][0]["light"])


if __name__ == "__main__":
    main()
