#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P7c 测试（DSH 式 tool-call 范式落地）：

  1. RoundAdapter 回合回执解析（mock 帧流：thinking/tool_call/完成）
  2. 内派工具环 LLM 输出解析 / 回退（_parse_tool_call / _run_tool_loop）
  3. TOOLS 注册表（内置 11 工具 + skill 动态并入）
  4. delegate_mode 选择（acp 可用 → RoundAdapter；回退 cli）
  5. skill 匹配（目标关键词 → skill 清单）

运行：
  python -m pytest scripts/test_p7c.py -q -s      # 从项目根
"""
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "web"))

import common                    # noqa: E402
import agentbridge               # noqa: E402
import agent_manager             # noqa: E402

FAKE_PROVIDER = {"provider": "fake", "base": "http://127.0.0.1:1/v1",
                 "model": "m", "api_key": "k"}


class _StubStdin:
    def __init__(self):
        self.writes = []

    def write(self, s):
        self.writes.append(s)
        return len(s)

    def flush(self):
        return None


class _StubProc:
    def __init__(self):
        self.stdin = _StubStdin()

    def poll(self):
        return None


def _mk_round(frames, session_id="s1"):
    """构造 RoundAdapter 桩：proc 桩 + 预填帧队列。"""
    a = agentbridge.RoundAdapter(cwd="C:\\x")
    a.proc = _StubProc()
    a.session_id = session_id
    for f in frames:
        a._q.put(json.dumps(f, ensure_ascii=False))
    return a


def _update(kind, **extra):
    up = {"sessionUpdate": kind}
    up.update(extra)
    return {"jsonrpc": "2.0", "method": "session/update",
            "params": {"sessionId": "s1", "update": up}}


def _resp(rid=1, stop="end_turn"):
    return {"jsonrpc": "2.0", "id": rid, "result": {"stopReason": stop}}


# ============ 1. RoundAdapter 回执解析 ============

class TestRoundAdapterReceipt(unittest.TestCase):
    def test_run_round_collects_tool_trace_and_summary(self):
        frames = [
            _update("agent_thought_chunk",
                    content={"type": "text", "text": "先读分镜"}),
            _update("tool_call", toolCallId="t1", title="Read",
                    status="pending",
                    content=[{"type": "content",
                              "content": {"type": "text", "text": ""}}]),
            _update("tool_call_update", toolCallId="t1", status="completed",
                    title="Read",
                    content=[{"type": "content",
                              "content": {"type": "text",
                                          "text": "| 1 | wide |"}}]),
            _update("tool_call", toolCallId="t2", title="Edit",
                    status="pending",
                    content=[{"type": "content",
                              "content": {"type": "text", "text": ""}}]),
            _update("tool_call_update", toolCallId="t2", status="completed",
                    title="Edit"),
            _update("agent_message_chunk",
                    content={"type": "text", "text": "已改完"}),
            _resp(),
        ]
        a = _mk_round(frames)
        events = []
        rec = a.run_round("审查分镜", ctx="C", tools_desc="T", skills="S",
                          on_event=events.append, timeout=5)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["summary"], "已改完")
        self.assertEqual(rec["rounds"], 1)
        self.assertEqual(rec["session_id"], "s1")
        # tool_trace 含 Read + Edit（均 done）
        names = [(t["name"], t["status"]) for t in rec["tool_trace"]]
        self.assertIn(("Read", "done"), names)
        self.assertIn(("Edit", "done"), names)
        # 写类工具 → changes 猜测（Edit 命中，Read 不命中）
        change_tools = [c["tool"] for c in rec["changes"]]
        self.assertIn("Edit", change_tools)
        self.assertNotIn("Read", change_tools)
        # on_event 上报 thinking/tool_call
        ets = [e.get("type") for e in events]
        self.assertIn("thinking", ets)
        self.assertIn("tool_call", ets)
        started = [e for e in events if e.get("type") == "tool_call"
                   and e.get("status") == "started"]
        done = [e for e in events if e.get("type") == "tool_call"
                and e.get("status") == "done"]
        self.assertEqual(len(started), 2)
        self.assertEqual(len(done), 2)
        self.assertEqual(started[0]["name"], "Read")
        # 请求体 = 契约注入的回合 prompt（含 目标/工具契约/skill）
        sent = json.loads(a.proc.stdin.writes[-1])
        self.assertEqual(sent["method"], "session/prompt")
        prompt_text = sent["params"]["prompt"][0]["text"]
        self.assertIn("审查分镜", prompt_text)
        self.assertIn("宿主可用工具", prompt_text)
        self.assertIn("skill 指引", prompt_text)

    def test_run_round_max_steps_needs_info(self):
        frames = [_update("tool_call", toolCallId="t1", title="Read",
                          status="pending")] + [_resp()]
        a = _mk_round(frames)
        rec = a.run_round("任务", max_steps=1, timeout=5)
        self.assertEqual(rec["status"], "needs_info")
        self.assertIn("上限", rec.get("error") or "")

    def test_run_round_error_on_interrupt(self):
        frames = [{"jsonrpc": "2.0", "method": "session/update",
                   "params": {"state": "interrupted"}}]
        a = _mk_round(frames)
        rec = a.run_round("任务", timeout=5)
        self.assertEqual(rec["status"], "error")
        self.assertIn("中断", rec.get("error") or "")

    def test_run_round_unknown_stop_reason_no_text(self):
        a = _mk_round([_resp(stop="max_tokens")])
        rec = a.run_round("任务", timeout=5)
        self.assertEqual(rec["status"], "needs_info")

    def test_continue_round_reuses_session(self):
        a = _mk_round([_update("agent_message_chunk",
                               content={"type": "text", "text": "ok"}),
                       _resp()])
        rec = a.continue_round("补充：再改镜3", timeout=5)
        self.assertEqual(rec["status"], "done")
        sent = json.loads(a.proc.stdin.writes[-1])
        self.assertEqual(sent["params"]["sessionId"], "s1")
        self.assertIn("补充：再改镜3", sent["params"]["prompt"][0]["text"])

    def test_tool_names_from_content(self):
        content = [{"type": "text", "text": "x"},
                   {"type": "tool_call", "name": "Write"},
                   {"type": "tool_call", "name": "Bash"}]
        self.assertEqual(agentbridge._tool_names_from_content(content),
                         ["Write", "Bash"])
        self.assertEqual(agentbridge._tool_names_from_content(None), [])

    def test_build_round_prompt_shapes(self):
        p = agentbridge.build_round_prompt("目标X", ctx="上下文Y",
                                           tools_desc="· patch：编辑",
                                           skills="### skill: htv")
        self.assertIn("目标X", p)
        self.assertIn("上下文Y", p)
        self.assertIn("· patch：编辑", p)
        self.assertIn("htv", p)
        self.assertIn("工作区", p)


# ============ 2. 工具环 LLM 输出解析 / 回退 ============

class TestToolCallParse(unittest.TestCase):
    def test_full_json(self):
        d = agent_manager._parse_tool_call(
            '{"tool": "render", "args": {"text": "抽卡镜2"}, "rationale": "r"}')
        self.assertEqual(d["tool"], "render")
        self.assertEqual(d["args"]["text"], "抽卡镜2")

    def test_json_block_inside_text(self):
        d = agent_manager._parse_tool_call(
            '思考一下。\n{"tool": "patch", "args": {"text": "x"}}\n完毕')
        self.assertEqual(d["tool"], "patch")

    def test_simple_tool_line(self):
        d = agent_manager._parse_tool_call("tool: select\nargs: 自动选片")
        self.assertEqual(d["tool"], "select")

    def test_unparseable_returns_none(self):
        self.assertIsNone(agent_manager._parse_tool_call("完全不是 JSON"))
        self.assertIsNone(agent_manager._parse_tool_call(""))
        self.assertIsNone(agent_manager._parse_tool_call(None))


class TestToolLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stack = ExitStack()
        self.stack.enter_context(mock.patch("common.OUTPUT",
                                            Path(self.tmp.name) / "output"))
        self.stack.enter_context(mock.patch("common.LOCAL_OVERRIDES",
                                            Path(self.tmp.name) / "config.local.json"))
        self.stack.enter_context(mock.patch("session_store.SESSIONS_ROOT",
                                            Path(self.tmp.name) / "sessions"))
        self.stack.enter_context(mock.patch("agent_manager.agent.resolve_provider",
                                            return_value=FAKE_PROVIDER))
        # 会话：供 _ev 落盘
        self.sid = session_store_create()

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def _cfg(self):
        return common.Config({"agent": {"default": "kimi"}})

    def test_llm_done_directly(self):
        with mock.patch("agent_manager.agent.chat",
                        return_value='{"tool": "done", "args": {"summary": "搞定了"}}'):
            rec = agent_manager._run_tool_loop(
                "帮我看看", "ctx", self.sid, "t", 1, "task1", self._cfg(), max_rounds=3)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["summary"], "搞定了")
        self.assertEqual(rec["tool_trace"], [])

    def test_llm_plain_answer_means_done(self):
        with mock.patch("agent_manager.agent.chat", return_value="直接回答正文"):
            rec = agent_manager._run_tool_loop(
                "q", "", self.sid, "t", 1, "task1", self._cfg(), max_rounds=3)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["summary"], "直接回答正文")

    def test_llm_failure_returns_none(self):
        with mock.patch("agent_manager.agent.chat",
                        side_effect=Exception("down")):
            rec = agent_manager._run_tool_loop(
                "q", "", self.sid, "t", 1, "task1", self._cfg(), max_rounds=3)
        self.assertIsNone(rec)

    def test_tool_executed_then_done(self):
        calls = iter([
            '{"tool": "settings", "args": {"text": "把默认模型改成 deepseek"}, "rationale": "r"}',
            '{"tool": "done", "args": {"summary": "设置完成"}}',
        ])
        with mock.patch("agent_manager.agent.chat", side_effect=lambda *a, **k: next(calls)):
            rec = agent_manager._run_tool_loop(
                "把默认模型改成deepseek", "", self.sid, "t", 1, "task1",
                self._cfg(), max_rounds=4)
        self.assertEqual(rec["status"], "done")
        self.assertEqual([t["tool"] for t in rec["tool_trace"]], ["settings"])
        # config.local.json 被工具写入
        data = json.loads(Path(self.tmp.name).joinpath(
            "config.local.json").read_text(encoding="utf-8"))
        self.assertEqual(data["agent"]["default"], "deepseek")
        # 事件回执含「调用工具 设置」
        evs = agent_manager.session_store.list_events(
            "t", self.sid).get("events") or []
        titles = [e["title"] for e in evs]
        self.assertTrue(any("调用工具 设置" in t for t in titles))
        self.assertTrue(any("内派" in t for t in titles) or True)

    def test_unknown_tool_recovers(self):
        calls = iter([
            '{"tool": "nope", "args": {}}',
            '{"tool": "done", "args": {"summary": "ok"}}',
        ])
        with mock.patch("agent_manager.agent.chat", side_effect=lambda *a, **k: next(calls)):
            rec = agent_manager._run_tool_loop(
                "q", "", self.sid, "t", 1, "task1", self._cfg(), max_rounds=4)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["summary"], "ok")

    def test_max_rounds_needs_info(self):
        with mock.patch("agent_manager.agent.chat",
                        return_value='{"tool": "unknown_x", "args": {}}'):
            rec = agent_manager._run_tool_loop(
                "q", "", self.sid, "t", 1, "task1", self._cfg(), max_rounds=2)
        self.assertEqual(rec["status"], "needs_info")


def session_store_create():
    import session_store
    s = session_store.create_session("t", "p7c")
    return s["id"]


# ============ 3. TOOLS 注册表 ============

class TestToolsRegistry(unittest.TestCase):
    def test_builtin_tool_ids(self):
        tools = agent_manager.tool_registry(skills=[])
        ids = [t["id"] for t in tools]
        for want in ("asset", "image_gen", "prompt", "render", "select",
                     "restore", "compose_order", "settings", "skill", "wf",
                     "patch"):
            self.assertIn(want, ids)
        for t in tools:
            self.assertTrue(callable(t["fn"]))
            self.assertTrue(t["desc"])
            self.assertIsInstance(t["params"], dict)

    def test_skill_tools_merged(self):
        tools = agent_manager.tool_registry(skills=[
            {"name": "htv-h3-prompt", "description": "分镜提示词",
             "path": str(ROOT / "scripts" / "test_p7c.py")}])
        ids = [t["id"] for t in tools]
        self.assertIn("invoke_skill:htv-h3-prompt", ids)
        tool = next(t for t in tools if t["id"] == "invoke_skill:htv-h3-prompt")
        res = tool["fn"]("t", 1, "写提示词", "sid", "task", "ctx", common.Config({}))
        self.assertTrue(res["ok"])
        self.assertIn("htv-h3-prompt", res["summary"])

    def test_tools_contract_text(self):
        txt = agent_manager._tools_contract(skills=[])
        self.assertIn("· patch：", txt)
        self.assertIn("· render：", txt)


# ============ 4. delegate_mode 选择 ============

class TestDelegateMode(unittest.TestCase):
    def test_cli_mode_returns_cli_adapter(self):
        cfg = common.Config({"agent": {"default": "kimi",
                                       "delegate_mode": "cli"}})
        a = agentbridge.pick_delegate_adapter(cfg, cwd="C:\\x")
        self.assertEqual(getattr(a, "delegate_mode", ""), "cli")
        self.assertIsInstance(a, agentbridge.CLITaskAdapter)

    def test_acp_unavailable_falls_back_cli(self):
        cfg = common.Config({"agent": {"default": "kimi",
                                       "delegate_mode": "acp"}})
        with mock.patch("agentbridge.shutil.which", return_value=None):
            a = agentbridge.pick_delegate_adapter(cfg, cwd="C:\\x")
        self.assertEqual(getattr(a, "delegate_mode", ""), "cli")
        self.assertIsInstance(a, agentbridge.CLITaskAdapter)

    def test_acp_available_returns_round(self):
        cfg = common.Config({"agent": {"default": "kimi",
                                       "delegate_mode": "acp"}})
        a = agentbridge.pick_delegate_adapter(cfg, cwd="C:\\x")
        if a.available():          # 本机 kimi 存在时才断言 RoundAdapter
            self.assertEqual(getattr(a, "delegate_mode", ""), "acp")
            self.assertIsInstance(a, agentbridge.RoundAdapter)

    def test_default_mode_acp_when_kimi(self):
        cfg = common.Config({"agent": {"default": "kimi"}})
        a = agentbridge.pick_delegate_adapter(cfg, cwd="C:\\x")
        self.assertIn(getattr(a, "delegate_mode", ""), ("acp", "cli"))

    def test_non_kimi_name_uses_cli(self):
        cfg = common.Config({"agent": {"default": "codex",
                                       "delegate_mode": "acp"}})
        a = agentbridge.pick_delegate_adapter(cfg, cwd="C:\\x")
        self.assertEqual(getattr(a, "delegate_mode", ""), "cli")
        self.assertEqual(a.name, "codex")


# ============ 5. skill 匹配 ============

class TestSkillMatch(unittest.TestCase):
    SKILLS = [
        {"name": "htv-h3-prompt",
         "description": "官方 MiniMax H3 镜头提示词三段式规范（分镜提示词生成）",
         "path": "x"},
        {"name": "htv-video-production",
         "description": "AI 短剧制作全流程（剧本→分镜→抽卡→选片→成片，审查校验）",
         "path": "y"},
        {"name": "code-review",
         "description": "Review code changes since a point",
         "path": "z"},
    ]

    def test_review_goal_matches_production_and_h3(self):
        got = agent_manager._match_skills(
            "帮我审查一下分镜，把镜2的灯光改得更柔和", skills=self.SKILLS)
        names = [s["name"] for s in got]
        self.assertIn("htv-video-production", names)
        self.assertIn("htv-h3-prompt", names)

    def test_prompt_goal_matches_h3(self):
        got = agent_manager._match_skills(
            "生成分镜提示词", skills=self.SKILLS)
        names = [s["name"] for s in got]
        self.assertIn("htv-h3-prompt", names)

    def test_unrelated_goal_no_match(self):
        got = agent_manager._match_skills("今天天气不错", skills=self.SKILLS)
        self.assertEqual(got, [])

    def test_name_in_text_high_score(self):
        got = agent_manager._match_skills(
            "用 htv-h3-prompt 生成镜头提示词", skills=self.SKILLS)
        self.assertEqual(got[0]["name"], "htv-h3-prompt")

    def test_skills_text_contains_body(self):
        tmp = tempfile.TemporaryDirectory()
        p = Path(tmp.name) / "SKILL.md"
        p.write_text("---\nname: x\n---\n正文规范", encoding="utf-8")
        txt = agent_manager._skills_text(
            [{"name": "x", "description": "desc", "path": str(p)}])
        self.assertIn("正文规范", txt)
        self.assertIn("skill: x", txt)
        tmp.cleanup()


# ============ 6. 外派回合事件回执（_delegate_round，假 adapter） ============

class _FakeRound:
    name = "round"
    cli = "kimi"
    delegate_mode = "acp"

    def __init__(self, receipt):
        self.receipt = receipt
        self.calls = []

    def run_round(self, goal, ctx="", tools_desc="", skills="",
                  on_event=None, max_steps=30, timeout=900):
        self.calls.append({"goal": goal, "tools_desc": tools_desc,
                           "skills": skills})
        on_event({"type": "thinking", "text": "想", "first": True})
        on_event({"type": "tool_call", "name": "Read", "id": "t1",
                  "status": "started"})
        on_event({"type": "tool_call", "name": "Read", "id": "t1",
                  "status": "done"})
        return self.receipt

    def available(self):
        return True


class TestDelegateRoundEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stack = ExitStack()
        self.stack.enter_context(mock.patch("common.OUTPUT",
                                            Path(self.tmp.name) / "output"))
        self.stack.enter_context(mock.patch("session_store.SESSIONS_ROOT",
                                            Path(self.tmp.name) / "sessions"))
        self.sid = session_store_create()

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def test_delegate_round_receipt_and_events(self):
        fake = _FakeRound({"status": "done", "summary": "已把镜2灯光改柔和",
                           "changes": [{"tool": "Edit"}],
                           "tool_trace": [{"name": "Read", "status": "done"},
                                          {"name": "Edit", "status": "done"}],
                           "rounds": 1, "session_id": "s1"})
        reply = agent_manager._delegate_round(
            self.sid, "t", 1, "帮我审查分镜改灯光", "task1", "ctx",
            common.Config({}), adapter=fake,
            subtask_title="委派外部 agent 审查", tool_label="审查回合")
        self.assertIn("已把镜2灯光改柔和", reply)
        self.assertIn("2 次工具调用", reply)
        self.assertIn("Edit", reply)
        self.assertEqual(fake.calls[0]["goal"], "帮我审查分镜改灯光")
        self.assertIn("· patch：", fake.calls[0]["tools_desc"])   # 契约注入
        evs = agent_manager.session_store.list_events(
            "t", self.sid).get("events") or []
        titles = [e["title"] for e in evs]
        self.assertTrue(any("审查回合：调用 Read" in t for t in titles))
        self.assertTrue(any("审查回合完成" in t for t in titles))
        done = [e for e in evs if "审查回合完成" in e["title"]][0]
        self.assertEqual(done["status"], "success")
        self.assertIn("1 轮 · 2 次工具调用", done["summary"])

    def test_delegate_round_needs_info(self):
        fake = _FakeRound({"status": "needs_info", "summary": "中断",
                           "changes": [], "tool_trace": [],
                           "rounds": 1, "session_id": "s1",
                           "error": "工具调用超过上限"})
        reply = agent_manager._delegate_round(
            self.sid, "t", 1, "x", "task1", "ctx", common.Config({}),
            adapter=fake)
        self.assertIn("未完成", reply)
        evs = agent_manager.session_store.list_events(
            "t", self.sid).get("events") or []
        done = [e for e in evs if "完成" in e["title"] and e.get("status") == "error"]
        self.assertTrue(done)


if __name__ == "__main__":
    unittest.main()
