#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 SSE 事件总线测试（web/event_bus.py，docs/11-前端重构设计方案.md §9.1）。

运行：
  python -m pytest scripts -q -s        # 全量（含本文件）
"""
import sys
import time
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

import event_bus  # noqa: E402


def test_publish_filtered_by_project():
    """按 project 过滤：只发给匹配订阅。"""
    a = event_bus.subscribe("p1")
    b = event_bus.subscribe("p2")
    try:
        event_bus.publish("rev", {"rev": "x"}, project="p1")
        ev = next(event_bus.iter_events(a))
        assert ev[0] == "rev"
        assert ev[1] == '{"rev": "x"}'
        assert event_bus._SUBS[b]["q"].empty()   # p2 收不到
    finally:
        event_bus.unsubscribe(a)
        event_bus.unsubscribe(b)


def test_publish_all_when_no_project():
    """无 project 过滤 → 广播全部订阅。"""
    a = event_bus.subscribe("p1")
    try:
        event_bus.publish("job", {"id": "job0001"})
        ev = next(event_bus.iter_events(a))
        assert ev[0] == "job"
        assert "job0001" in ev[1]
    finally:
        event_bus.unsubscribe(a)


def test_heartbeat_none_on_timeout():
    """心跳超时：iter_events 产出 None（调用方写 : ping 注释行）。"""
    old = event_bus.HEARTBEAT_SECONDS
    event_bus.HEARTBEAT_SECONDS = 0.15
    cid = event_bus.subscribe("p")
    try:
        t0 = time.time()
        frame = next(event_bus.iter_events(cid))
        assert frame is None
        assert time.time() - t0 >= 0.10
    finally:
        event_bus.HEARTBEAT_SECONDS = old
        event_bus.unsubscribe(cid)


def test_prune_stale_subscription():
    """连接超时清理：无活动超时的订阅被 prune 移除。"""
    cid = event_bus.subscribe("p")
    event_bus.touch(cid)
    with event_bus._LOCK:
        event_bus._SUBS[cid]["last"] = time.time() - 999
    event_bus.prune(max_idle=60)
    assert cid not in event_bus._SUBS


def test_queue_full_drops_oldest():
    """慢消费者：队列满丢最旧，保证新事件可达（SSE 是增量流）。"""
    old = event_bus.QUEUE_MAX
    event_bus.QUEUE_MAX = 2
    cid = event_bus.subscribe("p")
    try:
        for i in range(4):
            event_bus.publish("rev", {"rev": str(i)}, project="p")
        ev = next(event_bus.iter_events(cid))
        assert ev[1] == '{"rev": "2"}'   # 只保留最新两条
    finally:
        event_bus.QUEUE_MAX = old
        event_bus.unsubscribe(cid)
