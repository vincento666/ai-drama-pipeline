#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""素材生成引擎语义适配层（P7b）：外部引擎（ComfyUI 工作流 / 在线 API）能力收敛 + 引擎注册表。

设计（docs/13 P7b）：
  外部引擎能力对本项目收敛为三类「素材资源生成」：
    kind=refimg     美术参考资源（角色/场景参考图）
    kind=storyframe 分镜/预览帧
    kind=video      视频片段（抽卡；单段或链式长视频）
  （kind=prompt 由 LLM+skill 完成，不依赖外部引擎，不在本层。）

本模块职责（仅标准库）：
  1. 工作流解析：经典 UI 格式 / 新版 LiteGraph 格式（nodes 数组）/ 纯 API 格式 → 统一 API 图
  2. analyze_workflow(path)   能力识别（kind 列表+置信度 / chain / ref_input / audio）+ 槽位清单
  3. suggest_mapping(...)     规则命中生成业务参数 → node.inputs.槽 映射 + 每槽说明
  4. llm_suggest_mapping(...) 规则未覆盖槽 → LLM（agent.chat）兜底；失败静默回退规则结果
  5. engine_from_workflow / load_engines / save_engines / engine_changed  引擎注册表
     （config.local.json engines 段；内置 builtin 引擎代码级兜底，不写入配置）

