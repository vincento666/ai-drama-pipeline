#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收：视频制作流水线（选片 4 镜 → 参考图晋升 → 拼接成片）+ 配置读写。"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:18999"


def api(path, payload=None, method=None, timeout=120):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    print("== 1. 候选现状 ==")
    for shot in (1, 2, 3, 4):
        c = api("/api/candidates/smoke/1/%d" % shot)
        names = [f["name"] for f in c.get("files", [])]
        print("  镜%d: %s" % (shot, ", ".join(names) or "无"))

    print("== 2. 选片 4 镜（选中原因留痕） ==")
    for shot in (1, 2, 3, 4):
        r = api("/api/select", {"project": "smoke", "episode": 1, "shot": shot,
                                "file": "shot_%02d_01.mp4" % shot, "note": "验收冒烟选中"})
        print("  镜%d 选中: %s" % (shot, r.get("ok")))

    print("== 3. 参考图晋升（F9：选中片首帧 → refs/shot_XX.png） ==")
    c = api("/api/canvas/smoke/1")
    refs = {r["shot"]: r["image"] for r in c["storyboard"]["refs"]}
    print("  refs 图: %s" % {k: v for k, v in refs.items() if v})

    print("== 4. 拼接成片 ==")
    r = api("/api/compose", {"project": "smoke", "episode": 1})
    print("  compose:", json.dumps(r, ensure_ascii=False)[:200])

    print("== 5. 成片与质检 ==")
    st = api("/api/episode-status/smoke/1")
    print("  selected:", st.get("selected"))
    print("  composed:", st.get("composed"))

    print("== 6. 配置读写（config.local.json 覆盖） ==")
    g = api("/api/config-agent")
    print("  agent.default:", g["agent"].get("default"), "| lhh.available:", g["lhh"]["available"],
          "| lhh.source:", g["lhh"]["source"])
    p = api("/api/config-agent", {"agent": {"default": "kimi", "max_rounds": 5}}, method="PUT")
    print("  PUT ok:", p.get("ok"), "| default:", p["agent"].get("default"))
    g2 = api("/api/config-agent")
    print("  回读 default:", g2["agent"].get("default"))


if __name__ == "__main__":
    main()
