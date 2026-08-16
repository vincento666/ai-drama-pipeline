#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主线编排：剧本 → 资产 → 分镜提示词 → 抽卡 → 校验 → 拼接。

用法示例：
  python3 scripts/pipeline.py init my-drama --episodes 5
  python3 scripts/pipeline.py run my-drama --episode 1 --dry-run
  python3 scripts/pipeline.py run my-drama --episode 1
  python3 scripts/pipeline.py verify my-drama --episode 1
  python3 scripts/pipeline.py compose my-drama --episode 1
"""
import argparse
import re
import sys
from pathlib import Path

from common import load_config, project_dir, episode_dir, asset_table, OUTPUT, ROOT
from gen_storyboard import gen_h3, gen_seedance, load_storyboard
from render import render as render_cmd

SCRIPT_TEMPLATE = """# {title}（四幕结构剧本 · 草稿，人工审改）

> 方法论：起承转合四幕。AI 只负责格式与初稿，爽点/节奏/钩子人工把关。
> 每 3-5 秒一个信息点；结尾留钩子追下集。

## 核心梗（一句话卖点）
（写这里）

## 人物小传
- （角色名）：（一句话人设 + 辨识度颜色/标志）

## 第一幕 · 起（0:00-0:20）
（发生了什么：情境建立，人物登场）

## 第二幕 · 承（0:20-0:45）
（冲突升温，人物互动）

## 第三幕 · 转（0:45-1:10）
（反转/高潮：情绪爆发点）

## 第四幕 · 合（1:10-1:30+）
（结局/悬念，钩子：下一集会怎样？）

## 分集规划（多集时）
- E{n}：本集核心事件 + 结尾钩子
"""

STORYBOARD_TEMPLATE = """# E{n:02d} 分镜（{title}）

> 列：镜号 | 景别 | 机位运动 | 时长 | 角色 | 场景 | 灯光 | 对白/音效 | 备注(情绪/转场)
> 景别词表：远景 wide / 全景 medium-wide / 中景 medium / 近景 close-up / 特写 extreme close-up
> 机位词表：推近 push in / 拉远 pull back / 左摇 pan left / 右摇 pan right / 跟随 tracking / 环绕 orbit / 固定 static / 手持 handheld
> 每镜 5-10 秒；单集 8-12 镜。

