#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 编剧（对齐 Toonflow 结构化流程）：事件图谱 → 故事骨架(分集决策) → 逐集剧本 → 资产提取。

分层产物（项目 output/<项目>/ 下）：
  小说.md        原始素材
  小说事件.md    章节事件图谱（事件列表）
  故事骨架.md    故事核/人物小传(大三角≤4)/三幕结构/分集决策表 ← "分段"的真相
  剧本.md        逐集结构化剧本（每集：场景核心/集末钩子/镜头序列）
  资产清单.md    从剧本提取的角色/场景/道具（→ 资产库登记）

双模式：LLM（配置 llm_base 一键生成）/ Agent 指令（无 LLM 时输出指令给 Reasonix/Codex/Claude）。
"""
import json
import sys
import urllib.request
from pathlib import Path

import common         # 路径约定（episode_dir 等）
from common import ConfigError, load_config, project_dir
import agent          # 生成 Agent 内核（spec 03）：本文件的 LLM 层为其薄兼容层
import gen_storyboard  # LLM 分镜表解析（本轮整改）

NOVEL_FILE = "小说.md"
EVENTS_FILE = "小说事件.md"
SKELETON_FILE = "故事骨架.md"
SCRIPT_FILE = "剧本.md"
ASSETS_FILE = "资产清单.md"


def _llm(cfg):
    """兼容读取：优先 agent 模块（llm.provider 预设），缺失时回退旧键 comfyui.llm_base。"""
    try:
        prov = agent.resolve_provider(cfg)
        return prov["base"], prov["model"], prov["api_key"]
    except ConfigError:
        base = (cfg.get_path("comfyui.llm_base", "")
                or "http://127.0.0.1:11434").rstrip("/")
        return base, cfg.get_path("comfyui.llm_model", ""), ""


def llm_available(cfg):
    try:
        base, model, key = _llm(cfg)
    except ConfigError:
        return False, ""
    headers = {"Authorization": "Bearer " + key} if key else {}
    # OpenAI 兼容：/models；Ollama：/api/tags
    for path in ("/models", "/api/tags"):
        try:
            req = urllib.request.Request(base + path, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
            if path == "/models" and data.get("data"):
                return True, base
            if path == "/api/tags" and data.get("models"):
                return True, base
        except Exception:
            continue
    return False, base


def pick_model(cfg, base):
    _, model, key = _llm(cfg)
    if model:
        return model
    headers = {"Authorization": "Bearer " + key} if key else {}
    for path in ("/models", "/api/tags"):
        try:
            req = urllib.request.Request(base + path, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
            if path == "/models":
                ids = [m.get("id") for m in data.get("data", [])]
            else:
                ids = [m.get("name") for m in data.get("models", [])]
            return ids[0] if ids else ""
        except Exception:
            continue
    return ""


def call_llm(base, model, prompt, timeout=600):
    """兼容入口：委托 agent.chat（带系统提示词，本轮整改）。"""
    _, _, key = _llm(load_config())
    return agent.chat(base, model, key,
                      [{"role": "system", "content": agent.SYSTEM_PROMPT},
                       {"role": "user", "content": prompt}], timeout=timeout)


# ============ 各层提示词 ============

def _brief_block(brief):
    return ("【创作简报（一致性/风格锚点，必须遵守）】\n%s\n\n" % brief) if brief else ""


def events_prompt(novel_text, title, brief=""):
    """① 事件图谱：小说 → 事件列表。"""
    return _brief_block(brief) + (
        "你是影视改编分析师。请把下面的小说/素材分解为 5-12 个关键事件，"
        "每个事件按下面的格式输出（Markdown）：\n\n"
        "## 事件 N｜时间：<叙事时间>｜地点：<地点>｜人物：<出场人物>\n"
        "<事件描述：发生了什么、人物动机、冲突点/转折>\n\n"
        "要求：\n"
        "1. 事件按叙事顺序排列，覆盖完整故事弧（开端→发展→高潮→结局）；\n"
        "2. 每个事件标注时间/地点/人物/冲突点；\n"
        "3. 只输出事件图谱正文，不要解释。\n\n"
        "===== 小说/素材 =====\n%s"
    ) % novel_text[:6000]


def skeleton_prompt(events_text, title, brief=""):
    """② 故事骨架：事件 → 故事核/人物小传(大三角≤4)/三幕/分集决策表。"""
    return _brief_block(brief) + (
        "你是短剧故事骨架搭建 Agent（对齐行业方法论）。请基于事件图谱产出故事骨架，"
        "严格按以下结构输出 Markdown：\n\n"
        "## 故事核（一句话）\n"
        "<一句话核心吸引力，≤50字>\n\n"
        "## 人物小传（大三角核心角色，≤4人）\n"
        "### 主角｜<姓名>\n"
        "- 身份/特征/境遇/行动/结局：<五要素一句话>\n"
        "- 金手指与边界：<能做什么｜绝不能做什么>\n"
        "- 说话风格/出场：<句式+口头禅>｜<有记忆点的出场>\n"
        "### 反一号｜<姓名>\n"
        "- 五要素 + 合理动机（非工具人）\n"
        "### 关键配角（1-2人，表格一行）\n"
        "| 姓名 | 功能 | 与主角关系 | 说话风格 |\n\n"
        "## 三幕结构\n"
        "### 第一幕：起（建立）\n### 第二幕：承（冲突升温）\n### 第三幕：转+合（高潮/收束+钩子）\n"
        "每幕一行说明：功能/核心问题/幕末转折。\n\n"
        "## 分集决策表（分段 = 分集，一行一集，行数=总集数）\n"
        "| 集 | 集标题 | 戏剧功能 | 场景核心 | 集末钩子 | 付费点 |\n"
        "|----|--------|----------|----------|----------|--------|\n"
        "| 1 | ... | 建立/引入 | <这集给观众什么体验> | <最后5-10秒钩子> | 无 |\n"
        "| 2 | ... | 发展 | ... | ... | 无 |\n"
        "...（每集一行，集末钩子必须有）\n\n"
        "约束：总集数 = 项目配置（未给则 6 集）；每集必须有集末钩子；"
        "人物小传只写大三角核心角色。\n\n"
        "===== 事件图谱 =====\n%s"
    ) % (events_text[:6000])


def script_prompt(skeleton_text, novel_text, title, brief=""):
    """③ 逐集剧本：骨架分集决策表 → 逐集结构化剧本。"""
    return _brief_block(brief) + (
        "你是短剧编剧 Agent。请严格按分集决策表逐集生成结构化剧本，"
        "每集输出：\n\n"
        "## 集 {N}｜{集标题}\n"
        "**场景核心：** <这集的核心体验>\n"
        "**集末钩子：** <与决策表一致>\n"
        "**镜头序列：**\n"
        "- 镜1｜场景<场景代号如S01>｜景别<wide/medium/close-up>｜运镜<static/push in等>｜角色<C01等>｜<画面动作>｜<对白或音效>\n"
        "- 镜2｜...\n"
        "（每集 3-8 镜；单镜 3-6 秒；镜头连续有逻辑）\n\n"
        "要求：\n"
        "1. 严格按分集决策表的集数与钩子；\n"
        "2. 人物言行符合骨架人物小传；\n"
        "3. 场景/角色/道具用代号（S01/C01/P01），后续统一登记资产；\n"
        "4. 只输出剧本正文。\n\n"
        "===== 分集决策表/骨架 =====\n%s\n\n"
        "===== 原素材（参考） =====\n%s"
    ) % (skeleton_text[:6000], novel_text[:3000])


def assets_prompt(script_text, title, brief=""):
    """④ 资产提取：剧本 → 角色/场景/道具清单。"""
    return _brief_block(brief) + (
        "你是影视资产分析师。请从剧本中提取所有资产（角色/场景/道具），输出 Markdown 表格：\n\n"
        "| 类型 | 代号 | 名称 | 描述（用于生成参考图/一致性） |\n"
        "|------|------|------|------------------------------|\n"
        "| 角色 | C01 | <名> | <外貌/服饰/性格/标志物> |\n"
        "| 场景 | S01 | <名> | <环境/氛围/光线> |\n"
        "| 道具 | P01 | <名> | <外观/作用> |\n\n"
        "要求：\n"
        "1. 代号与剧本镜头序列中的一致（C/S/P + 两位数字）；\n"
        "2. 描述具体到可直接生成参考图；\n"
        "3. 只输出资产表格。\n\n"
        "===== 剧本 =====\n%s"
    ) % script_text[:8000]


def brief_from_idea_prompt(idea, title=""):
    """从零编剧 ①：想法 → 创作简报（一致性/风格锚点，与链式生成共用）。"""
    t = "（作品暂定名《%s》）" % title if title else ""
    return (
        "你是本地化 HTV 短剧创作总监。用户只有一句创作想法，还没有任何素材，"
        "请把想法打磨成可执行的《创作简报》Markdown%s，作为后续 小说/剧本/分镜/资产 "
        "链式生成的唯一上下文锚点。\n\n"
        "## 创作简报\n"
        "### 一句话故事核\n<≤50字，核心吸引力>\n"
        "### 题材与卖点\n### 目标观众\n### 整体风格（视觉与音乐）\n"
        "### 时长与分集（单集时长、总集数，默认单集 1-2 分钟、共 6 集）\n"
        "### 主要角色（名称/身份/外貌锚定/性格/冲突）\n### 关键场景\n"
        "### 对白语言风格\n### 一致性锚点（外观词汇固定，生成时不得换词）\n"
        "### 约束与红线\n\n"
        "要求：想法中未提及的项合理补全（不要写「待定」）；只输出简报正文，不要解释。\n\n"
        "===== 创作想法 =====\n%s"
    ) % (t, idea[:2000])


def novel_from_idea_prompt(idea, brief, title=""):
    """从零编剧 ②：想法+简报 → 3000-6000 字短剧小说素材（支撑链式编剧）。"""
    return _brief_block(brief) + (
        "你是短剧小说素材写手。请基于创作想法与创作简报，写出一篇 3000-6000 字的"
        "短剧小说素材（不是完整剧本，是供改编的事件素材），要求：\n"
        "1. 覆盖完整故事弧：开端→发展→高潮→结局，节奏紧凑，适合短剧快节奏；\n"
        "2. 人物清晰：主角/反一号/关键配角（含外貌锚定与动机）；\n"
        "3. 场景 3-5 个，能映射为 S01/S02… 代号；\n"
        "4. 冲突与反转明确，结尾留强钩子（追下集）；\n"
        "5. 人物/场景/道具出现时标注代号（C01/S01/P01），供后续资产登记；\n"
        "6. 只输出小说正文（Markdown），不要解释。\n\n"
        "===== 创作想法 =====\n%s"
    ) % (idea[:2000])


# ============ 文件读写 ============

BRIEF_FILE = "创作简报.md"


def read_brief(project):
    """读取创作简报（AI 访谈产物，链式生成的一致性/风格锚点）。"""
    return _read(project, BRIEF_FILE)


def write_brief(project, text):
    """写入创作简报。"""
    return _write(project, BRIEF_FILE, text)


def _read(project, fname):
    root = project_dir(project)
    p = root / fname
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _write(project, fname, text):
    root = project_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    dest = root / fname
    # P5.1：链式写入前快照（守卫式导入——doc_versions 顶部 import ai_writer，
    # 函数内导入避免循环；快照失败静默不阻塞写盘）
    try:
        import doc_versions as _dv
        _doc = _DOC_OF_FILE.get(str(fname).split("/")[-1])
        if _doc:
            _dv.snapshot(project, _doc, source="ai_writer",
                         note="AI 链式写入 %s" % fname)
    except Exception:
        pass
    dest.write_text(text, encoding="utf-8")
    return dest


def read_novel(project): return _read(project, NOVEL_FILE)
def read_events(project): return _read(project, EVENTS_FILE)
def read_skeleton(project): return _read(project, SKELETON_FILE)
def read_script(project): return _read(project, SCRIPT_FILE)
def read_assets(project): return _read(project, ASSETS_FILE)

# P5.1：文件名 → 文档版本 doc key（链式写入快照用；分镜走 workflow_patch/PUT 已有快照，不在此列）
_DOC_OF_FILE = {
    "小说.md": "novel",
    "创作简报.md": "brief",
    "小说事件.md": "script",
    "故事骨架.md": "script",
    "剧本.md": "script",
    "资产清单.md": "assets",
}

def write_novel(project, text): return _write(project, NOVEL_FILE, text)
def write_events(project, text): return _write(project, EVENTS_FILE, text)
def write_skeleton(project, text): return _write(project, SKELETON_FILE, text)
def write_script(project, text): return _write(project, SCRIPT_FILE, text)
def write_assets(project, text): return _write(project, ASSETS_FILE, text)


# ============ Agent 指令（无 LLM 主路径） ============

def _agent_wrap(title, project, prompt, out_file, next_hint):
    return (
        "【任务 · 项目 %s】\n"
        "你是本项目 %s 的%s。请执行下方提示词产出内容：\n\n"
        "1. 执行提示词，产出完整结果；\n"
        "2. 写入项目目录的 %s（UTF-8 Markdown）；\n"
        "3. 产出后告知用户：产物是草稿，可审改；%s\n\n"
        "===== 提示词 =====\n%s\n\n"
        "===== 交付 =====\n写入文件：output/%s/%s"
    ) % (project, project, title, out_file, next_hint, prompt, project, out_file)


def agent_events_instruction(project):
    return _agent_wrap("改编分析师 Agent（事件图谱）", project, events_prompt(read_novel(project), project),
                       EVENTS_FILE, "随后可继续生成故事骨架（分集决策）。")


def agent_skeleton_instruction(project):
    events = read_events(project)
    if not events:
        return "【先提取事件图谱】请先执行 提取事件 步骤（写入 小说事件.md），再生成故事骨架。"
    return _agent_wrap("故事骨架 Agent（分集决策）", project, skeleton_prompt(events, project),
                       SKELETON_FILE, "骨架含分集决策表（分段），随后可继续生成逐集剧本。")


def agent_script_instruction(project):
    skeleton = read_skeleton(project)
    if not skeleton:
        return "【先生成故事骨架】请先执行 故事骨架 步骤（写入 故事骨架.md），再生成剧本。"
    return _agent_wrap("编剧 Agent（逐集剧本）", project,
                       script_prompt(skeleton, read_novel(project), project),
                       SCRIPT_FILE, "剧本按集生成，随后可提取资产并生成分镜。")


def agent_assets_instruction(project):
    script = read_script(project)
    if not script:
        return "【先生成剧本】请先执行 剧本 步骤（写入 剧本.md），再提取资产。"
    return _agent_wrap("资产分析师 Agent", project, assets_prompt(script, project),
                       ASSETS_FILE, "资产清单将用于登记资产库（角色/场景/道具）。")


# ============ 链式编剧（事件→骨架→剧本→资产） ============

_STEP_LABELS = {"events": "事件图谱", "skeleton": "故事骨架",
                "script": "剧本", "assets": "资产清单"}


def chain(project, title="", on_step=None):
    """一键链式编剧：事件→骨架→剧本→资产。返回 (mode, results)。

    mode = 'llm'：本地 LLM 依次生成并写入文件，results = 已生成的模式列表；
    mode = 'agent'：无 LLM，返回合并的 Agent 指令（results 为空）。

    on_step(label, summary)：可选进度回调（P3.5），每完成一步（事件图谱/故事骨架/
    剧本/资产清单）调用一次，label 见 _STEP_LABELS；默认 None 不破坏现有调用方。
    """
    cfg = load_config()
    ok, base = llm_available(cfg)
    title = title or project
    brief = read_brief(project)
    order = [
        ("events", lambda: events_prompt(read_novel(project), title, brief), write_events,
         lambda: agent_events_instruction(project)),
        ("skeleton", lambda: skeleton_prompt(read_events(project), title, brief), write_skeleton,
         lambda: agent_skeleton_instruction(project)),
        ("script", lambda: script_prompt(read_skeleton(project), read_novel(project), title, brief),
         write_script, lambda: agent_script_instruction(project)),
        ("assets", lambda: assets_prompt(read_script(project), title, brief), write_assets,
         lambda: agent_assets_instruction(project)),
    ]
    if not ok:
        parts = []
        for _mode, prompt_fn, _writer, agent_fn in order:
            parts.append(agent_fn())
        return "agent", parts
    model = pick_model(cfg, base)
    done = []
    for mode, prompt_fn, writer, _agent in order:
        prompt = prompt_fn()
        if not prompt or prompt.startswith("【先"):
            continue
        text = call_llm(base, model, prompt)
        writer(project, text)
        done.append(mode)
        if on_step:
            try:
                on_step(_STEP_LABELS.get(mode, mode), "已生成 %s" % mode)
            except Exception:
                pass
    return "llm", done


# ============ 从零编剧（无小说：想法 → 创作简报 → 小说素材） ============

def brief_from_idea(project, idea, title="", on_step=None):
    """从零编剧 ①：想法 → 创作简报.md（已有简报则跳过，视为成功）。返回是否成功。

    走现有 llm_available / pick_model / call_llm（config llm.provider 实测可用）；
    无 LLM 或 LLM 未产出内容返回 False（调用方决定错误提示/委派）。
    """
    if read_brief(project):
        return True
    cfg = load_config()
    ok, base = llm_available(cfg)
    if not ok:
        return False
    model = pick_model(cfg, base)
    text = call_llm(base, model, brief_from_idea_prompt(idea, title or project))
    text = (text or "").strip()
    if not text:
        return False
    write_brief(project, text)
    if on_step:
        try:
            on_step("brief", "已生成 创作简报.md")
        except Exception:
            pass
    return True


def novel_from_idea(project, idea, title="", brief="", on_step=None):
    """从零编剧 ②：想法+简报 → 小说.md（3000-6000 字素材，支撑链式编剧）。返回是否成功。

    已有 小说.md 则跳过（视为成功）；无 LLM 或 LLM 未产出内容返回 False。
    """
    if read_novel(project):
        return True
    cfg = load_config()
    ok, base = llm_available(cfg)
    if not ok:
        return False
    model = pick_model(cfg, base)
    text = call_llm(base, model, novel_from_idea_prompt(idea, brief, title or project))
    text = (text or "").strip()
    if not text:
        return False
    write_novel(project, text)
    if on_step:
        try:
            on_step("novel", "已生成 小说.md")
        except Exception:
            pass
    return True


def storyboard_from_script(project, episode=1):
    """解析 剧本.md 的镜头序列 → 分镜.md（E<episode>/分镜.md）。

    剧本每集格式：
      ## 集 N｜集标题
      **镜头序列：**
      - 镜1｜场景S01｜景别wide｜运镜push in｜角色C01｜动作｜对白
    映射到分镜列：镜号/景别/运镜/时长/角色/场景/灯光/对白/备注。
    无镜头序列的集 → 生成 1 行默认分镜。
    """
    import re as _re
    from pathlib import Path
    from common import episode_dir
    script = read_script(project)
    if not script:
        return None
    rows = []
    cur_ep = None
    for line in script.splitlines():
        line = line.strip()
        m = _re.match(r"^##\s*集\s*(\d+)", line)
        if m:
            cur_ep = int(m.group(1))
            continue
        if cur_ep != episode:   # 只提取当前集的镜头，不跨集串号
            continue
        if line.startswith("- 镜"):
            # 镜1｜场景S01｜景别wide｜运镜push in｜角色C01｜动作｜对白
            parts = [x.strip() for x in line.lstrip("- ").split("｜")]
            if len(parts) >= 3:
                # 字段名映射（允许 "镜1" "场景S01" 等键值前缀）
                def grab(prefix, default=""):
                    for x in parts[1:]:
                        if x.startswith(prefix):
                            return x[len(prefix):].strip()
                    return default
                scene = grab("场景") or grab("S0") or ""
                frame = grab("景别") or "medium"
                camera = grab("运镜") or "static"
                chars = grab("角色") or grab("C0") or ""
                dialog = grab("对白") or grab("音效") or ""
                note = grab("备注") or ""
                # 无前缀字段按位置回退（剧本常见裸写）：
                # 镜号｜场景｜景别｜运镜｜角色｜动作｜对白
                if not frame and len(parts) >= 3:
                    frame = parts[1] or "medium"
                if not camera and len(parts) >= 4:
                    camera = parts[2] or "static"
                if not note and len(parts) >= 6:
                    note = parts[5]
                if not dialog and len(parts) >= 7:
                    dialog = parts[6]
                rows.append({"shot": str(len(rows) + 1), "frame": frame,
                             "camera": camera, "dur": "5", "chars": chars,
                             "scene": scene or "S01", "light": "",
                             "dialogue": dialog, "note": note})
    if not rows:
        rows = [{"shot": "1", "frame": "medium", "camera": "static", "dur": "5",
                 "chars": "", "scene": "S01", "light": "", "dialogue": "", "note": "来自剧本"}]
    e_dir = episode_dir(project, episode)
    e_dir.mkdir(parents=True, exist_ok=True)
    header = ["# E%02d 分镜（%s）" % (episode, project),
              "> 由剧本镜头序列生成，可手动调整"]
    dest = e_dir / "分镜.md"
    dest.write_text(_md(rows, header), encoding="utf-8")
    return dest


def _md(rows, header):
    head = "\n".join(header) + "\n"
    cols = [("shot", "镜号"), ("frame", "景别"), ("camera", "机位运动"),
            ("dur", "时长"), ("chars", "角色"), ("scene", "场景"),
            ("light", "灯光"), ("dialogue", "对白/音效"), ("note", "备注")]
    lines = [head, "| " + " | ".join(c[1] for c in cols) + " |",
             "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(k, "") or "").strip() for k, _ in cols) + " |")
    return "\n".join(lines) + "\n"


def renumber_storyboard_rows(rows):
    """按位置重编镜号（LLM 输出的镜号顺序不可信）。"""
    out = []
    for i, r in enumerate(rows, 1):
        row = dict(r)
        row["shot"] = str(i)
        out.append(row)
    return out


def llm_storyboard(name, episode=1, chat_fn=None, cfg=None):
    """剧本 → 分镜（LLM 版，本轮整改）：agent.generate(storyboard_from_script) →
    解析 Markdown 表格 → 按位置重编号 → 写入 分镜.md。

    无剧本或任一步失败返回 None（调用方回退解析器版）。
    """
    cfg = cfg or load_config()
    script_text = read_script(name)
    if not script_text:
        return None
    style = cfg.get_path("project.style_prefix", "") or ""
    try:
        text = agent.generate("storyboard_from_script",
                              {"script_text": script_text, "style": style},
                              cfg=cfg, chat_fn=chat_fn)
        rows = gen_storyboard.parse_markdown_table(text or "")
        rows = renumber_storyboard_rows(rows)
    except Exception:
        return None
    e_dir = common.episode_dir(name, episode)
    header = ["# E%02d 分镜（%s）" % (episode, name),
              "> 由 AI（LLM）按剧本生成，可手动调整"]
    dest = e_dir / "分镜.md"
    dest.write_text(_md(rows, header), encoding="utf-8")
    return dest


# ============ 主流程 ============

def main():
    cfg = load_config()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "help":
        print("用法: python ai_writer.py events|skeleton|script|assets <项目>  (无 LLM 输出 Agent 指令)")
        return
    if cmd == "check":
        ok, base = llm_available(cfg)
        model = pick_model(cfg, base) if ok else ""
        print("LLM 可用: %s" % ("是（%s / %s）" % (base, model) if ok else "否（%s 不可达）" % base))
        return
    if len(sys.argv) < 3:
        print("缺项目名"); return
    project = sys.argv[2]
    steps = {
        "events": (events_prompt(read_novel(project), project), EVENTS_FILE, write_events),
        "skeleton": (skeleton_prompt(read_events(project), project), SKELETON_FILE, write_skeleton),
        "script": (script_prompt(read_skeleton(project), read_novel(project), project), SCRIPT_FILE, write_script),
        "assets": (assets_prompt(read_script(project), project), ASSETS_FILE, write_assets),
    }
    if cmd not in steps:
        print("未知命令"); return
    prompt, out_file, writer = steps[cmd]
    if not prompt or prompt.startswith("【先"):
        print(prompt or "缺前置产物"); return
    ok, base = llm_available(cfg)
    if not ok:
        # 无 LLM → 输出 Agent 指令
        inst = {"events": agent_events_instruction, "skeleton": agent_skeleton_instruction,
                "script": agent_script_instruction, "assets": agent_assets_instruction}[cmd](project)
        print(inst)
        return
    model = pick_model(cfg, base)
    print("[LLM] %s / %s 生成中…" % (base, model))
    text = call_llm(base, model, prompt)
    dest = writer(project, text)
    print("[完成] %s 已写入 %s" % (out_file, dest))


if __name__ == "__main__":
    main()
