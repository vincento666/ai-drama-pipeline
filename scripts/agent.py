#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简单生成 Agent（spec: docs/specs/03-agent模块.md）。

提示词 → 模型 API（OpenAI 兼容）→ 内容。提供商预设：deepseek / qwen / kimi / local。
仅标准库。公共 seam：resolve_provider / chat_endpoint / parse_chat_response / generate / chat。
"""
import json
import re
import urllib.error
import urllib.request

from common import ConfigError, load_config


class AgentError(Exception):
    """上游（模型 API）错误。status = HTTP 状态码（本地失败为 None）。"""

    def __init__(self, message, status=None, provider=None):
        super().__init__(message)
        self.status = status
        self.provider = provider


SYSTEM_PROMPT = (
    "你是本地化 HTV 短剧流水线的生成 Agent。只输出要求的内容本身，"
    "用规范 Markdown；不解释、不寒暄。项目领域词汇以 CONTEXT.md 为准。"
)


# ============ 配置与端点 ============

def resolve_provider(cfg):
    """按 llm.provider 取预设 → {provider, base, model, api_key}。

    provider 缺失或为 custom 时用旧键 llm.base/model/api_key 兜底；
    预设内空字段同样回退旧键；base/model 仍空 → ConfigError；
    未知 provider → ConfigError 并列出可用预设。
    """
    name = (cfg.get_path("llm.provider", "") or "custom").strip()
    presets = cfg.get_path("llm.providers", {}) or {}
    legacy_base = cfg.get_path("llm.base", "") or ""
    legacy_model = cfg.get_path("llm.model", "") or ""
    legacy_key = cfg.get_path("llm.api_key", "") or ""
    if name == "custom":
        base, model, key = legacy_base, legacy_model, legacy_key
    elif name in presets:
        p = presets[name] or {}
        base = p.get("base") or legacy_base
        model = p.get("model") or legacy_model
        key = p.get("api_key") or legacy_key
    else:
        available = ", ".join(sorted(presets)) or "无预设"
        raise ConfigError("未知模型提供商: %s（可用: %s）" % (name, available))
    if not base or not model:
        raise ConfigError("提供商 %s 缺少 base/model 配置（检查 llm.providers.%s）" % (name, name))
    return {"provider": name, "base": base, "model": model, "api_key": key}


def chat_endpoint(base):
    """规范化 OpenAI 兼容端点：base 不以 /v1 结尾则补 /v1，再拼 /chat/completions。"""
    b = base.rstrip("/")
    if not b.endswith("/v1"):
        b += "/v1"
    return b + "/chat/completions"


# ============ 调用与解析 ============

def parse_chat_response(data, status=200):
    """OpenAI 兼容响应 → 正文文本。正文优先，空则回退 reasoning_content；错误响应抛 AgentError。"""
    if isinstance(data, dict) and data.get("error"):
        msg = data["error"].get("message") or json.dumps(data["error"], ensure_ascii=False)
        raise AgentError("上游错误: %s" % msg, status=status)
    choices = (data or {}).get("choices") or []
    if not choices:
        raise AgentError("响应缺少 choices", status=status)
    msg = choices[0].get("message") or {}
    return msg.get("content") or msg.get("reasoning_content") or ""


def _http_error_text(code, data):
    if isinstance(data, dict) and data.get("error"):
        m = data["error"].get("message")
        if m:
            return "HTTP %s: %s" % (code, m)
    return "HTTP %s" % code


def chat(base, model, key, messages, temperature=0.8, max_tokens=16384, timeout=600):
    """一次对话（OpenAI 兼容 /chat/completions）→ 正文文本。失败抛 AgentError。"""
    url = chat_endpoint(base)
    body = json.dumps({"model": model, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = getattr(r, "status", 200)
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8"))
        except Exception:
            data = None
        raise AgentError(_http_error_text(e.code, data), status=e.code)
    except AgentError:
        raise
    except Exception as e:
        raise AgentError("调用失败: %s" % e)
    return parse_chat_response(data, status)


# ============ 任务模板 ============

def build_storyboard_prompt(payload):
    """task: storyboard_from_script —— 剧本 → 分镜表提示词。payload: {script_text, style}。"""
    script_text = payload.get("script_text", "")
    style = payload.get("style", "")
    style_line = "整体风格：%s。" % style if style else ""
    return (
        "你是分镜师。把剧本拆成逐镜分镜表（Markdown 表格），列："
        "镜号|景别|运镜|时长|角色|场景|灯光|对白|备注。\n"
        "要求：1) 镜号从 1 连续编号；2) 单镜 3-6 秒；3) 角色/场景用代号（如 C01/S01，剧本没有则沿用其写法）；"
        "4) 时长列只填数字秒（如 4），不带单位；5) %s6) 只输出表格。\n\n===== 剧本 =====\n%s"
    ) % (style_line, script_text[:8000])


def build_shot_ref_prompt(payload):
    """task: shot_ref —— 分镜单行 → 参考图提示词（M1 供文生图）。payload: {shot, style}。"""
    shot = payload.get("shot", "")
    style = payload.get("style", "")
    style_line = "整体风格：%s。" % style if style else ""
    return (
        "为下面这个分镜写一张参考图生成提示词（英文，供文生图模型使用），"
        "包含：景别/构图、角色外观（角色代号保持与资产一致）、场景环境、光线、色调。"
        "只输出提示词文本。%s\n\n===== 分镜 =====\n%s"
    ) % (style_line, str(shot)[:2000])


# ============ AI 访谈（onboarding，grill 风格追问 → 创作简报） ============

def build_onboard_questions_prompt(payload):
    """task: onboard_questions —— 描述+已答 → 下一轮追问（犀利、聚焦缺口、一次 3-5 个）。"""
    description = payload.get("description", "")
    qa = payload.get("qa", []) or []
    qa_block = "\n".join("- Q: %s\n  A: %s" % (q.get("q", ""), q.get("a", ""))
                         for q in qa) if qa else "（首轮，无已答）"
    return (
        "你是本地化 HTV 短剧创作顾问，在开拍前用追问补齐创作细节（对齐 grill 风格："
        "犀利、聚焦缺口、一次少量问题，不啰嗦）。\n"
        "===== 创作者想法 =====\n%s\n\n===== 已确认细节 =====\n%s\n\n"
        "请找出仍然缺失或含糊的关键细节，输出 3-5 个追问问题（每行一个，格式：- 问题）。\n"
        "优先追问：题材与核心卖点、目标观众、整体风格（视觉+音乐）、单集时长与总集数、"
        "主要角色（数量/关系/冲突）、关键场景、对白语言风格、尺度与禁忌红线。"
    ) % (description[:2000], qa_block)


def build_onboard_brief_prompt(payload):
    """task: onboard_brief —— 描述+问答 → 创作简报（链式生成的一致性/风格锚点）。"""
    description = payload.get("description", "")
    qa = payload.get("qa", []) or []
    qa_block = "\n".join("- Q: %s\n  A: %s" % (q.get("q", ""), q.get("a", ""))
                         for q in qa) if qa else "（无补充问答）"
    return (
        "你是本地化 HTV 短剧创作总监。基于创作者的描述与问答，产出《创作简报》Markdown，"
        "作为后续 剧本/分镜/资产 链式生成的唯一上下文锚点。\n\n"
        "## 创作简报\n"
        "### 题材与卖点\n### 目标观众\n### 整体风格（视觉与音乐）\n"
        "### 时长与分集（单集时长、总集数）\n### 主要角色（名称/身份/外貌锚定/性格/冲突）\n"
        "### 关键场景\n### 对白语言风格\n### 一致性锚点（外观词汇固定，生成时不得换词）\n"
        "### 禁忌与红线\n\n"
        "要求：把已确认信息全部纳入；未确认项写「待定」；只输出简报正文。\n\n"
        "===== 创作者想法 =====\n%s\n\n===== 问答记录 =====\n%s"
    ) % (description[:2000], qa_block)


def parse_questions(text):
    """LLM 输出的问题列表 → 纯问题数组（容错 - / 1. / 1、 前缀）。"""
    out = []
    for line in str(text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^[-*•]?\s*\d*[\.、)]?\s*", "", s)
        if s and not s.startswith(("问题", "Q：")):
            out.append(s)
    return out


# ============ AgentBar 指令拆解（规则版 dry-run，spec 06 §4） ============

def parse_command(text):
    """自然语言指令 → 动作清单（规则版 dry-run；LLM 精拆解后续替换同一 seam）。

    动作：storyboard_gen / shot_ref / draw / compose；shot 为镜号或 None。
    镜号就近提取（前 12 后 16 字符窗口），并继承上一条动作的镜号（如「重抽它」）。
    """
    t = text or ""
    actions = []
    last_shot = None

    def shot_in(snippet):
        m = re.search(r"第\s*(\d+)\s*镜|镜\s*(\d+)", snippet)
        return int(m.group(1) or m.group(2)) if m else None

    if re.search(r"生成分镜|拆.*分镜|剧本.*分镜", t):
        actions.append({"task": "storyboard_gen", "shot": None})
    for m in re.finditer(r"参考图", t):
        ctx = t[max(0, m.start() - 12):m.end() + 12]
        n = shot_in(ctx)
        if n:
            last_shot = n
        actions.append({"task": "shot_ref", "shot": n or last_shot})
    for m in re.finditer(r"重抽|重跑|抽卡", t):
        tail = t[m.end():m.end() + 16]
        n = shot_in(tail)
        if n:
            last_shot = n
        actions.append({"task": "draw", "shot": last_shot})
    if re.search(r"拼接|成片|合成", t):
        actions.append({"task": "compose", "shot": None})
    return actions


_TASKS = {
    "storyboard_from_script": build_storyboard_prompt,
    "shot_ref": build_shot_ref_prompt,
    "onboard_questions": build_onboard_questions_prompt,
    "onboard_brief": build_onboard_brief_prompt,
}


def generate(task, payload=None, cfg=None, chat_fn=None):
    """任务名 + payload → [system, user] messages → chat_fn → 文本。

    chat_fn 默认真实 chat（可注入 mock 以便测试）；cfg 默认读 config.yaml。
    """
    cfg = cfg or load_config()
    chat_fn = chat_fn or chat
    payload = payload or {}
    builder = _TASKS.get(task)
    if builder is None:
        raise ValueError("未知任务: %s（可用: %s）" % (task, ", ".join(sorted(_TASKS))))
    prov = resolve_provider(cfg)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": builder(payload)}]
    return chat_fn(prov["base"], prov["model"], prov["api_key"], messages)
