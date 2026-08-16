#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent 模块单元测试（TDD · spec: docs/specs/03-agent模块.md）。

seams：resolve_provider / chat_endpoint / parse_chat_response / generate（模板拼接，mock chat）/ chat（mock urlopen）。
运行：
  python -m unittest scripts.test_agent -v      # 从项目根
  python scripts/test_agent.py                   # 直接运行
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common          # noqa: E402
import agent           # noqa: E402
import ai_writer       # noqa: E402（薄兼容层测试）
import gen_storyboard  # noqa: E402（LLM 分镜解析测试）


def cfg(providers=None, **llm_kw):
    llm = dict(llm_kw)
    llm.setdefault("providers", providers or {})
    return common.Config({"llm": llm})


class TestResolveProvider(unittest.TestCase):
    """seam: resolve_provider —— 预设选择 / 旧键兜底 / 错误报告。"""

    def test_preset_selected(self):
        c = cfg(provider="qwen",
                providers={"qwen": {"base": "https://q.example", "model": "qwen-plus", "api_key": "k"}})
        self.assertEqual(agent.resolve_provider(c),
                         {"provider": "qwen", "base": "https://q.example",
                          "model": "qwen-plus", "api_key": "k"})

    def test_preset_empty_fields_fall_back_to_legacy(self):
        c = cfg(provider="qwen", base="https://legacy", model="m-legacy", api_key="sk-legacy",
                providers={"qwen": {"base": "", "model": "", "api_key": ""}})
        got = agent.resolve_provider(c)
        self.assertEqual(got["base"], "https://legacy")
        self.assertEqual(got["model"], "m-legacy")
        self.assertEqual(got["api_key"], "sk-legacy")

    def test_no_provider_uses_legacy_keys(self):
        c = cfg(base="https://legacy", model="m1", api_key="k1")
        got = agent.resolve_provider(c)
        self.assertEqual(got["provider"], "custom")
        self.assertEqual(got["base"], "https://legacy")
        self.assertEqual(got["model"], "m1")
        self.assertEqual(got["api_key"], "k1")

    def test_unknown_provider_raises_and_lists_available(self):
        c = cfg(provider="foo",
                providers={"deepseek": {"base": "https://d", "model": "m", "api_key": ""},
                           "qwen": {"base": "https://q", "model": "m", "api_key": ""}})
        with self.assertRaises(common.ConfigError) as cm:
            agent.resolve_provider(c)
        self.assertIn("foo", str(cm.exception))
        self.assertIn("deepseek", str(cm.exception))
        self.assertIn("qwen", str(cm.exception))

    def test_missing_base_raises(self):
        c = cfg(provider="qwen", providers={"qwen": {"base": "", "model": "", "api_key": ""}})
        with self.assertRaises(common.ConfigError):
            agent.resolve_provider(c)


class TestChatEndpoint(unittest.TestCase):
    """seam: chat_endpoint —— /v1 规范化。"""

    def test_appends_v1(self):
        self.assertEqual(agent.chat_endpoint("https://api.deepseek.com"),
                         "https://api.deepseek.com/v1/chat/completions")

    def test_keeps_existing_v1(self):
        self.assertEqual(agent.chat_endpoint("https://api.moonshot.cn/v1"),
                         "https://api.moonshot.cn/v1/chat/completions")

    def test_trailing_slash_normalized(self):
        self.assertEqual(agent.chat_endpoint("http://127.0.0.1:11434/v1/"),
                         "http://127.0.0.1:11434/v1/chat/completions")


class TestParseChatResponse(unittest.TestCase):
    """seam: parse_chat_response —— 正文/推理回退/上游错误。"""

    def test_content(self):
        self.assertEqual(agent.parse_chat_response(
            {"choices": [{"message": {"content": "hi"}}]}), "hi")

    def test_reasoning_fallback(self):
        self.assertEqual(agent.parse_chat_response(
            {"choices": [{"message": {"content": "", "reasoning_content": "think"}}]}), "think")

    def test_upstream_error_raises_with_status(self):
        with self.assertRaises(agent.AgentError) as cm:
            agent.parse_chat_response({"error": {"message": "upstream boom"}}, status=401)
        self.assertEqual(cm.exception.status, 401)
        self.assertIn("upstream boom", str(cm.exception))

    def test_no_choices_raises(self):
        with self.assertRaises(agent.AgentError):
            agent.parse_chat_response({"choices": []})


