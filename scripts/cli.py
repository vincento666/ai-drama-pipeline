#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 CLI（spec: docs/specs/04-harness接口.md）。L3 编排层 = 外部 harness agent 的唯一入口契约。

退出码：0 成功 / 2 参数错 / 3 配置错 / 4 上游（模型/ComfyUI）错误。
--json：stdout 只输出 JSON（错误也是 JSON）；否则人类可读文本。
子命令（M0）：
  cli.py agent chat <prompt> [--in FILE] [--json]
  cli.py agent generate <task> [--in FILE|stdin(JSON)] [--json]
"""
import argparse
import json
import sys

from common import ConfigError, load_config
import agent
import agentbridge   # 外部 harness agent 适配（spec 08）

EXIT_OK, EXIT_USAGE, EXIT_CONFIG, EXIT_UPSTREAM = 0, 2, 3, 4


def build_parser():
    p = argparse.ArgumentParser(prog="cli.py", exit_on_error=False,
                                description="本地化 HTV 流水线 CLI（harness agent 契约）")
    sub = p.add_subparsers(dest="cmd")
    a = sub.add_parser("agent", help="提示词 → 模型生成（agent 模块）", exit_on_error=False)
    a.add_argument("action", choices=["chat", "generate"],
                   help="chat: 直接对话；generate: 任务模板生成")
    a.add_argument("text", nargs="?", default="",
                   help="chat 的提示词 / generate 的任务名（storyboard_from_script、shot_ref）")
    a.add_argument("--in", dest="in_file", default=None,
                   help="输入文件（chat: 纯文本；generate: JSON payload）")
    ar = sub.add_parser("agent-run", help="下发任务给外部 harness agent（Manager 单轮）",
                        exit_on_error=False)
    ar.add_argument("project", help="项目名")
    ar.add_argument("--goal", default="", help="任务目标（一句话）")
    ar.add_argument("--agent", default="kimi", help="外部 agent 适配器：kimi/codex/claude/dsh")
    ar.add_argument("--context", default="", help="上下文文件（可选）")
    al = sub.add_parser("agent-list", help="列出项目的 agent 任务", exit_on_error=False)
    al.add_argument("project", help="项目名")
    ars = sub.add_parser("agent-resume", help="重跑任务（同目标+上下文，新一轮）",
                         exit_on_error=False)
    ars.add_argument("project", help="项目名")
    ars.add_argument("task_id", help="任务 id")
    ars.add_argument("--agent", default="kimi", help="外部 agent 适配器")
    alo = sub.add_parser("agent-loop", help="LHH 自动循环（Manager→Executor→Auditor）",
                         exit_on_error=False)
    alo.add_argument("project", help="项目名")
    alo.add_argument("--goal", default="", help="循环目标")
    alo.add_argument("--agent", default="kimi", help="Executor 适配器（kimi/dsh）")
    alo.add_argument("--max-rounds", type=int, default=8, help="最大轮数")
    alo.add_argument("--audit", default="", help="业务验收（逗号分隔：storyboard/script/assets/composed）")
    return p


def _payload(ns):
    """generate 的 payload：--in FILE（JSON）或 stdin 管道 JSON；都没有则 {}。"""
    if ns.in_file:
        with open(ns.in_file, encoding="utf-8") as fh:
            return json.loads(fh.read())
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    return {}


def _err(code, message, as_json):
    if as_json:
        return code, json.dumps({"ok": False, "code": code, "error": message}, ensure_ascii=False)
    return code, "错误: " + message


def run_agent(ns, as_json):
    """agent 子命令 → (exit_code, output_text)。"""
    try:
        if ns.action == "chat":
            text = ns.text
            if ns.in_file:
                with open(ns.in_file, encoding="utf-8") as fh:
                    text = fh.read()
            if not text or not text.strip():
                return _err(EXIT_USAGE, "chat 需要提示词（参数或 --in FILE）", as_json)
            prov = agent.resolve_provider(load_config())
            out = agent.chat(prov["base"], prov["model"], prov["api_key"],
                             [{"role": "system", "content": agent.SYSTEM_PROMPT},
                              {"role": "user", "content": text}])
        else:  # generate
            if not ns.text:
                return _err(EXIT_USAGE,
                            "generate 需要任务名（storyboard_from_script / shot_ref）", as_json)
            out = agent.generate(ns.text, _payload(ns))
        if as_json:
            return EXIT_OK, json.dumps({"ok": True, "text": out}, ensure_ascii=False)
        return EXIT_OK, out
    except ConfigError as e:
        return _err(EXIT_CONFIG, str(e), as_json)
    except agent.AgentError as e:
        return _err(EXIT_UPSTREAM, str(e), as_json)
    except (ValueError, OSError) as e:  # json.JSONDecodeError ⊂ ValueError
        return _err(EXIT_USAGE, str(e), as_json)


def run_agent_task(ns, as_json, resume=False):
    """agent-run / agent-resume：下发/重跑任务给外部 harness agent（spec 08）。"""
    import agentbridge
    try:
        if resume:
            prev = agentbridge.read_task(ns.project, ns.task_id)
            d = agentbridge.task_dir(ns.project, ns.task_id)
            goal = (d / "goal.md").read_text(encoding="utf-8")
            context = (d / "prompt.txt").read_text(encoding="utf-8")
            tid = agentbridge.run_task(ns.project, goal, context,
                                       agentbridge.get_adapter(ns.agent))
        else:
            if not ns.goal.strip():
                return _err(EXIT_USAGE, "agent-run 需要 --goal", as_json)
            context = ""
            if ns.context:
                context = Path(ns.context).read_text(encoding="utf-8")
            tid = agentbridge.run_task(ns.project, ns.goal, context,
                                       agentbridge.get_adapter(ns.agent))
        task = agentbridge.read_task(ns.project, tid)
        if as_json:
            return EXIT_OK, json.dumps({"ok": True, "task_id": tid,
                                        "status": task["status"],
                                        "result": task["result"]},
                                       ensure_ascii=False)
        tail = "\n".join(task["transcript"][-10:])
        return EXIT_OK, "任务 %s → %s\n%s" % (tid, task["status"], tail)
    except ValueError as e:
        return _err(EXIT_USAGE, str(e), as_json)


def run_agent_list(ns, as_json):
    """agent-list：任务列表 + 状态。"""
    import agentbridge
    tasks = agentbridge.list_tasks(ns.project)
    if as_json:
        return EXIT_OK, json.dumps({"ok": True, "tasks": tasks}, ensure_ascii=False)
    lines = ["%s %s" % (t["id"], t["status"]) for t in tasks]
    return EXIT_OK, ("无任务" if not lines else "\n".join(lines))


def run_agent_loop(ns, as_json):
    """agent-loop：LHH 自动循环（Manager 内置 LLM 决策 → Executor → Auditor 业务验收）。"""
    try:
        if not ns.goal.strip():
            return _err(EXIT_USAGE, "agent-loop 需要 --goal", as_json)
        adapter = agentbridge.get_adapter(ns.agent)

        def verify(project, episode, rev_before):
            for name in [x.strip() for x in ns.audit.split(",") if x.strip()]:
                fn = agentbridge.BUSINESS_AUDITS.get(name)
                if fn:
                    ok, info = fn(project, episode)
                    if not ok:
                        return False, info
            return agentbridge._default_verify(project, episode, rev_before)

        lid, state = agentbridge.run_loop(ns.project, ns.goal, adapter=adapter,
                                          max_rounds=ns.max_rounds, verify=verify)
        if as_json:
            return EXIT_OK, json.dumps({"ok": True, "loop_id": lid, "state": state},
                                       ensure_ascii=False)
        return EXIT_OK, "loop %s | rounds=%d verified=%s evidence=%d" % (
            lid, state["rounds"], state["verified"], len(state["evidence"]))
    except ValueError as e:
        return _err(EXIT_USAGE, str(e), as_json)


def main(argv=None):
    """入口（可测 seam）：返回 (exit_code, output_text)，不打印、不 sys.exit。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    parser = build_parser()
    try:
        ns = parser.parse_args(argv)
    except argparse.ArgumentError as e:
        return _err(EXIT_USAGE, str(e), as_json)
    if ns.cmd == "agent":
        return run_agent(ns, as_json)
    if ns.cmd == "agent-run":
        return run_agent_task(ns, as_json)
    if ns.cmd == "agent-resume":
        return run_agent_task(ns, as_json, resume=True)
    if ns.cmd == "agent-list":
        return run_agent_list(ns, as_json)
    if ns.cmd == "agent-loop":
        return run_agent_loop(ns, as_json)
    return _err(EXIT_USAGE, "未知命令: %s\n%s" % (ns.cmd, parser.format_usage()), as_json)


if __name__ == "__main__":
    code, text = main()
    print(text, file=(sys.stderr if code else sys.stdout))
    sys.exit(code)
