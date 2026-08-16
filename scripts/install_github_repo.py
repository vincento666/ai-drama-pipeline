#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 GitHub 安装仓库到本地目录（api.github.com trees + raw.githubusercontent.com 批量拉取，
github.com/codeload 不可达时可用）。也是 skill_mgr 安装工具的底层实现。

用法: python scripts/install_github_repo.py <owner/repo> <target_dir> [ref=main] [--skip docs,*.gif]
      python scripts/install_github_repo.py <owner/repo> <target_dir> [ref] --only <子目录> [--force]

核心函数 install_repo() 可被 import 复用（skill_mgr.install_from_url 走同一 api+raw 链路），
CLI 保持原行为（进度打印 + 断点续传：目标已存在且非空且未 --force → 跳过）。
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

UA = {"User-Agent": "dsh-installer"}


def api_get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def raw_get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def install_repo(repo, target, ref="main", only="", skip=None, force=False, verbose=True):
    """核心安装逻辑（CLI 与 skill_mgr 复用）：api trees → raw 批量拉取 → 写盘。

    参数：
      repo   owner/name
      target 目标目录（Path 或 str）
      ref    git ref（分支/tag/commit sha）
      only   仅拉取该子目录（相对仓库根，不带首尾斜杠亦可）
      skip   跳过规则集合（路径前缀或后缀匹配，如 {"docs", ".gif"}）
      force  覆盖已存在文件（默认断点续传：已存在且非空 → 跳过）
      verbose 进度打印（CLI 用；库调用方传 False）

    返回 (ok_count, fail_list)。fail_list = [(path, error)]。
    """
    target = Path(target)
    skip = set(skip or [])
    only = (only or "").strip("/") + "/" if only else ""
    tree = api_get("https://api.github.com/repos/%s/git/trees/%s?recursive=1" % (repo, ref))
    files = [t for t in tree.get("tree", []) if t.get("type") == "blob"]
    if only:
        files = [t for t in files if t["path"].startswith(only)]
    ok, fail = 0, []
    for t in files:
        p = t["path"]
        rel = p[len(only):] if only else p
        if any(p.startswith(s) or p.endswith(s) for s in skip if s):
            if verbose:
                print("skip:", p)
            continue
        dest = target / rel
        if dest.exists() and dest.stat().st_size > 0 and not force:
            continue  # 断点续传：已存在跳过
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = "https://raw.githubusercontent.com/%s/%s/%s" % (repo, ref, p)
        for attempt in range(3):
            try:
                data = raw_get(url)
                dest.write_bytes(data)
                ok += 1
                break
            except Exception as ex:
                if attempt == 2:
                    fail.append((p, str(ex)))
                else:
                    time.sleep(1.5)
        if verbose and ok and ok % 25 == 0:
            print("... %d files" % ok)
    if verbose:
        print("done: %d ok, %d fail" % (ok, len(fail)))
        for p, e in fail[:10]:
            print("FAIL", p, e)
    return ok, fail


def main():
    repo = sys.argv[1]
    target = Path(sys.argv[2])
    ref = sys.argv[3] if len(sys.argv) > 3 else "main"
    skip = set()
    if "--skip" in sys.argv:
        skip = set(x.strip() for x in sys.argv[sys.argv.index("--skip") + 1].split(","))
    only = ""
    force = False
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].strip("/")
    if "--force" in sys.argv:
        force = True
    install_repo(repo, target, ref=ref, only=only, skip=skip, force=force, verbose=True)


if __name__ == "__main__":
    main()