class TestGenerate(unittest.TestCase):
    """seam: generate —— 任务→模板→messages→chat_fn 透传（不触网络）。"""

    def test_storyboard_task_builds_messages_and_returns_chat_result(self):
        captured = {}

        def fake_chat(base, model, key, messages, **kw):
            captured.update(base=base, model=model, key=key, messages=messages)
            return "生成的分镜表"

        c = cfg(provider="deepseek",
                providers={"deepseek": {"base": "https://api.deepseek.com", "model": "m", "api_key": "k"}})
        out = agent.generate("storyboard_from_script",
                             {"script_text": "## 集 1\n镜头序列…", "style": "国风水墨"},
                             cfg=c, chat_fn=fake_chat)
        self.assertEqual(out, "生成的分镜表")
        self.assertEqual(captured["base"], "https://api.deepseek.com")
        self.assertEqual(captured["model"], "m")
        self.assertEqual(captured["key"], "k")
        msgs = captured["messages"]
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")
        self.assertIn("分镜", msgs[1]["content"])
        self.assertIn("## 集 1", msgs[1]["content"])
        self.assertIn("国风水墨", msgs[1]["content"])

    def test_shot_ref_task_builds_prompt_with_shot_fields(self):
        captured = {}

        def fake_chat(base, model, key, messages, **kw):
            captured["content"] = messages[1]["content"]
            return "a cinematic close-up of ..."

        agent.generate("shot_ref",
                       {"shot": "镜1｜场景S01｜景别close-up｜角色C01｜动作：对峙", "style": "ink wash"},
                       cfg=cfg(base="https://b", model="m", api_key=""),
                       chat_fn=fake_chat)
        content = captured["content"]
        self.assertIn("镜1", content)
        self.assertIn("close-up", content)
        self.assertIn("ink wash", content)

    def test_unknown_task_raises(self):
        with self.assertRaises(ValueError) as cm:
            agent.generate("nope", {}, cfg=cfg(base="https://b", model="m", api_key=""),
                           chat_fn=lambda *a, **k: "")
        self.assertIn("nope", str(cm.exception))


class TestChat(unittest.TestCase):
    """seam: chat —— HTTP 调用（mock urlopen）与响应解析。"""

    def test_chat_posts_to_normalized_endpoint_and_returns_content(self):
        payload = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

        class FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload

        with mock.patch("agent.urllib.request.urlopen", return_value=FakeResp()) as urlopen:
            out = agent.chat("https://api.deepseek.com", "m", "k",
                             [{"role": "user", "content": "hi"}])
        self.assertEqual(out, "ok")
        req = urlopen.call_args[0][0]
        self.assertTrue(req.full_url.endswith("/v1/chat/completions"), req.full_url)
        sent = json.loads(req.data.decode("utf-8"))
        self.assertEqual(sent["model"], "m")
        self.assertEqual(sent["messages"][0]["content"], "hi")
        self.assertIn("Authorization", req.headers)


class TestAiWriterCompat(unittest.TestCase):
    """ai_writer 旧调用点 → agent 模块的薄兼容层（spec 03 迁移要求）。"""

    def test_call_llm_delegates_to_agent_chat(self):
        fake_cfg = common.Config({"llm": {"provider": "custom", "base": "https://b",
                                          "model": "m", "api_key": "k"}})
        with mock.patch("agent.chat", return_value="正文") as chat, \
                mock.patch("ai_writer.load_config", return_value=fake_cfg):
            out = ai_writer.call_llm("https://b", "m", "提示词", timeout=30)
        self.assertEqual(out, "正文")
        chat.assert_called_once()
        args = chat.call_args[0]
        self.assertEqual(args[0], "https://b")
        self.assertEqual(args[1], "m")
        self.assertEqual(args[2], "k")
        self.assertEqual(args[3][0]["role"], "system")     # 系统提示词先行（本轮整改）
        self.assertEqual(args[3][1]["content"], "提示词")
        self.assertEqual(chat.call_args[1]["timeout"], 30)


