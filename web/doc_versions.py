#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P5 文档版本 / 快照 / 回滚（docs/11-前端重构设计方案.md §10，仅标准库）。

数据落盘（profile/ 已 gitignore）：
  profile/versions/<project>/<doc>.jsonl      版本索引（每行 {rev, ts, source, note}，rev 升序追加）
  profile/versions/<project>/<doc>/<rev>.md   内容快照（避免单文件膨胀；每文档滚动保留 MAX_REVS 份）

doc ∈ novel|brief|script|board|assets|compose，各 doc 内容模型：
  novel   项目/小说.md（单文件）
  brief   项目/创作简报.md（单文件）
  script  项目/小说事件.md + 故事骨架.md + 剧本.md（多文件，marker 分段序列化）
  board   E<ep>/分镜.md（单文件，按集）
  assets  项目/资产清单.md + assets/.registry/*.md（多文件）
  compose E<ep>/selected-note.md（单文件；成片.mp4 为二进制，无文本快照源，当前无触发点）

触发点（避开 ai_writer.py / agent_manager.py，见 P5 任务单）：
  - workflow_patch.apply_patch（应用前，按改动目标文件归类 doc）
  - server.py PUT storyboard / /api/novel / /api/brief / /api/asset
恢复（restore）先快照当前状态（保证可再撤销），再写回目标版本内容，
并广播 rev + doc.diff（由调用方——server.py——负责 event_bus 广播）。
"""
import difflib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import common        # noqa: E402  路径（OUTPUT / ASSETS 随测试可重定向）
import ai_writer     # noqa: E402  文档文件名常量（只读，不改其写入）

MAX_REVS = 20        # 每文档滚动保留上限（docs/11 §10：每文档上限 20 份）


def _versions_root():
    """版本存储根：随 common.OUTPUT 派生（生产 = ROOT/profile/versions；
    单元测试重定向 OUTPUT 到临时目录时快照落到临时目录，不污染仓库 profile/）。"""
    return common.OUTPUT.parent / "profile" / "versions"

DOCS = ("novel", "brief", "script", "board", "assets", "compose")
DOC_LABELS = {"novel": "小说", "brief": "简报", "script": "剧本",
              "board": "分镜", "assets": "资产", "compose": "成片"}

# 多文件 doc 的 marker 分段格式（单文件 doc 直接存原文）
_FILE_MARK = "\n<!-- @@FILE:%s@@ -->\n"
_FILE_RE = re.compile(r"^<!-- @@FILE:(.*?)@@ -->\s*$")
_MULTI = {"script", "assets"}
_GLOBAL_PROJECT = "_global"   # /api/asset 全局资产登记的快照项目名（不创建 output/_global）


# ============ 内容模型：doc → 文件部件 ============

def _file_parts(project, doc, episode=1):
    """doc → [(part_name|None, Path)]。单文件 doc 的 part_name=None（整文即文件）。

    board/compose 按集定位；assets 额外含全局注册表（registry:<code> → assets/.registry/<code>.md）。
    _GLOBAL_PROJECT 只登记注册表部分，不触碰项目目录（避免污染项目列表）。
    """
    if doc == "novel":
        return [(None, common.project_dir(project) / ai_writer.NOVEL_FILE)]
    if doc == "brief":
        return [(None, common.project_dir(project) / ai_writer.BRIEF_FILE)]
    if doc == "script":
        root = common.project_dir(project)
        return [(ai_writer.EVENTS_FILE, root / ai_writer.EVENTS_FILE),
                (ai_writer.SKELETON_FILE, root / ai_writer.SKELETON_FILE),
                (ai_writer.SCRIPT_FILE, root / ai_writer.SCRIPT_FILE)]
    if doc == "board":
        return [(None, common.episode_dir(project, episode) / "分镜.md")]
    if doc == "assets":
        parts = []
        if project != _GLOBAL_PROJECT:
            parts.append((ai_writer.ASSETS_FILE,
                          common.project_dir(project) / ai_writer.ASSETS_FILE))
        reg = common.ASSETS / ".registry"
        if reg.is_dir():
            for f in sorted(reg.iterdir()):
                if f.suffix == ".md" and f.is_file():
                    parts.append(("registry:" + f.stem, f))
        return parts
    if doc == "compose":
        return [(None, common.episode_dir(project, episode) / "selected-note.md")]
    raise ValueError("未知文档: %s（可用: %s）" % (doc, "/".join(DOCS)))


def _serialize(parts):
    """[(name|None, path)] → 快照文本（多文件 doc 用 marker 分段；单文件 doc 返回原文）。"""
    if not parts:
        return ""
    if len(parts) == 1 and parts[0][0] is None:
        p = parts[0][1]
        return p.read_text(encoding="utf-8") if p.exists() else ""
    chunks = []
    for name, path in parts:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        chunks.append((_FILE_MARK % name) + text.rstrip("\n"))
    body = "".join(chunks)
    return body.lstrip("\n") + ("\n" if body else "")


def _deserialize(text):
    """marker 分段文本 → [(name, content)]（与 _serialize 互逆）。"""
    out, cur = [], None
    for line in text.split("\n"):
        m = _FILE_RE.match(line)
        if m:
            if cur is not None:
                out.append(cur)
            cur = [m.group(1).strip(), []]
        elif cur is not None:
            cur[1].append(line)
    if cur is not None:
        out.append(cur)
    if not out and text.strip():
        out.append([None, text.split("\n")])
    return [(name, "\n".join(lines).strip("\n")) for name, lines in out]


def _write_part(project, doc, name, content, episode=1):
    """把单个部件内容写回原文件（name=None → 单文件 doc 的主文件）。"""
    if name is None:
        parts = _file_parts(project, doc, episode)
        if not parts:
            return
        path = parts[0][1]
    elif name.startswith("registry:"):
        path = common.ASSETS / ".registry" / (name[len("registry:"):] + ".md")
    else:
        path = common.project_dir(project) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_doc(project, doc, episode=1):
    """读文档当前内容 → (text, parts)。parts: [{name, path, text}]（供 diff 分部件）。"""
    file_parts = _file_parts(project, doc, episode)
    parts = [{"name": n, "path": str(p),
              "text": p.read_text(encoding="utf-8") if p.exists() else ""}
             for n, p in file_parts]
    return _serialize(file_parts), parts


def _is_multi(doc):
    return doc in _MULTI


# ============ 版本索引（jsonl） ============

def _revs_path(project, doc):
    return _versions_root() / project / (doc + ".jsonl")


def _rev_dir(project, doc):
    return _versions_root() / project / doc


def _read_revs(project, doc):
    """全部版本记录（按 rev 降序）。文件不存在返回 []。"""
    p = _revs_path(project, doc)
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if isinstance(rec, dict) and rec.get("rev"):
                out.append(rec)
    except Exception:
        return []
    out.sort(key=lambda r: int(r["rev"]), reverse=True)
    return out


def _trim(project, doc):
    """滚动保留最近 MAX_REVS 份（索引 + 内容文件）。"""
    revs = _read_revs(project, doc)
    if len(revs) <= MAX_REVS:
        return
    keep = revs[:MAX_REVS]
    p = _revs_path(project, doc)
    with open(p, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    rdir = _rev_dir(project, doc)
    for r in revs[MAX_REVS:]:
        f = rdir / ("%d.md" % int(r["rev"]))
        if f.exists():
            try:
                f.unlink()
            except OSError:
                pass


# ============ 对外 API ============

def snapshot(project, doc, source="", note="", episode=1):
    """写前快照：捕获文档当前内容为新版本。返回 rev（int）；内容为空或失败返回 None。

    由写盘端点/apply_patch 在**写入前**调用（undo 的“上一版本” = 最新一条快照）。
    任何异常都不抛出——快照是附加能力，绝不能拖垮写盘主流程。
    """
    try:
        if doc not in DOCS:
            return None
        text, _parts = read_doc(project, doc, episode)
        if not text.strip():
            return None
        revs = _read_revs(project, doc)
        rev = (max(int(r["rev"]) for r in revs) + 1) if revs else 1
        rdir = _rev_dir(project, doc)
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / ("%d.md" % rev)).write_text(text, encoding="utf-8")
        rec = {"rev": rev, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
               "source": source or "", "note": note or ""}
        with open(_revs_path(project, doc), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _trim(project, doc)
        return rev
    except Exception:
        return None


def list_revs(project, doc):
    """版本列表（倒序）→ [{rev, ts, source, note}]。"""
    if doc not in DOCS:
        return []
    return _read_revs(project, doc)


def get_rev_content(project, doc, rev):
    """指定版本内容文本；不存在抛 ValueError。"""
    p = _rev_dir(project, doc) / ("%d.md" % int(rev))
    if not p.exists():
        raise ValueError("版本内容缺失: %s/%s #%s" % (project, doc, rev))
    return p.read_text(encoding="utf-8")


def restore(project, doc, rev, episode=1):
    """恢复指定版本内容写回原文件。

    先快照当前状态（source=restore，保证回滚后可再次撤销），再写回目标版本。
    返回恢复记录 {rev, ts, source, note}；版本不存在/内容缺失抛 ValueError。
    """
    if doc not in DOCS:
        raise ValueError("未知文档: %s" % doc)
    rev = int(rev)
    revs = _read_revs(project, doc)
    rec = next((r for r in revs if int(r["rev"]) == rev), None)
    if rec is None:
        raise ValueError("版本不存在: %s/%s #%s" % (project, doc, rev))
    content = get_rev_content(project, doc, rev)
    snapshot(project, doc, source="restore", note="回滚前状态", episode=episode)
    parts = _deserialize(content) if _is_multi(doc) else [(None, content)]
    if _is_multi(doc) and not parts:
        raise ValueError("版本内容无法解析: %s/%s #%s" % (project, doc, rev))
    for name, text in parts:
        _write_part(project, doc, name, text, episode)
    return rec


def _line_diff(old_text, new_text):
    """行级 diff（difflib.SequenceMatcher，仅标准库）：
    返回 (added: [new 行号], removed: [old 行号])，行号 1 起。"""
    old = (old_text or "").splitlines()
    new = (new_text or "").splitlines()
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    added, removed = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            removed += list(range(i1 + 1, i2 + 1))
        if tag in ("replace", "insert"):
            added += list(range(j1 + 1, j2 + 1))
    return added, removed


def diff(project, doc, rev, episode=1):
    """当前内容 vs 指定 rev 的 diff（供 GET /api/docs/revs/diff）。

    返回 {diff: unified_diff 文本, files: [{name, added, removed}]}；
    files 按部件给出行号（多文件 doc 的 name 为文件名/registry:<code>，单文件为 None）。
    """
    if doc not in DOCS:
        raise ValueError("未知文档: %s" % doc)
    rev = int(rev)
    revs = _read_revs(project, doc)
    rec = next((r for r in revs if int(r["rev"]) == rev), None)
    if rec is None:
        raise ValueError("版本不存在: %s/%s #%s" % (project, doc, rev))
    old_text = get_rev_content(project, doc, rev)
    new_text, parts = read_doc(project, doc, episode)
    full = "".join(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                                        fromfile="版本 #%d（%s）" % (rev, rec.get("ts", "")),
                                        tofile="当前", lineterm="\n"))
    files = []
    if _is_multi(doc):
        old_parts = {name: t for name, t in _deserialize(old_text)}
        for p in parts:
            added, removed = _line_diff(old_parts.get(p["name"], ""), p["text"])
            if added or removed:
                files.append({"name": p["name"], "added": added, "removed": removed})
    else:
        added, removed = _line_diff(old_text, new_text)
        if added or removed:
            files.append({"name": None, "added": added, "removed": removed})
    return {"diff": full, "files": files}


def doc_of_change(ch):
    """变更项 → 文档 key（apply_patch / /api/patch 广播用）；无归属（ref 提示词等）返回 None。

    op=shot → board；op=script 按 block 归类（novel/brief/assets/其余→script）；ref 无文本 doc。
    """
    op = (ch or {}).get("op")
    if op in ("shot", "reorder"):
        return "board"
    if op == "script":
        block = (ch or {}).get("block")
        if block == "novel":
            return "novel"
        if block == "brief":
            return "brief"
        if block == "assets":
            return "assets"
        return "script"          # events/skeleton/script 三块归剧本
    return None


if __name__ == "__main__":
    # 自测：python web/doc_versions.py <project> <doc> [episode]
    import argparse
    ap = argparse.ArgumentParser(description="文档版本工具（P5）")
    ap.add_argument("project")
    ap.add_argument("doc", choices=DOCS)
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--snapshot", action="store_true", help="对当前内容做一次快照")
    ap.add_argument("--revs", action="store_true", help="列出版本")
    a = ap.parse_args()
    if a.snapshot:
        print("快照 rev:", snapshot(a.project, a.doc, source="cli", episode=a.episode))
    if a.revs or not a.snapshot:
        for r in list_revs(a.project, a.doc):
            print("#%s %s [%s] %s" % (r["rev"], r["ts"], r["source"], r["note"]))
