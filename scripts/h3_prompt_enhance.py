#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H3 分镜提示词 LLM 反推增强（P6c ① + P6d ①，docs/13 §3 执行计划 · T8/官方 skill 融合）。

把分镜行字段 + 资产名/描述 + 全局风格 + 用户附加描述（desc，如「画面要赛博朋克夜雨」）
反推为官方 MiniMax H3 三段式提示词（integrated_multimodal_description /
overall_soundscape / non_diegetic_music，缺一不可），供 ComfyUI H3 节点直接消费。

设计（docs/13 §3 P6a 1 + .agents/skills/htv-h3-prompt/SKILL.md）：
  - 复用 scripts/agent.py 的 resolve_provider + chat（OpenAI 兼容，仅标准库），
    与 ai_writer 同一链路（依赖最小：agent ← common，无额外依赖）
  - 系统提示词 = 内置公式（兜底）+ 已装 skill 内容（P6d ①：_load_skill_texts 按优先级
    加载 .agents/skills/h3-prompt-writing/SKILL.md + references/base-en.txt + ref-en.txt、
    .agents/skills/htv-h3-prompt/SKILL.md、.agents/skills/minimax-h3-prompt-skill-T8/（若存在），
    文件存在即拼入并标注来源文件名，缺失静默跳过；skill 优先：LLM 反推遵循 skill 官方公式）
  - 输出校验：三段齐全，缺段补 N/A；LLM 调用失败/无法识别 → 回退 render.build_h3_shot（rule 模式）

配置开关：config `h3.prompt_enhance: rule|llm`（默认 rule，config.local.json 可覆盖）。
统一入口 generate_shot_prompt() 按开关分发，返回 (prompt_text, mode)，mode ∈ llm|rule。
事件回执带 skill 信息：skill_receipt() 返回「已加载 skill：…」/「无已装 skill，使用内置公式」。
仅标准库。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common          # noqa: E402  路径/配置（load_config）
import agent           # noqa: E402  resolve_provider + chat（OpenAI 兼容）
import render          # noqa: E402  回退：build_h3_shot（rule 模式）
import gen_storyboard  # noqa: E402  parse_dur / classify_audio / fmt_time

DEFAULT_TIMEOUT = 120          # 单镜 LLM 反推超时（秒）；冒烟链路同款
DEFAULT_MODE = "rule"          # 默认开关：rule（规则组装，零成本）

SECTIONS = ("integrated_multimodal_description",
            "overall_soundscape",
            "non_diegetic_music")

SKILLS_ROOT = Path(__file__).resolve().parent.parent / ".agents" / "skills"
# 已装 skill 自动加载清单（P6d ①）：(目录名, 待加载相对路径序列)，顺序即优先级；
# references/ 等目录会展开加载其下全部 .md/.txt（minimax-h3-prompt-skill-T8 结构未知，按目录展开）。
SKILL_FILES = (
    ("h3-prompt-writing", ("SKILL.md", "references/base-en.txt", "references/ref-en.txt")),
    ("htv-h3-prompt", ("SKILL.md",)),
    ("minimax-h3-prompt-skill-T8", ("SKILL.md", "references")),
)

SYSTEM_PROMPT = """你是 H3 视频模型的资深分镜提示词工程师（官方 MiniMax H3 Prompt Guide）。
把输入的分镜行信息反推为 H3 单镜三段式提示词，用英文输出，供 ComfyUI MiniMaxH3AudioConditioningT8 节点直接消费。

必须严格输出三段，缺一不可，段首固定为以下三个锚点之一：
integrated_multimodal_description: ...
overall_soundscape: ...
non_diegetic_music: ...

## integrated_multimodal_description 结构锚点（官方公式，逐项落实为自然英文句，禁止标签堆叠）
1. 开场：`[Shot N] Live-action, cinematic, <景别> shot <画面核心>`；非首镜用 `[Shot N] At hh:mm:ss.mmm, the camera cuts to ...`（起始时刻已给出）。
2. 主体与动作：画面核心 = 主体（角色代号保持与资产一致，不得换词）+ 动作 + 场景环境（set in/at <场景>）。
3. 场景环境与光影色调：开场建立环境细节 + 光源类型/色温（lit by <光源>），并体现全局风格的色调。
4. 镜头运镜：每镜只有一个主运镜（类型+幅度+速度的自然英文句），如 "The camera pushes in with small amplitude at slow speed toward the subject."；严禁堆叠多个运镜。
5. 视觉风格：全局风格 <style> 作为风格锚点并入描述。
6. 画质约束：结尾统一加 "High quality, sharp focus, filmic grade."
7. 对白：说话者标注 (S1)，台词用 <d>[Chinese] 原文</d> 包裹，保留原文不翻译。
8. 音效：作为画面内动作声融入描述（Sound of <sfx>）。
9. 参考锁定细节：从分镜行与资产描述提取 3-5 条受保护细节（角色外观/道具/场景标志物），在描述中明确写出，保证跨镜一致性。

## overall_soundscape
1-4 句英文：环境音 + 物理动作音 + 非语言人声（呼吸/沉默）；不重复对白与 BGM；无环境音写 N/A。

## non_diegetic_music
1-3 句英文：乐器配置 / BPM / 节奏模式 / 动态（起落爆收）；与上一镜的衔接说明
（气闸缓冲：新镜开头保持上镜末构图约 2 秒 + 微小运动，再切新场景）；无 BGM 写 N/A
（分镜备注含「无BGM/静音/无配乐」时）。

## 用户附加描述（最高优先级）
用户对画面的额外要求（如「画面要赛博朋克夜雨」）必须落实进
integrated_multimodal_description 与 overall_soundscape；与分镜行冲突时以用户描述为准。

只输出三段式提示词本身，不要任何解释、标题或代码块。"""


