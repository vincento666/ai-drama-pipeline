#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 主链路验收（DSH 侧）：SSE 事件完整性 + 顺序 + 终态 + doc.diff/rev 刷新链。

用法: python scripts/smoke_accept.py [port=18999]
不改业务数据：patch 用例先备份 smoke/E01/分镜.md，跑完还原。
"""
import json
import shutil
import sys
import threading
import time
import urllib.request
import urllib.parse
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18999
BASE = "http://127.0.0.1:%d" % PORT
PROJECT = "smoke"
EPISODE = 1
SB = Path("output") / PROJECT / ("E%02d" % EPISODE) / "分镜.md"

recv = []          # (event, payload)
recv_lock = threading.Lock()
stop = threading.Event()


def sse_listen():
    url = "%s/api/events?%s" % (BASE, urllib.parse.urlencode(
        {"project": PROJECT, "episode": EPISODE}))
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            ev = None
            for raw in r:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    with recv_lock:
                        recv.append((ev, line[5:].strip()))
    except Exception as ex:
        with recv_lock:
            recv.append(("__sse_error__", str(ex)))
    finally:
        stop.set()


def api_get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def api_post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_for(pred, timeout=90, label="?"):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with recv_lock:
            if pred(recv):
                return True
        if stop.is_set():
            return False
        time.sleep(0.3)
    return False


def main():
    print("== SSE 主链路验收 (port %d) ==" % PORT)
    backup = None
    if SB.exists():
        backup = SB.with_suffix(".md.bak")
        shutil.copy2(SB, backup)

    t = threading.Thread(target=sse_listen, daemon=True)
    t.start()
    time.sleep(0.8)

    # 1) 建会话 + chat「你好」→ trace + session.msg
    sess = api_post("/api/sessions", {"project": PROJECT, "title": "验收冒烟"})
    sid = sess["session"]["id"]
    print("[1] 会话创建:", sid)
    r = api_post("/api/sessions/%s/chat" % sid, {"text": "你好", "episode": 1})
    print("[1] chat 你好 →", r.get("task_id"))
    ok1 = wait_for(lambda rs: any(e == "session.msg" for e, _ in rs), 60, "session.msg")
    print("[1] session.msg 到达:", "OK" if ok1 else "FAIL")

    # 2) chat patch「把镜1的灯光改为夜景」→ doc.diff + rev + trace 终态
    r2 = api_post("/api/sessions/%s/chat" % sid, {"text": "把镜1的灯光改为夜景", "episode": 1})
    print("[2] chat patch →", r2.get("task_id"))
    ok2 = wait_for(lambda rs: any(e == "doc.diff" for e, _ in rs), 60, "doc.diff")
    print("[2] doc.diff 到达:", "OK" if ok2 else "FAIL")
    ok3 = wait_for(lambda rs: any(e == "rev" for e, _ in rs), 30, "rev")
    print("[2] rev 到达:", "OK" if ok3 else "FAIL")

    # 3) 事件完整性：终态检查（每个 task 的 running 事件都要有配对终态）
    time.sleep(1.5)
    evs = api_get("/api/sessions/%s/events?limit=100" % sid).get("events") or []
    runs, terms = {}, {}
    for e in evs:
        k = (e.get("kind"), e.get("title"))
        if e.get("status") == "running":
            runs[k] = runs.get(k, 0) + 1
        else:
            terms[k] = terms.get(k, 0) + 1
    stuck = {k: v for k, v in runs.items() if terms.get(k, 0) < v}
    print("[3] 事件数:", len(evs), "| 卡死 running:", stuck if stuck else "无 [OK]")
    print("[3] 顺序（前 12 条）:")
    for e in evs[:12]:
        print("    %-9s %-8s %-28s %s" % (e.get("status"), e.get("kind"),
                                           (e.get("title") or "")[:26], (e.get("summary") or "")[:20]))

    # 4) messages 收尾（tool + assistant 都存在）
    msgs = api_get("/api/sessions/%s/messages" % sid).get("messages") or []
    roles = [m.get("role") for m in msgs]
    print("[4] 消息 roles:", roles, "| tool 含事件:", any(
        m.get("role") == "tool" and (m.get("meta") or {}).get("events") for m in msgs))

    # 5) 画布 rev 是否变化（刷新链依据）
    c1 = api_get("/api/canvas/%s/%d" % (PROJECT, EPISODE))
    time.sleep(1)
    c2 = api_get("/api/canvas/%s/%d" % (PROJECT, EPISODE))
    print("[5] canvas rev 变化（patch 后）:", c1.get("rev"), "→", c2.get("rev"),
          "|", "OK" if c1.get("rev") != c2.get("rev") else "注意:未变(可能patch前已变)")

    # 清理：删会话 + 还原分镜.md
    try:
        req = urllib.request.Request(BASE + "/api/sessions/%s" % sid, method="DELETE")
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass
    if backup and backup.exists():
        shutil.copy2(backup, SB)
        backup.unlink()
    print("== 验收结束 ==")


if __name__ == "__main__":
    main()
