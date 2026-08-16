#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资产库管理：登记 / 列表 / 校验 / 素材清单生成。仅标准库。"""
import argparse
import re
import sys
from pathlib import Path

from common import ASSETS, asset_table, validate_code, PREFIX_NAMES, ROOT

FOLDER_BY_PREFIX = {"C": "characters", "S": "scenes", "P": "props", "R": "refs"}

BIBLE_TEMPLATE = """# 角色圣经：{name}（{code}）

> 每个角色一份。生成任何含该角色的镜头前，把本文件 + 定妆照一起作为输入。

## 基本信息
- 编号：{code}（C 系列：角色）
- 名字：{name}
- 身份/职业：
- 性格关键词：

## 外貌（写死，跨镜头不变）
- 发型：
- 脸型/五官特征：
- 瞳色（hex）：#______
- 体型：
- 其他（伤疤/纹身/痣）：

## 服装（颜色方案 = 辨识度）
- 主色（hex）：#______
- 上身：
- 下身：
- 标志性配饰：

## 绑定道具
- 永远手持/佩戴：{name} 与 P____（道具）绑定

## 声音（对白用 {speaker} 标记，如 (S01)）
- 音色：
- 语速/语气习惯：

## 动作与表情习惯
- 招牌动作：
- 情绪外化方式（愤怒/悲伤/开心分别怎么演）：

## 禁忌（转成排除句，放进提示词）
- 绝无：眼镜 / 纹身 / 现代元素 / ______
"""


def cmd_register(args):
    validate_code(args.code)
    prefix = args.code[0]
    folder = ASSETS / FOLDER_BY_PREFIX[prefix]
    folder.mkdir(parents=True, exist_ok=True)

    if args.image:
        src = Path(args.image)
        if not src.exists():
            sys.exit("图片不存在: %s" % src)
        target = folder / ("%s_%s%s" % (args.code, args.name, src.suffix.lower()))
        if target.exists() and not args.force:
            sys.exit("已存在 %s，加 --force 覆盖" % target.name)
        target.write_bytes(src.read_bytes())
        print("[OK] 图片已复制到 %s" % target)
    else:
        print("[提示] 未提供 --image，稍后把素材图放入 %s/ 并以 %s_%s.* 命名"
              % (folder, args.code, args.name))

    # 登记痕迹（registry/），无图也能被 check 发现
    reg = ASSETS / ".registry" / ("%s.md" % args.code)
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text("# %s\nname: %s\ntype: %s\n" % (args.code, args.name, prefix),
                   encoding="utf-8")
    print("[OK] 登记痕迹: %s" % reg)

    if prefix == "C":
        bible = ASSETS / "bible" / ("%s_%s.md" % (args.code, args.name))
        if bible.exists() and not args.force:
            print("[跳过] 角色圣经已存在: %s" % bible.name)
        else:
            bible.parent.mkdir(parents=True, exist_ok=True)
            bible.write_text(BIBLE_TEMPLATE.format(name=args.name, code=args.code,
                                                   speaker="S" + args.code[1:]),
                             encoding="utf-8")
            print("[OK] 角色圣经模板已生成: %s" % bible)

    print("[OK] 登记完成：%s %s（%s）" % (args.code, args.name, PREFIX_NAMES[prefix]))


def remove_asset(code):
    """删除资产：登记痕迹 + 同名图片 + 角色圣经。返回 {code, removed: [路径...]}。

    编号不存在 = 无操作（removed 为空）。公共 seam（本轮整改，UI/CLI 共用）。
    """
    validate_code(code)
    removed = []
    reg = ASSETS / ".registry" / ("%s.md" % code)
    if reg.exists():
        reg.unlink()
        removed.append(str(reg))
    folder = ASSETS / FOLDER_BY_PREFIX[code[0]]
    if folder.exists():
        for f in folder.iterdir():
            if f.is_file() and f.stem.startswith(code + "_"):
                f.unlink()
                removed.append(str(f))
    if code[0] == "C":
        bible = ASSETS / "bible"
        if bible.exists():
            for f in bible.iterdir():
                if f.is_file() and f.stem.startswith(code + "_"):
                    f.unlink()
                    removed.append(str(f))
    return {"code": code, "removed": removed}


