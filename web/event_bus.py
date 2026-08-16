#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 SSE 事件总线（docs/11-前端重构设计方案.md §9.1，仅标准库）。

线程安全订阅表：每个 SSE 连接一个订阅（queue.Queue + 活动时间戳）。
- subscribe(project) / unsubscribe(cid)：连接生命周期（按项目过滤）。
- publish(event, data, project=None)：广播一条 JSON 事件；project 非空只发给匹配订阅。
- iter_events(cid)：迭代器，产出 (event, payload) 帧；心跳超时产出 None（调用方写 : ping）。
- touch(cid)：连接有活动（成功写出一帧/心跳）时刷新，供超时清理判定。
- prune(max_idle)：清理超过 max_idle 秒无活动的订阅（服务端连接超时兜底）。

事件载荷约定（docs/11 §9.1 事件表）：
  rev        {rev, episode}        画布事实源摘要变化（facts_rev）
  job        {id,status,progress,message,meta,...}  RENDER_JOBS 任务进度
  trace      {session_id, task_id, event}           manager 事件回执实时推送
  session.msg {session_id, task_id, chunk}          会话回复流式 chunk（空串=收尾）
  doc.diff   {doc, summary, episode?}               AI 写盘后文档变更摘要
"""
import json
import queue
import threading
import time

HEARTBEAT_SECONDS = 15    # 心跳间隔（docs/11 §9.1：15s）
QUEUE_MAX = 500           # 慢消费者事件上限（超限丢最旧，SSE 是增量流，新事件优先）
PRUNE_IDLE_SECONDS = 90   # 订阅无活动超时（连接超时清理）

_LOCK = threading.Lock()
_SUBS = {}                # cid -> {"project", "q": Queue, "last": float}
_seq = [0]


def subscribe(project):
    """注册订阅（按项目过滤），返回连接 id；SSE handler 在 finally 里 unsubscribe。"""
    with _LOCK:
        _seq[0] += 1
        cid = _seq[0]
        if len(_SUBS) > 64:          # 订阅较多时顺带清一次僵尸连接
            _prune_locked(PRUNE_IDLE_SECONDS)
        _SUBS[cid] = {"project": project,
                      "q": queue.Queue(maxsize=QUEUE_MAX),
                      "last": time.time()}
        return cid


def unsubscribe(cid):
    with _LOCK:
        _SUBS.pop(cid, None)


def touch(cid):
    """连接有活动（成功写出一帧/心跳）时刷新 last（供 prune 判定）。"""
    with _LOCK:
        sub = _SUBS.get(cid)
        if sub is not None:
            sub["last"] = time.time()


def publish(event, data, project=None):
    """广播一条事件：data 为 dict → JSON 序列化为 data 载荷；按 project 过滤。"""
    try:
        payload = json.dumps(data, ensure_ascii=False)
    except Exception:
        return
    with _LOCK:
        for cid, sub in list(_SUBS.items()):
            if project is not None and sub["project"] != project:
                continue
            try:
                sub["q"].put_nowait((event, payload))
            except queue.Full:
                # 慢消费者：丢最旧一条，保证新事件可达（心跳仍会维持连接）
                try:
                    sub["q"].get_nowait()
                    sub["q"].put_nowait((event, payload))
                except Exception:
                    pass


def iter_events(cid):
    """生成器：产出 (event, payload)；心跳超时产出 None（调用方写 : ping 注释行）。"""
    q = None
    with _LOCK:
        sub = _SUBS.get(cid)
        if sub is None:
            return
        q = sub["q"]
    while True:
        try:
            yield q.get(timeout=HEARTBEAT_SECONDS)
        except queue.Empty:
            yield None


def prune(max_idle=PRUNE_IDLE_SECONDS):
    """清理超过 max_idle 秒无活动（含写出成功）的订阅（服务端连接超时清理）。"""
    with _LOCK:
        _prune_locked(max_idle)


def _prune_locked(max_idle):
    now = time.time()
    dead = [cid for cid, sub in _SUBS.items() if now - sub["last"] > max_idle]
    for cid in dead:
        _SUBS.pop(cid, None)


def active_count():
    with _LOCK:
        return len(_SUBS)
