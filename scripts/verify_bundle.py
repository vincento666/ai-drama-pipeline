#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 dist bundle 是否含 P6b 标记。"""
import re
from pathlib import Path

d = Path("web/dist")
idx = (d / "index.html").read_text(encoding="utf-8")
m = re.search(r'src="([^"]+)"', idx)
if not m:
    print("no js src found in index.html")
    raise SystemExit(1)
js = d / m.group(1).lstrip("/")
b = js.read_text(encoding="utf-8")
print("js:", js.name, "len:", len(b))
for mark in ["ShotPromptPanel", "compose-order", "分镜提示词", "hasPrompt",
             "拖拽", "重排", "生成分镜提示词", "播放"]:
    print("[%s]" % mark, mark in b)
