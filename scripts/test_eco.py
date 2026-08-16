#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P4 设置页后端测试（docs/11 §6）：/api/eco 生态清单 + /api/config-agent/test 连通探测。

测试对象为 web/server.py 的模块级函数（桥只做路由与序列化，业务逻辑可测）：
  list_local_skills / eco_items / run_eco_cmd / probe_adapter_cli / harness_detection

运行：
  python -m pytest scripts/test_eco.py -q -s      # 从项目根（-s 避免 pytest 吞 stdin 影响 _payload）
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "web"))

import server                    # noqa: E402
import agentbridge               # noqa: E402


class TestLocalSkills(unittest.TestCase):
    def test_lists_real_repo_skills(self):
        skills = server.list_local_skills()
        self.assertIsInstance(skills, list)
        self.assertTrue(skills)
        caveman = next((s for s in skills if s["id"] == "caveman"), None)
        self.assertIsNotNone(caveman)
        self.assertEqual(caveman["type"], "skill")
        self.assertTrue(caveman["installed"])
        self.assertIn("path", caveman)
        # frontmatter name 解析：caveman 的 SKILL.md frontmatter name = caveman
        self.assertEqual(caveman["name"], "caveman")

    def test_missing_dir_returns_empty(self):
        with mock.patch("server.ROOT", Path(tempfile.mkdtemp())):
            self.assertEqual(server.list_local_skills(), [])

    def test_skills_have_desc_or_name(self):
        for s in server.list_local_skills():
            self.assertTrue(s["name"])
            self.assertIsInstance(s["desc"], str)


class TestEcoItems(unittest.TestCase):
    def test_manifest_items_with_mapped_types(self):
        items = server.eco_items()
        by_id = {i["id"]: i for i in items}
        self.assertIn("audio-t8", by_id)
        self.assertEqual(by_id["audio-t8"]["type"], "plugin")
        self.assertIn("prompt-skill", by_id)
        self.assertEqual(by_id["prompt-skill"]["type"], "skill")
        self.assertIn("auto-short-drama", by_id)
        self.assertEqual(by_id["auto-short-drama"]["type"], "h3")
        for i in items:
            self.assertIn(i["type"], ("plugin", "skill", "h3"))
            self.assertIn("installed", i)
            self.assertTrue(i["name"])

    def test_includes_local_skills(self):
        items = server.eco_items()
        ids = {i["id"] for i in items}
        self.assertIn("caveman", ids)


class TestRunEcoCmd(unittest.TestCase):
    def test_refresh_returns_list_output(self):
        code, output = server.run_eco_cmd("refresh")
        self.assertEqual(code, 0)
        self.assertIn("生态", output)
        self.assertIn("custom_nodes", output)

    def test_install_unknown_id_errors(self):
        code, output = server.run_eco_cmd("install", "nope-unknown")
        self.assertNotEqual(code, 0)
        self.assertIn("未知插件", output)

    def test_check_unknown_id_errors(self):
        code, output = server.run_eco_cmd("check", "nope-unknown")
        self.assertNotEqual(code, 0)


class FakeAdapter:
    def __init__(self, cli, prompt_args=None):
        self.cli = cli
        self.prompt_args = prompt_args or []


class TestProbeAdapterCli(unittest.TestCase):
    def test_real_cli_version(self):
        ok, output = server.probe_adapter_cli(FakeAdapter("python"), timeout=15)
        self.assertTrue(ok)
        self.assertIn("Python", output)

    def test_missing_cli_reports_false(self):
        ok, output = server.probe_adapter_cli(FakeAdapter("definitely-no-such-cli-xyz"))
        self.assertFalse(ok)
        self.assertIn("未找到", output)

    def test_bad_arg_falls_back_to_version(self):
        # 第一个候选（带无效参数的 --version）失败 → 回退裸 --version
        ok, output = server.probe_adapter_cli(
            FakeAdapter("python", ["--definitely-invalid-flag"]), timeout=15)
        self.assertTrue(ok)
        self.assertIn("Python", output)

    def test_kimi_adapter_probe(self):
        a = agentbridge.get_adapter("kimi")
        ok, output = server.probe_adapter_cli(a, timeout=15)
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(output, str)


class TestHarnessDetection(unittest.TestCase):
    def test_returns_triple_with_lhh(self):
        ok, output, lhh = server.harness_detection()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(output, str)
        self.assertIn("available", lhh)
        for key in ("source", "version", "dsh_cli", "win_loop", "sync", "reused"):
            self.assertIn(key, lhh)
        self.assertIn("LHH", output)


if __name__ == "__main__":
    unittest.main()
