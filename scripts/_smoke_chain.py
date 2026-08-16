#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""链式真实生成冒烟：骨架 → 剧本 → 资产 → 分镜（smoke 项目，v4 flash）。

用法：python scripts/_smoke_chain.py [project]
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:18999"
PROJECT = sys.argv[1] if len(sys.argv) > 1 else "smoke"


def api(path, payload=None, method=None, timeout=30):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_job(jid, label, deadline):
    while time.time() < deadline:
        s = api("/api/render/status/" + jid)
        if s["status"] == "running":
            print("  [%s] %s" % (label, s.get("message", "")))
        else:
            return s
        time.sleep(5)
    return {"status": "error", "message": "timeout"}


def step(label, path, payload, timeout_min=6):
    print("=== %s ===" % label)
    r = api(path, payload)
    s = wait_job(r["job"], label, time.time() + timeout_min * 60)
    if s["status"] != "done":
        print("  FAILED: %s" % s.get("message"))
        return None
    res = s.get("result") or {}
    if res.get("mode") != "llm":
        print("  AGENT 模式（无 LLM 或失败）: %s" % res.get("error", ""))
        return None
    text = res.get("text") or ""
    print("  OK, %d 字" % len(text))
    print("  前 200 字: %s" % text[:200].replace("\n", " / "))
    return res


def main():
    print("项目: %s" % PROJECT)
    step("① 故事骨架", "/api/ai-write/" + PROJECT, {"mode": "skeleton"})
    step("② 逐集剧本", "/api/ai-write/" + PROJECT, {"mode": "script"})
    step("③ 资产清单", "/api/ai-write/" + PROJECT, {"mode": "assets"})
    print("=== ④ 镜头分镜（LLM 优先，job 轮询） ===")
    try:
        r = api("/api/storyboard-gen", {"project": PROJECT, "episode": 1})
        s = wait_job(r["job"], "镜头分镜", time.time() + 6 * 60)
        if s["status"] != "done":
            print("  FAILED: %s" % s.get("message"))
            return
        res = s.get("result") or {}
        print("  OK method=%s path=%s" % (res.get("method"), res.get("path")))
    except Exception as ex:
        print("  FAILED: %s" % ex)


if __name__ == "__main__":
    main()
