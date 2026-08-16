#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli 模块单元测试（TDD · spec: docs/specs/04-harness接口.md）。

seams：cli.main(argv) -> (exit_code, output_text)；命令编排（mock agent 层，不触网络）。
退出码：0 成功 / 2 参数错 / 3 配置错 / 4 上游错误。
运行：
  python -m unittest scripts.test_cli -v      # 从项目根
  python scripts/test_cli.py                   # 直接运行
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import agent           # noqa: E402
import cli             # noqa: E402
import common          # noqa: E402

FAKE_PROVIDER = {"provider": "deepseek", "base": "https://b", "model": "m", "api_key": "k"}


class TestAgentChat(unittest.TestCase):
    def test_chat_returns_text(self):
        with mock.patch("cli.agent.resolve_provider", return_value=FAKE_PROVIDER), \
                mock.patch("cli.agent.chat", return_value="生成结果") as chat:
            code, out = cli.main(["agent", "chat", "写三镜分镜"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "生成结果")
        chat.assert_called_once()
        messages = chat.call_args[0][3]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["content"], "写三镜分镜")

    def test_chat_json_output(self):
        with mock.patch("cli.agent.resolve_provider", return_value=FAKE_PROVIDER), \
                mock.patch("cli.agent.chat", return_value="结果"):
            code, out = cli.main(["--json", "agent", "chat", "hi"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["text"], "结果")

    def test_chat_empty_prompt_code2(self):
        code, out = cli.main(["agent", "chat", "   "])
        self.assertEqual(code, 2)

    def test_chat_upstream_error_code4(self):
        with mock.patch("cli.agent.resolve_provider", return_value=FAKE_PROVIDER), \
                mock.patch("cli.agent.chat", side_effect=agent.AgentError("上游错误", status=500)):
            code, out = cli.main(["agent", "chat", "hi"])
        self.assertEqual(code, 4)
        self.assertIn("上游错误", out)

    def test_chat_config_error_code3(self):
        with mock.patch("cli.agent.resolve_provider",
                        side_effect=common.ConfigError("缺少配置")):
            code, out = cli.main(["agent", "chat", "hi"])
        self.assertEqual(code, 3)

    def test_chat_reads_in_file(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with open(fd, "w", encoding="utf-8") as fh:
            fh.write("文件里的提示词")
        try:
            with mock.patch("cli.agent.resolve_provider", return_value=FAKE_PROVIDER), \
                    mock.patch("cli.agent.chat", return_value="x") as chat:
                code, out = cli.main(["agent", "chat", "--in", path])
            self.assertEqual(code, 0)
            self.assertEqual(chat.call_args[0][3][1]["content"], "文件里的提示词")
        finally:
            Path(path).unlink(missing_ok=True)


class TestAgentGenerate(unittest.TestCase):
    def test_generate_task_default_payload(self):
        with mock.patch("cli.agent.generate", return_value="分镜文本") as gen:
            code, out = cli.main(["agent", "generate", "storyboard_from_script"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "分镜文本")
        gen.assert_called_once_with("storyboard_from_script", {})

    def test_generate_payload_from_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with open(fd, "w", encoding="utf-8") as fh:
            json.dump({"script_text": "剧本", "style": "水墨"}, fh)
        try:
            with mock.patch("cli.agent.generate", return_value="x") as gen:
                code, out = cli.main(["agent", "generate", "storyboard_from_script", "--in", path])
            self.assertEqual(code, 0)
            gen.assert_called_once_with("storyboard_from_script", {"script_text": "剧本", "style": "水墨"})
        finally:
            Path(path).unlink(missing_ok=True)

    def test_generate_json_mode(self):
        with mock.patch("cli.agent.generate", return_value="文本"):
            code, out = cli.main(["--json", "agent", "generate", "shot_ref"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["text"], "文本")

    def test_generate_upstream_error_code4(self):
        with mock.patch("cli.agent.generate", side_effect=agent.AgentError("boom", status=500)):
            code, out = cli.main(["agent", "generate", "storyboard_from_script"])
        self.assertEqual(code, 4)

    def test_generate_unknown_task_code2(self):
        with mock.patch("cli.agent.generate", side_effect=ValueError("未知任务: x")):
            code, out = cli.main(["agent", "generate", "x"])
        self.assertEqual(code, 2)

    def test_generate_missing_task_code2(self):
        code, out = cli.main(["agent", "generate"])
        self.assertEqual(code, 2)


class TestGlobalErrors(unittest.TestCase):
    def test_unknown_command_code2(self):
        code, out = cli.main(["nope"])
        self.assertEqual(code, 2)

    def test_unknown_command_json(self):
        code, out = cli.main(["--json", "nope"])
        self.assertEqual(code, 2)
        data = json.loads(out)
        self.assertFalse(data["ok"])
        self.assertEqual(data["code"], 2)


class TestAgentRun(unittest.TestCase):
    """agent-run / agent-resume / agent-list（spec 08，mock agentbridge 层）。"""

    def test_agent_run_calls_run_task_with_goal(self):
        with mock.patch("cli.agentbridge.run_task", return_value="t0001") as rt, \
                mock.patch("cli.agentbridge.get_adapter", return_value=object()), \
                mock.patch("cli.agentbridge.read_task",
                           return_value={"status": "done", "transcript": ["行1"],
                                        "result": {"ok": True}}):
            code, out = cli.main(["agent-run", "t", "--goal", "审查分镜", "--agent", "kimi"])
        self.assertEqual(code, 0)
        self.assertIn("t0001", out)
        self.assertEqual(rt.call_args[0][1], "审查分镜")

    def test_agent_run_json(self):
        with mock.patch("cli.agentbridge.run_task", return_value="t0002"), \
                mock.patch("cli.agentbridge.get_adapter", return_value=object()), \
                mock.patch("cli.agentbridge.read_task",
                           return_value={"status": "done", "transcript": [],
                                        "result": {"ok": True, "exit_code": 0}}):
            code, out = cli.main(["--json", "agent-run", "t", "--goal", "g"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["task_id"], "t0002")
        self.assertTrue(data["ok"])

    def test_agent_run_missing_goal_code2(self):
        code, out = cli.main(["agent-run", "t"])
        self.assertEqual(code, 2)

    def test_agent_list_json(self):
        with mock.patch("cli.agentbridge.list_tasks",
                        return_value=[{"id": "t1", "status": "done"}]):
            code, out = cli.main(["--json", "agent-list", "t"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["tasks"][0]["id"], "t1")

    def test_agent_resume_reads_goal_and_reruns(self):
        task_dir = {"goal.md": "原目标", "prompt.txt": "原上下文"}

        class FakeFile:
            def __init__(self, name):
                self.name = name

            def read_text(self, encoding="utf-8"):
                return task_dir.get(self.name, "")

        class FakeDir:
            def __truediv__(self, name):
                return FakeFile(str(name))

        with mock.patch("cli.agentbridge.read_task",
                        return_value={"status": "failed", "transcript": [], "result": None}), \
                mock.patch("cli.agentbridge.task_dir", return_value=FakeDir()), \
                mock.patch("cli.agentbridge.get_adapter", return_value=object()), \
                mock.patch("cli.agentbridge.run_task", return_value="t0003") as rt:
            code, out = cli.main(["agent-resume", "t", "t0001"])
        self.assertEqual(code, 0)
        self.assertIn("t0003", out)
        self.assertIn("原目标", rt.call_args[0][1])

    def test_agent_loop_requires_goal(self):
        code, out = cli.main(["agent-loop", "t"])
        self.assertEqual(code, 2)

    def test_agent_loop_calls_run_loop_with_audit(self):
        with mock.patch("cli.agentbridge.get_adapter", return_value=object()), \
                mock.patch("cli.agentbridge.run_loop",
                           return_value=("L0001", {"rounds": 1, "verified": [1],
                                                  "evidence": []})) as rl:
            code, out = cli.main(["--json", "agent-loop", "t", "--goal", "g",
                                  "--audit", "storyboard,script", "--max-rounds", "3"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["loop_id"], "L0001")
        self.assertEqual(rl.call_args[1]["max_rounds"], 3)
        self.assertTrue(callable(rl.call_args[1]["verify"]))


if __name__ == "__main__":
    unittest.main()
