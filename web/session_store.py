#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 会话存储层（仅标准库）。

落盘（docs/11-前端重构设计方案.md §7 / §9.4）：
  profile/sessions/<project>/<session-id>.json         会话（meta + messages + tasks）
  profile/sessions/<project>/<session-id>.events.jsonl 审计事件回执（P3 前端读它做时间线）

会话 JSON：
  {id, project, title, created, updated, archived,
   messages: [{role: user|assistant|tool, text, ts, meta}],
   tasks: [{id, title, kind, status, created, updated, summary}]}

事件 JSONL 每行：
  {ts, session_id, task_id, kind, title, status, summary, detail}
  kind ∈ subtask|command|search|tool|patch；status ∈ running|success|error|skip

上限：每项目 50 个非归档会话，超出把最旧的非归档会话置 archived=true（记录保留）。
"""
import json
import re
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_ROOT = ROOT / "profile" / "sessions"
MAX_SESSIONS = 50          # 每项目非归档会话上限（docs §13 默认）
MAX_TASKS = 50             # 单会话保留任务条数（滚动）
ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
ROLES = ("user", "assistant", "tool")
KINDS = ("subtask", "command", "search", "tool", "patch")
STATUSES = ("running", "success", "error", "skip")

_LOCK = threading.Lock()


def _check_project(project):
    if not project or not PROJECT_RE.match(str(project)):
        raise ValueError("非法项目名: %r" % project)
    return str(project)


def _check_sid(sid):
    if not sid or not ID_RE.match(str(sid)):
        raise ValueError("非法会话 id: %r" % sid)
    return str(sid)


def _session_path(project, sid):
    p = SESSIONS_ROOT / project / ("%s.json" % sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _events_path(project, sid):
    return SESSIONS_ROOT / project / ("%s.events.jsonl" % sid)


def _read_raw(project, sid):
    p = _session_path(project, sid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_raw(session):
    _session_path(session["project"], session["id"]).write_text(
        json.dumps(session, ensure_ascii=False, indent=1), encoding="utf-8")


def _read_all(project):
    """读某项目全部会话文件（按 updated 倒序）。"""
    _check_project(project)
    d = SESSIONS_ROOT / project
    out = []
    if not d.exists():
        return out
    for f in sorted(d.glob("*.json")):
        sid = f.stem
        if not ID_RE.match(sid):
            continue
        s = _read_raw(project, sid)
        if s is None:
            continue
        out.append(s)
    out.sort(key=lambda s: s.get("updated") or s.get("created") or 0, reverse=True)
    return out


def list_sessions(project):
    """会话列表（含 archived 标记 + running 状态点）。"""
    out = []
    for s in _read_all(project):
        running = any((t or {}).get("status") == "running"
                      for t in (s.get("tasks") or []))
        out.append({
            "id": s["id"], "project": s["project"],
            "title": s.get("title") or s["id"],
            "created": s.get("created"), "updated": s.get("updated"),
            "archived": bool(s.get("archived")), "running": running,
        })
    return out


def create_session(project, title=""):
    """新建会话：id = uuid 前 12 位；标题空 → 「会话 N」；超上限归档最旧活跃会话。"""
    project = _check_project(project)
    with _LOCK:
        sessions = _read_all(project)
        if len(sessions) >= MAX_SESSIONS:
            active = [s for s in sessions if not s.get("archived")]
            if active:
                oldest = min(active, key=lambda s: s.get("updated")
                             or s.get("created") or 0)
                oldest["archived"] = True
                _write_raw(oldest)
        now = time.time()
        title = (title or "").strip() or "会话 %d" % (len(sessions) + 1)
        session = {
            "id": uuid.uuid4().hex[:12],
            "project": project,
            "title": title,
            "created": now, "updated": now,
            "archived": False,
            "messages": [], "tasks": [],
        }
        _write_raw(session)
        return session


def get_session(project, sid):
    """取会话 dict；不存在返回 None。"""
    project, sid = _check_project(project), _check_sid(sid)
    return _read_raw(project, sid)


def delete_session(project, sid):
    """删除会话（json + events 文件）。返回是否删除成功。"""
    project, sid = _check_project(project), _check_sid(sid)
    with _LOCK:
        p = _session_path(project, sid)
        if not p.exists():
            return False
        p.unlink()
        ep = _events_path(project, sid)
        if ep.exists():
            ep.unlink()
        return True


def touch(project, sid):
    """更新会话 updated 时间戳。"""
    project, sid = _check_project(project), _check_sid(sid)
    with _LOCK:
        s = _read_raw(project, sid)
        if s is None:
            return False
        s["updated"] = time.time()
        _write_raw(s)
        return True


def add_message(project, sid, role, text, meta=None):
    """追加一条消息。返回新消息 dict。"""
    project, sid = _check_project(project), _check_sid(sid)
    if role not in ROLES:
        raise ValueError("非法 role: %r（可用 %s）" % (role, "/".join(ROLES)))
    msg = {"role": role, "text": text or "", "ts": time.time(), "meta": meta or {}}
    with _LOCK:
        s = _read_raw(project, sid)
        if s is None:
            raise KeyError("会话不存在: %s" % sid)
        s.setdefault("messages", []).append(msg)
        s["updated"] = msg["ts"]
        _write_raw(s)
    return msg


def list_messages(project, sid):
    """消息列表（正序）。"""
    s = get_session(project, sid)
    return (s or {}).get("messages") or []


def add_task(project, sid, task):
    """追加任务到会话任务队列。task: {id, title, kind, status, ...}。"""
    project, sid = _check_project(project), _check_sid(sid)
    with _LOCK:
        s = _read_raw(project, sid)
        if s is None:
            raise KeyError("会话不存在: %s" % sid)
        tasks = s.setdefault("tasks", [])
        tasks.append(task)
        if len(tasks) > MAX_TASKS:
            del tasks[:len(tasks) - MAX_TASKS]
        s["updated"] = time.time()
        _write_raw(s)


def update_task(project, sid, task_id, patch):
    """按 task_id 更新任务字段（status/summary/updated…）。"""
    project, sid = _check_project(project), _check_sid(sid)
    with _LOCK:
        s = _read_raw(project, sid)
        if s is None:
            return False
        for t in s.get("tasks") or []:
            if t.get("id") == task_id:
                t.update(patch or {})
                t["updated"] = time.time()
                s["updated"] = t["updated"]
                _write_raw(s)
                return True
        return False


def list_tasks(project, sid):
    """会话任务队列（新→旧）。"""
    s = get_session(project, sid)
    tasks = list((s or {}).get("tasks") or [])
    tasks.sort(key=lambda t: t.get("created") or 0, reverse=True)
    return tasks


def add_event(project, sid, kind, title, status, summary="", detail="", task_id=None):
    """写一行审计事件回执（追加 events.jsonl）。kind/status 校验。"""
    project, sid = _check_project(project), _check_sid(sid)
    if kind not in KINDS:
        raise ValueError("非法事件 kind: %r（可用 %s）" % (kind, "/".join(KINDS)))
    if status not in STATUSES:
        raise ValueError("非法事件 status: %r（可用 %s）" % (status, "/".join(STATUSES)))
    ev = {"ts": round(time.time(), 3), "session_id": sid, "task_id": task_id,
          "kind": kind, "title": title or "", "status": status,
          "summary": summary or "", "detail": detail or ""}
    with _LOCK:
        p = _events_path(project, sid)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def list_events(project, sid, limit=100, offset=0, task_id=None, kind=None, status=None):
    """审计事件（倒序，新→旧），支持 limit/offset 分页与 task_id/kind/status 过滤。

    返回 {events, total}；total = 过滤后的总数（用于分页）。
    """
    s = get_session(project, sid)
    if s is None:
        return {"events": [], "total": 0}
    p = _events_path(project, sid)
    rows = []
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            if task_id is not None and ev.get("task_id") != task_id:
                continue
            if kind and ev.get("kind") != kind:
                continue
            if status and ev.get("status") != status:
                continue
            rows.append(ev)
    total = len(rows)
    rows.reverse()                          # 倒序：新 → 旧
    rows = rows[offset:offset + limit]
    return {"events": rows, "total": total}
