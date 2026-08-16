#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ACP 对话端点冒烟：POST /api/agent-chat → 轮询流式 lines → reply。"""
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
    r = api("/api/agent-chat", {"project": "smoke", "text": "只回复两个字：在线"})
    print("chat job:", r["job"])
    last_n = 0
    deadline = time.time() + 300
    while time.time() < deadline:
        s = api("/api/agent-chat/status/" + r["job"])
        lines = s.get("lines") or []
        if len(lines) > last_n:
            for line in lines[last_n:]:
                print("  [流式] " + line[:100])
            last_n = len(lines)
        if s["status"] in ("done", "error"):
            print("status:", s["status"], "|", s.get("message"))
            break
        time.sleep(2)
    s = api("/api/agent-chat/status/" + r["job"])
    print("reply:", (s.get("reply") or "")[:200])
    print("session:", s.get("session_id"))
    # 多轮：同项目同会话
    r2 = api("/api/agent-chat", {"project": "smoke",
                                 "text": "读当前目录 E01/分镜.md 第一行并原样回复"})
    time.sleep(3)
    s2 = api("/api/agent-chat/status/" + r2["job"])
    print("第二轮 reply:", (s2.get("reply") or "")[:200])
    print("session 保持:", s2.get("session_id") == s.get("session_id"))


if __name__ == "__main__":
    main()
