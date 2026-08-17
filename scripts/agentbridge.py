#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部 harness agent 适配器（spec: docs/specs/08-agent-adapter.md，对齐 LongHorizon-Harness）。

宿主 = 本产品（Manager 主循环 + 状态存储 + Auditor 校验 + 交互接口）；
执行 = 外部 agent（kimi / codex / claude / dsh），经轻量 AgentAdapter 接入。

状态目录：output/<项目>/agent/tasks/<task_id>/
  goal.md / prompt.txt / transcript.jsonl / result.json / evidence.md
"""
import json
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import ai_writer
import common
import gen_storyboard
import refs


# ============ 事实源 rev（展示层自动刷新信号，spec 09 v2） ============

_FACTS_PATTERNS = (
    "小说.md", "小说事件.md", "故事骨架.md", "剧本.md", "资产清单.md", "创作简报.md",
    "E{ep}/分镜.md", "E{ep}/refs/*.prompt.md", "E{ep}/refs/*.png",
    "E{ep}/shots/*.mp4", "E{ep}/shots/.candidates/*.mp4", "E{ep}/成片.mp4",
)


def facts_rev(project, episode=1):
    """事实源文件（剧本四块+简报+分镜+refs+shots+成片）mtime 摘要 → 短哈希。

    任何事实源变化（外部 agent 改文件 / /api/patch / 访谈简报 / 抽卡产物）都改变 rev，
    前端轮询到变化即全量刷新展示层。
    """
    root = common.project_dir(project)
    entries = []
    ep_s = "%02d" % int(episode)
    for pat in _FACTS_PATTERNS:
        for f in sorted(root.glob(pat.replace("{ep}", ep_s))):
            if f.is_file():
                entries.append("%s:%d:%d" % (f.name, f.stat().st_mtime_ns, f.stat().st_size))
    # 资产库（跨项目共享，影响资产条）
    for folder in ("characters", "scenes", "props", "refs", "bible", ".registry"):
        d = common.ASSETS / folder
        if d.exists():
            for f in sorted(d.iterdir()):
                if f.is_file():
                    entries.append("A:%s:%d" % (f.name, f.stat().st_mtime_ns))
    return str(abs(hash("\n".join(entries))) % 10 ** 12)


# ============ 项目文档摘要（外部 harness 默认上下文，工作区=项目目录） ============

def build_project_summary(project, episode=1, max_chars=4000):
    """项目文档摘要：简报 + 剧本（截断）+ 分镜表（截断）+ 资产数。

    作为外部 harness 任务的默认上下文；外部 agent 工作区即项目目录。
    """
    parts = ["# 项目 %s 文档摘要（工作区 = 本目录，可直接读写下列文件）" % project]
    brief = ai_writer.read_brief(project)
    if brief:
        parts.append("\n## 创作简报\n%s" % brief[:1200])
    script = ai_writer.read_script(project)
    if script:
        parts.append("\n## 剧本.md（前 %d 字）\n%s" % (min(1200, max_chars), script[:1200]))
    sb = common.episode_dir(project, episode) / "分镜.md"
    if sb.exists():
        try:
            rows = gen_storyboard.load_storyboard(sb)
            parts.append("\n## E%02d/分镜.md（%d 镜，前 %d 行）\n%s"
                         % (episode, len(rows), min(30, len(rows)),
                            "\n".join(sb.read_text(encoding="utf-8").splitlines()[:32])))
        except Exception:
            parts.append("\n## E%02d/分镜.md（解析失败，原样前 20 行）\n%s"
                         % (episode, "\n".join(
                             sb.read_text(encoding="utf-8", errors="ignore")
                             .splitlines()[:20])))
    else:
        parts.append("\n## E%02d/分镜.md（0 镜，未生成——可由剧本生成分镜）" % episode)
    try:
        assets = common.asset_table()
        parts.append("\n## 资产（%d 项）\n%s" % (
            len(assets),
            ", ".join("%s %s" % (a["code"], a["name"]) for a in assets[:30])))
    except Exception:
        pass
    parts.append(_kanban_section(project, episode))
    return "\n".join(parts)


def _kanban_section(project, episode=1):
    """制作看板状态（P4a ③）：轻量文件探测，供外部 agent 快速判断推进哪一步。

    只做文件存在性/行数/计数，不做网络探测（ComfyUI 可用性 = config 有 base_url）。
    """
    root = common.project_dir(project)
    ep_s = "E%02d" % int(episode)
    e_dir = root / ep_s

    def mark(p):
        return "✅" if p.exists() else "⬜"

    def size(p):
        try:
            return len(p.read_text(encoding="utf-8").strip())
        except Exception:
            return 0

    lines = ["\n## 制作看板状态"]
    rows = [
        ("创作简报.md", root / ai_writer.BRIEF_FILE),
        ("小说.md", root / ai_writer.NOVEL_FILE),
        ("剧本.md", root / ai_writer.SCRIPT_FILE),
        ("资产清单.md", root / ai_writer.ASSETS_FILE),
        ("%s/分镜.md" % ep_s, e_dir / "分镜.md"),
        ("%s/成片.mp4" % ep_s, e_dir / "成片.mp4"),
    ]
    for label, p in rows:
        n = " %d 字" % size(p) if p.exists() else ""
        lines.append("- %s %s%s" % (mark(p), label, n))
    # 分镜行数（load_storyboard 或行数统计，try/except 容错）
    sb = e_dir / "分镜.md"
    n_shots = 0
    if sb.exists():
        try:
            n_shots = len(gen_storyboard.load_storyboard(sb))
        except Exception:
            try:
                n_shots = sum(1 for ln in sb.read_text(encoding="utf-8",
                                                       errors="ignore").splitlines()
                              if ln.strip().startswith("|") and "镜号" not in ln)
            except Exception:
                n_shots = 0
    lines.append("- 分镜镜数：%d 镜" % n_shots)
    # 已选片数量（shots/*.mp4 顶层计数，候选在 .candidates/ 不计）
    picked = 0
    shots_dir = e_dir / "shots"
    if shots_dir.exists():
        try:
            picked = len([f for f in shots_dir.glob("*.mp4") if f.is_file()])
        except Exception:
            picked = 0
    lines.append("- %s/shots/ 已选片：%d 个（候选在 .candidates/）" % (ep_s, picked))
    # ComfyUI 可用性（配置存在即可，不做网络探测，避免慢）
    try:
        base = common.load_config().get_path("comfyui.base_url", "")
        lines.append("- ComfyUI：%s%s" % (base or "未配置", "（配置存在，未探测）" if base else ""))
    except Exception:
        lines.append("- ComfyUI：未知")
    return "\n".join(lines)


# ============ 流程推进模板（对话窗快捷卡，spec 10） ============

FLOW_TEMPLATES = [
    {"key": "onboard", "label": "访谈出简报", "mode": "builtin",
     "hint": "剧本侧板 AI 访谈：一句话想法 → 追问 → 创作简报"},
    {"key": "aiwrite", "label": "一键 AI 编剧", "mode": "job", "endpoint": "ai-write-all",
     "goal": "小说 → 事件 → 骨架 → 剧本 → 资产（含创作简报上下文）"},
    {"key": "storyboard", "label": "AI 拆分镜", "mode": "job", "endpoint": "storyboard-gen",
     "goal": "剧本 → 分镜表（LLM 优先，回退解析器）"},
    {"key": "shotref", "label": "生成全镜参考图提示词", "mode": "builtin",
     "goal": "逐镜 POST /api/shot-ref 生成参考图提示词（LLM）"},
    {"key": "draw", "label": "批量抽卡", "mode": "job", "endpoint": "render",
     "goal": "全镜抽卡（每镜 1-2 候选，快速档；ComfyUI 需在线）"},
    {"key": "compose", "label": "拼接成片", "mode": "job", "endpoint": "compose",
     "goal": "已选片按镜号拼接成片"},
    {"key": "polish", "label": "委派精修（外部 agent）", "mode": "external",
     "goal": "审查项目文档（剧本/分镜/参考图提示词）并直接编辑改进；"
             "可运行 python ../scripts/cli.py 查询或推进；完成后总结改动。工作区=项目目录。"},
]


def flow_templates():
    return [dict(t) for t in FLOW_TEMPLATES]


# ============ LHH 自动 Loop（Manager→Executor→Auditor，spec 10 核心补缺） ============

def _decide_next(project, goal, state, cfg=None):
    """Manager 决策：用内置 LLM（不依赖外部 agent）从目标+已验证状态生成下一步任务。

    返回单步任务文本；无法继续/已完成时返回「完成」。
    """
    cfg = cfg or common.load_config()
    summary = build_project_summary(project, 1)
    done = "、".join("第%d轮" % r for r in state.get("verified") or []) or "无"
    prompt = (
        "你是短剧流水线的 Manager。目标：%s\n\n"
        "已完成并通过验证的轮次：%s\n失败证据：%s\n\n"
        "项目现状：\n%s\n\n"
        "请决定下一步做什么（边界明确的一个小任务，可由外部 agent 或本地执行），"
        "或输出「完成」如果目标已达成/无法推进。只输出任务描述或「完成」。"
        % (goal[:500], done, "、".join(str(e.get("round")) for e in state.get("evidence") or []) or "无",
           summary[:1500]))
    try:
        prov = _resolve_provider(cfg)
        reply = _chat_internal(prov, prompt)
    except Exception:
        reply = "完成"
    return (reply or "").strip() or "完成"


def _resolve_provider(cfg):
    base = cfg.get_path("llm.base", "") or ""
    model = cfg.get_path("llm.model", "") or ""
    key = cfg.get_path("llm.api_key", "") or ""
    if not base or not model:
        raise ValueError("llm 未配置")
    return {"base": base, "model": model, "key": key}


def _chat_internal(prov, prompt):
    import urllib.request
    body = json.dumps({"model": prov["model"],
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.4, "max_tokens": 1024}).encode("utf-8")
    req = urllib.request.Request(prov["base"].rstrip("/") + "/v1/chat/completions",
                                 data=body,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": "Bearer " + prov["key"]}
                                             if prov["key"] else {})})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (data["choices"][0]["message"].get("content") or "").strip()


def _default_verify(project, episode=1, rev_before=None):
    """Auditor 默认校验：本轮执行后事实源 rev 有变化 = 有产出。"""
    rev_now = facts_rev(project, episode)
    if rev_before is None:
        return True, rev_now
    return rev_now != rev_before, rev_now


def run_loop(project, goal, adapter=None, max_rounds=8, decide=None, verify=None,
             episode=1, cwd=None):
    """LHH 自动循环：Manager(decide) → Executor(adapter 或内置) → Auditor(verify) → checkpoint/evidence。

    - decide(goal, state) → 下一步任务文本 或「完成」（默认内置 LLM 决策，不依赖外部 agent）；
    - verify(project, round_no) → (bool, info)（默认：事实源 rev 变化即算产出）；
    - adapter 为 None → 内置执行（LLM 直接产出，仅记录）；
    - 任一通过验证的轮次即完成（v1 简化）；状态落 output/<项目>/agent/loops/<loop_id>/。

    返回 (loop_id, state)。
    """
    decide = decide or (lambda g, s: _decide_next(project, g, s))
    verify = verify or _default_verify
    cwd = Path(cwd) if cwd else common.project_dir(project)
    loops_dir = common.project_dir(project) / "agent" / "loops"
    loops_dir.mkdir(parents=True, exist_ok=True)
    loop_id = "L%04d" % (int(time.time() * 1000) % 10000)
    d = loops_dir / loop_id
    d.mkdir()
    (d / "goal.md").write_text(goal or "", encoding="utf-8")
    state = {"rounds": 0, "verified": [], "evidence": [], "loop_id": loop_id}
    rev_before = facts_rev(project, episode)
    for rnd in range(1, max_rounds + 1):
        task = decide(goal, state)
        if not task or task.strip().lower() in ("完成", "done", "无", "不需要"):
            break
        rd = d / "rounds" / ("r%02d" % rnd)
        rd.mkdir(parents=True)
        (rd / "task.md").write_text(task, encoding="utf-8")
        if adapter is not None:
            tid = run_task(project, task, build_project_summary(project, episode),
                           adapter, cwd=cwd)
            ok = read_task(project, tid).get("status") == "done"
            (rd / "result.json").write_text(
                json.dumps({"executor": adapter.name, "task_id": tid}), encoding="utf-8")
        else:
            ok = True   # 内置执行：Manager 决策本身即产出（记录任务文本）
        state["rounds"] = rnd
        verdict, info = verify(project, episode, rev_before)
        if ok and verdict:
            state["verified"].append(rnd)
            rev_before = info
            (d / "checkpoint.json").write_text(json.dumps(state, ensure_ascii=False),
                                               encoding="utf-8")
            break
        state["evidence"].append({"round": rnd, "reason": "验证未通过" if ok else "执行失败"})
        (d / "evidence.md").write_text(
            json.dumps(state["evidence"], ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "checkpoint.json").write_text(json.dumps(state, ensure_ascii=False),
                                       encoding="utf-8")
    return loop_id, state


# ============ Auditor 业务校验（LHH Auditor 的领域化 verify） ============

def audit_storyboard_parses(project, episode=1):
    """分镜表可解析且非空（给 run_loop verify 用）。返回 (bool, 说明)。"""
    sb = common.episode_dir(project, episode) / "分镜.md"
    if not sb.exists():
        return False, "缺 分镜.md"
    try:
        rows = gen_storyboard.load_storyboard(sb)
    except Exception as ex:
        return False, "分镜解析失败: %s" % ex
    return len(rows) > 0, "%d 镜" % len(rows)


def audit_script_present(project):
    """剧本.md 非空。"""
    text = ai_writer.read_script(project)
    return bool((text or "").strip()), "%d 字" % len((text or "").strip())


def audit_assets_valid(project):
    """资产表可读且编号名称完整。"""
    try:
        rows = common.asset_table()
        bad = [a["code"] for a in rows if not (a.get("name") or "").strip()]
        return (not bad, "%d 项资产" % len(rows)) if not bad else (False, "缺名称: %s" % ",".join(bad))
    except Exception as ex:
        return False, str(ex)


def audit_composed(project, episode=1):
    """成片已生成。"""
    p = common.episode_dir(project, episode) / "成片.mp4"
    return (p.exists(), "成片已生成" if p.exists() else "未拼接")


BUSINESS_AUDITS = {
    "storyboard": audit_storyboard_parses,
    "script": audit_script_present,
    "assets": audit_assets_valid,
    "composed": audit_composed,
}


# ============ 状态存储（Manager 侧） ============

def tasks_dir(project):
    d = common.project_dir(project) / "agent" / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def task_dir(project, task_id):
    return tasks_dir(project) / task_id


def _safe_id(task_id):
    if not re.match(r"^[A-Za-z0-9_-]+$", task_id or ""):
        raise ValueError("非法 task_id: %r" % task_id)
    return task_id


def create_task(project, goal, context=""):
    """新建任务：goal.md（原始目标）+ prompt.txt（单步提示词），状态 running。"""
    tid = "t%04d" % (int(time.time() * 1000) % 10000)
    d = task_dir(project, tid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "goal.md").write_text(goal or "", encoding="utf-8")
    prompt = "【任务目标】\n%s\n\n【项目上下文】\n%s" % (goal or "", context or "")
    (d / "prompt.txt").write_text(prompt, encoding="utf-8")
    (d / "transcript.jsonl").write_text("", encoding="utf-8")
    (d / "result.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    return tid


def append_transcript(project, task_id, line):
    _safe_id(task_id)
    p = task_dir(project, task_id) / "transcript.jsonl"
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": round(time.time(), 2), "line": line},
                            ensure_ascii=False) + "\n")


def set_result(project, task_id, result):
    _safe_id(task_id)
    d = task_dir(project, task_id)
    payload = dict(result or {})
    payload["status"] = "done" if payload.get("ok") else "failed"
    (d / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                   encoding="utf-8")


def read_task(project, task_id):
    _safe_id(task_id)
    d = task_dir(project, task_id)
    result = {"status": "running", "result": None, "transcript": []}
    rp = d / "result.json"
    if rp.exists():
        try:
            result["result"] = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            pass
        result["status"] = (result["result"] or {}).get("status", "running")
    tp = d / "transcript.jsonl"
    if tp.exists():
        lines = []
        for raw in tp.read_text(encoding="utf-8").splitlines():
            try:
                lines.append(json.loads(raw).get("line", ""))
            except Exception:
                continue
        result["transcript"] = lines
    return result


def list_tasks(project):
    d = tasks_dir(project)
    out = []
    for sub in sorted(d.iterdir(), reverse=True):
        if not sub.is_dir():
            continue
        task = read_task(project, sub.name)
        task["id"] = sub.name
        out.append(task)
    return out


# ============ AgentAdapter（Executor 侧） ============

class AgentAdapter:
    """外部 agent 适配器基类。子类保留外部 agent 原生执行循环。"""

    name = "base"

    def available(self):
        return False

    def execute(self, cwd, prompt_text, on_line=None, timeout=1800):
        raise NotImplementedError

    def resume_cmd(self, cwd):
        raise NotImplementedError


def _run_cli(cmd, cwd, on_line=None, timeout=1800):
    """跑外部 CLI，逐行回传 on_line；返回 (exit_code, stdout)。"""
    out_lines = []
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            out_lines.append(line)
            if on_line:
                on_line(line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return -1, "\n".join(out_lines)
    return proc.returncode or 0, "\n".join(out_lines)


class CLITaskAdapter(AgentAdapter):
    """通用 CLI 适配器：非交互单 prompt 模式（对齐 LHH 的 AgentAdapter 形态）。"""

    name = "cli"
    cli = None          # 可执行名，如 kimi
    prompt_args = None  # 附加参数列表（如 -m kimi-code/k3-256k）

    def __init__(self, name=None, cli=None, prompt_args=None, timeout=1800):
        self.name = name or self.name
        self.cli = cli or self.cli
        self.prompt_args = list(prompt_args or self.prompt_args or [])
        self.timeout = timeout

    def available(self):
        return shutil.which(self.cli) is not None

    def build_cmd(self, prompt_text):
        return [self.cli, "-p", prompt_text] + self.prompt_args

    def execute(self, cwd, prompt_text, on_line=None, timeout=None):
        if not self.available():
            return 127, "CLI 不存在: %s" % self.cli
        return _run_cli(self.build_cmd(prompt_text), cwd, on_line,
                        timeout or self.timeout)

    def resume_cmd(self, cwd):
        return [self.cli, "-c"]


class KimiAdapter(CLITaskAdapter):
    """kimi-code（本机实测可用）：kimi -p <prompt> -m kimi-code/k3-256k。"""

    name = "kimi"
    cli = "kimi"
    prompt_args = ["-m", "kimi-code/k3-256k", "--output-format", "text"]


class CodexAdapter(CLITaskAdapter):
    name = "codex"
    cli = "codex"
    prompt_args = ["exec"]


class ClaudeAdapter(CLITaskAdapter):
    name = "claude"
    cli = "claude"


class DshAdapter(CLITaskAdapter):
    name = "dsh"
    cli = "dsh"
    prompt_args = ["--profile", "headless"]


ADAPTER_DEFAULTS = {
    "kimi": {"cmd": "kimi",
             "args": ["-m", "kimi-code/k3-256k", "--output-format", "text"],
             "timeout": 1800, "skills_dir": ".agents/skills"},
    "codex": {"cmd": "codex", "args": ["exec"], "timeout": 1800, "skills_dir": ""},
    "claude": {"cmd": "claude", "args": [], "timeout": 1800, "skills_dir": ""},
    "dsh": {"cmd": "dsh", "args": ["--profile", "headless"], "timeout": 1800,
            "skills_dir": ""},
}


def get_adapter(name):
    """按 config.yaml agent.adapters 构造适配器（spec 10）；缺失回退内置默认。"""
    name = (name or "").strip() or "kimi"
    cfg = common.load_config()
    cfgs = cfg.get_path("agent.adapters", {}) or {}
    spec = cfgs.get(name) or ADAPTER_DEFAULTS.get(name)
    if spec is None:
        raise ValueError("未知 agent 适配器: %s（可用: %s）"
                         % (name, ", ".join(sorted(ADAPTER_DEFAULTS))))
    args = list(spec.get("args") or [])
    skills_dir = spec.get("skills_dir") or ""
    if skills_dir:
        args += ["--skills-dir", str(common.ROOT / skills_dir)]
    return CLITaskAdapter(name=name, cli=spec.get("cmd") or name,
                          prompt_args=args, timeout=int(spec.get("timeout") or 1800))


# ============ ACP 交互式适配器（spec 11：像原生 CLI 一样对话） ============

def _text_blocks(result):
    """ACP session/result → 文本块列表（result.message.content[].text）。"""
    msg = result.get("message") or {}
    out = []
    for c in msg.get("content") or []:
        if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
            out.append(c["text"])
    return out


def _update_text(message):
    """ACP session/update 的 message → 可读描述（工具调用/文本摘要）。"""
    if not isinstance(message, dict):
        return str(message)
    content = message.get("content") or []
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                t = c.get("type")
                if t == "text" and c.get("text"):
                    parts.append(c["text"])
                elif t == "tool_call" and c.get("name"):
                    parts.append("[调用 %s]" % c.get("name"))
                elif t == "tool_result":
                    parts.append("[工具结果]")
            else:
                parts.append(str(c))
        return " ".join(parts)
    return str(content)


class AcpAdapter(AgentAdapter):
    """交互式 ACP 适配器：外部 agent 原生 CLI 对话体验——多轮、流式、可中断。

    通过 `<cli> acp`（stdio JSON-RPC）连接；session 保持可多轮；
    skills/tools/搜索等原生能力全保留（工作区 = 会话 cwd）。
    kimi 帧形态：流式文本 = session/update.update.sessionUpdate 为
    agent_message_chunk / agent_thought_chunk（content.text）；完成 = 响应帧 stopReason。
    """

    name = "acp"
    cli = "kimi"

    def __init__(self, cwd=None, session_id=None, config=None):
        self.cwd = str(cwd) if cwd else str(common.ROOT)
        self.session_id = session_id
        self.config = config or {"model": "kimi-code/k3-256k", "thinking": "max",
                                 "mode": "auto"}   # mode auto = 自动批准安全操作
        self.proc = None
        self._q = queue.Queue()
        self._rid = 0

    def available(self):
        return shutil.which(self.cli) is not None

    def start(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen([self.cli, "acp"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._reader, daemon=True).start()
        self._request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                                     "clientInfo": {"name": "htv-agent", "version": "1"}})
        if not self.session_id:
            try:
                res = self._request("session/new", {"cwd": self.cwd, "mcpServers": {},
                                                    "config": self.config})
            except RuntimeError:
                res = self._request("session/new", {"cwd": self.cwd, "mcpServers": {}})
            self.session_id = res.get("sessionId") or "s1"

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def _reader(self):
        for line in self.proc.stdout:
            s = line.strip()
            if s:
                self._q.put(s)

    def _write(self, obj):
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _request(self, method, params, timeout=120):
        self._rid += 1
        rid = self._rid
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        end = time.time() + timeout
        while time.time() < end:
            try:
                frame = json.loads(self._q.get(timeout=0.3))
            except queue.Empty:
                continue
            if frame.get("id") == rid:
                if "error" in frame:
                    raise RuntimeError("ACP %s 失败: %s" % (method, frame["error"]))
                return frame.get("result") or {}
        raise TimeoutError("ACP %s 超时" % method)

    def chat(self, text, on_line=None, timeout=600):
        """多轮对话：session/prompt（prompt 为内容数组），流式收集消息/思考与最终文本。

        返回 (最终消息文本, updates)。on_line 每收到一段文本/事件即回调。
        完成信号 = 本请求的响应帧（stopReason end_turn）。
        """
        self.start()
        self._rid += 1
        rid = self._rid
        self._write({"jsonrpc": "2.0", "id": rid, "method": "session/prompt",
                     "params": {"sessionId": self.session_id,
                                "prompt": [{"type": "text", "text": text}]}})
        message_parts, thought_parts, updates = [], [], []
        end = time.time() + timeout
        while time.time() < end:
            try:
                frame = json.loads(self._q.get(timeout=0.3))
            except queue.Empty:
                continue
            m = frame.get("method")
            if m == "session/update":
                p = frame.get("params") or {}
                update = p.get("update") or {}
                kind = update.get("sessionUpdate") or ""
                content = update.get("content") or {}
                chunk = content.get("text") if isinstance(content, dict) else None
                if kind == "agent_message_chunk" and chunk:
                    message_parts.append(chunk)
                    if on_line:
                        on_line(chunk)
                elif kind == "agent_thought_chunk" and chunk:
                    thought_parts.append(chunk)
                elif p.get("state") == "interrupted":
                    raise RuntimeError("ACP 会话被中断")
                updates.append({"kind": kind, "text": chunk or ""})
            elif m == "session/result":   # 兼容其它实现：结果通知
                p = frame.get("params") or {}
                for block in _text_blocks(p.get("result") or {}):
                    message_parts.append(block)
                    if on_line:
                        on_line(block)
                break
            elif frame.get("id") == rid:   # 响应帧 = 完成
                break
        return "".join(message_parts), updates


# ============ P7c RoundAdapter：回合式外派执行器（对齐 LHH run_episode 语义） ============

_MUTATING_TOOL_HINTS = (
    "write", "edit", "patch", "apply", "insert", "replace", "delete", "remove",
    "bash", "shell", "run", "mkdir", "move", "copy", "rename", "rm",
    "multi_edit", "notepad", "create", "save",
)


def build_round_prompt(goal, ctx="", tools_desc="", skills="", max_chars=4000):
    """回合任务 prompt（对齐 LHH build_role_executor_prompt 形态）：

    目标 + 项目上下文（工作区=项目目录）+ 宿主可用工具契约 + 相关 skill 指引。
    """
    parts = ["# 回合任务（Round，对齐 LongHorizon-Harness run_episode）\n"]
    parts.append("## 目标\n%s" % (goal or "").strip())
    if ctx:
        parts.append("\n## 项目上下文（工作区 = 项目目录，可直接读写下列文件）\n%s"
                     % str(ctx)[:max_chars])
    if tools_desc:
        parts.append("\n## 宿主可用工具（契约注入：宿主可代执行；你也可以用自身原生工具）\n%s"
                     % str(tools_desc))
    if skills:
        parts.append("\n## 相关 skill 指引（遵循其规范执行）\n%s" % str(skills)[:max_chars])
    parts.append("\n## 要求\n"
                 "1) 在当前工作区内自主调用工具完成任务；\n"
                 "2) 需要读写项目文档时直接用你的文件工具（Read/Write/Edit/Bash 等）；\n"
                 "3) 完成后总结：改动了哪些文件、结果如何。")
    return "\n\n".join(parts)


def _tool_names_from_content(content):
    """ACP content 块列表 → 工具名列表（type=tool_call 块）。"""
    out = []
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_call" and c.get("name"):
                out.append(c["name"])
    return out


class RoundAdapter(AcpAdapter):
    """回合式外派执行器（P7c，对齐 LHH AgentAdapter.run_episode(prompt, env)）。

    一次 run_round = 一个 ACP 回合（复用 AcpAdapter 常驻会话）：
      启动会话 → 发送回合 prompt（目标+上下文+工具契约+skill 指引）→
      流式收集 thinking / message / tool_call（session/update）→
      经 on_event 上报宿主（转 trace 事件）→ 响应帧 stopReason → 结构化回执。

    回执：{status: done|error|needs_info, summary, changes, tool_trace, rounds, session_id}
      - changes    从 tool_call 轨迹提取的「文件改动猜测」（写类工具名）
      - tool_trace [{name, status}]（status ∈ started/done/error）
    多轮：continue_round(instruction) 同会话续回合（宿主补充指令）。
    max_steps 工具调用超限 → needs_info（可 continue_round 继续）。
    """

    name = "round"

    def __init__(self, cwd=None, session_id=None, config=None, cli=None, max_steps=30):
        super().__init__(cwd=cwd, session_id=session_id, config=config)
        if cli:
            self.cli = cli
        self.max_steps = int(max_steps or 30)

    def _cancel(self):
        """尝试取消当前回合（ACP v2 session/cancel；不支持则静默）。"""
        try:
            self._write({"jsonrpc": "2.0", "method": "session/cancel",
                         "params": {"sessionId": self.session_id}})
        except Exception:
            pass

    def run_round(self, goal, ctx="", tools_desc="", skills="", on_event=None,
                  max_steps=None, timeout=900):
        """执行一个回合：发送回合任务 prompt → 流式收集 → 结构化回执。"""
        self.start()
        prompt = build_round_prompt(goal, ctx, tools_desc, skills)
        self._rid += 1
        rid = self._rid
        self._write({"jsonrpc": "2.0", "id": rid, "method": "session/prompt",
                     "params": {"sessionId": self.session_id,
                                "prompt": [{"type": "text", "text": prompt}]}})
        message_parts, thought_parts = [], []
        tools = {}            # toolCallId -> {"name", "status", "order"}
        order = [0]
        status = "error"
        error = ""
        stop_reason = ""
        end = time.time() + timeout
        while time.time() < end:
            try:
                frame = json.loads(self._q.get(timeout=0.3))
            except queue.Empty:
                continue
            m = frame.get("method")
            if m == "session/request_permission":
                # ACP 权限请求（写文件等操作需宿主批准）：自动批准首个 allow 选项。
                # 客户端须以「同 id 的 JSON-RPC 响应」回复 outcome=selected（v2 协议）；
                # delegate 语义 = 授权外部 agent 改项目文件（对应 CLI mode=auto）。
                p = frame.get("params") or {}
                opts = p.get("options") or []
                pick = next((o for o in opts
                             if str(o.get("kind") or "").startswith("allow")), None)
                if pick is None:
                    pick = next((o for o in opts
                                 if str(o.get("kind") or "").startswith("reject")), None)
                if pick is not None:
                    try:
                        self._write({"jsonrpc": "2.0", "id": frame.get("id"),
                                     "result": {"outcome": {
                                         "outcome": "selected",
                                         "optionId": pick.get("optionId")}}})
                    except Exception:
                        pass
                continue
            if m == "session/update":
                p = frame.get("params") or {}
                if p.get("state") == "interrupted":
                    status, error = "error", "ACP 会话被中断"
                    break
                up = p.get("update") or {}
                kind = up.get("sessionUpdate") or ""
                content = up.get("content") or {}
                if kind == "agent_message_chunk" and isinstance(content, dict) and content.get("text"):
                    message_parts.append(content["text"])
                    if on_event:
                        try:
                            on_event({"type": "message", "text": content["text"]})
                        except Exception:
                            pass
                elif kind == "agent_thought_chunk" and isinstance(content, dict) and content.get("text"):
                    thought_parts.append(content["text"])
                    if on_event and len(thought_parts) == 1:
                        try:
                            on_event({"type": "thinking", "text": content["text"], "first": True})
                        except Exception:
                            pass
                elif kind in ("tool_call", "tool_call_update", "tool_result"):
                    tcid = up.get("toolCallId") or up.get("tool_call_id") or ""
                    name = up.get("title") or up.get("name") or ""
                    st = str(up.get("status") or "started").lower()
                    if kind == "tool_call":
                        # 新工具调用开始
                        if tcid not in tools:
                            order[0] += 1
                            tools[tcid] = {"name": name or "?", "status": "started",
                                           "order": order[0]}
                            if on_event:
                                try:
                                    on_event({"type": "tool_call", "name": name or "?",
                                              "id": tcid, "status": "started"})
                                except Exception:
                                    pass
                    elif tcid in tools:
                        # 完成/错误
                        if st == "completed":
                            tools[tcid]["status"] = "done"
                            if on_event:
                                try:
                                    on_event({"type": "tool_call", "name": tools[tcid]["name"],
                                              "id": tcid, "status": "done"})
                                except Exception:
                                    pass
                        elif st in ("error", "failed"):
                            tools[tcid]["status"] = "error"
                            if on_event:
                                try:
                                    on_event({"type": "tool_call", "name": tools[tcid]["name"],
                                              "id": tcid, "status": "error"})
                                except Exception:
                                    pass
                # max_steps 工具调用数超限 → 中断回合，返回 needs_info
                if len(tools) >= int(max_steps if max_steps is not None else self.max_steps):
                    self._cancel()
                    status, error = "needs_info", (
                        "工具调用超过 %d 次上限，回合中断（可 continue_round 继续）"
                        % (max_steps if max_steps is not None else self.max_steps))
                    break
            elif m == "session/result":      # 兼容其它实现：结果通知
                p = frame.get("params") or {}
                res = p.get("result") or {}
                for block in _text_blocks(res):
                    message_parts.append(block)
                    if on_event:
                        try:
                            on_event({"type": "message", "text": block})
                        except Exception:
                            pass
                for name in _tool_names_from_content((res.get("message") or {}).get("content")):
                    if not any(t["name"] == name for t in tools.values()):
                        order[0] += 1
                        tools["m%d" % order[0]] = {"name": name, "status": "done",
                                                   "order": order[0]}
                        if on_event:
                            try:
                                on_event({"type": "tool_call", "name": name,
                                          "status": "done"})
                            except Exception:
                                pass
                status = "done"
                break
            elif frame.get("id") == rid:     # 响应帧 = 完成
                res = frame.get("result") or {}
                stop_reason = str(res.get("stopReason") or res.get("stop_reason") or "")
                for name in _tool_names_from_content((res.get("message") or {}).get("content")):
                    if not any(t["name"] == name for t in tools.values()):
                        order[0] += 1
                        tools["m%d" % order[0]] = {"name": name, "status": "done",
                                                   "order": order[0]}
                        if on_event:
                            try:
                                on_event({"type": "tool_call", "name": name,
                                          "status": "done"})
                            except Exception:
                                pass
                if stop_reason in ("end_turn", "done", "complete", "success"):
                    status = "done"
                elif stop_reason in ("max_tokens", "cancelled", "interrupted"):
                    status, error = "needs_info", "回合停止：stopReason=%s" % stop_reason
                else:
                    status = "done" if message_parts else "error"
                    if not message_parts:
                        error = "回合无文本输出（stopReason=%s）" % stop_reason
                break
        else:
            status, error = "error", "回合超时（%ss）" % timeout
        return self._receipt(status, message_parts, thought_parts, tools, error)

    def continue_round(self, instruction, on_event=None, max_steps=None, timeout=900):
        """同会话续回合：宿主补充指令（上下文/工具契约已在会话内）。"""
        return self.run_round(instruction, ctx="", tools_desc="", skills="",
                              on_event=on_event, max_steps=max_steps, timeout=timeout)

    def _receipt(self, status, message_parts, thought_parts, tools, error=""):
        """构建结构化回执。"""
        tool_trace = [{"name": t["name"], "status": t["status"]}
                      for _, t in sorted(tools.items(), key=lambda kv: kv[1]["order"])]
        changes = []
        for name in {t["name"] for t in tool_trace}:
            low = (name or "").lower()
            if any(h in low for h in _MUTATING_TOOL_HINTS):
                changes.append({"tool": name, "note": "可能改动项目文件"})
        summary = "".join(message_parts).strip() or (error or "（无文本输出）")
        return {
            "status": status,
            "summary": summary[:2000],
            "changes": changes,
            "tool_trace": tool_trace,
            "rounds": 1,
            "session_id": self.session_id,
            "thought_chars": sum(len(x) for x in thought_parts),
            "error": error or None,
        }

    # ---- 兼容 CLITaskAdapter 的 execute 形态（run_loop / run_task 可复用） ----
    def execute(self, cwd, prompt_text, on_line=None, timeout=1800):
        """把整段 prompt 当作一个回合目标执行 → (exit_code, stdout)。"""
        try:
            receipt = self.run_round(prompt_text, on_event=None, timeout=timeout)
        except Exception as ex:
            return 1, "回合执行失败: %s" % ex
        code = 0 if receipt["status"] == "done" else 1
        if on_line:
            try:
                on_line(receipt["summary"])
            except Exception:
                pass
        return code, receipt["summary"]


def pick_delegate_adapter(cfg=None, name=None, cwd=None):
    """delegate_mode（config agent.delegate_mode：acp|cli）选择外派适配器。

    - acp（默认，且默认 agent 为 kimi 且 kimi 可用）→ RoundAdapter；
    - 否则回退 cli → get_adapter(name)（CLITaskAdapter 单发）。
    返回的 adapter 带 delegate_mode 属性（'acp' | 'cli'），供事件文案区分。
    """
    cfg = cfg or common.load_config()
    name = (name or (cfg.get_path("agent.default", "") or "kimi")).strip() or "kimi"
    mode = str(cfg.get_path("agent.delegate_mode", "") or "").strip().lower()
    if not mode:
        mode = "acp" if shutil.which("kimi") else "cli"
    if mode == "acp" and name == "kimi":
        try:
            a = RoundAdapter(cwd=cwd)
            if a.available():
                a.delegate_mode = "acp"
                return a
        except Exception:
            pass
        mode = "cli"                       # acp 不可用 → 回退 cli
    a = get_adapter(name)
    a.delegate_mode = "cli"
    return a


# ============ Manager 单轮调度 ============

def run_task(project, goal, context="", adapter=None, cwd=None, tid=None):
    """Manager 单轮：建任务（或复用已有 tid）→ 组装 prompt → 外部 agent 执行（流式 transcript）→ 落 result。

    返回 task_id；adapter 可注入（测试用假 adapter）；tid 预建可让调用方提前拿到任务号（流式回显）。
    """
    adapter = adapter or get_adapter("kimi")
    cwd = Path(cwd) if cwd else common.ROOT
    tid = tid or create_task(project, goal, context)
    prompt = (task_dir(project, tid) / "prompt.txt").read_text(encoding="utf-8")

    def on_line(line):
        append_transcript(project, tid, line)

    code, stdout = adapter.execute(cwd, prompt, on_line=on_line)
    if not stdout.strip():
        stdout = "（外部 agent 无文本输出，exit=%s）" % code
        append_transcript(project, tid, stdout)
    set_result(project, tid, {"ok": code == 0, "exit_code": code,
                              "summary": stdout[-2000:],
                              "adapter": adapter.name})
    return tid


# ============ Auditor（真实依据） ============

def audit_file_exists(project, task_id, relpath):
    """校验任务目录下产物文件存在（不轻信 agent 自述）。"""
    _safe_id(task_id)
    p = task_dir(project, task_id) / relpath
    return p.is_file()
