#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公共工具：极简 YAML 子集解析 + 路径约定 + 资产扫描。仅标准库。"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
LOCAL_OVERRIDES = ROOT / "config.local.json"   # 运行期覆盖（设置界面写这里，不碰 config.yaml）
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"

VALID_PREFIXES = ("C", "S", "P", "R")
PREFIX_NAMES = {"C": "角色", "S": "场景", "P": "道具", "R": "风格参考"}


class ConfigError(Exception):
    """配置错误：缺文件 / 缺键 / 未知模型提供商等。"""


class Config(dict):
    def __init__(self, data):
        super().__init__(data)

    def get_path(self, key, default):
        """取嵌套键，如 'comfyui.base_url'。"""
        node = self
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def _unquote(value):
    """剥离匹配的成对引号（YAML 字符串值）；无引号原样返回。"""
    s = value.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def parse_yaml_subset(text):
    """解析 YAML 子集：注释(#)、key: value、缩进嵌套、'- ' 列表。"""
    lines = []
    for raw in text.splitlines():
        # 去掉整行注释和行内注释
        line = raw.split(" #")[0].rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue  # 跳过空行与纯注释行（注释行无冒号，不能进 build）
        lines.append(line)

    def build(idx, indent):
        node = {}
        while idx[0] < len(lines):
            line = lines[idx[0]]
            cur_indent = len(line) - len(line.lstrip())
            if cur_indent < indent:
                break
            if cur_indent > indent:
                raise ValueError("不支持的缩进层级: %r" % line)
            stripped = line.strip()
            if stripped.startswith("- "):
                item = _unquote(stripped[2:])
                node.setdefault("_list", []).append(item)
                idx[0] += 1
                continue
            if ":" not in stripped:
                raise ValueError("无法解析: %r" % line)
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            idx[0] += 1
            if value == "":
                child = build(idx, cur_indent + 2)
                # 列表展开：'- ' 收集为 _list
                if "_list" in child:
                    node[key] = child["_list"]
                else:
                    node[key] = child
            elif value == "[]":
                node[key] = []  # 空列表字面量（如 claude: args: []），否则会存成字符串 "[]"
            else:
                node[key] = _unquote(value)
        return node

    result = build([0], 0)
    return result


def _deep_merge(base, over):
    """深层合并：over 的 dict 键递归合并，其余覆盖。"""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("缺少配置文件: %s" % CONFIG_PATH)
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        data = parse_yaml_subset(fh.read())
    # 运行期覆盖：config.local.json（设置界面写入，不修改 config.yaml）
    if LOCAL_OVERRIDES.exists():
        try:
            extra = json.loads(LOCAL_OVERRIDES.read_text(encoding="utf-8"))
            data = _deep_merge(data, extra)
        except Exception:
            pass
    return Config(data)


def asset_table():
    """扫描 assets/ 返回 [{code, name, type, type_name, image, bible}]。
    数据源：.registry/（登记痕迹）+ 图片目录 + bible/（角色圣经）。"""
    rows = {}
    # 1) 登记痕迹：无图资产也能被 check 发现
    reg_dir = ASSETS / ".registry"
    if reg_dir.exists():
        for f in sorted(reg_dir.iterdir()):
            if f.suffix.lower() != ".md":
                continue
            m = re.match(r"^([CSPR]\d{2})$", f.stem)
            if not m:
                continue
            name = f.stem
            text = f.read_text(encoding="utf-8", errors="ignore")
            nm = re.search(r"^name:\s*(.+)$", text, re.M)
            if nm:
                name = nm.group(1).strip()
            code = m.group(1)
            rows[code] = {"code": code, "name": name, "type": code[0],
                          "type_name": PREFIX_NAMES[code[0]], "image": None,
                          "bible": None}
    # 2) 图片目录：更新 image 字段
    for prefix in VALID_PREFIXES:
        folder = ASSETS / ("characters" if prefix == "C"
                           else "scenes" if prefix == "S"
                           else "props" if prefix == "P" else "refs")
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir()):
            if f.is_dir() or f.name.startswith("."):
                continue
            m = re.match(r"^([CSPR])(\d{2})_?(.*?)(\.[A-Za-z0-9]+)?$", f.stem)
            if not m:
                continue
            code = "%s%s" % (m.group(1), m.group(2))
            r = rows.setdefault(code, {"code": code, "name": m.group(3) or f.stem,
                                       "type": m.group(1),
                                       "type_name": PREFIX_NAMES[m.group(1)],
                                       "image": None, "bible": None})
            r["image"] = f.name
            if m.group(3):
                r["name"] = m.group(3)
    # 3) bible/：记录角色圣经文件
    bible_dir = ASSETS / "bible"
    if bible_dir.exists():
        for f in sorted(bible_dir.iterdir()):
            if f.suffix.lower() != ".md":
                continue
            m = re.match(r"^(C\d{2})_?(.*?)$", f.stem)
            if not m:
                continue
            code = m.group(1)
            r = rows.setdefault(code, {"code": code, "name": m.group(2) or f.stem,
                                       "type": "C", "type_name": PREFIX_NAMES["C"],
                                       "image": None, "bible": None})
            r["bible"] = f.name
            if m.group(2):
                r["name"] = m.group(2)
    result = sorted(rows.values(), key=lambda r: (r["type"], r["code"]))
    return result


def validate_code(code):
    if not re.match(r"^[CSPR]\d{2}$", code):
        raise ValueError("编号格式应为 C01 / S01 / P01 / R01 等（前缀+两位数字）")
    return code


def project_dir(name):
    p = OUTPUT / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def episode_dir(name, episode):
    e = project_dir(name) / ("E%02d" % int(episode))
    e.mkdir(parents=True, exist_ok=True)
    return e
