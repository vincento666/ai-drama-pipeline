#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agentbridge ACP 适配器单元测试（TDD · spec 11：交互式对话）。

seams：_text_blocks / _update_text（纯函数帧解析）；AcpAdapter.chat 的帧循环（注入假帧）。
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import agentbridge   # noqa: E402


class TestAcpParsers(unittest.TestCase):
    def test_text_blocks(self):
        result = {"message": {"role": "assistant", "content": [
            {"type": "text", "text": "你好"},
            {"type": "tool_call", "name": "Read"},
            {"type": "text", "text": "世界"},
        ]}}
        self.assertEqual(agentbridge._text_blocks(result), ["你好", "世界"])

    def test_text_blocks_empty(self):
        self.assertEqual(agentbridge._text_blocks({}), [])

    def test_update_text_tool_summary(self):
        msg = {"role": "assistant", "content": [
            {"type": "tool_call", "name": "Bash"},
            {"type": "text", "text": "结果行"},
        ]}
        s = agentbridge._update_text(msg)
        self.assertIn("[调用 Bash]", s)
        self.assertIn("结果行", s)

    def test_update_text_plain(self):
        self.assertEqual(agentbridge._update_text("裸文本"), "裸文本")


class _StubProc:
    def poll(self):
        return None

    class _Stdin:
        @staticmethod
        def write(s):
            return len(s)

        @staticmethod
        def flush():
            return None

    stdin = _Stdin()


class TestAcpChatLoop(unittest.TestCase):
    """chat 帧循环：注入假帧到内部队列，验证文本收集与 on_line 回调（不启真实进程）。"""

    def _mk(self):
        a = agentbridge.AcpAdapter(cwd="C:\\x")
        a.proc = _StubProc()          # 桩：跳过 start() 的真实 spawn
        a.session_id = "s1"
        a._q.put(json.dumps({"jsonrpc": "2.0", "method": "session/update",
                             "params": {"sessionId": "s1", "update": {
                                 "sessionUpdate": "agent_thought_chunk",
                                 "content": {"type": "text", "text": "思考中"}}}}))
        a._q.put(json.dumps({"jsonrpc": "2.0", "method": "session/update",
                             "params": {"sessionId": "s1", "update": {
                                 "sessionUpdate": "agent_message_chunk",
                                 "content": {"type": "text", "text": "最终"}}}}))
        a._q.put(json.dumps({"jsonrpc": "2.0", "method": "session/update",
                             "params": {"sessionId": "s1", "update": {
                                 "sessionUpdate": "agent_message_chunk",
                                 "content": {"type": "text", "text": "回答"}}}}))
        a._q.put(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"stopReason": "end_turn"}}))
        return a

    def test_chat_collects_text_and_streams(self):
        a = self._mk()
        lines = []
        text, updates = a.chat("你好", on_line=lines.append, timeout=5)
        self.assertEqual(text, "最终回答")          # 消息块拼接（思考块不计入）
        self.assertEqual(lines, ["最终", "回答"])   # on_line 收到的是各块原文
        self.assertEqual(len(updates), 3)

    def test_chat_interrupt_raises(self):
        a = agentbridge.AcpAdapter(cwd="C:\\x")
        a.proc = _StubProc()
        a.session_id = "s1"
        a._q.put(json.dumps({"jsonrpc": "2.0", "method": "session/update",
                             "params": {"state": "interrupted"}}))
        with self.assertRaises(RuntimeError):
            a.chat("hi", timeout=5)


if __name__ == "__main__":
    unittest.main()