def _shot_block(shot, shot_no, start_sec):
    """分镜行 → 用户可见字段块（容错缺失字段）。"""
    dlg, sfx = gen_storyboard.classify_audio(shot.get("dialogue") or shot.get("sfx"))
    rows = [
        ("镜号", shot_no),
        ("起始时刻", gen_storyboard.fmt_time(start_sec)),
        ("景别", shot.get("frame") or "medium"),
        ("运镜", shot.get("camera") or "static"),
        ("时长(秒)", shot.get("dur") or "5"),
        ("角色", shot.get("chars") or ""),
        ("场景", shot.get("scene") or ""),
        ("灯光", shot.get("light") or ""),
        ("对白", dlg),
        ("音效", sfx),
        ("备注", shot.get("note") or ""),
    ]
    return "\n".join("%s: %s" % (k, v) for k, v in rows if v)


def _assets_block(assets):
    """资产表 → 名称/类型/描述行（外观锚定）。"""
    lines = []
    for code, a in (assets or {}).items():
        name = a.get("name") or ""
        typ = a.get("type") or ""
        desc = a.get("desc") or a.get("description") or ""
        lines.append("%s: %s%s%s" % (
            code, name, ("（%s）" % typ) if typ else "",
            (" —— %s" % desc) if desc else ""))
    return "\n".join(lines) or "（无）"


# ============ P6d ① 已装 skill 自动加载（写剧本/分镜提示词时自动调用） ============

def load_skill_texts():
    """按优先级加载已装 skill 内容 → [(来源标签, 文本)]；文件缺失/目录不存在静默跳过。

    来源标签 = "<skill名>/<相对路径>"（如 h3-prompt-writing/references/base-en.txt），
    标注进系统提示词，LLM 反推据此遵循 skill 的官方公式与结构锚点。
    """
    out = []
    for name, rels in SKILL_FILES:
        base = SKILLS_ROOT / name
        if not base.is_dir():
            continue
        for rel in rels:
            p = base / rel
            if p.is_dir():                      # 目录 → 展开其下全部 .md/.txt
                try:
                    subs = sorted(p.iterdir())
                except OSError:
                    continue
                for f in subs:
                    if f.is_file() and f.suffix.lower() in (".md", ".txt"):
                        _append_skill_text(out, "%s/%s" % (name, f.relative_to(base)), f)
            elif p.is_file():
                _append_skill_text(out, "%s/%s" % (name, rel), p)
    return out


def _append_skill_text(out, label, path):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    if text.strip():
        out.append((label, text))


def loaded_skill_names():
    """已加载（存在至少一个待加载文件）的 skill 目录名列表（事件回执/API 响应用）。"""
    names = []
    for name, rels in SKILL_FILES:
        base = SKILLS_ROOT / name
        if not base.is_dir():
            continue
        for rel in rels:
            p = base / rel
            if p.is_file():
                try:
                    if p.stat().st_size > 0:
                        names.append(name)
                        break
                except OSError:
                    continue
            elif p.is_dir():
                try:
                    if any(f.is_file() for f in p.iterdir()):
                        names.append(name)
                        break
                except OSError:
                    continue
    return names


def skill_receipt():
    """事件回执文案：「已加载 skill：h3-prompt-writing、htv-h3-prompt」/「无已装 skill，使用内置公式」。"""
    names = loaded_skill_names()
    if names:
        return "已加载 skill：%s" % "、".join(names)
    return "无已装 skill，使用内置公式"


def build_system_prompt():
    """系统提示词 = 内置公式（SYSTEM_PROMPT 兜底）+ 已装 skill 内容（skill 优先，标注来源文件）。"""
    parts = [SYSTEM_PROMPT]
    for label, text in load_skill_texts():
        parts.append("\n\n===== 已加载 skill 文件：%s =====\n%s" % (label, text))
    return "\n".join(parts)


