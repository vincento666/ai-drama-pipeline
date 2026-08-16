#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 访谈冒烟：追问 → 回答 → 创作简报（真实 v4 flash）。"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:18999"


def api(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode("utf-8"))
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    desc = ("一部古镜题材的短剧：山村少年捡到能预知三日的古镜，靠它救全村，却被镜中黑影索要代价。"
            "目标观众是下沉市场，做竖屏爽感短剧。")
    r1 = api("/api/onboard/smoke", {"description": desc, "want": "questions"})
    print("=== 第一轮追问 ===")
    for i, q in enumerate(r1.get("questions", []), 1):
        print("%d. %s" % (i, q))
    answers = [{"q": r1["questions"][0], "a": "水墨赛璐璐混搭，BGM 用国风+惊悚双线"},
               {"q": r1["questions"][1], "a": "单集 2-3 分钟，共 12 集"},
               {"q": r1["questions"][2], "a": "主要角色 3 人：小满、爷爷、镜灵（反派）"}]
    r2 = api("/api/onboard/smoke", {"description": desc, "answers": answers, "want": "brief"})
    print("=== 创作简报（前 500 字） ===")
    print((r2.get("brief") or "")[:500])
    print("path:", r2.get("path"))


if __name__ == "__main__":
    main()
