#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ACP 完整帧探测：prompt 全程帧 dump（含 result/response 的完整 JSON）。"""
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

    def wait_frame(duration, label):
        end = time.time() + duration
        while time.time() < end:
            try:
                line = q.get(timeout=0.3)
                print("[%s] %s" % (label, line))
                return line
            except queue.Empty:
                continue
        return None

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": 1, "clientCapabilities": {},
                     "clientInfo": {"name": "probe", "version": "0.1"}}})
    wait_frame(4, "init")
    send({"jsonrpc": "2.0", "id": 2, "method": "session/new",
          "params": {"cwd": r"S:\Develop\AIGC\ai-drama-pipeline-export\ai-drama-pipeline\output\smoke",
                     "mcpServers": {}}})
    newf = wait_frame(4, "new")
    session_id = None
    if newf:
        f = json.loads(newf)
        if "result" in f:
            session_id = f["result"].get("sessionId")
    print("session_id =", session_id)
    send({"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
          "params": {"sessionId": session_id,
                     "prompt": [{"type": "text", "text": "只回复两个字：收到"}]}})
    # dump 90 秒内的所有帧（不截断）
    end = time.time() + 90
    while time.time() < end:
        try:
            line = q.get(timeout=0.3)
            print("[prompt] " + line)
            f = json.loads(line)
            if f.get("method") == "session/result" or f.get("id") == 3:
                pass  # 继续看是否还有帧；超时结束
        except queue.Empty:
            continue
    proc.kill()


if __name__ == "__main__":
    main()