def build_messages(shot, shot_no, start_sec, style, assets, desc, system_prompt=None):
    """反推三段式的 [system, user] 消息（结构锚点内嵌于系统提示词）。

    system_prompt 缺省用内置公式；P6d ① enhance 传入 build_system_prompt()
    （内置公式 + 已装 skill 内容）。
    """
    user = (
        "===== 分镜行（第 %d 镜，起始时刻 %s） =====\n%s\n\n"
        "===== 资产（外观锚定，跨镜不得换词） =====\n%s\n\n"
        "===== 全局风格 =====\n%s\n\n"
        "===== 用户附加描述 =====\n%s\n\n"
        "请输出该镜的 H3 三段式提示词（英文，只输出提示词本身）。"
        % (shot_no, gen_storyboard.fmt_time(start_sec),
           _shot_block(shot, shot_no, start_sec),
           _assets_block(assets),
           style or "（未设置，按通用写实电影风）",
           desc or "（无）"))
    return [{"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            {"role": "user", "content": user}]


# ============ 输出校验与修复 ============

def split_sections(text):
    """LLM 输出 → {段名: 内容}；无法识别任何锚点 → None（触发 rule 回退）。

    容错：锚点后跟 半角冒号/全角冒号/空格；缺段不出现在结果里。
    """
    if not text or not isinstance(text, str):
        return None
    pos = {}
    for a in SECTIONS:
        p = text.find(a + ":")
        if p == -1:
            p = text.find(a + "：")
        if p != -1:
            pos[a] = p
    if not pos:
        return None
    out = {}
    ordered = sorted(pos.items(), key=lambda kv: kv[1])
    for i, (a, p) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(text)
        out[a] = text[p + len(a):end].lstrip(":： \t\n").strip()
    return out


def repair(text):
    """校验 + 修复：三段齐全直接规整；缺段补 N/A；完全无法识别 → None。

    返回规整后的三段式文本，或 None（调用方回退 rule 模式）。
    """
    parts = split_sections(text)
    if parts is None:
        return None
    for a in SECTIONS:
        if not parts.get(a):
            parts[a] = "N/A"
    return ("integrated_multimodal_description: %s\n\n"
            "overall_soundscape: %s\n\n"
            "non_diegetic_music: %s"
            % (parts[SECTIONS[0]], parts[SECTIONS[1]], parts[SECTIONS[2]]))


# ============ 主入口 ============

def enhance(shot, shot_no, start_sec, style, assets, desc, cfg=None, timeout=DEFAULT_TIMEOUT):
    """LLM 反推三段式（含校验/修复）；失败回退 rule 模式。

    P6d ①：系统提示词 = 内置公式 + 已装 skill 内容（build_system_prompt），
    LLM 反推遵循 skill 的官方公式与结构锚点。
    返回 (prompt_text, mode)，mode ∈ llm|rule。
    """
    cfg = cfg or common.load_config()
    try:
        prov = agent.resolve_provider(cfg)
        text = agent.chat(prov["base"], prov["model"], prov["api_key"],
                          build_messages(shot, shot_no, start_sec, style, assets, desc,
                                         system_prompt=build_system_prompt()),
                          temperature=0.7, timeout=timeout)
    except Exception:
        return _rule_prompt(shot, shot_no, start_sec, style, assets), "rule"
    fixed = repair(text)
    if fixed is None:
        return _rule_prompt(shot, shot_no, start_sec, style, assets), "rule"
    return fixed, "llm"


def generate_shot_prompt(shot, shot_no, start_sec, style, assets, desc, cfg=None,
                         timeout=DEFAULT_TIMEOUT):
    """统一入口：按 config `h3.prompt_enhance` 分发（rule|llm）。

    返回 (prompt_text, mode)，mode ∈ llm|rule —— 调用方据此写回执（「LLM 反推」/「规则组装」）。
    """
    cfg = cfg or common.load_config()
    mode = str(cfg.get_path("h3.prompt_enhance", DEFAULT_MODE) or DEFAULT_MODE).strip().lower()
    if mode == "llm":
        return enhance(shot, shot_no, start_sec, style, assets, desc, cfg, timeout)
    return _rule_prompt(shot, shot_no, start_sec, style, assets), "rule"


def _rule_prompt(shot, shot_no, start_sec, style, assets):
    """rule 模式：委托 render.build_h3_shot（官方三段式规则组装，零 LLM 成本）。"""
    return render.build_h3_shot(shot, shot_no, start_sec, style, assets=assets)


if __name__ == "__main__":
    # 自测：python scripts/h3_prompt_enhance.py <shot_no> "<用户描述>"
    import argparse
    ap = argparse.ArgumentParser(description="H3 提示词 LLM 反推自测")
    ap.add_argument("--shot-no", type=int, default=1)
    ap.add_argument("--desc", default="", help="用户附加描述，如 画面要赛博朋克夜雨")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    a = ap.parse_args()
    cfg = common.load_config()
    shot = {"shot": str(a.shot_no), "frame": "medium", "camera": "push in",
            "dur": "5", "chars": "C01", "scene": "S01", "light": "rainy neon",
            "dialogue": "对白：你终于回来了", "note": ""}
    text, mode = generate_shot_prompt(shot, a.shot_no, 0,
                                      cfg.get_path("project.style_prefix", ""),
                                      {}, a.desc, cfg, a.timeout)
    print("== mode: %s ==" % mode)
    print(text)