向后兼容铁律：未配置 engines 时 render/抽卡/成片行为与现状完全一致
（render.resolve_workflow(engine_id=None) 走原 builtin/template 逻辑）。
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for _p in (str(SCRIPTS),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common                      # noqa: E402  路径/配置（load_config / LOCAL_OVERRIDES）
import agent                       # noqa: E402  LLM 兜底（resolve_provider + chat）

# ============ 常量与能力识别规则表 ============

KINDS = ("refimg", "storyframe", "video")
KIND_LABELS = {
    "refimg": "美术参考资源（角色/场景参考图）",
    "storyframe": "分镜/预览帧",
    "video": "视频片段（抽卡；单段或链式长视频）",
}

# 每 kind 的业务参数规格（suggest_mapping 的默认 params_spec）
DEFAULT_PARAMS = {
    "video": ("prompt", "width", "height", "frames", "steps", "seed",
              "prefix", "ref_image", "audio"),
    "refimg": ("prompt", "width", "height", "steps", "seed", "prefix", "image"),
    "storyframe": ("prompt", "width", "height", "steps", "seed", "prefix", "image"),
}

# 能力识别规则表（按 class_type/节点组合；spec P7b §1）
#  video 核心生成节点（H3 条件 / 参考生视频 / 链式）
_GEN_VIDEO = re.compile(
    r"MiniMaxH3.*(Conditioning|ReferenceToVideo|ToVideo|Chain|MotionContext|BlockCache"
    r"|Loop|AVDecode|Decode)", re.I)
#  chain 长视频节点族
_CHAIN = re.compile(r"MiniMaxH3Chain", re.I)
#  图像生成（CLIPTextEncode + 采样/VAE）
_GEN_IMAGE = re.compile(r"(CLIPTextEncode|CLIPTextEncodeFlorence2|KSampler|"
                        r"SamplerCustomAdvanced|UNETLoader|CheckpointLoader|VAELoader)", re.I)
#  参考输入（LoadImage / 参考视频）
_REF_IMAGE = re.compile(r"(LoadImage|LoadImageSequence)")
_REF_VIDEO = re.compile(r"(LoadVideo|MiniMaxH3ReferenceVideoPrepare|ReferenceVideo|"
                        r"VHS_LoadVideo)")
#  音频（LoadAudio / H3 音频解码 / 含音频输出）
_AUDIO = re.compile(r"(LoadAudio|MiniMaxH3.*Audio|VAEDecodeAudio|VHS_VideoCombine)")
#  输出节点
_OUTPUT_VIDEO = re.compile(r"(VHS_VideoCombine|MiniMaxH3ChainAssemble|SaveVideo|"
                           r"MiniMaxH3ChainLoopEnd)")
_OUTPUT_IMAGE = re.compile(r"SaveImage")

# 新版 LiteGraph 格式下「widgets_values 未作为 inputs 暴露」的常见节点 → 按名称表整表赋值。
# 名称顺序 = 该节点 class 的 widget 定义顺序（ComfyUI 官方/主流节点稳定约定）。
_WIDGET_INPUTS = {
    "LoadImage": ("image", "upload"),
    "LoadAudio": ("audio",),
    "LoadVideo": ("video", "force_rate", "force_size", "custom_width", "custom_height",
                  "frame_load_cap", "skip_first_frames", "select_every_nth"),
    "VAELoader": ("vae_name",),
    "CLIPLoader": ("clip_name", "type", "device"),
    "UNETLoader": ("unet_name", "weight_dtype"),
    "LoraLoaderModelOnly": ("lora_name", "strength_model"),
    "LoraLoaderBypassModelOnly": ("lora_name", "strength_model"),
    "RandomNoise": ("noise_seed", "noise_mode"),
    "KSamplerSelect": ("sampler_name",),
    "BasicScheduler": ("scheduler", "steps", "denoise"),
    "CheckpointLoaderSimple": ("ckpt_name",),
    "EmptyLatentImage": ("width", "height", "batch_size"),
    "EmptyH3LatentImage": ("width", "height", "batch_size"),
    "SaveImage": ("filename_prefix",),
    "VHS_VideoCombine": ("frame_rate", "loop_count", "filename_prefix", "format",
                         "pix_fmt", "crf", "save_metadata", "trim_to_audio",
                         "pingpong", "save_output"),
    "MiniMaxH3ReferenceToVideo": ("prompt", "width", "height", "length",
                                  "ref_image_size"),
    "MiniMaxH3ChainPlan": ("plan",),
}
# 孤儿 widget（inputs 未暴露、但转换后需要保留的输入）：键=节点类型，值=名称顺序。
# 目前只需链式计划 JSON（MiniMaxH3ChainPlan 的首个 widget）。
_ORPHAN_RULES = {
    "MiniMaxH3ChainPlan": ("plan",),
}

# 生成节点优先集（suggest_mapping 优先在这些节点上找尺寸/时长/步数槽）
_GEN_NODE_PRIORITY = re.compile(
    r"(MiniMaxH3.*Conditioning|MiniMaxH3ReferenceToVideo|CLIPTextEncode|"
    r"MiniMaxH3ChainPlan|MiniMaxH3ChainCurrent)", re.I)


# ============ 工作流解析（经典 UI / LiteGraph / API 三格式 → 统一 API 图） ============

def _load_raw(path):
    """读工作流 JSON（路径校验 + 文件缺失 ConfigError）。"""
    p = Path(path)
    if not p.is_file():
        raise common.ConfigError("工作流不存在: %s" % p)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as ex:
        raise common.ConfigError("工作流解析失败 %s: %s" % (p, ex))


def ui_to_api(wf_ui):
    """经典 ComfyUI 导出（UI 格式，dict of id → {class_type, widgets_values, input_order}）
    → API 格式（widgets_values 按 input_order 并入 inputs，去 _meta）。"""
    out = {}
    for nid, node in (wf_ui or {}).items():
        if not isinstance(node, dict):
            continue
        node = dict(node)
        inputs = dict(node.get("inputs") or {})
        widgets = node.get("widgets_values") or []
        order = node.get("input_order") or []
        for name, value in zip(order, widgets):
            inputs[name] = value
        out[str(nid)] = {"class_type": node.get("class_type", ""), "inputs": inputs}
    return out


def litegraph_to_api(data):
    """新版 ComfyUI LiteGraph 导出（{nodes:[...], links:[...]}）→ API 格式。

    - 链接输入 → [源节点, 输出槽]（按 links 解析）
    - widget 输入（inputs 里带 widget 键）→ 对齐 widgets_values 取值
    - 常见节点孤儿 widget（LoadImage/RandomNoise/ChainPlan 等）→ 按名称表补全
    """
    nodes = {n.get("id"): n for n in (data.get("nodes") or []) if isinstance(n, dict)}
    links = {}
    for l in data.get("links") or []:
        if isinstance(l, (list, tuple)) and len(l) >= 6 and l[0] is not None:
            # [link_id, origin_id, origin_slot, target_id, target_slot, type]
            links[l[0]] = (l[1], l[2])
    out = {}
    for nid, node in nodes.items():
        ctype = node.get("type") or ""
        inputs = {}
        pending_widget = []          # 未在 JSON 里带 value 的 widget 输入
        for inp in node.get("inputs") or []:
            if not isinstance(inp, dict):
                continue
            name = inp.get("name")
            if not name:
                continue
            if inp.get("link") is not None:
                src = links.get(inp["link"])
                if src:
                    inputs[name] = [src[0], src[1]]
            elif inp.get("widget"):
                w = inp["widget"]
                if isinstance(w, dict) and "value" in w and w["value"] is not None:
                    inputs[name] = w["value"]
                else:
                    pending_widget.append(inp)
        wv = list(node.get("widgets_values") or [])
        # 1) 名称表整表赋值（按 widget 定义顺序；已存在的链接输入跳过）
        if ctype in _WIDGET_INPUTS:
            for i, nm in enumerate(_WIDGET_INPUTS[ctype]):
                if i < len(wv) and nm and nm not in inputs:
                    inputs[nm] = wv[i]
        # 2) 孤儿规则（链式计划 JSON 等）
        if ctype in _ORPHAN_RULES:
            for i, nm in enumerate(_ORPHAN_RULES[ctype]):
                if i < len(wv) and nm not in inputs:
                    inputs[nm] = wv[i]
        # 3) 兜底 zip：未表节点的 widget 输入，数量对得上才按序对齐
        unlinked = [i for i in pending_widget if i.get("link") is None]
        if unlinked and len(unlinked) == len(wv):
            for inp, val in zip(unlinked, wv):
                if inp["name"] not in inputs:
                    inputs[inp["name"]] = val
        out[str(nid)] = {"class_type": ctype, "inputs": inputs}
    return out


def is_litegraph(data):
    """新版 LiteGraph 格式判定：dict 且含 nodes 数组、值里无 class_type。"""
    if not isinstance(data, dict) or "nodes" not in data:
        return False
    return not any(isinstance(v, dict) and "class_type" in v
                   for v in data.values())


def to_api_graph(data):
    """任意导出格式 → 统一 API 图（{nid: {class_type, inputs}}）。"""
    if not isinstance(data, dict):
        raise common.ConfigError("工作流顶层必须是 JSON 对象")
    if any("widgets_values" in (v or {}) for v in data.values()
           if isinstance(v, dict)):
        return ui_to_api(data)
    if is_litegraph(data):
        return litegraph_to_api(data)
    # 纯 API 格式：透传（nid 字符串化）
    out = {}
    for nid, node in data.items():
        if isinstance(node, dict) and "class_type" in node:
            out[str(nid)] = {"class_type": node["class_type"],
                             "inputs": dict(node.get("inputs") or {})}
    if not out:
        raise common.ConfigError("无法识别工作流格式（非 UI/LiteGraph/API 任一形态）")
    return out


def hash_workflow(path):
    """工作流文件内容 sha256（前 16 位十六进制），供引擎记录比对变更。"""
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        digest = ""
    return digest


# ============ 能力识别 ============

def _capability(nodes):
    """按节点 class_type 组合识别能力 → {kinds:[{kind, confidence}], chain, ref_input, audio}。"""
    types = [n["class_type"] for n in nodes]
    has = lambda rx: any(rx.search(t) for t in types)          # noqa: E731
    kinds = []
    # video：H3 生成/链式节点
    if has(_GEN_VIDEO):
        if has(re.compile(r"MiniMaxH3.*(Conditioning|ReferenceToVideo)", re.I)):
            conf = 0.95
        elif has(_CHAIN):
            conf = 0.85
        else:
            conf = 0.7
        kinds.append({"kind": "video", "confidence": conf})
    elif has(re.compile(r"(VHS_VideoCombine|SaveVideo)", re.I)):
        kinds.append({"kind": "video", "confidence": 0.6})
    # refimg / storyframe：图像生成（CLIPTextEncode + 采样/VAE）
    if has(re.compile(r"CLIPTextEncode", re.I)):
        if has(re.compile(r"(VAELoader|UNETLoader|CheckpointLoader|KSampler|SamplerCustomAdvanced)", re.I)):
            conf_img = 0.8
        else:
            conf_img = 0.5
        kinds.append({"kind": "refimg", "confidence": conf_img})
        kinds.append({"kind": "storyframe", "confidence": conf_img - 0.1})
    # 兜底：纯链式（无核心条件节点也有 video 能力）
    if not kinds and has(_CHAIN):
        kinds.append({"kind": "video", "confidence": 0.75})
    kinds.sort(key=lambda k: -k["confidence"])
    return {
        "kinds": kinds,
        "chain": has(_CHAIN),
        "ref_input": has(_REF_IMAGE) or has(_REF_VIDEO),
        "audio": has(_AUDIO),
    }


def _summarize(cap, n_nodes, node_types):
    """一句话摘要：主能力 + 特征（chain/ref/audio）+ 核心节点。"""
    top = cap["kinds"][0]["kind"] if cap["kinds"] else "?"
    label = KIND_LABELS.get(top, top)
    feats = []
    if cap["chain"]:
        feats.append("链式长视频")
    if cap["ref_input"]:
        feats.append("参考图/参考视频输入")
    if cap["audio"]:
        feats.append("音频")
    core = next((t for t in node_types if _GEN_NODE_PRIORITY.search(t)), node_types[0] if node_types else "?")
    return ("%d 节点 %s 工作流（%s）：核心 %s%s，可作 %s 引擎"
            % (n_nodes, ("MiniMaxH3" if "MiniMaxH3" in " ".join(node_types[:6]) else "ComfyUI"),
               "、".join(feats) or "标准生成", core,
               "（含音频解码）" if cap["audio"] else "",
               label))


# ============ analyze_workflow ============

def _input_type(node_id, name, api_inputs, raw_entries):
    """输入的类型：优先原格式 inputs 条目，缺失按名称启发式。"""
    for e in raw_entries or []:
        if e.get("name") == name and e.get("type"):
            return e["type"]
    if name in ("width", "height", "length", "frames", "steps", "seed", "noise_seed",
                "batch_size", "frame_rate", "loop_count"):
        return "INT"
    if name in ("prompt", "text", "image", "audio", "video", "filename_prefix",
                "ckpt_name", "unet_name", "vae_name", "clip_name", "lora_name",
                "upload", "plan"):
        return "STRING"
    return ""


def analyze_workflow(path):
    """扫描 + 语义分析工作流 → 分析结果 dict（spec P7b §1）。"""
    raw = _load_raw(path)
    api = to_api_graph(raw)
    nodes = []
    for nid, node in sorted(api.items(), key=lambda kv: _num(kv[0])):
        raw_node = None
        if isinstance(raw, dict) and "nodes" in raw:
            raw_node = next((n for n in raw.get("nodes") or []
                             if str(n.get("id")) == str(nid)), None)
        entries = (raw_node or {}).get("inputs") or [] if isinstance(raw_node, dict) else []
        inputs = []
        for name, value in (node.get("inputs") or {}).items():
            inputs.append({"name": name,
                           "type": _input_type(nid, name, node["inputs"], entries),
                           "value": value})
        outputs = []
        for o in (raw_node or {}).get("outputs") or []:
            if isinstance(o, dict):
                outputs.append({"name": o.get("name") or "",
                                "type": o.get("type") or ""})
        nodes.append({"id": str(nid), "class_type": node.get("class_type", ""),
                      "title": (raw_node or {}).get("title") or "",
                      "inputs": inputs, "outputs": outputs})
    cap = _capability(nodes)
    node_types = [n["class_type"] for n in nodes]
    return {
        "path": str(Path(path)),
        "name": Path(path).name,
        "hash": hash_workflow(path),
        "nodes": nodes,
        "capability": cap,
        "summary": _summarize(cap, len(nodes), node_types),
    }


def _num(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return 1 << 30


# ============ suggest_mapping（规则命中） ============

# 业务参数 → 槽位规则：names=输入名命中；gen=优先生成节点；loaders=加载器节点取 input 名
_PARAM_RULES = {
    "prompt":    {"names": ("prompt", "text", "description"), "gen": True},
    "width":     {"names": ("width",), "gen": True},
    "height":    {"names": ("height",), "gen": True},
    "frames":    {"names": ("length", "frames", "frame_count"), "gen": True},
    "steps":     {"names": ("steps",), "gen": False},   # 采样器/调度器节点上；生成节点常无 steps 槽
    "seed":      {"names": ("noise_seed", "seed"), "gen": False},
    "prefix":    {"names": ("filename_prefix", "output_name", "prefix"), "gen": False},
    "image":     {"loaders": ("LoadImage",), "input": "image", "gen": False,
                  "feed": ("first_frame", "image")},
    "ref_image": {"loaders": ("LoadImage", "LoadVideo"), "gen": False, "feed": ("ref",)},
    "audio":     {"loaders": ("LoadAudio",), "input": "audio", "gen": False},
}

_LOADER_SLOT = {"LoadImage": "image", "LoadVideo": "video", "LoadAudio": "audio"}


def _gen_rank(nodes, class_type):
    """生成节点优先序：核心 H3 条件/参考生视频最高，CLIPTextEncode 次之，其余 0。"""
    if re.search(r"MiniMaxH3.*(Conditioning|ReferenceToVideo)", class_type, re.I):
        return 3
    if re.search(r"CLIPTextEncode", class_type, re.I):
        return 2
    if re.search(r"MiniMaxH3Chain(Plan|Current)", class_type, re.I):
        return 1
    return 0


def _find_named_slot(nodes, names, gen_only=False):
    """在节点 inputs 里找输入名 ∈ names 的槽位 → (slot, node, input)。"""
    best = None
    for n in nodes:
        if n["class_type"] in ("Reroute", "MarkdownNote", "Note", "PrimitiveFloat"):
            continue
        for i in n["inputs"]:
            if i["name"] in names:
                rank = _gen_rank(nodes, n["class_type"])
                if gen_only and rank == 0:
                    continue
                cand = (rank, -len(n["inputs"]), n, i)
                if best is None or cand[:2] > best[:2]:
                    best = cand
    return best[2:] if best else (None, None)


def _find_loader_slot(nodes, loader_rx, input_name=None, feed=None, used=None):
    """找加载器节点槽位；feed 给定 → 优先喂给生成节点指定输入（含 ref/first_frame 语义）的加载器。"""
    used = used or set()
    # 生成节点上被链接为 ref/first_frame 的加载器优先（按 API 图链接解析）
    if feed:
        for n in nodes:
            if _gen_rank(nodes, n["class_type"]) == 0:
                continue
            for i in n["inputs"]:
                if i["name"] not in feed:
                    continue
                v = i["value"]
                if isinstance(v, list) and len(v) == 2:
                    src = str(v[0])
                    if src not in used and loader_rx.search(
                            next((x["class_type"] for x in nodes if x["id"] == src), "")):
                        return "%s.inputs.%s" % (src, _LOADER_SLOT.get(
                            next((x["class_type"] for x in nodes if x["id"] == src), ""),
                            input_name or "image"))
    for n in nodes:
        if loader_rx.search(n["class_type"]) and n["id"] not in used:
            slot = "%s.inputs.%s" % (n["id"], _LOADER_SLOT.get(n["class_type"], input_name or "image"))
            return slot
    return None


def suggest_mapping(analysis, kind, params_spec=None):
    """规则命中生成映射（业务参数名 → node.inputs.槽）+ 每槽说明；未覆盖槽 → unclassified。

    params_spec：业务参数名列表（缺省按 kind 默认规格）。
    """
    kind = kind if kind in KINDS else ("video" if kind in ("抽卡", "视频") else KINDS[0])
    params = list(params_spec) if params_spec else list(DEFAULT_PARAMS.get(kind, DEFAULT_PARAMS["video"]))
    nodes = analysis.get("nodes") or []
    mapping, notes, unclassified = {}, {}, []
    used = set()
    for p in params:
        rule = _PARAM_RULES.get(p)
        slot = None
        if rule is None:
            unclassified.append(p)
            continue
        if rule.get("loaders"):
            slot = _find_loader_slot(
                nodes, re.compile("|".join(rule["loaders"])),
                input_name=rule.get("input"), feed=rule.get("feed"), used=used)
            if slot:
                nid = slot.split(".")[0]
                used.add(nid)
                ltype = next((n["class_type"] for n in nodes if n["id"] == nid), "")
                notes[p] = ("%s → %s：工作流含 %s 加载器，注入业务%s文件名即可换素材。"
                            % (slot, p, ltype, p))
        else:
            node, inp = _find_named_slot(nodes, rule["names"], gen_only=rule.get("gen", False))
            if node and inp:
                slot = "%s.inputs.%s" % (node["id"], inp["name"])
                gen_note = "（生成节点）" if _gen_rank(nodes, node["class_type"]) else ""
                notes[p] = ("%s → %s：%s 的 %s 输入%s%s。"
                            % (slot, p, node["class_type"], inp["name"], gen_note,
                               "，原值 %r" % (str(inp["value"])[:40],) if inp.get("value") is not None else ""))
        if slot:
            mapping[p] = slot
        else:
            unclassified.append(p)
    return {"kind": kind, "mapping": mapping, "notes": notes,
            "unclassified": unclassified, "mode": "rule"}


# ============ llm_suggest_mapping（LLM 兜底） ============

def _json_from_llm(text):
    """从 LLM 输出提取 JSON 对象（容忍 ```json 代码块包裹 / 前后废话）。"""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM 输出无 JSON 对象")
    return json.loads(t[start:end + 1])


def _llm_slots_summary(analysis):
    """压缩的节点槽位清单（供 LLM 判断槽位，防超长）。"""
    lines = []
    for n in (analysis.get("nodes") or [])[:40]:
        ins = ", ".join("%s:%s" % (i["name"], i["type"] or "?")
                        for i in n["inputs"][:14])
        lines.append("%s %s inputs[%s]" % (n["id"], n["class_type"], ins))
    return "\n".join(lines) or "（空）"


def llm_suggest_mapping(analysis, kind, desc="", cfg=None, rule=None, timeout=90):
    """规则结果基础上对 unclassified/低置信槽做 LLM 兜底（agent.chat，deepseek 在线）。

    输入 = 分析结果 JSON + 任务说明；输出 = JSON mapping+说明。任何失败静默回退规则结果。
    返回 {kind, mapping, notes, unclassified, mode: rule|llm}。
    """
    rule = rule or suggest_mapping(analysis, kind)
    if not rule["unclassified"]:
        return rule                       # 规则全命中 → 无需 LLM
    cfg = cfg or common.load_config()
    prompt = (
        "你是 ComfyUI 工作流语义适配助手。下面是一个工作流的节点槽位清单（nodeid class_type "
        "inputs[输入名:类型...]）与目标 kind=%s。请为未分类的业务参数找出应注入的槽位。\n\n"
        "节点清单：\n%s\n\n"
        "业务参数：%s\n"
        "已由规则命中的映射（不要改动）：%s\n"
        "请只输出一个 JSON 对象：{\"mapping\": {\"参数\": \"nodeid.inputs.输入名\"}, "
        "\"notes\": {\"参数\": \"一句话说明为什么选这个槽位\"}}。"
        "槽位必须在上面节点清单中存在；找不到的不要写进 mapping。不要输出解释。"
        % (kind, _llm_slots_summary(analysis),
           "、".join(rule["unclassified"]), json.dumps(rule["mapping"], ensure_ascii=False)))
    if (desc or "").strip():
        prompt += "\n\n用户补充说明：%s" % desc.strip()[:500]
    try:
        prov = agent.resolve_provider(cfg)
        text = agent.chat(prov["base"], prov["model"], prov["api_key"],
                          [{"role": "system",
                            "content": "只输出 JSON，不要 Markdown 代码块包裹以外的内容。"},
                           {"role": "user", "content": prompt}],
                          temperature=0.2, timeout=timeout)
        data = _json_from_llm(text)
        llm_map = {str(k): str(v) for k, v in (data.get("mapping") or {}).items()
                   if isinstance(v, (str, int))}
    except Exception:
        return rule                       # LLM 失败 → 静默回退规则结果
    if not llm_map:
        return rule
    for p, slot in llm_map.items():
        if p in rule["mapping"] or p not in rule["unclassified"]:
            continue                      # 规则结果优先，不覆盖
        if not _slot_ok(analysis, slot):
            continue                      # 槽位不在分析结果 → 丢弃
        rule["mapping"][p] = slot
        notes = data.get("notes") or {}
        rule["notes"][p] = ("%s → %s：%s" % (slot, p,
                            str(notes.get(p) or "LLM 兜底命中"))).strip()
    rule["unclassified"] = [p for p in rule["unclassified"] if p not in rule["mapping"]]
    rule["mode"] = "llm"
    return rule


# ============ 引擎注册表（config.local.json engines 段） ============

def load_engines():
    """已注册引擎列表（config engines 段；未配置 → 空列表，不写配置）。"""
    try:
        engs = common.load_config().get_path("engines", None)
    except Exception:
        engs = None
    return list(engs) if isinstance(engs, list) else []


def save_engines(engines):
    """写 config.local.json 的 engines 段（深合并保留其他段）→ 返回全量。"""
    overrides = {"engines": engines}
    if common.LOCAL_OVERRIDES.exists():
        try:
            old = json.loads(common.LOCAL_OVERRIDES.read_text(encoding="utf-8"))
            overrides = common._deep_merge(old or {}, overrides)
        except Exception:
            pass
    common.LOCAL_OVERRIDES.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=1), encoding="utf-8")
    return overrides


