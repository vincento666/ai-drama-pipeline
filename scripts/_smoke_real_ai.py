#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整改冒烟：资产删除 + 真实 AI 单步编剧（LLM job）。"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:18999"


def api(path, payload=None, method=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    # 1) 资产删除：注册一个临时资产再删除
    reg = api("/api/asset", {"code": "P99", "name": "临时冒烟资产"})
    print("1. register:", reg)
    delres = api("/api/asset/P99", method="DELETE")
    print("2. delete:", delres)
    assert delres["ok"] and delres["removed"] >= 1, "delete failed"

    # 2) 真实 AI 单步编剧：小说 → 事件图谱（后台 job）
    novel = ("少年林小满自幼失怙，与爷爷在山村相依为命。一日，他在后山捡到一枚古镜，"
             "镜中竟能映出三日后之事。他借此避开了一场山洪，救了全村，却被镜中黑影盯上——"
             "黑影要在月圆之夜夺回古镜，代价是全村的记忆。")
    r = api("/api/ai-write/smoke", {"novel": novel, "mode": "events"})
    print("3. ai-write job:", r)
    jid = r["job"]
    deadline = time.time() + 300
    while time.time() < deadline:
        s = api("/api/render/status/" + jid)
        print("   status:", s["status"], s.get("message", ""))
        if s["status"] in ("done", "error"):
            break
        time.sleep(5)
    res = s.get("result") or {}
    print("4. result mode:", res.get("mode"), "| ok:", res.get("ok"))
    if res.get("mode") == "llm":
        print("5. 事件图谱前 300 字：")
        print(res.get("text", "")[:300])
    else:
        print("   （LLM 不可用/失败：", s.get("message"), "）")


if __name__ == "__main__":
    main()