def cmd_remove(args):
    result = remove_asset(args.code)
    if not result["removed"]:
        print("[提示] %s 无登记痕迹或文件，无需删除" % args.code)
        return
    print("[OK] 已删除 %s（%d 个文件）：" % (args.code, len(result["removed"])))
    for p in result["removed"]:
        print("  - %s" % p)


def cmd_list(_args):
    rows = asset_table()
    if not rows:
        print("资产库为空。用 register 登记，或直接把图片放入 assets/{characters,scenes,props,refs}/ 并按 C01_xxx.png 命名。")
        return
    by_type = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    for prefix in ("C", "S", "P", "R"):
        if prefix in by_type:
            print("\n== %s (%s) ==" % (prefix, PREFIX_NAMES[prefix]))
            for r in by_type[prefix]:
                img = r.get("image") or "（缺图）"
                print("  %s  %s  图:%s" % (r["code"], r["name"], img))


def cmd_check(_args):
    rows = asset_table()
    problems = 0
    for r in rows:
        if not r.get("image"):
            print("[警告] %s %s 缺定妆照/素材图" % (r["code"], r["name"]))
            problems += 1
        if r["type"] == "C":
            bible = ASSETS / "bible" / ("%s_%s.md" % (r["code"], r["name"]))
            if not bible.exists():
                print("[警告] %s %s 缺角色圣经 (bible/%s_%s.md)"
                      % (r["code"], r["name"], r["code"], r["name"]))
                problems += 1
    # 检查孤儿文件（未按编号规范命名）
    for prefix, folder_name in FOLDER_BY_PREFIX.items():
        folder = ASSETS / folder_name
        if not folder.exists():
            continue
        for f in folder.iterdir():
            if f.is_dir() or f.name.startswith("."):
                continue
            if not re.match(r"^[CSPR]\d{2}_", f.stem):
                print("[警告] %s/%s 未按编号规范命名（应为 %sXX_描述.ext）"
                      % (folder_name, f.name, prefix))
                problems += 1
    if problems == 0:
        print("资产库校验通过：%d 项资产，无缺失。" % len(rows))
    else:
        print("\n共 %d 个问题待处理。" % problems)
        sys.exit(1)


def cmd_manifest(args):
    rows = asset_table()
    lines = ["# 素材清单（由 asset_manager 生成）\n",
             "| 编号 | 类型 | 名称 | 文件 | 说明 |",
             "|---|---|---|---|---|"]
    for r in rows:
        name = args.name if args.name else r["name"]
        img = r.get("image") or "-"
        desc = "%s 参考图" % PREFIX_NAMES[r["type"]]
        lines.append("| %s | %s | %s | %s | %s |"
                     % (r["code"], PREFIX_NAMES[r["type"]], name, img, desc))
    content = "\n".join(lines) + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print("[OK] 素材清单已生成: %s（%d 项）" % (out, len(rows)))


def main():
    ap = argparse.ArgumentParser(description="AI 短剧资产库管理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("register", help="登记资产（生成圣经模板/复制图片）")
    p.add_argument("code", help="编号，如 C01 / S01 / P01")
    p.add_argument("--name", default="", help="名称，如 林冲")
    p.add_argument("--image", default="", help="素材图路径（复制进资产库）")
    p.add_argument("--force", action="store_true", help="覆盖已存在文件")
    p.set_defaults(fn=cmd_register)

    p = sub.add_parser("list", help="列出全部资产")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("remove", help="删除资产（登记痕迹+图片+角色圣经）")
    p.add_argument("code", help="编号，如 C01 / S01 / P01")
    p.set_defaults(fn=cmd_remove)

    p = sub.add_parser("check", help="校验资产完整性（缺图/缺圣经/命名违规）")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("manifest", help="生成素材清单 markdown")
    p.add_argument("--out", default=str(ROOT / "output" / "素材清单.md"))
    p.add_argument("--name", default="", help="覆盖清单中的名称列")
    p.set_defaults(fn=cmd_manifest)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