def find_engine(engines, engine_id_or_name):
    """按 id 或 name 找引擎；找不到返回 None。"""
    key = str(engine_id_or_name or "").strip()
    for e in engines or []:
        if str(e.get("id")) == key or str(e.get("name")) == key:
            return e
    return None


def builtin_engine():
    """内置默认引擎（代码级兜底）：kind=video → render.build_workflow，不写入配置。"""
    return {"id": "builtin", "kind": "video", "name": "内置 H3 构造器",
            "provider": "builtin", "builtin": True,
            "note": "render.build_workflow 内置构造器（T2VA/I2VA/Ref2VA）；未配置引擎时的默认兜底",
            "enabled": True}


def engine_from_workflow(path, kind, name, mapping, note=""):
    """组装引擎记录：{id, kind, name, provider: comfyui, workflow, mapping, note, hash, enabled}。

    id 由 path+kind 哈希生成 → 同一工作流重复注册幂等（覆盖式更新）。
    """
    kind = kind if kind in KINDS else "video"
    digest = hashlib.sha1(("%s|%s" % (str(path), kind)).encode("utf-8")).hexdigest()[:8]
    return {
        "id": "eng%s" % digest,
        "kind": kind,
        "name": (name or "").strip() or Path(path).stem[:24],
        "provider": "comfyui",
        "workflow": str(path),
        "mapping": dict(mapping or {}),
        "note": (note or "").strip(),
        "hash": hash_workflow(path),
        "enabled": True,
    }


