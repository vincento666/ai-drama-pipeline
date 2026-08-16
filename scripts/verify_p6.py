#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P6a/P6b 联验（18999）：compose-order / render 403 / selected 过滤 / bundle 标记。"""
import io
import json
import urllib.request as u

BASE = "http://127.0.0.1:18999"


def get(p):
    return json.loads(u.urlopen(BASE + p, timeout=30).read())


def post(p, payload):
    req = u.Request(BASE + p, data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(u.urlopen(req, timeout=30).read())


print("[order]", get("/api/compose-order?project=smoke&episode=1"))
try:
    r = post("/api/render", {"project": "smoke", "episode": 1, "only": "3", "shots": 1})
    print("[render403]", r)
except Exception as e:
    print("[render403]", "HTTP", getattr(e, "code", e))
st = get("/api/episode-status/smoke/1")
print("[status] selected=%d" % len(st.get("selected", [])))
h = u.urlopen(BASE + "/", timeout=10)
idx = h.read().decode("utf-8", "replace")
js = idx.split('src="')[1].split('"')[0]
b = u.urlopen(BASE + js, timeout=20).read().decode("utf-8", "replace")
for mark in ["ShotPromptPanel", "播放", "compose-order", "分镜提示词", "hasPrompt", "拖拽", "重排", "生成分镜提示词"]:
    print("[bundle:%s]" % mark, mark in b)