| 镜号 | 景别 | 机位运动 | 时长 | 角色 | 场景 | 灯光 | 对白/音效 | 备注 |
|---|---|---|---|---|---|---|---|---|
| 1 | wide | push in | 5 | 无 | S01 | golden hour | 环境音：风声 | 开场建立场景 |
| 2 | medium | static | 5 | C01 | S01 | golden hour | 对白：这里发生了什么 | 引入主角 |
| 3 | close-up | static | 5 | C01 | S01 | golden hour | 音效：心跳声 | 情绪铺垫 |
| 4 | medium | pan right | 5 | C01, C02 | S01 | golden hour | 对白：必须阻止你 | 冲突开始 |
| 5 | medium close-up | handheld | 6 | C01, C02 | S01 | overcast | 对白：我不会后退 | 高潮 |
| 6 | extreme close-up | static | 4 | C02 | S01 | overcast | 音效：雷声 | 反转 |
| 7 | wide | crane up | 5 | C01, C02 | S01 | overcast | 配乐渐强 | 收束 |
| 8 | medium | static | 5 | C01 | S01 | golden hour | 对白：明天见 | 钩子结尾 |
"""


def confirm(prompt_text):
    try:
        return input("%s [y/N] " % prompt_text).strip().lower() in ("y", "yes")
    except EOFError:
        return True


def cmd_init(args):
    root = project_dir(args.name)
    (root / "shots").mkdir(exist_ok=True)
    script = root / "剧本.md"
    if not script.exists():
        script.write_text(SCRIPT_TEMPLATE.format(title=args.name, n=args.episodes),
                          encoding="utf-8")
        print("[OK] 剧本骨架: %s" % script)
    for ep in range(1, args.episodes + 1):
        e_dir = episode_dir(args.name, ep)
        sb = e_dir / "分镜.md"
        if not sb.exists():
            sb.write_text(STORYBOARD_TEMPLATE.format(title=args.name, n=ep),
                          encoding="utf-8")
            print("[OK] 分镜模板: %s" % sb)
        (e_dir / "shots").mkdir(exist_ok=True)
    print("[完成] 项目 %s 已初始化（%d 集）" % (args.name, args.episodes))


def step_script(project, episode):
    sb = episode_dir(project, episode) / "分镜.md"
    if not sb.exists():
        print("[检查] 缺分镜文件: %s" % sb)
        return False
    shots = load_storyboard(sb)
    cfg = load_config()
    style = cfg.get_path("project.style_prefix", "")
    prompts = root_out = episode_dir(project, episode) / "prompts_h3.md"
    prompts.write_text(gen_h3(shots, style) + "\n", encoding="utf-8")
    print("[OK] 已生成 H3 三段式提示词（%d 镜）→ %s" % (len(shots), prompts))
    return True


def step_verify(project, episode):
    e_dir = episode_dir(project, episode)
    ok = True
    if not (project_dir(project) / "剧本.md").exists():
        print("[检查] 缺剧本.md（先 init 或手写）")
        ok = False
    sb = e_dir / "分镜.md"
    if not sb.exists():
        print("[检查] 缺分镜.md")
        ok = False
    shots = load_storyboard(sb) if sb.exists() else []
    n_needed = max(1, len(shots))
    shot_files = [f for f in (e_dir / "shots").iterdir() if f.suffix.lower() in
                  (".mp4", ".mov", ".mkv", ".webm")]
    if len(shot_files) < n_needed:
        print("[检查] shots/ 视频不足：需要≥%d 个，当前 %d 个" % (n_needed, len(shot_files)))
        ok = False
    else:
        print("[OK] shots/ 视频齐全：%d 个（需 %d）" % (len(shot_files), n_needed))
    rows = asset_table()
    registered = {r["code"] for r in rows}
    needed_codes = set()
    for s in shots:
        for c in (s.get("chars") or "").split(","):
            c = c.strip()
            m = re.match(r"^[CSPR]\d{2}$", c)
            if m:
                needed_codes.add(c)
    missing = sorted(needed_codes - registered)
    if missing:
        print("[检查] 分镜引用了未登记的资产编号：%s（用 asset_manager register 登记）" % missing)
        ok = False
    return ok


def step_compose(project, episode, dry_run):
    from compose import compose
    e_dir = episode_dir(project, episode)
    cfg = load_config()
    return compose(e_dir / "shots", e_dir / "成片.mp4",
                   ffmpeg=cfg.get_path("compose.ffmpeg", "ffmpeg"),
                   fps=int(cfg.get_path("compose.fps", 24)), dry_run=dry_run)


STEPS = [
    ("剧本", "检查剧本.md 存在（init 生成骨架，人工改写）"),
    ("资产", "校验 C/S/P 资产登记齐全（asset_manager check）"),
    ("分镜", "解析 E{n:02d}/分镜.md → 生成 H3 三段式提示词"),
    ("生成", "在 ComfyUI/h3-studio 按提示词抽卡，选中片拷入 E{n:02d}/shots/"),
    ("校验", "verify：视频数≥分镜数、剧本/分镜齐全、引用资产已登记"),
    ("拼接", "compose：ffmpeg 拼成 E{n:02d}/成片.mp4"),
]


def cmd_run(args):
    dry = args.dry_run
    project, ep = args.name, int(args.episode)
    e_dir = episode_dir(project, ep)

    if dry:
        print("== [DRY-RUN] 项目 %s 第 %d 集流水线预览 ==" % (project, ep))
    for i, (name, desc) in enumerate(STEPS, 1):
        print("\n[%d/%d] %s —— %s" % (i, len(STEPS), name,
                                      desc.format(n=ep)))
        if dry:
            continue
        if not args.yes and not confirm("执行该步骤？"):
            print("（跳过）")
            continue
        if name == "剧本":
            script = project_dir(project) / "剧本.md"
            if not script.exists():
                print("[检查] 缺 %s，请先 pipeline init %s" % (script, project))
        elif name == "资产":
            import subprocess
            subprocess.run([sys.executable, str(ROOT / "scripts" / "asset_manager.py"),
                            "check"])
        elif name == "分镜":
            step_script(project, ep)
        elif name == "生成":
            prompts = e_dir / "prompts_h3.md"
            print("提示词在 %s\n→ 打开 http://127.0.0.1:8188（h3-studio 或 ComfyUI），"
                  "每镜抽 3-5 个变体，把选中的视频拷入 %s"
                  % (prompts, e_dir / "shots"))
        elif name == "校验":
            step_verify(project, ep)
        elif name == "拼接":
            step_compose(project, ep, dry_run=False)
    if dry:
        print("\n[DRY-RUN] 结束：链路无阻塞，可正式运行。")
    else:
        print("\n[完成] 第 %d 集主流程执行完毕，剩下剪辑/字幕/发布（见 docs/08）。" % ep)


def main():
    ap = argparse.ArgumentParser(description="AI 短剧/漫剧流水线编排")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化项目")
    p.add_argument("name", help="项目名")
    p.add_argument("--episodes", type=int, default=5)
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("run", help="跑完整流水线（交互式）")
    p.add_argument("name")
    p.add_argument("--episode", type=int, default=1)
    p.add_argument("--dry-run", action="store_true", help="只预览不执行")
    p.add_argument("--yes", action="store_true", help="跳过确认")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("storyboard", help="分镜 → 提示词")
    p.add_argument("name")
    p.add_argument("--episode", type=int, default=1)
    p.add_argument("--format", choices=["h3", "seedance"], default="h3")
    p.set_defaults(fn=lambda a: step_script(a.name, a.episode))

    p = sub.add_parser("verify", help="校验第 N 集素材完整性")
    p.add_argument("name")
    p.add_argument("--episode", type=int, default=1)
    p.set_defaults(fn=lambda a: sys.exit(0 if step_verify(a.name, a.episode) else 1))

    p = sub.add_parser("compose", help="拼接成片")
    p.add_argument("name")
    p.add_argument("--episode", type=int, default=1)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=lambda a: sys.exit(0 if step_compose(a.name, a.episode, a.dry_run) else 1))

    p = sub.add_parser("render", help="ComfyUI API 自动出片（逐镜抽候选，HANDOFF 待办 #1）")
    p.add_argument("name")
    p.add_argument("--episode", type=int, default=1)
    p.add_argument("--shots", type=int, default=1, help="每镜候选数（抽卡批量）")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--frames", type=int)
    p.add_argument("--steps", type=int)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--only", help="只渲染指定镜号，如 1,3")
    p.add_argument("--image", help="首帧图文件名（ComfyUI/input 下），给出则走 I2VA")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--timeout", type=int, default=1800)
    p.set_defaults(fn=lambda a: sys.exit(0 if render_cmd(
        a.name, a.episode, a.shots, a.width, a.height, a.frames, a.steps,
        a.seed, a.only, a.dry_run, a.timeout, a.image) else 1))

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