def engine_changed(engine):
    """工作流文件 hash 与注册时不一致 → 变更提醒（文件缺失也算变更）。"""
    cur = hash_workflow(engine.get("workflow") or "")
    return bool(cur) and cur != engine.get("hash")


def engine_view(engine):
    """引擎展示视图：+ changed 标记（GET /api/engines 用）。"""
    e = dict(engine or {})
    if e.get("builtin"):
        return e
    e["changed"] = engine_changed(e)
    e["changed_note"] = ("工作流文件已变更（hash 不一致），建议重新对接" if e["changed"]
                         else "与注册时一致")
    return e


def _slot_ok(analysis, slot):
    """槽位合法性：nodeid.inputs.name，节点存在且该输入存在于节点 inputs。"""
    parts = str(slot or "").split(".")
    if len(parts) != 3 or parts[1] != "inputs":
        return False
    for n in analysis.get("nodes") or []:
        if n["id"] == parts[0]:
            return any(i["name"] == parts[2] for i in n["inputs"])
    return False


def validate_register(name, kind, path, mapping):
    """注册前校验 → (ok, error)。校验：kind 合法、path 可读可分析、mapping 槽位存在。"""
    kind = (kind or "").strip()
    if kind not in KINDS:
        return False, "kind 必须 ∈ %s" % "、".join(KINDS)
    if not (name or "").strip():
        return False, "name 不能为空"
    try:
        analysis = analyze_workflow(path)
    except common.ConfigError as ex:
        return False, str(ex)
    for p, slot in (mapping or {}).items():
        if not _slot_ok(analysis, slot):
            return False, "映射槽位无效: %s = %s（应为 nodeid.inputs.槽，且槽位存在于该节点）" % (p, slot)
    return True, ""


