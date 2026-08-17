#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 会话 Manager 骨架（docs/11-前端重构设计方案.md §7/§8）+ P6a 全操作分支。

会话里的每句自然语言 → 意图分派（v1 规则式，复用现有能力）→ 规划执行 →
每一步写 events.jsonl 回执（running → success/error/skip）+ 更新会话任务状态 →
回合结束追加 assistant 消息（前端轮询 messages/tasks 回显，P3 换 SSE）。

分派规则（规则式 v1，命中即执行，未命中走默认；顺序即优先级，docs/13 §3 P6a 1）：
  剧本/编剧/写        → ai_writer 链式编剧（对齐 /api/ai-write-all：chain + 资产登记 + 拆全部分镜）
  分镜提示词/刷新提示词 → prompt 分支（T8：分镜行+资产+H3 → refs/*.prompt.md）——必须先于 storyboard（含「分镜」）
  登记/删除资产        → asset 分支（T4：asset_manager 登记/删除）——必须先于 patch（含 删/加）
  给角色C01生成参考图   → image-gen 分支（T5：外部生图注入资产）——带 角色/资产/画 语境才算；裸「出图/抽卡/渲染」→ render
  抽卡/渲染/生成视频    → render 抽卡 job（对齐 /api/render 链路，硬前置：分镜提示词已生成；成功后自动质检）
  放到…前/后/调整顺序   → compose-order 工具（T11：读写 E{n}/compose.order.json）——注意「交换镜X和镜Y」「把镜X移到镜Y前/后」→ patch（workflow_patch reorder，改分镜.md）
  选片/选第N镜第M候选   → select 分支（T10：自动 gold take 或对话指定）
  回滚/撤销到          → restore 分支（T12：doc_versions.restore + _ev patch 广播 doc.diff/rev）
  设置/默认模型/阈值    → settings 分支（T14：写 config.local.json agent 段）——必须先于 patch（含 改）
  分镜                → 剧本→分镜（LLM 优先，回退解析器，对齐 /api/storyboard-gen）
  成片/拼接/合成       → compose 拼接（对齐 /api/compose，顺序读 compose.order.json）
  改/修改/加/删/交换镜/移到镜 → workflow_patch 规则解析写盘；解析失败 → 委派外部 adapter 直接编辑
  其他                → agentbridge.run_loop（内置 Manager 或外部 adapter；问候语直接回复）

结果写盘全部走现有链路（ai_writer / workflow_patch / render / compose / agentbridge），
事实源 rev 变化 → 前端现有 rev 轮询自动回显。仅标准库。
"""
import json
import re
import sys
import threading
import time
import uuid
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
SCRIPTS = ROOT / "scripts"
for _p in (str(SCRIPTS), str(WEB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common                      # noqa: E402  路径/配置
import agent                       # noqa: E402  LLM 聊天（resolve_provider + chat，工具环用）
import ai_writer                   # noqa: E402  编剧链（事件→骨架→剧本→资产→分镜）
import agentbridge                 # noqa: E402  外部 harness 适配 + run_loop + 任务存储
import workflow_patch              # noqa: E402  agent 写盘（所改即所得）
import render as render_mod        # noqa: E402  抽卡（ComfyUI）
import compose as compose_mod      # noqa: E402  拼接成片
import review as review_mod        # noqa: E402  候选质检（抽卡后自动质检 / select 分支）
import session_store               # noqa: E402  会话/事件落盘
import event_bus                   # noqa: E402  P3 SSE 事件总线（docs/11 §9.1，写 events.jsonl 处同步广播）
import gen_storyboard              # noqa: E402  分镜解析（prompt / select 分支）
import refs                        # noqa: E402  分镜提示词存储（prompt 分支）
import asset_manager               # noqa: E402  资产登记/删除（asset 分支）
import compose_order               # noqa: E402  成片顺序（compose-order 工具）
import doc_versions                # noqa: E402  版本回滚（restore 分支）
import image_gen                   # noqa: E402  外部生图（image-gen 分支）
import h3_prompt_enhance           # noqa: E402  H3 提示词 LLM 反推增强（P6c：prompt 分支 llm 模式）
import skill_mgr                   # noqa: E402  P6d Skill 管理（list/install/create，docs/13 §2）
import wf_adapter                  # noqa: E402  P7b 素材生成引擎语义适配（工作流扫描/分析/映射/引擎注册表）

DEFAULT_EPISODE = 1
DEFAULT_SHOTS_PER_SHOT = 3         # 对齐 /api/render 默认

_INTENT_RULES = [
    # (kind, 关键词正则列表) —— 命中即分派；顺序即优先级。
    # P7b wf 分支最前（含 工作流/引擎/wf 才命中）：「用工作流X抽卡」含 抽卡 → 必须先于 render；
    #   「对接工作流」「注册引擎」含 设置/改 等 → 必须先于 settings/patch。
    ("wf",          [r"工作流", r"引擎", r"\bwf\b"]),
    # P6a 新增分支的优先级说明（docs/13 §3 P6a 1）：
    #   - skill 分支最前（P6d ③）：「创建/制作」类关键词与 patch 的「加/删」区分——
    #     必须含 skill/技能 才命中（「创建 skill」不会误入 patch）
    #   - prompt 必须先于 storyboard（「生成分镜提示词」含「分镜」）
    #   - image_gen 先于 render：带 角色/资产/画 语境 → 生图；裸「出图/抽卡/渲染」→ 抽卡
    #   - asset 先于 patch（「删除资产C01」「添加角色C02」含 删/加）
    #   - settings 先于 patch（「把默认模型改成X」含 改）
    #   - compose_order 用「放到…前/后」「调整顺序」；「交换镜X和镜Y」「把镜X移到镜Y前/后」→ patch（reorder）
    ("skill",      [r"安装\s*(?:这个)?\s*(?:skill|技能)", r"install\s+skill",
                    r"创建\s*(?:skill|技能)", r"create\s+skill",
                    r"制作\s*(?:skill|技能)", r"新\s*(?:skill|技能)",
                    r"列出\s*(?:skill|技能)", r"list\s+skills?",
                    r"(?:skill|技能)\s*(?:列表|清单|管理)"]),
    ("aiwrite",     [r"剧本", r"编剧", r"写"]),
    ("prompt",      [r"分镜提示词", r"刷新提示词", r"生成提示词", r"提示词刷新"]),
    ("asset",       [r"登记资产", r"资产入库", r"添加角色", r"新增角色", r"登记角色",
                     r"添加场景", r"新增场景", r"添加道具", r"新增道具",
                     r"删除资产", r"删除角色", r"删除场景", r"删除道具"]),
    ("image_gen",   [r"给.{0,16}(角色|资产|C\d{2}|S\d{2}|P\d{2}).{0,16}(生成|画|绘制).{0,8}(图|像)",
                     r"(生成|画|绘制).{0,12}(角色|人物|场景|道具|[CSPR]\d{2}).{0,14}(图|像)",
                     r"(角色|人物|场景|道具|[CSPR]\d{2}).{0,16}出图",
                     r"出图.{0,8}(角色|资产|人物)"]),
    ("render",      [r"抽卡", r"渲染", r"生成视频", r"视频生成", r"重抽", r"出图"]),
    ("compose_order", [r"放\s*到\s*镜\s*\d+\s*[前后]", r"调整顺序", r"重排顺序",
                       r"成片顺序", r"拼接顺序", r"顺序调整", r"顺序交换"]),
    ("select",      [r"选片", r"选\s*(?:第)?\s*\d+\s*镜\s*(?:第)?\s*\d+"]),
    ("restore",     [r"回滚", r"撤销", r"还原到", r"恢复\s*到"]),
    ("settings",    [r"设置", r"默认模型", r"上下文阈值", r"阈值调到", r"阈值改成"]),
    # P7c review 分支：审查/审阅 → 外派回合（RoundAdapter acp 或 CLI 单发）——
    # 必须先于 storyboard（「审查…分镜」含「分镜」，不能误入拆分镜）
    ("review",      [r"审查", r"审阅", r"帮我检查", r"检查一下", r"\breview\b"]),
    ("storyboard",  [r"分镜"]),
    ("compose",     [r"成片", r"拼接", r"合成"]),
    ("patch",       [r"改", r"修改", r"加", r"删", r"交换\s*镜", r"移\s*到\s*镜"]),
]

_KIND_LABEL = {
    "wf": "工作流引擎对接",
    "skill": "Skill 管理",
    "aiwrite": "一键 AI 编剧",
    "storyboard": "AI 拆分镜",
    "render": "批量抽卡",
    "compose": "拼接成片",
    "patch": "编辑项目文档",
    "prompt": "生成分镜提示词",
    "asset": "资产登记/删除",
    "image_gen": "外部生图注入资产",
    "select": "自动选片",
    "restore": "版本回滚",
    "compose_order": "成片顺序编排",
    "settings": "设置",
    "review": "审查/外派回合",
    "default": "通用对话/执行",
}

# ============ P7c 内派工具环：TOOLS 注册表（DSH 式 tool-call 范式） ============
# 每个工具 = 现有分支执行器（复用 _run_xxx 全链路与 _ev 回执）；LLM 作为路由选择工具。
# {id, name, desc, params(简表), fn(project, episode, text, session_id, task_id, ctx, cfg) -> {ok, summary, detail?, error?}}


def _build_handlers():
    """分支执行器注册表（_run_turn 与 TOOLS 注册表共用）。"""
    return {
        "wf": _run_wf,
        "skill": _run_skill,
        "aiwrite": _run_aiwrite,
        "storyboard": _run_storyboard,
        "render": _run_render,
        "compose": _run_compose,
        "patch": _run_patch,
        "prompt": _run_prompt,
        "asset": _run_asset,
        "image_gen": _run_image_gen,
        "select": _run_select,
        "restore": _run_restore,
        "compose_order": _run_compose_order,
        "settings": _run_settings,
        "review": _run_review,
        "default": _run_default,
    }


_TOOL_SPECS = [
    # (id, name, desc, params, kind)
    ("asset", "资产登记/删除", "登记或删除资产（角色/场景/道具），如「登记资产 C04 名称 林冲」「删除资产C01」",
     {"text": "资产操作指令（含资产代号）"}, "asset"),
    ("image_gen", "外部生图注入资产", "给角色/场景/道具生成参考图并关联资产，如「给角色 C01 生成一张古装书生参考图」",
     {"text": "生图指令（含资产代号与画面描述）"}, "image_gen"),
    ("prompt", "生成分镜提示词", "为分镜生成 H3 三段式参考图提示词（refs/*.prompt.md），如「生成分镜提示词」",
     {"text": "提示词指令（可含镜号与附加描述）"}, "prompt"),
    ("render", "批量抽卡", "调用 ComfyUI 抽卡生成候选视频，如「抽卡」「重抽镜2」",
     {"text": "抽卡指令（可含镜号）"}, "render"),
    ("select", "自动选片", "按质检结果自动选中候选，或「选第3镜第2候选」",
     {"text": "选片指令"}, "select"),
    ("restore", "版本回滚", "回滚文档到历史版本，如「回滚分镜到版本3」",
     {"text": "回滚指令（含文档与版本号）"}, "restore"),
    ("compose_order", "成片顺序编排", "调整成片拼接顺序，如「把镜3放到镜1前面」「调整顺序」",
     {"text": "顺序指令"}, "compose_order"),
    ("settings", "设置", "写 config.local.json agent 段，如「把默认模型改成 deepseek」「上下文阈值调到 20000」",
     {"text": "设置指令"}, "settings"),
    ("skill", "Skill 管理", "列出/安装/创建 skill，如「列出 skill」「创建 skill xxx 描述 …」",
     {"text": "skill 指令"}, "skill"),
    ("wf", "工作流引擎对接", "扫描/分析/对接 ComfyUI 工作流为引擎，或用已注册引擎抽卡",
     {"text": "工作流指令"}, "wf"),
    ("patch", "编辑项目文档", "规则解析自然语言编辑指令并写盘分镜/剧本，如「把镜3的灯光改为夜景」；解析失败会委派外部 agent",
     {"text": "编辑指令（含镜号/字段/新值）"}, "patch"),
]


def _make_tool_fn(kind):
    """把分支执行器包装为工具 fn：调用 handler，异常 → {ok: False, error}。"""
    def fn(project, episode, text, session_id, task_id, ctx, cfg):
        handler = _build_handlers().get(kind) or _build_handlers().get("default")
        try:
            reply = handler(session_id, project, episode, (text or "").strip(),
                            task_id, ctx, cfg)
            return {"ok": True, "summary": (reply or "")[:600]}
        except Exception as ex:
            return {"ok": False, "error": str(ex)[:300]}
    fn.__name__ = "tool_%s" % kind
    return fn


def _skill_invoke_fn(name, path):
    """skill 工具 fn：读取 SKILL.md 内容作为结果回填（DSH 式 skill 注入会话）。"""
    def fn(project, episode, text, session_id, task_id, ctx, cfg):
        try:
            content = Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception as ex:
            return {"ok": False, "error": "SKILL.md 读取失败: %s" % ex}
        return {"ok": True,
                "summary": "已加载 skill「%s」（%d 字），请严格遵循其规范执行任务"
                           % (name, len(content)),
                "detail": content[:3000]}
    fn.__name__ = "tool_skill_%s" % name
    return fn


def tool_registry(skills=None):
    """TOOLS 注册表：内置工具 + 已装 skill 动态并入（invoke_skill:<name>）。"""
    tools = [{"id": tid, "name": name, "desc": desc, "params": params,
              "kind": kind, "fn": _make_tool_fn(kind)}
             for tid, name, desc, params, kind in _TOOL_SPECS]
    try:
        skills = skills if skills is not None else skill_mgr.list_skills()
    except Exception:
        skills = skills or []
    for s in skills or []:
        name = s.get("name") or ""
        if not name:
            continue
        tools.append({
            "id": "invoke_skill:%s" % name,
            "name": "invoke_skill:%s" % name,
            "desc": "调用 skill「%s」：%s（把 SKILL.md 规范注入会话后按其执行）"
                    % (name, (s.get("description") or "")[:100]),
            "params": {"text": "要按该 skill 规范执行的任务指令"},
            "kind": "skill", "skill": name,
            "fn": _skill_invoke_fn(name, s.get("path") or ""),
        })
    return tools


# ============ P7c skill 匹配（工具环上下文自动携带 / 外派回合指引） ============

_SKILL_HINT_KWS = ("分镜", "提示词", "镜头", "镜", "prompt", "h3", "抽卡", "渲染",
                   "选片", "成片", "剧本", "编剧", "审查", "review", "skill", "视频",
                   "资产", "灯光", "场景", "角色", "运镜", "景别", "质检", "校验",
                   "制作", "项目", "工作流", "生图")


def _match_skills(text, skills=None, limit=3):
    """按目标关键词匹配 skill 名/描述 → 命中的 skill 清单（工具环自动携带）。

    skills 可注入（测试用）；默认扫描 .agents/skills/。匹配规则：
      名称整体出现在目标 → 高分；目标分词出现在 名称/描述 → 加分；
      目标的领域关键词（分镜/提示词/抽卡…）被 skill 名称/描述覆盖 → 每词加分。
    """
    t = (text or "").strip().lower()
    if skills is None:
        try:
            skills = skill_mgr.list_skills()
        except Exception:
            skills = []
    goal_kws = [kw for kw in _SKILL_HINT_KWS if kw in t]
    toks = [w for w in re.split(r"[\s，。、；;:：（）()《》/\\-]+", t) if len(w) >= 2]
    scored = []
    for s in skills or []:
        name = (s.get("name") or "").lower()
        desc = (s.get("description") or "").lower()
        hay = name + " " + desc
        score = 0
        if name and name in t:
            score += 4
        for tk in toks:
            if tk in name:
                score += 2
            elif tk in desc:
                score += 1
        for kw in goal_kws:
            if kw in hay:
                score += 2
        if score >= 2:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _s, s in scored[:limit]]


def _skills_text(skills):
    """命中 skill → 指引文本（名称+描述+SKILL.md 前段）。"""
    lines = []
    for s in skills or []:
        lines.append("### skill: %s" % (s.get("name") or ""))
        if s.get("description"):
            lines.append("描述：%s" % s["description"])
        path = s.get("path")
        if path:
            try:
                body = Path(path).read_text(encoding="utf-8", errors="ignore")
                lines.append(body[:1200])
            except Exception:
                pass
    return "\n".join(lines)


# ============ P7c 内派工具环（LLM 路由 → 宿主执行 → 回填循环） ============

def _parse_tool_call(text):
    """LLM 回合输出 → {tool, args, rationale}；不可解析 → None（回退现状规则分支）。

    容错：整段 JSON / 提取 {...} 块 / 简单 tool: xxx 行。
    """
    t = (text or "").strip()
    if not t:
        return None
    for candidate in (t,):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and data.get("tool"):
                return data
        except Exception:
            pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict) and data.get("tool"):
                return data
        except Exception:
            pass
    m = re.search(r'tool["\']?\s*[:：]\s*["\']?([A-Za-z0-9_:-]+)', t)
    if m:
        return {"tool": m.group(1), "args": {},
                "rationale": t[:200]}
    return None


def _tool_loop_messages(goal, ctx, tools, skills):
    """工具环 system+user prompt：目标 + 上下文 + 工具清单 + skill 指引。"""
    tool_lines = []
    for t in tools:
        tool_lines.append("- %s：%s。参数：%s"
                          % (t["id"], t["desc"], json.dumps(t.get("params") or {},
                                                            ensure_ascii=False)))
    sys_prompt = (
        "你是 AI 短剧流水线的内派执行器（DSH 式工具环）。你的工作方式：\n"
        "1) 阅读目标与上下文；2) 从「可用工具」里选择最合适的工具，输出一行 JSON："
        "{\"tool\": \"<工具id>\", \"args\": {\"text\": \"<给该工具的自然语言指令>\"}, "
        "\"rationale\": \"<一句话理由>\"}；\n"
        "3) 宿主执行工具后会返回结果，你根据结果决定下一步：继续选工具或完成；\n"
        "4) 目标已达成时输出 {\"tool\": \"done\", \"args\": {\"summary\": \"<结果摘要>\"}}；\n"
        "5) 只能输出 JSON 本身，不要多余解释。\n\n"
        "可用工具：\n%s"
        % "\n".join(tool_lines))
    parts = ["# 目标\n%s" % (goal or "").strip()]
    if ctx:
        parts.append("\n# 上下文\n%s" % str(ctx)[:3000])
    if skills:
        parts.append("\n# 相关 skill 指引（优先遵循）\n%s" % skills[:2500])
    user = "\n\n".join(parts)
    return [{"role": "system", "content": sys_prompt},
            {"role": "user", "content": user}]


def _run_tool_loop(goal, ctx, session_id, project, episode, task_id, cfg,
                   max_rounds=8):
    """内派工具环：LLM 读目标+上下文+工具清单+skill → 选工具 → 宿主执行 → 回填循环。

    返回回执 {status: done|needs_info|error, summary, tool_trace, rounds, mode}
    或 None（LLM 不可用/全失败 → 调用方回退现状分支）。
    """
    try:
        prov = agent.resolve_provider(cfg)
    except Exception:
        return None
    tools = tool_registry()
    skills = _match_skills(goal)
    history = _tool_loop_messages(goal, ctx, tools, skills)
    trace, rounds = [], 0
    for rnd in range(1, max_rounds + 1):
        rounds = rnd
        try:
            reply = agent.chat(prov["base"], prov["model"], prov["api_key"],
                               history, temperature=0.2, max_tokens=2048,
                               timeout=300)
        except Exception:
            # LLM 失败 → 静默回退现状分支
            if trace:
                break
            return None
        decision = _parse_tool_call(reply)
        if decision is None:
            # 非工具输出 → 视为完成（LLM 直接回答）
            return {"status": "done", "summary": (reply or "").strip()[:600],
                    "tool_trace": trace, "rounds": rounds - 1, "mode": "tool_loop"}
        tool_id = str(decision.get("tool") or "").strip()
        if tool_id in ("done", "__done__", "完成", "finish", "completed"):
            args = decision.get("args") or {}
            return {"status": "done",
                    "summary": str(args.get("summary") or "")[:600] or (reply or "").strip()[:600],
                    "tool_trace": trace, "rounds": rounds - 1, "mode": "tool_loop"}
        tool = next((t for t in tools if t["id"] == tool_id), None)
        if tool is None:
            history.append({"role": "assistant", "content": reply})
            history.append({"role": "user", "content":
                            "未知工具 %s。可选：%s。请重新输出 {tool, args}。"
                            % (tool_id, "、".join(t["id"] for t in tools[:40]))})
            continue
        args = decision.get("args") or {}
        args_text = str(args.get("text") or args.get("instruction")
                        or args.get("query") or "")
        if not args_text:
            args_text = str(goal)[:200]
        title = "调用工具 %s" % tool["name"]
        _ev(project, session_id, task_id, "tool", title, "running",
            (args_text or "")[:120])
        result = tool["fn"](project, episode, args_text, session_id, task_id,
                            ctx, cfg)
        ok = bool(result.get("ok"))
        if ok:
            _ev(project, session_id, task_id, "tool", title, "success",
                (result.get("summary") or "完成")[:120])
        else:
            _ev(project, session_id, task_id, "tool", title, "error",
                (result.get("error") or "执行失败")[:120])
        trace.append({"tool": tool_id, "ok": ok})
        backfill = (result.get("detail") or json.dumps(result, ensure_ascii=False))[:2000]
        history.append({"role": "assistant", "content": reply})
        history.append({"role": "user", "content": "工具结果：\n%s" % backfill})
    return {"status": "needs_info",
            "summary": "工具环超过 %d 轮上限，未能确认完成" % max_rounds,
            "tool_trace": trace, "rounds": rounds, "mode": "tool_loop"}


def _tools_contract(skills=None):
    """外派回合契约注入：宿主 TOOLS 注册表清单（id + 描述）。"""
    lines = []
    for t in tool_registry(skills=skills):
        lines.append("· %s：%s" % (t["id"], t["desc"]))
    return "\n".join(lines)


# ============ P7c 统一总结环节（外派/工具环完成 → LLM 总结器 → 落盘） ============
# 对应 DSH「subagent 后台跑完 → 结算通知 → 宿主总结输出」事件驱动范式：
#   handler（后台线程）完成时 _set_summarize 标记请求 → _run_turn 收尾统一唤起
#   _summarize_turn：LLM(agent.chat) 读 结构化回执+原始目标+会话最近上下文 →
#   {做了什么, 产物/变更, 问题/风险, 建议下一步}（中文）→ assistant 消息
#   （meta 含 {mode, tool_trace 摘要}）+ session.msg SSE + trace「回合完成 · 已总结」；
#   LLM 失败/不可解析 → 回执原文兜底（绝不阻塞回合收尾）。

_SUMMARIZE_MODE_LABEL = {
    "acp": "外派回合（ACP）",
    "cli": "外派（CLI）",
    "tool_loop": "内派工具环",
}


def _set_summarize(text, ctx, mode, receipt):
    """回合内标记总结请求（handler 完成时调用；_run_turn 收尾统一执行）。"""
    try:
        _CUR.summarize = {"mode": mode, "goal": text, "ctx": ctx,
                          "receipt": receipt or {}}
    except Exception:
        pass


def _tool_trace_brief(tool_trace):
    """tool_trace → 摘要串（如 Read×2 · Edit×1）。"""
    if not tool_trace:
        return ""
    from collections import Counter
    cnt = Counter((t.get("name") or "?").strip() or "?" for t in tool_trace)
    return " · ".join("%s×%d" % (n, c) for n, c in sorted(cnt.items()))


def _parse_summary_json(text):
    """总结器输出 → dict（容错：整段 JSON / 提取 {...} 块，须含已知键）；失败 None。"""
    t = (text or "").strip()
    if not t:
        return None
    keys = ("做了什么", "产物/变更", "问题/风险", "建议下一步")
    try:
        d = json.loads(t)
        if isinstance(d, dict) and any(k in d for k in keys):
            return d
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            if isinstance(d, dict) and any(k in d for k in keys):
                return d
        except Exception:
            pass
    return None


def _summarize_turn(project, session_id, task_id, req, cfg):
    """统一总结环节（外派 acp/cli 与内派工具环共用；成功/失败/needs_info 均触发）。

    输入 req: {mode, goal, ctx, receipt}；receipt = 结构化回执
    （summary / tool_trace / changes / rounds）。
    流程：LLM(agent.chat) 总结 → 结构化中文总结 → trace 事件
    「回合完成 · 已总结（N 轮 · M 次工具调用）」success → 返回 (总结文本, meta)。
    落盘（assistant 消息 + session.msg）由 _run_turn 收尾统一做；meta 供 assistant 消息携带。
    LLM 失败/输出不可解析 → 回执原文兜底（静默，不抛异常）。
    """
    mode = req.get("mode") or "tool_loop"
    receipt = req.get("receipt") or {}
    goal = (req.get("goal") or "").strip()
    ctx = req.get("ctx") or ""
    tool_trace = receipt.get("tool_trace") or []
    rounds = receipt.get("rounds") or 0
    changes = receipt.get("changes") or []
    n_tools = len(tool_trace)
    brief = _tool_trace_brief(tool_trace)
    raw_summary = (receipt.get("summary") or "").strip() \
        or (receipt.get("error") or "").strip()
    label = _SUMMARIZE_MODE_LABEL.get(mode, mode)

    # 1) LLM 总结器（结构化回执 + 原始目标 + 会话最近上下文）
    summary_text = ""
    try:
        prov = agent.resolve_provider(cfg)
        receipt_json = json.dumps({
            "status": receipt.get("status"),
            "summary": raw_summary[:800],
            "tool_trace": tool_trace[:20],
            "changes": changes[:10],
            "rounds": rounds,
            "error": receipt.get("error"),
        }, ensure_ascii=False)
        prompt = (
            "你是 AI 短剧流水线的回合总结器（DSH 结算通知）。\n"
            "执行器（%s）刚完成一个回合。基于【原始目标】【会话最近上下文】【执行回执】，"
            "输出一行 JSON 结构化总结（中文、简洁，每项一句话）：\n"
            "{\"做了什么\": \"...\", \"产物/变更\": \"...\", "
            "\"问题/风险\": \"...\", \"建议下一步\": \"...\"}\n"
            "只输出 JSON 本身，不要多余文字。\n\n"
            "【原始目标】\n%s\n\n【会话最近上下文（节选）】\n%s\n\n【执行回执】\n%s"
            % (label, goal[:500], str(ctx)[:800], receipt_json))
        out = agent.chat(prov["base"], prov["model"], prov["api_key"],
                         [{"role": "system", "content": agent.SYSTEM_PROMPT},
                          {"role": "user", "content": prompt}],
                         temperature=0.3, max_tokens=1024, timeout=120)
        data = _parse_summary_json(out)
        if data:
            lines = ["**回合总结（%s）**" % label]
            for k in ("做了什么", "产物/变更", "问题/风险", "建议下一步"):
                v = str(data.get(k) or "").strip()
                if v:
                    lines.append("- %s：%s" % (k, v))
            summary_text = "\n".join(lines)
    except Exception:
        summary_text = ""

    # 2) 兜底：LLM 失败/不可解析 → 回执原文（不阻塞收尾）
    if not summary_text:
        if raw_summary:
            summary_text = ("**回合总结（%s）**\n- 做了什么：%s"
                            % (label, raw_summary[:400]))
        else:
            summary_text = "回合未产出可总结内容（status=%s）。" \
                % (receipt.get("status") or "?")

    # 3) trace 事件「回合完成 · 已总结（N 轮 · M 次工具调用）」success
    try:
        _ev_terminal(project, session_id, task_id, "tool",
                     "回合完成 · 已总结（%s）" % label, "success",
                     "%d 轮 · %d 次工具调用%s"
                     % (rounds, n_tools, (" · %s" % brief) if brief else ""))
    except Exception:
        pass

    meta = {
        "mode": mode,
        "rounds": rounds,
        "tool_trace": tool_trace[:30],
        "tool_trace_brief": brief,
        "changes": changes[:10],
        "summarized": True,
    }
    return summary_text, meta

_GREET_RE = re.compile(
    r"^\s*(?:你好|您好|hi|hello|嗨|哈喽|在吗|在不在)[!！。.\s]*$", re.I)

_CUR = threading.local()      # 当前回合 episode + 总结请求（_run_turn 设置，_ev/_summarize 用）


def _doc_of(title):
    """从事件标题提取文档名（doc.diff 用）：分镜 > 成片 > 剧本 > 资产 > 简报 > 小说。"""
    t = title or ""
    for key, label in (("分镜", "分镜"), ("成片", "成片"), ("剧本", "剧本"),
                       ("资产", "资产"), ("简报", "简报"), ("小说", "小说")):
        if key in t:
            return label
    if "镜" in t and "→" in t:      # 分镜字段补丁（写盘 镜01 light → 夜景）
        return "分镜"
    return "项目文档"


# ============ 意图分派 ============

def dispatch_intent(text):
    """规则式意图分派：返回 kind（aiwrite/storyboard/render/compose/patch/default）。"""
    t = text or ""
    for kind, pats in _INTENT_RULES:
        for p in pats:
            if re.search(p, t):
                return kind
    return "default"


def _is_greeting(text):
    return bool(_GREET_RE.match(text or ""))


def _shot_numbers(text):
    """提取「第N镜/镜N」镜号列表（抽卡/重抽用）；无则 None（全部）。"""
    t = text or ""
    nums = [int(m) for m in re.findall(r"第\s*(\d+)\s*镜", t)]
    nums += [int(m) for m in re.findall(r"镜\s*(\d+)", t)]
    return sorted(set(nums)) or None


def _prompt_desc(text):
    """从 prompt 分支用户语料提取「用户附加描述」：去掉指令壳（给镜N/生成分镜提示词/请帮我…）。

    例：「给镜1生成分镜提示词，画面要阴雨赛博朋克」→「阴雨赛博朋克」；
    例：「刷新提示词，赛博朋克夜雨」→「赛博朋克夜雨」；无可提取 → ""（LLM 按分镜行/风格反推）。
    """
    t = (text or "").strip()
    t = re.sub(r"^(?:请|帮我|给我|给)\s*", "", t)
    t = re.sub(r"给\s*镜\s*\d+\s*[，,]?\s*", "", t)
    t = re.sub(r"(?:重新)?(?:生成|刷新)\s*(?:分镜)?提示词|(?:分镜)?提示词\s*(?:生成|刷新)", "", t)
    t = re.sub(r"画面(?:要|是|风格|效果)[：:]?\s*", "", t)   # 「画面要X」→ 保留 X
    t = re.sub(r"镜\s*\d+\s*", "", t)
    return t.strip(" ，。、；;:：")


def _extract_title(text):
    """从「《xxx》/『xxx』」提取作品名；无则空。"""
    m = re.search(r"[《『]([^》』]+)[》』]", text or "")
    return m.group(1).strip() if m else ""


def _default_adapter(cfg):
    """默认外部 adapter（config agent.default），不可用返回 None（走内置）。"""
    name = (cfg.get_path("agent.default", "") or "kimi").strip() or "kimi"
    try:
        a = agentbridge.get_adapter(name)
        if a.available():
            return a
    except Exception:
        pass
    return None


def _build_context(project, episode, session, cfg):
    """外部委派上下文：项目文档摘要 + 会话最近对话（按 agent.context_limit 截断）。"""
    limit = int(cfg.get_path("agent.context_limit", 20000) or 20000)
    ctx = agentbridge.build_project_summary(project, episode)
    msgs = []
    used = 0
    for m in reversed((session or {}).get("messages") or []):
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if used + len(text) > limit and msgs:
            break
        msgs.append("%s: %s" % ("用户" if m.get("role") == "user" else "助手", text))
        used += len(text)
        if len(msgs) >= 30:           # 最近 30 条上限
            break
    if msgs:
        ctx += "\n\n【会话最近对话】\n" + "\n".join(reversed(msgs))
    return ctx


# ============ 会话回合执行 ============

def start_chat(session_id, project, text, episode=DEFAULT_EPISODE):
    """启动一次对话回合：同步落 user 消息 + 任务占位，后台线程执行，立即返回 task_id。"""
    task_id = uuid.uuid4().hex[:8]
    session_store.add_message(project, session_id, "user", text,
                              {"task_id": task_id})
    cfg = common.load_config()
    session_store.add_task(project, session_id, {
        "id": task_id,
        "title": _KIND_LABEL[dispatch_intent(text)],
        "kind": dispatch_intent(text),
        "status": "running",
        "created": time.time(), "updated": time.time(),
        "summary": "正在分派…",
    })
    t = threading.Thread(target=_run_turn,
                         args=(session_id, project, text, episode, task_id),
                         daemon=True, name="session-%s" % task_id)
    t.start()
    return task_id


def _ev(project, session_id, task_id, kind, title, status, summary="", detail=""):
    try:
        ev = session_store.add_event(project, session_id, kind, title, status,
                                     summary, detail, task_id=task_id)
    except Exception:
        return
    # P3：写 events.jsonl 处同步广播（docs/11 §9.1）——trace 实时推送；
    # patch 成功 → doc.diff（AI 写盘变更摘要）+ rev（事实源摘要变化）
    try:
        event_bus.publish("trace",
                          {"session_id": session_id, "task_id": task_id, "event": ev},
                          project=project)
        if kind == "patch" and status == "success":
            ep = int(getattr(_CUR, "episode", DEFAULT_EPISODE) or DEFAULT_EPISODE)
            m = re.search(r"E(\d+)", title or "")
            doc_ep = int(m.group(1)) if m else ep
            event_bus.publish("doc.diff",
                              {"doc": _doc_of(title), "summary": summary or title,
                               "episode": doc_ep},
                              project=project)
            try:
                event_bus.publish("rev",
                                  {"rev": agentbridge.facts_rev(project, ep), "episode": ep},
                                  project=project)
            except Exception:
                pass
    except Exception:
        pass


def _task(project, session_id, task_id, **patch):
    try:
        session_store.update_task(project, session_id, task_id, patch)
    except Exception:
        pass


def _ev_terminal(project, session_id, task_id, kind, title, status, summary="", detail=""):
    """终态收尾事件：只写 events.jsonl + 广播 trace，不触发 doc.diff/rev。

    P3.5：回合收尾补发 running 的配对终态时用——patch 类 running 若在这里
    补 success 会误触发 doc.diff/rev 广播，故与 _ev 分开。
    """
    try:
        ev = session_store.add_event(project, session_id, kind, title, status,
                                     summary, detail, task_id=task_id)
    except Exception:
        return
    try:
        event_bus.publish("trace",
                          {"session_id": session_id, "task_id": task_id, "event": ev},
                          project=project)
    except Exception:
        pass


def _close_running_events(project, session_id, task_id, reply, ok):
    """统一终态收尾器（P3.5 问题 1/2）：回合收尾处把仍处于 running 的事件补终态。

    以 events.jsonl 为唯一事实（与 smoke_accept 的判定一致）：按 (kind, title) 计数，
    running 数 > 终态数的键 → 补发差额终态（成功回合标 success、失败回合标 error，
    summary 用最终 reply 摘要）。终态追加在对应 running 之后（写入顺序即显示顺序）。
    已显式终态的事件不受影响；本函数是兜底安全网，不重复不覆盖。
    """
    evs = session_store.list_events(project, session_id, limit=1000,
                                    task_id=task_id).get("events") or []
    counts = {}
    for e in evs:
        key = (e.get("kind"), e.get("title"))
        c = counts.setdefault(key, [0, 0])
        if e.get("status") == "running":
            c[0] += 1
        else:
            c[1] += 1
    status = "success" if ok else "error"
    base = (reply or "").strip()[:120] or ("回合完成" if ok else "回合失败")
    for (kind, title), (n_run, n_term) in counts.items():
        for _ in range(max(0, n_run - n_term)):
            _ev_terminal(project, session_id, task_id, kind, title, status,
                         summary=base)


def _run_turn(session_id, project, text, episode, task_id):
    """后台执行一次回合：分派 → 执行 → 事件/任务/消息收尾。"""
    _CUR.episode = episode       # P3：回合 episode 供 _ev 做 rev/doc.diff 广播
    _CUR.summarize = None        # P7c：回合总结请求（外派/工具环 handler 设置）
    cfg = common.load_config()
    session = session_store.get_session(project, session_id) or {}
    ctx = _build_context(project, episode, session, cfg)
    intent = dispatch_intent(text)
    reply = ""
    ok = False
    try:
        _ev(project, session_id, task_id, "subtask", "解析创作意图",
            "running", "manager 分派中…")
        _ev(project, session_id, task_id, "search", "检索项目文档",
            "running", "剧本/分镜/资产 摘要就绪")
        _ev(project, session_id, task_id, "search", "检索项目文档",
            "success", "上下文 %d 字" % len(ctx))
        _ev(project, session_id, task_id, "subtask", "解析创作意图",
            "success", "分派 → %s" % _KIND_LABEL[intent], detail=intent)
        _ev(project, session_id, task_id, "subtask", "执行中：%s"
            % _KIND_LABEL[intent], "running", "开始执行")

        handlers = _build_handlers()
        reply = handlers[intent](session_id, project, episode, text, task_id, ctx, cfg)
        ok = True
        _task(project, session_id, task_id,
              status="success", summary=(reply or "")[:200])
        _ev(project, session_id, task_id, "subtask", "执行中：%s"
            % _KIND_LABEL[intent], "success", "执行完成")
        _ev(project, session_id, task_id, "subtask", "回合完成",
            "success", "任务完成，已写盘回执")
    except Exception as ex:
        reply = "执行失败：%s" % ex
        _task(project, session_id, task_id, status="error", summary=reply[:200])
        _ev(project, session_id, task_id, "subtask", "执行中：%s"
            % _KIND_LABEL[intent], "error", "执行异常，见回合失败详情")
        _ev(project, session_id, task_id, "subtask", "回合失败",
            "error", reply[:200], detail=str(ex))

    # P3.5：统一终态收尾——本回合仍 running 的事件按结果补终态（先于 tool 快照，
    # 保证 tool 消息里的全量事件也带终态；顺序 = 追加顺序，紧跟对应 running 之后）
    _close_running_events(project, session_id, task_id, reply, ok)

    # P7c：统一总结环节——外派（acp/cli）与内派工具环完成时（含失败/needs_info）
    # 唤起 _summarize_turn（LLM 总结器）；总结文本作为最终回复，meta 进 assistant 消息
    sum_meta = {}
    try:
        sum_req = getattr(_CUR, "summarize", None)
        if sum_req is not None:
            reply, sum_meta = _summarize_turn(project, session_id, task_id,
                                              sum_req, cfg)
    except Exception:
        pass

    # 收尾：tool 消息（本回合事件回执，前端渲染为 EventTrace）+ assistant 回复
    evs = session_store.list_events(project, session_id, limit=200,
                                    task_id=task_id).get("events") or []
    if evs:
        evs.reverse()                 # 时间线正序（与 EventTrace 语义一致）
        try:
            session_store.add_message(project, session_id, "tool", "",
                                      {"task_id": task_id, "events": evs})
        except Exception:
            pass
    try:
        msg_meta = {"task_id": task_id, "intent": intent}
        msg_meta.update(sum_meta)     # P7c：{mode, rounds, tool_trace, tool_trace_brief, changes}
        session_store.add_message(project, session_id, "assistant", reply,
                                  msg_meta)
    except Exception:
        pass
    # P3：流式推送（docs/11 §9.3）——v1 = 回复完成后推整段 + 空 chunk 收尾；
    # ACP/run_loop 接流式 lines 后可逐步推真 chunk（前端按 chunk 累积打字机渲染）
    try:
        event_bus.publish("session.msg",
                          {"session_id": session_id, "task_id": task_id, "chunk": reply},
                          project=project)
        event_bus.publish("session.msg",
                          {"session_id": session_id, "task_id": task_id, "chunk": ""},
                          project=project)
    except Exception:
        pass
    try:
        session_store.touch(project, session_id)
    except Exception:
        pass

# ============ 执行器（复用现有链路） ============

def _run_aiwrite(session_id, project, episode, text, task_id, ctx, cfg):
    """剧本/编剧/写 → 链式编剧（事件→骨架→剧本→资产）。

    无小说时不再报错，走从零编剧：① 创作简报（有则跳过）→ ② 小说素材（LLM）→
    继续原链式编剧四步。对话里直接给完整素材（≥200 字）仍 write_novel 直写。
    """
    novel = ai_writer.read_novel(project)
    idea = (text or "").strip()
    if not novel and len(idea) >= 200:
        # 长文本直接当小说素材（对话即访谈）
        ai_writer.write_novel(project, idea)
        novel = ai_writer.read_novel(project)
    title = _extract_title(text) or project
    if not novel:
        # ---- 从零编剧（P4a）：想法 → 创作简报 → 小说素材 ----
        ok_llm, _base = ai_writer.llm_available(cfg)
        if not ok_llm:
            _ev(project, session_id, task_id, "subtask", "从零编剧",
                "error", "无可用 LLM（从零编剧需要 LLM 生成简报与小说素材）")
            return ("当前无可用 LLM：从零编剧（想法 → 创作简报 → 小说素材）需要 LLM 在线。"
                    "可先粘贴小说素材（≥200 字）再让我编剧。")
        if ai_writer.read_brief(project):
            _ev(project, session_id, task_id, "subtask", "从零编剧 ① 创作简报",
                "skip", "已有创作简报，跳过")
        else:
            _ev(project, session_id, task_id, "subtask", "从零编剧 ① 创作简报",
                "running", "LLM 从想法生成创作简报…")
            try:
                ok_brief = ai_writer.brief_from_idea(project, idea, title)
            except Exception as ex:
                _ev(project, session_id, task_id, "subtask", "从零编剧 ① 创作简报",
                    "error", str(ex)[:120])
                raise
            if not ok_brief:
                _ev(project, session_id, task_id, "subtask", "从零编剧 ① 创作简报",
                    "error", "LLM 未产出简报内容")
                raise RuntimeError("从零编剧 ① 创作简报失败：LLM 未产出内容")
            _ev(project, session_id, task_id, "subtask", "从零编剧 ① 创作简报",
                "success", "创作简报已生成")
        brief = ai_writer.read_brief(project)
        _ev(project, session_id, task_id, "subtask", "从零编剧 ② 小说素材",
            "running", "LLM 生成 3000-6000 字小说素材…")
        try:
            ok_novel = ai_writer.novel_from_idea(project, idea, title, brief)
        except Exception as ex:
            _ev(project, session_id, task_id, "subtask", "从零编剧 ② 小说素材",
                "error", str(ex)[:120])
            raise
        if not ok_novel:
            _ev(project, session_id, task_id, "subtask", "从零编剧 ② 小说素材",
                "error", "LLM 未产出小说素材")
            raise RuntimeError("从零编剧 ② 小说素材失败：LLM 未产出内容")
        novel = ai_writer.read_novel(project)
        _ev(project, session_id, task_id, "subtask", "从零编剧 ② 小说素材",
            "success", "小说素材已生成（%d 字）" % len(novel))
    _ev(project, session_id, task_id, "subtask", "链式编剧（事件→骨架→剧本→资产）",
        "running", "LLM 依次生成，耗时较长…")
    # P3.5 问题 3：长任务中间进度——预发 4 步 running 事件 + chain 回调逐发 success
    _AWRITE_STEPS = [("事件图谱", "①"), ("故事骨架", "②"), ("剧本", "③"), ("资产清单", "④")]
    step_title = {label: "编剧 %s %s" % (num, label) for label, num in _AWRITE_STEPS}
    ok_llm, _base = ai_writer.llm_available(cfg)
    if ok_llm:
        for label, num in _AWRITE_STEPS:
            _ev(project, session_id, task_id, "subtask", "编剧 %s %s" % (num, label),
                "running", "LLM 生成中…")

    def on_step(label, summary):
        t = step_title.get(label)
        if t:
            _ev(project, session_id, task_id, "subtask", t,
                "success", summary or "已生成")

    try:
        mode, results = ai_writer.chain(project, title, on_step=on_step)
    except Exception as ex:
        _ev(project, session_id, task_id, "subtask", "链式编剧（事件→骨架→剧本→资产）",
            "error", str(ex)[:120])
        raise
    if mode != "llm":
        _ev(project, session_id, task_id, "subtask", "链式编剧（事件→骨架→剧本→资产）",
            "error", "无可用 LLM，已生成 Agent 指令（可委派外部执行）")
        return ("当前无可用 LLM：已生成 %d 步 Agent 指令（事件/骨架/剧本/资产），"
                "可在对话里说「帮我执行编剧」委派外部 agent 落地。" % len(results or []))
    _ev(project, session_id, task_id, "subtask", "链式编剧（事件→骨架→剧本→资产）",
        "success", "已生成：%s" % "、".join(results or []))
    try:                              # 资产清单 → 资产库登记（复用 server 链路）
        from server import register_assets_from_list
        register_assets_from_list(project)
    except Exception:
        pass
    _ev(project, session_id, task_id, "patch", "写盘 剧本.md / 资产清单.md",
        "success", "已生成：%s" % "、".join(results or []))
    board = None
    if ai_writer.read_script(project):
        try:
            board = ai_writer.storyboard_from_script(project, episode)
        except Exception:
            pass
    _ev(project, session_id, task_id, "patch", "写盘 E%02d/分镜.md" % episode,
        "success", "由剧本镜头序列生成分镜" if board else "（分镜暂未生成）")
    return ("链式编剧完成：%s。%s"
            % ("、".join(results or []),
               "分镜已由剧本生成，中栏自动刷新。" if board else "可在对话里说「拆分镜」继续。"))


def _run_storyboard(session_id, project, episode, text, task_id, ctx, cfg):
    """分镜 → 剧本→分镜（LLM 优先，回退解析器；对齐 /api/storyboard-gen）。"""
    if not ai_writer.read_script(project):
        _ev(project, session_id, task_id, "subtask", "AI 拆分镜",
            "error", "缺剧本.md（先编剧生成剧本）")
        return "缺 剧本.md：请先在对话里说「写剧本」或到中栏剧本视图生成。"
    ok, _base = ai_writer.llm_available(cfg)
    dest, method = None, "parser"
    if ok:
        _ev(project, session_id, task_id, "command", "cli 分镜生成（LLM）",
            "running", "AI 按剧本拆分中…")
        try:
            dest = ai_writer.llm_storyboard(project, episode)
        except Exception:
            dest = None
        if dest is not None:
            method = "llm"
            _ev(project, session_id, task_id, "command", "cli 分镜生成（LLM）",
                "success", "AI 拆分完成")
        else:
            _ev(project, session_id, task_id, "command", "cli 分镜生成（LLM）",
                "error", "LLM 拆分失败，回退解析器")
    if dest is None:
        _ev(project, session_id, task_id, "command", "cli 分镜生成（解析器）",
            "running", "从剧本镜头序列提取分镜…")
        dest = ai_writer.storyboard_from_script(project, episode)
        if dest is not None:
            _ev(project, session_id, task_id, "command", "cli 分镜生成（解析器）",
                "success", "解析器提取完成")
        else:
            _ev(project, session_id, task_id, "command", "cli 分镜生成（解析器）",
                "error", "剧本缺少可解析的镜头序列")
    if not dest:
        _ev(project, session_id, task_id, "subtask", "AI 拆分镜",
            "error", "分镜生成失败（剧本无镜头序列）")
        return "分镜生成失败：剧本缺少可解析的镜头序列。"
    _ev(project, session_id, task_id, "patch", "写盘 E%02d/分镜.md" % episode,
        "success", "分镜已生成（%s）" % ("AI 拆分" if method == "llm" else "解析器提取"))
    return "分镜已生成（%s）：%s" % ("AI 拆分" if method == "llm" else "解析器提取", dest)


def _run_render(session_id, project, episode, text, task_id, ctx, cfg):
    """抽卡/渲染 → render 抽卡（对齐 /api/render；硬前置：分镜提示词已生成；成功后自动质检）。"""
    sb = common.episode_dir(project, episode) / "分镜.md"
    if not sb.exists():
        _ev(project, session_id, task_id, "subtask", "批量抽卡",
            "error", "缺分镜.md（先拆分镜）")
        return "缺分镜.md：请先在对话里说「拆分镜」生成分镜，再抽卡。"
    only = _shot_numbers(text)
    # P6a 硬前置（docs/12 §5）：该镜 refs/*.prompt.md 必须存在，缺失 → 拒绝 + 引导
    missing = _missing_prompts(project, episode, only)
    if missing is None:
        _ev(project, session_id, task_id, "subtask", "批量抽卡",
            "error", "分镜解析失败（先生成分镜）")
        return "分镜解析失败：请先「拆分镜」生成分镜，再抽卡。"
    if missing:
        _ev(project, session_id, task_id, "subtask", "批量抽卡",
            "error", "提示词未生成：镜%s" % ",".join(map(str, missing)))
        tail = " 等" if len(missing) > 8 else ""
        return ("镜%s%s 分镜提示词未生成，请先「生成分镜提示词」再抽卡。"
                % ("、".join(map(str, missing[:8])), tail))
    _ev(project, session_id, task_id, "command", "ComfyUI 抽卡",
        "running", ("仅镜 %s" % ",".join(map(str, only))) if only else "全镜抽卡（每镜 %d 候选）"
        % DEFAULT_SHOTS_PER_SHOT)
    kwargs = dict(project=project, episode=episode,
                  shots_per_shot=DEFAULT_SHOTS_PER_SHOT, only=only,
                  dry_run=False, timeout=1800)
    ok = render_mod.render(**kwargs)
    if not ok:
        _ev(project, session_id, task_id, "command", "ComfyUI 抽卡",
            "error", "生成失败，见桥日志")
        return "抽卡失败：ComfyUI 生成异常，请查看执行记录或桥日志。"
    try:                              # 抽卡完成后自动质检（对齐 run_render_job）
        review_mod.review_episode(project, episode)
    except Exception:
        pass
    _ev(project, session_id, task_id, "command", "ComfyUI 抽卡",
        "success", "抽卡完成，候选已质检")
    return "抽卡完成%s，候选与质检结果已刷新（中栏分镜视图可见）。" % (
        "（镜 %s）" % ",".join(map(str, only)) if only else "")


def _run_compose(session_id, project, episode, text, task_id, ctx, cfg):
    """成片/拼接 → compose 拼接（对齐 /api/compose；顺序读 compose.order.json）。"""
    e_dir = common.episode_dir(project, episode)
    if not (e_dir / "shots").exists():
        _ev(project, session_id, task_id, "subtask", "拼接成片",
            "error", "缺已选片 shots/（先抽卡选片）")
        return "缺已选片：请先抽卡并在分镜视图完成选片，再拼接成片。"
    _ev(project, session_id, task_id, "command", "ffmpeg 拼接",
        "running", "按镜号拼接 E%02d…" % episode)
    ffmpeg = cfg.get_path("compose.ffmpeg", "ffmpeg")
    fps = int(cfg.get_path("compose.fps", 24) or 24)
    order = compose_order.read_order(project, episode)   # P6a：成片顺序覆盖（缺省=分镜行序）
    ok = compose_mod.compose(e_dir / "shots", e_dir / "成片.mp4",
                             ffmpeg=ffmpeg, fps=fps, dry_run=False, order=order)
    if not ok:
        _ev(project, session_id, task_id, "command", "ffmpeg 拼接",
            "error", "拼接失败")
        return "拼接失败：请检查已选片是否完整。"
    _ev(project, session_id, task_id, "patch", "写盘 成片.mp4", "success", "成片已生成")
    return "成片已拼接：%s" % (e_dir / "成片.mp4")


def _delegate_external(session_id, project, episode, text, task_id, ctx, cfg,
                       subtask_title="委派外部 agent", tool_label="外派执行"):
    """外派统一入口（P7c）：delegate_mode=acp → RoundAdapter 回合；否则 CLI 单发。

    patch 解析失败 / review 分支共用；无可用适配器 → 明确错误引导。
    """
    _ev(project, session_id, task_id, "subtask", subtask_title,
        "running", "按 delegate_mode 选择执行器…")
    try:
        adapter = agentbridge.pick_delegate_adapter(
            cfg, cwd=str(common.project_dir(project)))
    except Exception as ex:
        adapter = None
    if adapter is None or not adapter.available():
        _ev(project, session_id, task_id, "subtask", subtask_title,
            "error", "无可用外部 agent（delegate_mode 不可用且无 CLI）")
        return ("当前无可用外部 agent（ACP/CLI 均不可用），且规则未命中可执行的指令。"
                "试试更明确的说法，或检查 agent 配置。")
    mode = getattr(adapter, "delegate_mode", "cli")
    if mode == "acp":
        return _delegate_round(session_id, project, episode, text, task_id, ctx,
                               cfg, adapter, subtask_title, tool_label)
    return _delegate_cli(session_id, project, episode, text, task_id, ctx, cfg,
                         adapter, subtask_title, tool_label)


def _delegate_round(session_id, project, episode, text, task_id, ctx, cfg,
                    adapter=None, subtask_title="委派外部 agent", tool_label="外派回合"):
    """RoundAdapter 外派回合：on_event → _ev tool 事件；结构化回执（summary+tool_trace+changes）。"""
    if adapter is None:
        try:
            adapter = agentbridge.pick_delegate_adapter(
                cfg, cwd=str(common.project_dir(project)))
        except Exception:
            return None
    if not (hasattr(adapter, "run_round") and hasattr(adapter, "available")):
        return None
    cli_name = getattr(adapter, "cli", adapter.name) or adapter.name
    skills = _match_skills(text)
    tools_desc = _tools_contract(skills=skills)
    skills_text = _skills_text(skills)

    def on_event(ev):
        try:
            et = ev.get("type")
            if et == "tool_call":
                title = "%s：调用 %s" % (tool_label, ev.get("name") or "?")
                if ev.get("status") == "started":
                    _ev(project, session_id, task_id, "tool", title, "running")
                else:
                    _ev(project, session_id, task_id, "tool", title, "success", "完成")
            elif et == "thinking" and ev.get("first"):
                _ev(project, session_id, task_id, "tool",
                    "%s：思考中" % tool_label, "running")
        except Exception:
            pass

    title = "%s执行中：%s（ACP）" % (tool_label, cli_name)
    _ev(project, session_id, task_id, "tool", title, "running",
        "RoundAdapter 回合执行中（目标+上下文+工具契约+skill 指引）…")
    try:
        receipt = adapter.run_round(text, ctx=ctx, tools_desc=tools_desc,
                                    skills=skills_text, on_event=on_event,
                                    max_steps=30, timeout=1500)
    except Exception as ex:
        _ev(project, session_id, task_id, "tool", title, "error", str(ex)[:200])
        _ev(project, session_id, task_id, "subtask", subtask_title,
            "error", str(ex)[:200])
        # 失败也要总结（问题+修复建议）
        _set_summarize(text, ctx, "acp", {"status": "error", "summary": "",
                                          "tool_trace": [], "changes": [],
                                          "rounds": 1, "error": str(ex)[:300]})
        return "外派回合失败：%s" % ex
    n_tools = len(receipt.get("tool_trace") or [])
    n_changes = len(receipt.get("changes") or [])
    st = receipt.get("status")
    summary = (receipt.get("summary") or "").strip()
    done_title = "%s完成：%s（ACP）" % (tool_label, cli_name)
    # P7c：完成（成功/失败/needs_info）→ 唤起统一总结环节
    _set_summarize(text, ctx, "acp", receipt)
    if st == "done":
        _ev(project, session_id, task_id, "tool", done_title, "success",
            "完成 %d 轮 · %d 次工具调用%s"
            % (receipt.get("rounds") or 1, n_tools,
               (" · 改动猜测 %d" % n_changes) if n_changes else ""))
        _ev(project, session_id, task_id, "subtask", subtask_title,
            "success", summary[:150])
        changes_txt = "、".join(c["tool"] for c in receipt.get("changes") or []) or "无写类工具"
        return ("%s\n\n—— 外派回合回执 ——\n%d 次工具调用 · %d 处改动猜测（%s）· 会话 %s"
                % (summary[:500], n_tools, n_changes, changes_txt,
                   receipt.get("session_id") or "?"))
    _ev(project, session_id, task_id, "tool", done_title, "error",
        "%s · %d 次工具调用（%s）"
        % (st, n_tools, (receipt.get("error") or "回合未完成")[:120]))
    _ev(project, session_id, task_id, "subtask", subtask_title, "error",
        "%s：%s" % (st, (receipt.get("error") or "回合未完成")[:120]))
    return "外派回合未完成（%s）：%s" % (st, (receipt.get("error") or summary)[:300])


def _delegate_cli(session_id, project, episode, text, task_id, ctx, cfg,
                  adapter=None, subtask_title="委派外部 agent", tool_label="外派执行"):
    """CLI 单发外派（保留原链路）：create_task + run_task + 回执。"""
    adapter = adapter or _default_adapter(cfg)
    if adapter is None or not adapter.available():
        _ev(project, session_id, task_id, "subtask", subtask_title,
            "error", "无可用外部 agent")
        return ("当前无可用外部 agent（CLI 不可用），且规则未命中可执行的指令。"
                "试试更明确的说法。")
    tool_title = "%s中：%s（CLI）" % (tool_label, adapter.name)
    _ev(project, session_id, task_id, "tool", tool_title,
        "running", "委派外部 agent 直接编辑项目文档中…（工作区 = 项目目录）")
    tid = agentbridge.create_task(project, text, ctx)
    agentbridge.run_task(project, text, ctx, adapter,
                         cwd=common.project_dir(project), tid=tid)
    res = agentbridge.read_task(project, tid)
    exit_code = (res.get("result") or {}).get("exit_code")
    exit_code = exit_code if exit_code is not None else "?"
    n_lines = len(res.get("transcript") or [])
    # P7c：CLI 单发也走统一总结环节（回执构造：summary + transcript 行数）
    cli_receipt = {
        "status": "done" if res.get("status") == "done" else "error",
        "summary": (res.get("result") or {}).get("summary")
        or (res.get("result") or {}).get("exit_code", "") or "外部 agent 无文本输出",
        "tool_trace": [{"name": "cli", "status": "done"}],
        "changes": [], "rounds": 1,
        "error": None if res.get("status") == "done"
        else "exit=%s · transcript %d 行" % (exit_code, n_lines),
    }
    _set_summarize(text, ctx, "cli", cli_receipt)
    if res.get("status") != "done":
        _ev(project, session_id, task_id, "tool", tool_title,
            "error", "外部 agent 执行失败：exit=%s · transcript %d 行"
            % (exit_code, n_lines), detail=str(res.get("result") or {})[:200])
        _ev(project, session_id, task_id, "subtask", subtask_title,
            "error", "外部执行失败（exit=%s · transcript %d 行）" % (exit_code, n_lines))
        return "外部编辑失败：%s" % ((res.get("result") or {}).get("summary") or "未知原因")[:300]
    _ev(project, session_id, task_id, "tool", tool_title,
        "success", "外部 agent 已回执：exit=%s · transcript %d 行" % (exit_code, n_lines))
    _ev(project, session_id, task_id, "subtask", subtask_title,
        "success", "外部 agent 已修改项目文档")
    return "外部 agent 已完成编辑，改动已写盘（中栏自动刷新）。"


def _run_patch(session_id, project, episode, text, task_id, ctx, cfg):
    """改/修改/加/删 → 规则解析写盘；解析失败 → 委派外部 agent（delegate_mode 分派）。"""
    changes = workflow_patch.parse_edit_action(text)
    if changes:
        _ev(project, session_id, task_id, "subtask", "解析编辑指令",
            "running", "规则解析命中 %d 条变更" % len(changes))
        result = workflow_patch.apply_patch(project, changes, episode)
        n_ok, n_err = len(result["applied"]), len(result["errors"])
        for a in result["applied"]:
            _ev(project, session_id, task_id, "patch", "写盘 %s" % a.get("summary"),
                "success", a.get("summary") or "")
        for e in result["errors"]:
            _ev(project, session_id, task_id, "patch", "写盘失败", "error",
                e.get("error") or "")
        _ev(project, session_id, task_id, "subtask", "解析编辑指令",
            "success", "已应用 %d 条" % n_ok)
        return "已应用 %d 条变更%s。" % (
            n_ok, ("，%d 条失败：%s" % (n_err, result["errors"][0]["error"]))
            if n_err else "")
    # 无法规则解析 → 委派外部 agent（delegate_mode：acp RoundAdapter 回合 / cli 单发）
    return _delegate_external(session_id, project, episode, text, task_id, ctx, cfg,
                              subtask_title="委派外部 agent 编辑",
                              tool_label="外派执行")


def _run_review(session_id, project, episode, text, task_id, ctx, cfg):
    """审查/审阅（P7c）→ 外派回合：delegate_mode=acp → RoundAdapter（工具轨迹→trace）；
    CLI 不可用/失败回退 cli 单发；均不可用 → 明确失败。
    """
    return _delegate_external(session_id, project, episode, text, task_id, ctx, cfg,
                              subtask_title="委派外部 agent 审查",
                              tool_label="审查回合")


def _run_default(session_id, project, episode, text, task_id, ctx, cfg):
    """其他 → 问候语直接回复；否则 P7c 先试内派工具环（有 LLM 且目标可工具化），
    失败/无 LLM 回退现有 run_loop 外派路径（delegate_mode 选择适配器）。"""
    if _is_greeting(text):
        _ev(project, session_id, task_id, "subtask", "通用对话",
            "success", "问候语直接回复")
        return ("你好！我是 AI 短剧流水线助手，会话已绑定项目「%s」。"
                "直接说想法即可，例如：写剧本 / 拆分镜 / 生成分镜提示词 / 抽卡 / 选片 / 拼接成片 / 把镜3灯光改为夜景。"
                % project)
    # ---- P7c ① 内派工具环（LLM 路由 → TOOLS 注册表工具 → 回填循环） ----
    _ev(project, session_id, task_id, "subtask", "内派工具环",
        "running", "LLM 读目标+工具清单，选择宿主工具执行…")
    receipt = _run_tool_loop(text, ctx, session_id, project, episode, task_id, cfg)
    if receipt is not None:
        n_trace = len(receipt.get("tool_trace") or [])
        if receipt.get("status") == "done":
            _ev(project, session_id, task_id, "tool", "内派工具环",
                "success", "完成 %d 轮 · %d 次工具调用"
                % (receipt.get("rounds") or 0, n_trace))
            _ev(project, session_id, task_id, "subtask", "内派工具环",
                "success", "工具环完成")
            # P7c：工具环完成 → 统一总结环节
            _set_summarize(text, ctx, "tool_loop", receipt)
            return (receipt.get("summary") or "已完成")[:600]
        if n_trace:
            _ev(project, session_id, task_id, "tool", "内派工具环",
                "error", "未确认完成（%d 轮 · %d 次工具调用），回退外派"
                % (receipt.get("rounds") or 0, n_trace))
        else:
            _ev(project, session_id, task_id, "subtask", "内派工具环",
                "skip", "LLM 不可用/无可工具化目标，走外派路径")
    else:
        _ev(project, session_id, task_id, "subtask", "内派工具环",
            "skip", "无可用 LLM，走外派路径")
    # ---- P7c ② 回退：现有 run_loop 外派路径（delegate_mode 选择适配器） ----
    _ev(project, session_id, task_id, "subtask", "自动循环执行",
        "running", "Manager 决策 → Executor 执行 → Auditor 校验…")
    adapter = agentbridge.pick_delegate_adapter(
        cfg, cwd=str(common.project_dir(project)))
    if adapter is not None and not adapter.available():
        adapter = None                     # 不可用 → 内置执行（保持原语义）
    mode = getattr(adapter, "delegate_mode", "cli") if adapter else "builtin"
    # P3.5 问题 4：自动循环外派也算工具调用（显示执行者 + rounds/verified 回执）
    tool_title = "外派执行中：%s（自动循环）" % (
        "%s/%s" % (adapter.name, mode) if adapter else "内置 Manager")
    _ev(project, session_id, task_id, "tool", tool_title,
        "running", "Manager → Executor → Auditor 循环执行中…")
    max_rounds = int(cfg.get_path("agent.max_rounds", 8) or 8)
    loop_id, state = agentbridge.run_loop(
        project, text, adapter=adapter, max_rounds=max_rounds,
        episode=episode, cwd=common.project_dir(project))
    verified = state.get("verified") or []
    rounds = int(state.get("rounds") or 0)
    if adapter is not None:
        # P7c：run_loop 外派（acp/cli）完成 → 统一总结环节（成功/失败均总结）
        _set_summarize(text, ctx, mode, {
            "status": "done" if verified else ("error" if rounds else "error"),
            "summary": ("完成 %d 轮，%d 轮通过校验（loop %s）"
                        % (rounds, len(verified), loop_id)),
            "tool_trace": [], "changes": [], "rounds": rounds,
            "error": None if verified else "未通过校验（loop %s）" % loop_id,
        })
    if verified:
        _ev(project, session_id, task_id, "tool", tool_title,
            "success", "完成 %d 轮，%d 轮通过校验（loop %s）" % (rounds, len(verified), loop_id))
        _ev(project, session_id, task_id, "subtask", "自动循环执行",
            "success", "完成 %d 轮，%d 轮通过校验（loop %s）"
            % (rounds, len(verified), loop_id))
        return ("自动循环完成：执行 %d 轮，%d 轮通过校验（loop %s）。"
                "改动已写盘，中栏自动刷新。" % (rounds, len(verified), loop_id))
    if rounds:
        _ev(project, session_id, task_id, "tool", tool_title,
            "error", "执行 %d 轮但未通过校验（见执行记录）" % rounds)
        _ev(project, session_id, task_id, "subtask", "自动循环执行",
            "error", "执行 %d 轮但未通过校验（见执行记录）" % rounds)
        return "执行了 %d 轮但未通过校验，详见右栏「执行记录」。可再描述得更具体一些。" % rounds
    _ev(project, session_id, task_id, "tool", tool_title,
        "error", "无法自动推进（无可用外部 agent / LLM）")
    _ev(project, session_id, task_id, "subtask", "自动循环执行",
        "error", "无法自动推进（无可用外部 agent / LLM）")
    return ("当前无法自动推进该目标（无可用外部 agent 或 LLM 决策）。"
            "可以换个说法，例如直接说「写剧本」或「拆分镜」。")


# ============ P6a 新分支（docs/13 §3 P6a 1，全走 _ev 回执 + 终态收尾器语义） ============

def _missing_prompts(project, episode, only=None):
    """该镜 refs/shot_XX.prompt.md 缺失列表（render 硬前置）。

    返回缺提示词的镜号列表；分镜缺失/解析失败/无行 → None（由调用方给「先拆分镜」引导）。
    """
    sb = common.episode_dir(project, episode) / "分镜.md"
    if not sb.exists():
        return None
    try:
        rows = gen_storyboard.load_storyboard(sb)
    except Exception:
        return None
    nums = []
    for r in rows:
        try:
            nums.append(int(str(r.get("shot") or "").strip()))
        except (TypeError, ValueError):
            continue
    if not nums:
        return None
    if only:
        if isinstance(only, str):
            wanted = {int(x) for x in re.split(r"[,\s]+", str(only)) if x.strip()}
        else:
            wanted = {int(x) for x in only if str(x).strip().lstrip("-").isdigit()}
        nums = [n for n in nums if n in wanted]
    return [n for n in nums
            if not (common.episode_dir(project, episode) / "refs"
                    / ("shot_%02d.prompt.md" % n)).exists()]


def _asset_code(text):
    """提取首个资产代号（C/S/P/R + 两位）。"""
    m = re.search(r"([CSPR])\s*(\d{2})", (text or "").upper())
    return ("%s%s" % (m.group(1), m.group(2))) if m else None


def _register_asset_local(code, name):
    """登记单个资产（对齐 server.register_asset 的注册表行为，不 import server）。"""
    common.validate_code(code)
    prefix = code[0]
    folder = common.ASSETS / asset_manager.FOLDER_BY_PREFIX[prefix]
    folder.mkdir(parents=True, exist_ok=True)
    reg = common.ASSETS / ".registry" / ("%s.md" % code)
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text("# %s\nname: %s\ntype: %s\n" % (code, name, prefix),
                   encoding="utf-8")
    return {"code": code, "name": name}


def _select_candidate(project, episode, shot_no, filename):
    """选中候选 → 复制为 shots/shot_XX.mp4（对齐 server.select_shot，不 import server）。"""
    src = common.episode_dir(project, episode) / "shots" / ".candidates" / filename
    if not src.exists():
        raise FileNotFoundError(filename)
    dst = common.episode_dir(project, episode) / "shots" / ("shot_%02d.mp4" % int(shot_no))
    dst.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(src, dst)
    return str(dst)


def _parse_restore(text):
    """「回滚分镜到版本3」→ (doc_key, rev)；无法解析 → (None, None)。

    doc 词 → doc_versions 键：分镜→board 剧本→script 资产→assets 小说→novel 简报→brief 成片→compose。
    未提文档名但有版本号 → 默认分镜（board）。
    """
    t = (text or "").strip()
    doc_map = [("分镜", "board"), ("剧本", "script"), ("资产", "assets"),
               ("小说", "novel"), ("简报", "brief"), ("成片", "compose")]
    doc_key = next((k for w, k in doc_map if w in t), None)
    m = re.search(r"版本\s*#?\s*(\d+)|第\s*(\d+)\s*版|回滚\s*到\s*#?\s*(\d+)", t)
    if not m:
        return None, None
    rev = int(m.group(1) or m.group(2) or m.group(3))
    return (doc_key or "board"), rev


def _run_prompt(session_id, project, episode, text, task_id, ctx, cfg):
    """生成分镜提示词（T8）：分镜行 + 资产（角色/场景名+描述）+ 全局风格 → refs/*.prompt.md。

    P6c（docs/13 §3 ①）：config h3.prompt_enhance=llm 时走 h3_prompt_enhance.enhance
    （LLM 反推三段式，吸收用户附加描述 desc；失败自动回退 rule），事件回执注明「LLM 反推」。
    """
    sb = common.episode_dir(project, episode) / "分镜.md"
    if not sb.exists():
        _ev(project, session_id, task_id, "subtask", "生成分镜提示词",
            "error", "缺分镜.md（先拆分镜）")
        return "缺分镜.md：请先「拆分镜」生成分镜，再生成提示词。"
    try:
        rows = gen_storyboard.load_storyboard(sb)
    except Exception as ex:
        _ev(project, session_id, task_id, "subtask", "生成分镜提示词",
            "error", "分镜解析失败：%s" % str(ex)[:120])
        return "分镜解析失败：%s" % ex
    only = _shot_numbers(text)
    style = cfg.get_path("project.style_prefix", "") or ""
    assets = {a["code"]: {"name": a["name"], "type": a["type"]}
              for a in common.asset_table()}
    prompt_mode = str(cfg.get_path("h3.prompt_enhance", "rule") or "rule").strip().lower()
    desc = _prompt_desc(text)
    start_times = {}
    t = 0
    for i, r in enumerate(rows, 1):
        start_times[i] = t
        t += gen_storyboard.parse_dur(r.get("dur"))
    targets = [(i, r) for i, r in enumerate(rows, 1)
               if only is None or i in only]
    if not targets:
        _ev(project, session_id, task_id, "subtask", "生成分镜提示词",
            "error", "镜号不存在（当前 %d 镜）" % len(rows))
        return "镜号不存在（当前 %d 镜）：%s" % (len(rows), "、".join(map(str, only)))
    _ev(project, session_id, task_id, "tool", "组装 H3 三段式提示词",
        "running", "分镜行 + 资产引用 + 全局风格（%d 镜）%s…" % (
            len(targets), "，LLM 反推模式" if prompt_mode == "llm" else ""))
    n_ok = 0
    used_modes = set()
    for i, r in targets:
        if prompt_mode == "llm":
            prompt, used = h3_prompt_enhance.generate_shot_prompt(
                r, i, start_times[i], style, assets, desc, cfg)
            used_modes.add(used)
        else:
            prompt = render_mod.build_h3_shot(r, i, start_times[i], style, assets=assets)
            used_modes.add("rule")
        refs.save_ref_prompt(project, episode, i, prompt)
        n_ok += 1
    if used_modes == {"llm"}:
        note = "LLM 反推"
    elif "llm" in used_modes:
        note = "LLM 反推（部分镜失败回退 rule）"
    else:
        note = "规则组装"
    # P6d ①：事件文案带 skill 信息（已加载 skill 清单 / 无 skill 用内置公式）
    skill_note = ""
    if prompt_mode == "llm":
        skill_note = "；" + h3_prompt_enhance.skill_receipt()
    _ev(project, session_id, task_id, "tool", "组装 H3 三段式提示词",
        "success", "已生成 %d 镜提示词（refs/*.prompt.md，%s%s）" % (n_ok, note, skill_note))
    _ev(project, session_id, task_id, "patch", "写盘 E%02d/refs/*.prompt.md" % episode,
        "success", "已生成 %d 镜分镜提示词（%s%s）" % (n_ok, note, skill_note))
    return ("分镜提示词已生成（%d 镜，%s%s%s）→ E%02d/refs/*.prompt.md，可开始抽卡。"
            % (n_ok, note, skill_note,
               ("；用户描述「%s」已纳入反推" % desc) if (prompt_mode == "llm" and desc) else "",
               episode))


def _run_asset(session_id, project, episode, text, task_id, ctx, cfg):
    """资产登记/删除（T4）：对话解析或 资产清单.md → asset_manager 登记/删除 → _ev 回执。"""
    codes = re.findall(r"[CSPR]\d{2}", (text or "").upper())
    if "删" in text and codes:
        removed = []
        for code in codes:
            try:
                res = asset_manager.remove_asset(code)
                removed.append((code, len(res.get("removed") or [])))
            except Exception as ex:
                _ev(project, session_id, task_id, "patch", "删除资产 %s" % code,
                    "error", str(ex)[:120])
        if removed:
            _ev(project, session_id, task_id, "patch", "写盘 删除资产",
                "success", "已删除：%s" % ", ".join("%s（%d 文件）" % (c, n)
                                                   for c, n in removed))
            return "已删除资产：%s。" % ", ".join("%s（%d 文件）" % (c, n)
                                                 for c, n in removed)
    # 登记：对话内解析（添加/登记/新增/入库 + 代号 + 名称）
    m = re.search(
        r"(?:添加|登记|新增|入库)\s*(?:资产|角色|场景|道具|风格参考)?\s*"
        r"([CSPR]\d{2})\s*(?:名称|名字)?\s*[:：]?\s*([^\s，。]+)",
        (text or "").upper())
    registered = []
    if m:
        code, name = m.group(1), m.group(2).strip()
        try:
            registered.append(_register_asset_local(code, name))
        except Exception as ex:
            _ev(project, session_id, task_id, "patch", "登记资产 %s" % code,
                "error", str(ex)[:120])
    # 资产清单.md 全量同步登记（幂等，对齐 server.register_assets_from_list）
    try:
        from server import register_assets_from_list
        register_assets_from_list(project)
    except Exception:
        pass
    if registered:
        _ev(project, session_id, task_id, "patch", "写盘 登记资产",
            "success", "已登记：%s" % ", ".join("%s %s" % (r["code"], r["name"])
                                               for r in registered))
        return "已登记资产：%s。" % ", ".join("%s %s" % (r["code"], r["name"])
                                            for r in registered)
    _ev(project, session_id, task_id, "subtask", "资产操作",
        "error", "未识别出可执行的资产操作")
    return ("未识别出资产操作：试试「登记资产 C04 名称 林冲」「添加角色 C02 名称 王五」"
            "「删除资产 C04」，或先把资产清单写入 资产清单.md 后说「登记资产」。")


def _run_image_gen(session_id, project, episode, text, task_id, ctx, cfg):
    """外部生图注入资产（T5）：解析目标资产代号 → image_gen → assets/<类型>/<代号>.png。"""
    if not image_gen.available(cfg):
        _ev(project, session_id, task_id, "tool", "外部生图",
            "error", image_gen.friendly_error(cfg))
        return ("生图不可用：%s" % image_gen.friendly_error(cfg))
    code = _asset_code(text)
    if not code:
        _ev(project, session_id, task_id, "tool", "外部生图",
            "error", "未识别资产代号（C/S/P + 两位数字）")
        return "未识别资产代号：请带上要生图的资产，如「给角色 C01 生成一张参考图」。"
    # 从对话提取描述（去意图词后的正文）
    prompt = _image_prompt(text, code)
    if not prompt:
        _ev(project, session_id, task_id, "tool", "外部生图",
            "error", "缺少画面描述")
        return "缺少画面描述：请补充画面内容，如「给角色 C01 生成一张古装书生的参考图」。"
    _ev(project, session_id, task_id, "tool", "外部生图 %s" % code,
        "running", "调生图 API（%s）…" % (cfg.get_path("image.model", "?") or "?"))
    try:
        rec = image_gen.inject_asset_image(project, code, prompt, cfg=cfg)
    except Exception as ex:
        _ev(project, session_id, task_id, "tool", "外部生图 %s" % code,
            "error", str(ex)[:200])
        return "生图失败：%s" % ex
    _ev(project, session_id, task_id, "tool", "外部生图 %s" % code,
        "success", "产物 → %s" % rec["path"])
    _ev(project, session_id, task_id, "patch", "写盘 资产图 %s.png" % code,
        "success", "资产 %s 已关联生图（注册表自动扫描图片目录）" % code)
    return ("已为 %s（%s）生成参考图 → %s。资产库已更新，分镜/提示词会自动引用该图。"
            % (rec["code"], rec["type_name"], rec["path"]))


def _image_prompt(text, code):
    """从对话提取生图描述：去掉意图词/代号，保留画面正文。"""
    t = re.sub(r"给\s*(角色|资产)?\s*%s\s*" % re.escape(code), "", text or "", flags=re.I)
    t = re.sub(r"(生成|画|绘制)\s*(一?张|一张|一个)?\s*(参考)?\s*(图|像)?\s*", "", t)
    t = re.sub(r"%s\s*" % re.escape(code), "", t)
    t = re.sub(r"[，。！？,.]", "", t).strip()
    return t


def _run_select(session_id, project, episode, text, task_id, ctx, cfg):
    """自动选片（T10）：质检 ok 优先（gold take：同 ok 取候选号最小=文件名最接近基础名），
    无 ok 取 warn；对话指定「选第N镜第M候选」也支持。"""
    cand_dir = common.episode_dir(project, episode) / "shots" / ".candidates"
    if not cand_dir.exists():
        _ev(project, session_id, task_id, "subtask", "自动选片",
            "error", "缺候选（先抽卡）")
        return "缺候选：请先抽卡生成候选，再选片。"
    # 显式指定：选第N镜第M候选
    m = re.search(r"选\s*(?:第)?\s*(\d+)\s*镜\s*(?:第)?\s*(\d+)\s*(?:候选|个|号)?", text or "")
    if m:
        shot_no, cand_no = int(m.group(1)), int(m.group(2))
        fname = "shot_%02d_%02d.mp4" % (shot_no, cand_no)
        if not (cand_dir / fname).exists():
            _ev(project, session_id, task_id, "subtask", "自动选片",
                "error", "候选不存在：%s" % fname)
            return "候选不存在：%s（请核对候选号）" % fname
        try:
            dst = _select_candidate(project, episode, shot_no, fname)
        except Exception as ex:
            _ev(project, session_id, task_id, "subtask", "自动选片",
                "error", str(ex)[:120])
            return "选片失败：%s" % ex
        _ev(project, session_id, task_id, "patch", "写盘 镜%02d 选中 %s" % (shot_no, fname),
            "success", "已选中（对话指定）")
        return "已选中 镜%d → %s（%s）。" % (shot_no, dst, fname)
    # 自动选片：按质检结果逐镜选 gold take
    _ev(project, session_id, task_id, "command", "自动选片（质检驱动）",
        "running", "解析候选质检结果（ok 优先 / warn 兜底）…")
    try:
        review_data = review_mod.review_episode(project, episode)
    except Exception as ex:
        _ev(project, session_id, task_id, "command", "自动选片（质检驱动）",
            "error", "质检失败：%s" % str(ex)[:120])
        return "选片失败：候选质检异常（%s）。" % ex
    shots = review_data.get("shots") or []
    if not shots:
        _ev(project, session_id, task_id, "command", "自动选片（质检驱动）",
            "error", "无质检候选")
        return "无质检候选：先抽卡并生成候选。"
    picked, skipped = [], []
    for g in shots:
        shot_no = int(g.get("shot"))
        cands = g.get("candidates") or []
        if not cands:
            skipped.append(shot_no)
            continue
        pool = [c for c in cands if c.get("verdict") == "ok"] or \
               [c for c in cands if c.get("verdict") == "warn"]
        if not pool:
            skipped.append(shot_no)
            continue
        pool.sort(key=lambda c: (c.get("candidate") or 99))   # gold take：候选号最小
        fname = pool[0]["file"]
        try:
            dst = _select_candidate(project, episode, shot_no, fname)
            picked.append((shot_no, fname))
        except Exception as ex:
            _ev(project, session_id, task_id, "patch", "写盘 镜%02d 选中" % shot_no,
                "error", str(ex)[:120])
    if picked:
        _ev(project, session_id, task_id, "command", "自动选片（质检驱动）",
            "success", "已选 %d 镜" % len(picked))
        _ev(project, session_id, task_id, "patch", "写盘 shots/shot_XX.mp4",
            "success", "自动选中：%s" % ", ".join("镜%d→%s" % (n, f) for n, f in picked))
    else:
        _ev(project, session_id, task_id, "command", "自动选片（质检驱动）",
            "error", "无 ok/warn 候选（全部 reject）")
    msg = "已自动选中 %d 镜：%s。" % (len(picked), "、".join("镜%d" % n for n, _ in picked))
    if skipped:
        msg += " 跳过（无候选/全废片）：%s。" % "、".join(map(str, skipped))
    if not picked:
        msg = "自动选片未选中任何镜头（候选均被质检标记为废片）。可先重抽，或指定「选第3镜第1候选」。"
    return msg


def _run_restore(session_id, project, episode, text, task_id, ctx, cfg):
    """版本回滚（T12）：doc_versions.restore + _ev patch 广播（doc.diff/rev 复用 _ev 逻辑）。"""
    doc_key, rev = _parse_restore(text)
    if rev is None:
        _ev(project, session_id, task_id, "subtask", "版本回滚",
            "error", "未识别文档/版本号")
        return ("未识别回滚目标：请说「回滚分镜到版本3」或「把剧本撤销到第2版」。"
                "版本列表可在 设置 → 版本历史 查看。")
    label = doc_versions.DOC_LABELS.get(doc_key, doc_key)
    try:
        rec = doc_versions.restore(project, doc_key, rev, episode=episode)
    except Exception as ex:
        _ev(project, session_id, task_id, "subtask", "版本回滚",
            "error", str(ex)[:200])
        return "回滚失败：%s" % ex
    _ev(project, session_id, task_id, "patch", "写盘 %s（回滚到 #%d）" % (label, rev),
        "success", "已恢复 %s 版本（%s）" % (rec.get("ts", "?"), rec.get("source", "")))
    return ("已回滚%s → 版本 #%d（%s）。中栏已刷新，可再「撤销到上一版」继续回退。"
            % (label, rev, rec.get("ts", "?")))


def _run_compose_order(session_id, project, episode, text, task_id, ctx, cfg):
    """成片顺序编排（T11）：读写 E{n}/compose.order.json（compose_order 模块）。"""
    sb = common.episode_dir(project, episode) / "分镜.md"
    if not sb.exists():
        _ev(project, session_id, task_id, "subtask", "成片顺序",
            "error", "缺分镜.md（先拆分镜）")
        return "缺分镜.md：先「拆分镜」生成分镜，再调整成片顺序。"
    result = compose_order.apply_natural_order(project, episode, text)
    if not result["ok"]:
        _ev(project, session_id, task_id, "subtask", "成片顺序",
            "error", result.get("error") or "顺序指令未识别")
        return "顺序调整失败：%s" % (result.get("error") or "未识别")
    order = result.get("order")
    if order is None:
        _ev(project, session_id, task_id, "patch", "写盘 E%02d/compose.order.json" % episode,
            "success", "已恢复默认顺序（分镜行序）")
        return "已恢复默认顺序：拼接按分镜行顺序。"
    _ev(project, session_id, task_id, "patch", "写盘 E%02d/compose.order.json" % episode,
        "success", "顺序：%s" % ",".join(map(str, order)))
    return ("成片顺序已更新：%s → %s。拼接时按此顺序；可再说「把镜3放到镜1前面」调整。"
            % (result.get("action", "set"),
               " → ".join("镜%d" % n for n in order)))


def _run_settings(session_id, project, episode, text, task_id, ctx, cfg):
    """设置（T14）：写 config.local.json 的 agent 段（复用 LOCAL_OVERRIDES + _deep_merge）。"""
    patch = {}
    m = re.search(r"默认模型\s*(?:改成|改为|设为|换成)\s*[:：]?\s*([A-Za-z0-9_.\-]+)", text or "")
    if m:
        patch["default"] = m.group(1).strip()
    m = re.search(r"上下文阈值\s*(?:改成|改为|设为|调到|调整到)\s*[:：]?\s*(\d+)", text or "")
    if m:
        patch["context_limit"] = int(m.group(1))
    if not patch:
        _ev(project, session_id, task_id, "subtask", "设置",
            "error", "未识别设置项")
        return ("支持对话设置：默认模型（如「把默认模型改成 deepseek」）、"
                "上下文阈值（如「上下文阈值调到 20000」）。其他配置请到设置页修改。")
    try:
        overrides = {"agent": patch}
        if common.LOCAL_OVERRIDES.exists():
            # utf-8-sig：兼容 Windows 工具写入的 UTF-8 BOM（PowerShell Set-Content 等）
            old = json.loads(common.LOCAL_OVERRIDES.read_text(encoding="utf-8-sig"))
            overrides = common._deep_merge(old or {}, overrides)
        common.LOCAL_OVERRIDES.write_text(
            json.dumps(overrides, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as ex:
        _ev(project, session_id, task_id, "subtask", "设置",
            "error", "写盘失败：%s" % str(ex)[:120])
        return "设置写入失败：%s" % ex
    _ev(project, session_id, task_id, "tool", "写盘 config.local.json agent 段",
        "success", "，".join("%s=%s" % (k, v) for k, v in patch.items()))
    return ("已更新设置：%s（config.local.json，立即生效）。"
            % "，".join("%s=%s" % (k, v) for k, v in patch.items()))


def _run_skill(session_id, project, episode, text, task_id, ctx, cfg):
    """Skill 管理（P6d ③）：列出已装 skill / 从 GitHub 安装 / 创建（LLM 生成 SKILL.md）。

    全走 skill_mgr（list_skills / install_from_url / create_skill），事件回执注明
    「已安装 skill：xxx（N 文件，frontmatter ✓）」/「已创建 skill：xxx」/错误引导；
    完成后提示「重新加载 agent 或新会话生效」。
    """
    t = (text or "").strip()
    # 1) 列出
    if re.search(r"列出\s*(?:skill|技能)|(?:skill|技能)\s*(?:列表|清单|管理)|list\s+skills?", t, re.I):
        skills = skill_mgr.list_skills()
        if not skills:
            _ev(project, session_id, task_id, "tool", "列出已装 skill",
                "success", "无已安装 skill（.agents/skills/ 为空）")
            return ("当前无已安装 skill。可说「安装 skill https://github.com/<owner>/<repo>」"
                    "或「创建 skill <名称> <描述>」。")
        names = "、".join("%s（%s）" % (s["name"], (s["description"] or "—")[:28])
                          for s in skills[:20])
        _ev(project, session_id, task_id, "tool", "列出已装 skill",
            "success", "%d 个：%s" % (len(skills), "、".join(s["name"] for s in skills[:20])))
        return ("已安装 %d 个 skill：%s。重新加载 agent 或新会话后生效。"
                % (len(skills), names))
    # 2) 安装（从 GitHub URL）
    m_url = re.search(r"https?://github\.com/[^\s，。]+", t)
    if m_url:
        url = m_url.group(0).strip("，。；;")
        only = None
        om = re.search(r"--only\s+([^\s，。]+)", t)
        if om:
            only = om.group(1).strip("/")
        _ev(project, session_id, task_id, "tool", "安装 skill（GitHub）",
            "running", "api+raw 链路拉取中…（60s 超时，断点续传）")
        try:
            res = skill_mgr.install_from_url(url, only=only)
        except Exception as ex:
            _ev(project, session_id, task_id, "tool", "安装 skill（GitHub）",
                "error", str(ex)[:120])
            return "skill 安装失败：%s" % ex
        if not res.get("ok"):
            _ev(project, session_id, task_id, "tool", "安装 skill（GitHub）",
                "error", res.get("error") or "拉取失败")
            return ("skill 安装失败：%s（可重试，断点续传——已存在文件跳过）。"
                    % (res.get("error") or "未知原因"))
        fm = res.get("frontmatter") or "✓"
        _ev(project, session_id, task_id, "tool", "安装 skill（GitHub）",
            "success", "已安装 skill：%s（%d 文件，frontmatter %s）"
            % (res["name"], res["files"], fm))
        return ("已安装 skill：%s（%d 个文件，frontmatter %s）→ .agents/skills/%s/。"
                "重新加载 agent 或新会话后生效。" % (res["name"], res["files"], fm, res["name"]))
    # 3) 创建（LLM 按 skill-create 规范生成 SKILL.md）
    if re.search(r"(?:创建|制作|新)\s*(?:skill|技能)|create\s+skill", t, re.I):
        m = re.search(r"(?:创建|制作|新)\s*(?:skill|技能)|create\s+skill", t, re.I)
        rest = t[m.end():].strip(" ，。：:；;")
        name, desc = "", ""
        nm = re.search(r"名为\s*([a-z0-9][a-z0-9-]*)", rest)
        if nm:
            name = nm.group(1)
            rest = rest.replace(nm.group(0), "").strip(" ，。：:；;")
        else:
            toks = re.split(r"[\s，,；;]+", rest)
            for tk in toks:
                if re.match(r"^[a-z0-9][a-z0-9-]*$", tk):
                    name = tk
                    break
            if name:
                rest = rest.replace(name, "", 1).strip(" ，。：:；;")
        rest = re.sub(r"^(?:描述|用途)(?:为|是)?\s*[:：]?\s*", "", rest).strip(" ，。：:；;")
        desc = rest
        if not name or not desc:
            _ev(project, session_id, task_id, "subtask", "创建 skill",
                "error", "需要 skill 名称与描述")
            return ("创建 skill 需要名称与描述：如「创建 skill shot-review 描述 分镜审校工具，"
                    "用于抽卡后逐镜质检」。")
        _ev(project, session_id, task_id, "tool", "创建 skill（LLM 生成 SKILL.md）",
            "running", "按 skill-create 规范生成中…（120s 超时）")
        try:
            res = skill_mgr.create_skill(name, desc)
        except Exception as ex:
            _ev(project, session_id, task_id, "tool", "创建 skill（LLM 生成 SKILL.md）",
                "error", str(ex)[:120])
            return "skill 创建失败：%s" % ex
        if not res.get("ok"):
            _ev(project, session_id, task_id, "tool", "创建 skill（LLM 生成 SKILL.md）",
                "error", res.get("error") or "生成失败")
            return "skill 创建失败：%s" % (res.get("error") or "未知原因")
        _ev(project, session_id, task_id, "tool", "创建 skill（LLM 生成 SKILL.md）",
            "success", "已创建 skill：%s（frontmatter ✓）" % name)
        return ("已创建 skill：%s → %s。重新加载 agent 或新会话后生效。"
                % (name, res.get("path")))
    # 4) 未识别具体操作 → 引导
    _ev(project, session_id, task_id, "subtask", "Skill 管理",
        "error", "未识别 skill 操作")
    return ("支持 skill 操作：\n"
            "  · 列出skill\n"
            "  · 安装 skill https://github.com/<owner>/<repo>（可加 --only <子目录>）\n"
            "  · 创建 skill <名称> <描述>（LLM 生成 SKILL.md）")


# ============ P7b 工作流引擎对接（wf 分支，全走 _ev 回执 + 终态收尾器语义） ============

def _wf_target(text):
    """从语料提取工作流目标：Windows 路径 / *.json 文件名；无则空串。"""
    t = (text or "").strip()
    m = re.search(r"[A-Za-z]:[\\/][^\s，。;；]+\.json", t)
    if m:
        return m.group(0).strip()
    m = re.search(r"([^\s，。;；]+\.json)", t)
    if m:
        return m.group(1).strip()
    return ""


def _wf_kind_hint(text):
    """从语料提取 kind 提示（参考图→refimg / 分镜→storyframe / 视频抽卡→video）。"""
    t = (text or "").strip()
    if re.search(r"(参考图|角色图|人物图|图片|形象|refimg)", t, re.I):
        return "refimg"
    if re.search(r"(分镜|预览|storyframe)", t, re.I):
        return "storyframe"
    if re.search(r"(视频|抽卡|长视频|video)", t, re.I):
        return "video"
    return ""


def _wf_match(items, target):
    """把目标（路径/文件名/关键词）匹配到扫描清单 → (item, path) 或 (None, 原目标)。"""
    t = (target or "").strip()
    if not t:
        return None, ""
    p = Path(t)
    if p.is_file():
        return None, str(p)
    stem = Path(t).stem.lower()
    for it in items:
        name = (it.get("name") or "")
        if t.lower() in name.lower() or (stem and stem in name.lower()):
            return it, it.get("path")
        if it.get("path") and t.lower() in str(it.get("path")).lower():
            return it, it.get("path")
    return None, t


def _run_wf(session_id, project, episode, text, task_id, ctx, cfg):
    """工作流引擎对接（P7b，docs/13 §3 P7b §4）：

    扫描 / 分析能力（这个工作流能做什么）/ 对接（adapt → 回执 mapping 草案，含「确认/注册」即落库）
    / 用已注册引擎抽卡（render(engine_id)）/ 错误引导（找不到 → 设置页扫描）。
    """
    t = (text or "").strip()
    target = _wf_target(t)
    kind_hint = _wf_kind_hint(t)
    confirm = bool(re.search(r"确认|注册", t))
    draw = bool(re.search(r"抽卡|渲染|生成视频", t)) and target
    # 兜底提取：「用工作流X抽卡」「确认注册 X」（无 .json 时按名称匹配）
    if draw and not target:
        m = re.search(r"用\s*(?:工作流)?\s*([^\s，。]+?)\s*(?:工作流)?\s*(?:来|去)?\s*抽卡", t)
        if m:
            target = m.group(1).strip()
            draw = bool(target)
    if confirm and not target:
        m = re.search(r"确认\s*注册\s*([^\s，。]+)", t)
        if m:
            target = m.group(1).strip()

    # ---- ① 用工作流X抽卡（已注册引擎优先） ----
    if draw and not confirm:
        engs = wf_adapter.load_engines()
        eng = wf_adapter.find_engine(engs, target) if target else None
        if eng is None:                     # 名称包含 / 工作流路径 匹配
            for e in engs:
                if target and (target.lower() in (e.get("name") or "").lower()
                               or str(Path(e.get("workflow") or ""))
                               == str(Path(target))):
                    eng = e
                    break
        if eng is None:
            items = wf_adapter.scan_workflows()
            hit, path = _wf_match(items, target)
            if hit:
                for e in engs:
                    if e.get("workflow") and Path(e["workflow"]) == Path(path):
                        eng = e
                        break
        if eng is None:
            _ev(project, session_id, task_id, "subtask", "用工作流抽卡",
                "error", "引擎「%s」未注册" % target)
            return ("工作流「%s」尚未注册为引擎：先说「对接工作流 %s 视频」生成映射草案，"
                    "再回复「确认注册」即可用「用该工作流抽卡」。也可到 设置 → ④ 工作流区 扫描后 AI 分析对接。"
                    % (target, target))
        if eng.get("kind") != "video":
            _ev(project, session_id, task_id, "subtask", "用工作流抽卡",
                "error", "引擎 %s 的 kind=%s，不能用于视频抽卡" % (eng.get("name"), eng.get("kind")))
            return "引擎「%s」kind=%s，抽卡需要 video 引擎。" % (eng.get("name"), eng.get("kind"))
        # 与 _run_render 相同的硬前置：分镜 + 分镜提示词
        sb = common.episode_dir(project, episode) / "分镜.md"
        if not sb.exists():
            _ev(project, session_id, task_id, "subtask", "用工作流抽卡",
                "error", "缺分镜.md（先拆分镜）")
            return "缺分镜.md：请先「拆分镜」生成分镜，再用工作流抽卡。"
        missing = _missing_prompts(project, episode)
        if missing is None:
            _ev(project, session_id, task_id, "subtask", "用工作流抽卡",
                "error", "分镜解析失败")
            return "分镜解析失败：请先「拆分镜」再抽卡。"
        if missing:
            _ev(project, session_id, task_id, "subtask", "用工作流抽卡",
                "error", "提示词未生成：镜%s" % ",".join(map(str, missing[:8])))
            return ("镜%s 分镜提示词未生成，请先「生成分镜提示词」再用工作流抽卡。"
                    % "、".join(map(str, missing[:8])))
        _ev(project, session_id, task_id, "command",
            "ComfyUI 抽卡（引擎 %s）" % eng.get("name"),
            "running", "按引擎映射注入模板后提交…")
        ok = render_mod.render(project=project, episode=episode,
                               shots_per_shot=DEFAULT_SHOTS_PER_SHOT,
                               dry_run=False, timeout=1800, engine=eng.get("id"))
        if not ok:
            _ev(project, session_id, task_id, "command",
                "ComfyUI 抽卡（引擎 %s）" % eng.get("name"),
                "error", "生成失败，见桥日志")
            return "抽卡失败：ComfyUI 生成异常（引擎 %s），请查看桥日志。" % eng.get("name")
        try:
            review_mod.review_episode(project, episode)
        except Exception:
            pass
        _ev(project, session_id, task_id, "command",
            "ComfyUI 抽卡（引擎 %s）" % eng.get("name"),
            "success", "抽卡完成，候选已质检")
        return ("已用引擎「%s」（%s）完成抽卡，候选与质检结果已刷新。"
                % (eng.get("name"), eng.get("id")))

    # ---- ② 扫描 / 能力清单 ----
    if re.search(r"扫描", t) or re.search(r"(?:有什么|有哪些|列出).{0,6}工作流", t):
        _ev(project, session_id, task_id, "tool", "扫描工作流",
            "running", "扫描 config eco.sources 各目录 *.json…")
        items = wf_adapter.scan_workflows()
        ok_items = [i for i in items if "error" not in i]
        _ev(project, session_id, task_id, "tool", "扫描工作流",
            "success", "发现 %d 个工作流（%d 失败）" % (len(ok_items),
                                                   len(items) - len(ok_items)))
        if not ok_items:
            return ("未在 eco.sources 发现工作流 JSON。可把 ComfyUI 导出的工作流放入"
                    " config eco.sources 目录（如 ComfyUI/workflows/…）后再说「扫描工作流」。")
        lines = []
        for i in ok_items[:12]:
            cap = i.get("capability") or {}
            kinds = "、".join("%s(%.2f)" % (k["kind"], k["confidence"])
                              for k in (cap.get("kinds") or []))
            feats = ("chain/ref/audio" if cap.get("chain") and cap.get("ref_input")
                     and cap.get("audio")
                     else "/".join(x for x, f in (("chain", cap.get("chain")),
                                                  ("ref", cap.get("ref_input")),
                                                  ("audio", cap.get("audio"))) if f))
            lines.append("  · %s —— %s%s：%s" % (i["name"], kinds,
                                                 ("（%s）" % feats) if feats else "",
                                                 (i.get("summary") or "")[:60]))
        _ev(project, session_id, task_id, "tool", "扫描工作流",
            "success", "能力清单：\n" + "\n".join(lines))
        return ("扫描到 %d 个工作流：\n%s\n\n对某个说「对接工作流 <名称> 视频」生成映射草案，"
                "确认后即可「用该工作流抽卡」。" % (len(ok_items), "\n".join(lines)))

    # ---- ③ 这个工作流能做什么（能力查询） ----
    if re.search(r"能做什么|能干什么|什么能力|能生成", t):
        items = wf_adapter.scan_workflows()
        if target:
            hit, path = _wf_match(items, target)
            if not path:
                _ev(project, session_id, task_id, "subtask", "工作流能力分析",
                    "error", "未找到工作流「%s」" % target)
                return ("未找到工作流「%s」：可先到 设置页 ④ 工作流区「扫描工作流」查看清单，"
                        "或直接说「扫描工作流」。" % target)
            try:
                a = wf_adapter.analyze_workflow(path)
            except Exception as ex:
                return "分析失败：%s" % ex
            cap = a.get("capability") or {}
            kinds = "、".join("%s（置信 %.2f）" % (k["kind"], k["confidence"])
                              for k in (cap.get("kinds") or []))
            feats = []
            if cap.get("chain"):
                feats.append("链式长视频（MiniMaxH3Chain* 循环拼接）")
            if cap.get("ref_input"):
                feats.append("参考图/参考视频输入")
            if cap.get("audio"):
                feats.append("音频")
            _ev(project, session_id, task_id, "tool", "工作流能力分析 %s" % a.get("name"),
                "success", "%s；%s" % (kinds, "；".join(feats) or "标准生成"))
            return ("「%s」能力：%s。%s\n%s\n\n可对接为引擎：说「对接工作流 %s %s」"
                    "生成映射草案，确认后注册。" % (a.get("name"), kinds,
                                              "；".join(feats) or "标准生成",
                                              a.get("summary"), a.get("name"),
                                              (cap.get("kinds") or [{}])[0].get("kind", "video")))
        return "想知道哪个工作流能做什么？先说「扫描工作流」看清单，再问「<工作流名> 能做什么」。"

    # ---- ④ 对接 / 注册 ----
    if target:
        items = wf_adapter.scan_workflows()
        hit, path = _wf_match(items, target)
        if not path or not Path(path).is_file():
            _ev(project, session_id, task_id, "subtask", "对接工作流",
                "error", "未找到工作流「%s」" % target)
            return ("未找到工作流「%s」：可先到 设置页 ④ 工作流区「扫描工作流」查看，"
                    "或确认路径正确（支持 S:/xxx/工作流.json 绝对路径）。" % target)
        try:
            a = wf_adapter.analyze_workflow(path)
        except Exception as ex:
            _ev(project, session_id, task_id, "subtask", "对接工作流",
                "error", "分析失败：%s" % str(ex)[:120])
            return "工作流分析失败：%s" % ex
        kind = kind_hint or ((a.get("capability") or {}).get("kinds") or [{}])[0].get("kind", "video")
        _ev(project, session_id, task_id, "tool", "AI 分析对接 %s" % a.get("name"),
            "running", "识别能力 + 生成映射草案（%s）…" % kind)
        draft = wf_adapter.suggest_mapping(a, kind)
        draft = wf_adapter.llm_suggest_mapping(a, kind, t, cfg, rule=draft)
        mapping = draft.get("mapping") or {}
        notes = draft.get("notes") or {}
        _ev(project, session_id, task_id, "tool", "AI 分析对接 %s" % a.get("name"),
            "success", "映射草案 %d 项：%s%s"
            % (len(mapping), "、".join("%s→%s" % (k, v) for k, v in mapping.items()),
               ("；未分类：%s" % "、".join(draft.get("unclassified") or []))
               if draft.get("unclassified") else ""))
        if not confirm:
            lines = ["工作流「%s」（kind=%s，%s）映射草案："
                     % (a.get("name"), kind, draft.get("mode") or "rule")]
            for p, slot in mapping.items():
                lines.append("  · %s → %s（%s）" % (p, slot, (notes.get(p) or "")[:44]))
            if draft.get("unclassified"):
                lines.append("  未命中槽：%s（LLM 也未兜底）"
                             % "、".join(draft.get("unclassified")))
            lines.append("回复「确认注册 %s」即写入引擎注册表（config.local.json engines 段）。"
                         % a.get("name"))
            return "\n".join(lines)
        # 含「确认/注册」→ 立即注册
        name = a.get("name", Path(path).stem)
        nm = re.search(r"注册\s*[:：]?\s*([^\s，。]+)", t)
        if nm:
            name = nm.group(1).strip()
        ok, err = wf_adapter.validate_register(name, kind, path, mapping)
        if not ok:
            _ev(project, session_id, task_id, "subtask", "注册引擎",
                "error", err[:200])
            return "注册校验失败：%s" % err
        eng = wf_adapter.engine_from_workflow(path, kind, name, mapping,
                                              note="对话对接（%s）" % draft.get("mode"))
        engines = wf_adapter.load_engines()
        engines = [e for e in engines if str(e.get("id")) != eng["id"]]
        engines.append(eng)
        wf_adapter.save_engines(engines)
        _ev(project, session_id, task_id, "patch", "写盘 config.local.json engines 段",
            "success", "已注册引擎 %s（id=%s，kind=%s）" % (name, eng["id"], kind))
        return ("已注册引擎：「%s」（id=%s，kind=%s，映射 %d 项）。"
                "可说「用工作流%s抽卡」开始抽卡。" % (name, eng["id"], kind,
                                                 len(mapping), name))

    # ---- ⑤ 引擎清单 / 未识别引导 ----
    engs = wf_adapter.load_engines()
    if engs:
        lines = ["已注册引擎（config engines 段）："]
        for e in engs:
            lines.append("  · %s（id=%s，kind=%s，%s）%s"
                         % (e.get("name"), e.get("id"), e.get("kind"),
                            Path(e.get("workflow") or "").name,
                            "⚠ 文件已变更" if wf_adapter.engine_changed(e) else ""))
        return "\n".join(lines)
    _ev(project, session_id, task_id, "subtask", "工作流引擎对接",
        "error", "未识别工作流操作")
    return ("支持工作流引擎操作：\n"
            "  · 扫描工作流（列出 eco.sources 内工作流能力）\n"
            "  · 对接工作流 <名称或路径> <refimg|storyframe|video>（生成映射草案）\n"
            "  · 确认注册（把草案写入引擎注册表）\n"
            "  · 用工作流<名称>抽卡（已注册引擎抽卡）\n"
            "或到 设置 → ④ 工作流区 扫描/AI 分析对接。")
