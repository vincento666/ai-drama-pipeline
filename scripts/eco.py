#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生态管理器：发现 / 安装 / 加载外部 H3 skill 与 ComfyUI 插件。

本项目定位 = 生态对接层：不重复实现 H3 生态的 skill/插件，只做
"清单化发现、一键安装到 custom_nodes、验证节点注册、加载进 render 管线"。

用法：
  python scripts/eco.py list                     # 列出生态清单 + 安装状态
  python scripts/eco.py check <id>               # 验证某插件节点是否注册（查 ComfyUI）
  python scripts/eco.py install <id>             # 安装：解压 zip 到 custom_nodes / 复制工作流与 skill
  python scripts/eco.py refresh                  # 从生态源目录重新发现可用 zip/工作流/skill

生态源：config.yaml 的 eco.sources（默认指向 ComfyUI/workflows/20260811自动短剧）。
"""
import argparse
import io
import shutil
import sys
import zipfile
from pathlib import Path

from common import load_config

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PROMPTS = ROOT / "prompts"


def load_eco_config():
    cfg = load_config()
    eco = cfg.get("eco", {})
    custom_nodes = Path(eco.get("custom_nodes", r"S:/Develop/AIGC/ComfyUI/ComfyUI_windows_portable/ComfyUI/custom_nodes"))
    sources = [Path(x) for x in eco.get("sources", [r"S:/Develop/AIGC/ComfyUI/workflows/20260811自动短剧"])]
    return cfg, custom_nodes, sources


def builtin_manifest():
    """内置生态清单（id → 元信息）。"""
    return {
        "audio-t8": {
            "name": "MiniMax H3 Audio T8", "type": "plugin",
            "desc": "核心生成节点（T2VA/I2VA/Ref2VA/双时钟采样），render 引擎依赖",
            "folder": "comfyui-minimax-h3-audio-T8-main", "marker": "MiniMaxH3AudioConditioningT8",
            "installed": True, "source": "已安装",
        },
        "motion-context": {
            "name": "ComfyUI H3 Motion Context", "type": "plugin",
            "desc": "跨镜运动/音频连续：上一段尾帧+音频喂给下一段（FR5 尾帧续接的完整实现）",
            "folder": "ComfyUI-H3-Motion-Context-main", "marker": "MiniMaxH3MotionContext",
            "zip": "ComfyUI-H3-Motion-Context-main.zip", "installed": False,
            "source": "自动短剧包/插件/",
        },
        "blockcache-t8": {
            "name": "MiniMax H3 Block Cache (T8)", "type": "plugin",
            "desc": "F1B0 Block Cache：音频/视频稳定时跳过 Block 1-49，采样加速",
            "folder": "comfyui-minimax-h3-blockcache-T8-main", "marker": "MiniMaxH3BlockCacheT8",
            "zip": "comfyui-minimax-h3-blockcache-T8-main.zip", "installed": False,
            "source": "自动短剧包/插件/",
        },
        "prompt-skill": {
            "name": "剧本转视频提示词生成指令（H3 prompt skill）", "type": "skill",
            "desc": "Agent 提示词生成 skill：切分规则/BGM 爆点/时间戳映射/输出格式",
            "file": "剧本转视频提示词生成指令.md", "installed": False,
            "source": "自动短剧包/",
        },
        "auto-short-drama": {
            "name": "自动短剧工作流（全自动/半自动）", "type": "workflow",
            "desc": "社区产线模板：ReferenceToVideo + MotionContext + BlockCache + 辅助节点",
            "files": ["H3 全自动更新.json", "H3 半自动更新.json"], "installed": False,
            "source": "自动短剧包/",
        },
    }


def find_source_files(custom_nodes, sources):
    """从生态源目录收集可用的 zip / 指令 / 工作流。"""
    found = {"zips": {}, "files": {}}
    for src in sources:
        if not src.exists():
            continue
        for f in src.iterdir():
            if f.is_file():
                if f.suffix.lower() == ".zip":
                    found["zips"][f.stem] = f
                else:
                    found["files"][f.stem] = f
        # 插件子目录
        plug_dir = src / "插件"
        if plug_dir.exists():
            for f in plug_dir.iterdir():
                if f.suffix.lower() == ".zip":
                    found["zips"][f.stem] = f
    return found


def eco_status():
    cfg, custom_nodes, sources = load_eco_config()
    found = find_source_files(custom_nodes, sources)
    manifest = builtin_manifest()
    rows = []
    for pid, m in manifest.items():
        # 插件：目录存在且含 marker 文件/节点
        installed = False
        if m["type"] == "plugin":
            folder = custom_nodes / m["folder"]
            installed = folder.exists() and any(f.suffix in (".py",) for f in folder.iterdir())
        elif m["type"] == "skill":
            installed = (PROMPTS / m.get("file", "")).exists()
        elif m["type"] == "workflow":
            installed = any((ROOT / "workflows" / x).exists() for x in m.get("files", []))
        rows.append({"id": pid, **m, "installed": installed})
    return cfg, custom_nodes, sources, found, rows


def cmd_list(_):
    cfg, custom_nodes, sources, found, rows = eco_status()
    print("生态管理器（本项目 = 生态对接层）\n")
    print("custom_nodes: %s" % custom_nodes)
    print("生态源: %s\n" % " ; ".join(str(s) for s in sources if s.exists()) or "（未找到生态源目录）")
    print("=== 生态清单 ===")
    for r in rows:
        mark = "✅" if r["installed"] else "⛔"
        print(" %s %-14s %s" % (mark, r["id"], r["name"]))
        print("       %s" % r["desc"])
    zips = found["zips"]
    print("\n=== 生态源中发现 %d 个 zip ===" % len(zips))
    for name, p in sorted(zips.items()):
        print("   %s  (%s)" % (name, p))
    for name, p in sorted(found["files"].items()):
        print("   [file] %s  (%s)" % (name, p))


def cmd_install(args):
    cfg, custom_nodes, sources, found, rows = eco_status()
    manifest = builtin_manifest()
    pid = args.id
    if pid not in manifest:
        print("[错误] 未知插件 id: %s（用 list 查看）" % pid)
        return 1
    m = manifest[pid]
    if m["installed"]:
        print("[跳过] %s 已安装" % pid)
        return 0
    custom_nodes.mkdir(parents=True, exist_ok=True)
    if m["type"] == "plugin":
        zname = m.get("zip")
        src = found["zips"].get(zname) or found["zips"].get(zname.rstrip(".zip"))
        if src is None:
            print("[错误] 未在生态源找到 %s.zip" % zname)
            return 1
        dest = custom_nodes / m["folder"]
        with zipfile.ZipFile(src) as z:
            z.extractall(custom_nodes)
        print("[安装] %s → %s" % (src.name, dest))
        print("[提示] 重启 ComfyUI 后节点 %s 注册生效" % m["marker"])
    elif m["type"] == "skill":
        src = found["files"].get(m["file"].replace(".md", ""))
        if src is None:
            print("[错误] 未找到 %s" % m["file"])
            return 1
        PROMPTS.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, PROMPTS / m["file"])
        print("[安装] skill → %s" % (PROMPTS / m["file"]))
        print("[提示] Agent 可读取该 skill 生成分镜提示词")
    elif m["type"] == "workflow":
        wf_dir = ROOT / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        for fn in m["files"]:
            src = found["files"].get(fn.replace(".json", ""))
            if src:
                shutil.copy2(src, wf_dir / fn)
                print("[安装] 工作流 → %s" % (wf_dir / fn))
        print("[提示] render 可加载该模板（自动短剧模式）")
    return 0


def cmd_check(args):
    """验证插件节点是否在 ComfyUI 注册（需 ComfyUI 运行）。"""
    import urllib.request
    manifest = builtin_manifest()
    pid = args.id
    if pid not in manifest:
        print("[错误] 未知 id")
        return 1
    marker = manifest[pid].get("marker")
    if not marker:
        print("[跳过] %s 无节点标记" % pid)
        return 0
    cfg = load_config()
    base = cfg.get_path("comfyui.base_url", "http://127.0.0.1:8188")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 不走系统代理
        with opener.open(base + "/object_info/" + marker, timeout=8) as r:
            data = r.read().decode("utf-8")
        ok = ("error" not in data.lower()[:200]) or (marker in data)
        print("[%s] 节点 %s %s" % ("OK" if ok else "缺", marker,
                                   "已注册" if ok else "未注册（装好后需重启 ComfyUI）"))
        return 0 if ok else 1
    except Exception as ex:
        print("[错误] 无法连接 ComfyUI（%s）: %s" % (base, ex))
        return 1


def cmd_refresh(_):
    """重新发现生态源：从 config 的 eco.sources 重新扫描 zip/工作流/skill 清单。"""
    cfg, custom_nodes, sources, found, rows = eco_status()
    n_src = sum(1 for s in sources if s.exists())
    print("生态源刷新完成：%d 个源目录，发现 %d 个 zip、%d 个文件"
          % (n_src, len(found["zips"]), len(found["files"])))
    for name, p in sorted(found["zips"].items()):
        print("  [zip] %s  (%s)" % (name, p))
    for name, p in sorted(found["files"].items()):
        print("  [file] %s  (%s)" % (name, p))
    return 0


def main():
    ap = argparse.ArgumentParser(description="H3 生态管理器（生态对接层）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出生态清单 + 安装状态").set_defaults(fn=cmd_list)
    sub.add_parser("refresh", help="从生态源重新发现 zip/工作流/skill").set_defaults(fn=cmd_refresh)
    p = sub.add_parser("install", help="安装插件/skill/工作流")
    p.add_argument("id")
    p.set_defaults(fn=cmd_install)
    p = sub.add_parser("check", help="验证节点注册（ComfyUI 需运行）")
    p.add_argument("id")
    p.set_defaults(fn=cmd_check)
    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
