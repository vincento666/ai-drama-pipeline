#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ACP 交互式对话冒烟：真实 kimi acp 多轮对话（原生能力：读文件 + 回答）。"""
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
import agentbridge  # noqa: E402

adapter = agentbridge.AcpAdapter(cwd=str(Path("output/smoke").resolve()))
adapter.start()
print("session:", adapter.session_id)

lines = []
text, updates = adapter.chat("只回复两个字：收到", on_line=lines.append)
print("=== 第一轮最终文本 ===")
print(text)
print("=== 事件数:", len(updates))

text2, _ = adapter.chat("现在读一下当前目录下 E01/分镜.md 的第一行并原样回复我", on_line=lines.append)
print("=== 第二轮（多轮会话保持）最终文本 ===")
print(text2[:300])

adapter.close()
