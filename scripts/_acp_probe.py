#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ACP 协议探测（Windows 安全版）：读线程 + 队列。"""
import json
import queue
import subprocess
import threading
import time


def main():
    proc = subprocess.Popen(["kimi", "acp"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)
    q = queue.Queue()
    def reader():
        for line in proc.stdout:
            s = line.strip()
            if s:
                q.put(s)
    threading.Thread(target=reader, daemon=True).start()

    def send(obj):
        proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def drain(duration, label):
        end = time.time() + duration
        while time.time() < end:
            try:
                line = q.get(timeout=0.3)
                print("[%s] %s" % (label, line[:400]))
            except queue.Empty:
                continue

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": 1, "clientCapabilities": {},
                     "clientInfo": {"name": "probe", "version": "0.1"}}})
    drain(4, "init")
    send({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {}})
    drain(4, "new")
    send({"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
          "params": {"sessionId": "s1", "prompt": "只回复两个字：收到"}})
    drain(30, "prompt")
    proc.kill()


if __name__ == "__main__":
    main()
