#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部生图 API 抽象（docs/13 §3 P6a 2，仅标准库）。

config.local.json 的 `image:` 段约定（OpenAI 兼容 images/generations 形态）：

    image:
      provider: <名称，展示用>
      base: https://api.example.com/v1      # OpenAI 兼容端点（可带 /v1）
      api_key: sk-xxx
      model: gpt-image-1                     # 生图模型名
      size: "1024x1024"                      # 可选，默认 1024x1024

未配置（缺 base/api_key/model 任一）→ available() == False。
生图 UI（设置页）留 P7；本轮后端支持 config.local.json 手动写入 image 段。

对外 seam：
  available(cfg)                     是否可用
  generate(prompt, size, out_path, cfg=None)  调 API → 写 PNG；失败抛异常
  inject_asset_image(project, code, prompt, cfg=None)  生图 → 资产注入
  friendly_error(cfg)                未配置时的引导文案
"""
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import common   # noqa: E402  路径（ASSETS / load_config / validate_code）

FOLDER_BY_PREFIX = {"C": "characters", "S": "scenes", "P": "props", "R": "refs"}
DEFAULT_SIZE = "1024x1024"
TIMEOUT = 120            # 单次生图请求超时（秒）


class ImageGenError(Exception):
    """生图失败（未配置 / API 错误 / 写盘失败）。"""


def image_cfg(cfg=None):
    """读 config 的 image: 段（config.yaml + config.local.json 覆盖后）。"""
    cfg = cfg or common.load_config()
    return dict(cfg.get_path("image", {}) or {})


def available(cfg=None):
    """生图可用性：image.base + api_key + model 齐备才可用。"""
    c = image_cfg(cfg)
    return bool((c.get("base") or "").strip()
                and (c.get("api_key") or "").strip()
                and (c.get("model") or "").strip())


def friendly_error(cfg=None):
    """未配置时的引导文案（事件 error + 对话回复用）。"""
    return ("未配置生图 API：请在 设置页 → 模型 Provider → 生图配置 填写 base/api_key/model"
            "（P7 提供设置页 UI；当前可在 config.local.json 手动写入 image 段："
            "{\"image\": {\"base\": \"...\", \"api_key\": \"...\", \"model\": \"...\"}}）")


def _request_json(url, payload, api_key, timeout=TIMEOUT):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer %s" % api_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        body = ex.read().decode("utf-8", errors="replace")[:300]
        raise ImageGenError("生图 API 返回 %s: %s" % (ex.code, body)) from ex
    except urllib.error.URLError as ex:
        raise ImageGenError("生图 API 连接失败: %s" % ex.reason) from ex


def generate(prompt, size=None, out_path=None, cfg=None):
    """调 OpenAI 兼容 images/generations 生图 → 写 PNG 到 out_path。

    返回 out_path；未配置 / API 失败 / 写盘失败抛 ImageGenError。
    """
    c = image_cfg(cfg)
    if not available(cfg):
        raise ImageGenError(friendly_error(cfg))
    base = (c.get("base") or "").rstrip("/")
    model = c.get("model")
    size = size or c.get("size") or DEFAULT_SIZE
    url = base + "/images/generations"
    payload = {"model": model, "prompt": prompt, "size": size,
               "response_format": "b64_json", "n": 1}
    data = _request_json(url, payload, c.get("api_key"))
    items = ((data or {}).get("data") or [])
    if not items or not items[0].get("b64_json"):
        raise ImageGenError("生图 API 未返回图片数据（data[0].b64_json 缺失）")
    raw = items[0]["b64_json"]
    try:
        img = base64.b64decode(raw)
    except Exception as ex:
        raise ImageGenError("生图返回数据解码失败: %s" % ex) from ex
    if not img:
        raise ImageGenError("生图返回空数据")
    if out_path is None:
        raise ImageGenError("需要 out_path（PNG 输出路径）")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_path.write_bytes(img)
    except OSError as ex:
        raise ImageGenError("生图产物写盘失败: %s" % ex) from ex
    return out_path


def inject_asset_image(project, code, prompt, size=None, cfg=None):
    """外部生图 → 资产注入：存 assets/<类型>/<代号>.png + 返回记录。

    资产注册表（assets/.registry/<code>.md）无需改动：common.asset_table()
    扫描图片目录时自动把 assets/characters/C01.png 关联为该资产 image 字段。
    返回 {code, path, type, type_name}。
    """
    common.validate_code(code)
    prefix = code[0]
    folder_name = FOLDER_BY_PREFIX[prefix]
    folder = common.ASSETS / folder_name
    out_path = folder / ("%s.png" % code)
    generate(prompt, size=size, out_path=out_path, cfg=cfg)
    return {"code": code, "path": str(out_path),
            "type": prefix, "type_name": common.PREFIX_NAMES[prefix]}


if __name__ == "__main__":
    # 自测：python web/image_gen.py <project> <code> <prompt...>
    import argparse
    ap = argparse.ArgumentParser(description="外部生图（资产注入）")
    ap.add_argument("project")
    ap.add_argument("code", help="资产代号，如 C01")
    ap.add_argument("prompt", nargs="+")
    ap.add_argument("--size", default=DEFAULT_SIZE)
    a = ap.parse_args()
    cfg = common.load_config()
    if not available(cfg):
        sys.exit(friendly_error(cfg))
    rec = inject_asset_image(a.project, a.code, " ".join(a.prompt),
                             size=a.size, cfg=cfg)
    print("[OK] %s %s 生图完成 → %s" % (rec["code"], rec["type_name"], rec["path"]))