# ============ 扫描（scan 端点 / manager wf 分支共用） ============

def _source_dirs():
    """config eco.sources 各目录（缺省回退 ComfyUI workflows 根）。"""
    try:
        cfg = common.load_config()
        dirs = cfg.get_path("eco.sources", None)
    except Exception:
        dirs = None
    if isinstance(dirs, list) and dirs:
        return [Path(x) for x in dirs]
    return [Path(r"S:/Develop/AIGC/ComfyUI/workflows")]


def scan_workflows(explicit_path=None):
    """扫描工作流 → 逐文件 analyze + 能力建议。

    explicit_path 给定 → 单文件扫描（供「对接工作流X」与验收用）；否则扫 eco.sources 各目录 *.json。
    返回 items 列表：{path, name, hash, capability, summary}；单个失败 → {path, name, error}。
    """
    files = []
    if explicit_path:
        files = [Path(explicit_path)]
    else:
        seen = {}
        for src in _source_dirs():
            if not src.exists() or not src.is_dir():
                continue
            for f in sorted(src.glob("*.json")):
                seen[f.name] = f          # 按文件名去重（多源同名取后扫到的）
        files = [seen[k] for k in sorted(seen)]
    items = []
    for f in files:
        try:
            a = analyze_workflow(f)
            items.append({"path": a["path"], "name": a["name"], "hash": a["hash"],
                          "capability": a["capability"], "summary": a["summary"]})
        except Exception as ex:
            items.append({"path": str(f), "name": f.name,
                          "error": str(ex)[:200]})
    return items