class TestFromScratchWriting(unittest.TestCase):
    """P4a ① 从零编剧：brief_from_idea / novel_from_idea（想法 → 简报 → 小说素材）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_brief_prompt_has_required_sections(self):
        p = ai_writer.brief_from_idea_prompt("民国旗袍女特工复仇", "刺玫")
        for key in ("一句话故事核", "题材与卖点", "目标观众", "整体风格", "主要角色",
                    "关键场景", "一致性锚点", "约束与红线"):
            self.assertIn(key, p)
        self.assertIn("民国旗袍女特工复仇", p)
        self.assertIn("刺玫", p)

    def test_novel_prompt_has_length_and_brief_block(self):
        brief = "## 创作简报\n- 风格：民国谍战"
        p = ai_writer.novel_from_idea_prompt("旗袍女特工复仇", brief, "刺玫")
        self.assertIn("3000-6000", p)
        self.assertIn("创作简报", p)
        self.assertIn("民国谍战", p)
        self.assertIn("旗袍女特工复仇", p)
        self.assertIn("C01/S01/P01", p)

    def test_brief_from_idea_writes_file_and_returns_true(self):
        with mock.patch("ai_writer.llm_available", return_value=(True, "https://b")), \
                mock.patch("ai_writer.pick_model", return_value="m"), \
                mock.patch("ai_writer.call_llm", return_value="## 创作简报\n民国谍战"):
            ok = ai_writer.brief_from_idea("t", "旗袍女特工复仇", "刺玫")
        self.assertTrue(ok)
        self.assertIn("民国谍战", ai_writer.read_brief("t"))

    def test_brief_from_idea_skips_when_exists(self):
        ai_writer.write_brief("t", "已有简报")
        with mock.patch("ai_writer.llm_available") as avail, \
                mock.patch("ai_writer.call_llm") as llm:
            ok = ai_writer.brief_from_idea("t", "想法")
        self.assertTrue(ok)
        avail.assert_not_called()
        llm.assert_not_called()
        self.assertEqual(ai_writer.read_brief("t"), "已有简报")

    def test_brief_from_idea_no_llm_returns_false(self):
        with mock.patch("ai_writer.llm_available", return_value=(False, "")):
            ok = ai_writer.brief_from_idea("t", "想法")
        self.assertFalse(ok)
        self.assertEqual(ai_writer.read_brief("t"), "")

    def test_novel_from_idea_writes_file_with_brief(self):
        ai_writer.write_brief("t", "## 创作简报\n民国谍战")
        with mock.patch("ai_writer.llm_available", return_value=(True, "https://b")), \
                mock.patch("ai_writer.pick_model", return_value="m"), \
                mock.patch("ai_writer.call_llm", return_value="## 第一章\n旗袍女特工潜入…"):
            ok = ai_writer.novel_from_idea("t", "旗袍女特工复仇", "刺玫",
                                           ai_writer.read_brief("t"))
        self.assertTrue(ok)
        self.assertIn("旗袍女特工潜入", ai_writer.read_novel("t"))

    def test_novel_from_idea_skips_when_novel_exists(self):
        ai_writer.write_novel("t", "已有小说")
        with mock.patch("ai_writer.llm_available") as avail, \
                mock.patch("ai_writer.call_llm") as llm:
            ok = ai_writer.novel_from_idea("t", "想法", "标题", "")
        self.assertTrue(ok)
        avail.assert_not_called()
        llm.assert_not_called()
        self.assertEqual(ai_writer.read_novel("t"), "已有小说")

    def test_novel_from_idea_empty_output_returns_false(self):
        with mock.patch("ai_writer.llm_available", return_value=(True, "https://b")), \
                mock.patch("ai_writer.pick_model", return_value="m"), \
                mock.patch("ai_writer.call_llm", return_value="   "):
            ok = ai_writer.novel_from_idea("t", "想法", "标题", "")
        self.assertFalse(ok)
        self.assertEqual(ai_writer.read_novel("t"), "")


class TestLlmStoryboard(unittest.TestCase):
    """seam: ai_writer.llm_storyboard / renumber_storyboard_rows（真实 AI 分镜，本轮整改）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_renumber_rows_by_position(self):
        rows = [{"shot": "7", "frame": "wide"}, {"shot": "2", "frame": "close-up"}]
        out = ai_writer.renumber_storyboard_rows(rows)
        self.assertEqual([r["shot"] for r in out], ["1", "2"])
        self.assertEqual(out[1]["frame"], "close-up")

    def test_llm_storyboard_writes_parsed_rows(self):
        table = ("| 镜号 | 景别 | 运镜 | 时长 | 角色 | 场景 | 灯光 | 对白 | 备注 |\n"
                 "|---|---|---|---|---|---|---|---|---|\n"
                 "| 9 | wide | push in | 5 | C01 | S01 | golden | 对白：你好 | 开场 |\n"
                 "| 3 | close-up | static | 3 | C01 | S01 | golden | 音效：心跳 | 情绪 |\n")

        def fake_chat(base, model, key, messages, **kw):
            return table

        cfg = common.Config({"llm": {"provider": "custom", "base": "https://b",
                                      "model": "m", "api_key": "k"}})
        ai_writer.write_script("t", "## 集 1\n镜头序列")
        dest = ai_writer.llm_storyboard("t", 1, chat_fn=fake_chat, cfg=cfg)
        self.assertIsNotNone(dest)
        rows = gen_storyboard.load_storyboard(dest)
        self.assertEqual([r["shot"] for r in rows], ["1", "2"])   # LLM 乱编号 → 位置重编号
        self.assertEqual(rows[0]["frame"], "wide")

    def test_llm_storyboard_no_script_returns_none(self):
        cfg = common.Config({"llm": {}})
        self.assertIsNone(ai_writer.llm_storyboard("t", 1, chat_fn=lambda *a, **k: "", cfg=cfg))

    def test_llm_storyboard_llm_failure_returns_none(self):
        def boom(*a, **k):
            raise agent.AgentError("upstream", status=500)

        cfg = common.Config({"llm": {"provider": "custom", "base": "https://b",
                                      "model": "m", "api_key": "k"}})
        ai_writer.write_script("t", "## 集 1\n镜头序列")
        self.assertIsNone(ai_writer.llm_storyboard("t", 1, chat_fn=boom, cfg=cfg))


class TestParseCommand(unittest.TestCase):
    """seam: parse_command —— AgentBar 指令 → 动作清单（规则版 dry-run，spec 06 §4）。"""

    def test_storyboard_gen(self):
        self.assertEqual(agent.parse_command("把剧本生成分镜"),
                         [{"task": "storyboard_gen", "shot": None}])

    def test_shot_ref_with_number(self):
        self.assertEqual(agent.parse_command("给第 3 镜生成参考图"),
                         [{"task": "shot_ref", "shot": 3}])

    def test_draw_single_shot(self):
        self.assertEqual(agent.parse_command("重抽镜5的候选"),
                         [{"task": "draw", "shot": 5}])

    def test_compose(self):
        self.assertEqual(agent.parse_command("把这一集拼接成片"),
                         [{"task": "compose", "shot": None}])

    def test_unknown_returns_none(self):
        self.assertEqual(agent.parse_command("今天天气不错"), [])

    def test_multi_actions_order(self):
        self.assertEqual(agent.parse_command("先给第 2 镜生成参考图，然后重抽它的候选"),
                         [{"task": "shot_ref", "shot": 2},
                          {"task": "draw", "shot": 2}])


class TestOnboard(unittest.TestCase):
    """seam: onboard_questions/onboard_brief/parse_questions —— AI 访谈追问（grill 风格）→ 创作简报。"""

    def test_questions_prompt_contains_context_and_scope(self):
        p = agent.build_onboard_questions_prompt(
            {"description": "都市逆袭短剧", "qa": [{"q": "题材？", "a": "逆袭"}]})
        self.assertIn("都市逆袭短剧", p)
        self.assertIn("题材？", p)
        self.assertIn("3-5", p)

    def test_brief_prompt_contains_anchors(self):
        p = agent.build_onboard_brief_prompt(
            {"description": "古风复仇", "qa": [{"q": "风格？", "a": "水墨"}]})
        self.assertIn("古风复仇", p)
        self.assertIn("水墨", p)
        self.assertIn("创作简报", p)

    def test_parse_questions_dash_and_numbered(self):
        self.assertEqual(agent.parse_questions("- 风格是什么？\n- 几集？"),
                         ["风格是什么？", "几集？"])
        self.assertEqual(agent.parse_questions("1. 时长？\n2. 角色设定？"),
                         ["时长？", "角色设定？"])
        self.assertEqual(agent.parse_questions(""), [])
        self.assertEqual(agent.parse_questions("   \n-  \n"), [])

    def test_onboard_tasks_registered(self):
        self.assertIn("onboard_questions", agent._TASKS)
        self.assertIn("onboard_brief", agent._TASKS)


class TestBriefInjection(unittest.TestCase):
    """创作简报注入链式生成（一站式流程的上下文锚点）。"""

    def test_read_brief_and_prompt_injection(self):
        with tempfile.TemporaryDirectory() as d:
            old = common.OUTPUT
            try:
                common.OUTPUT = Path(d)
                ai_writer.write_brief("t", "## 创作简报\n- 题材：都市逆袭\n- 风格：水墨")
                self.assertIn("水墨", ai_writer.read_brief("t"))
                # 注入在 chain/server 层显式传入（prompt 函数保持纯函数）
                p = ai_writer.events_prompt("小说正文", "t", ai_writer.read_brief("t"))
                self.assertIn("创作简报", p)
                self.assertIn("水墨", p)
                self.assertIn("小说正文", p)
                # 无简报时不注入，旧行为不变
                self.assertNotIn("创作简报", ai_writer.events_prompt("x", "t2"))
            finally:
                common.OUTPUT = old


if __name__ == "__main__":
    unittest.main()
