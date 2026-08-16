#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agentbridge 追加测试（TDD · spec 09 v2：统一侧边对话窗）。

seams：facts_rev（事实源 mtime 摘要）、build_project_summary（项目文档摘要）。
运行：
  python -m unittest scripts.test_agentbridge -v      # 从项目根
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common           # noqa: E402
import ai_writer        # noqa: E402（P4a ③：看板段文件探测）
import agentbridge      # noqa: E402


class TestFactsRev(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)
        self.old_assets = common.ASSETS
        common.ASSETS = Path(self.tmp.name) / "assets"

    def tearDown(self):
        common.OUTPUT = self.old
        common.ASSETS = self.old_assets
        self.tmp.cleanup()

    def test_rev_changes_when_storyboard_edited(self):
        e = common.episode_dir("t", 1)
        (e / "分镜.md").write_text("x", encoding="utf-8")
        r1 = agentbridge.facts_rev("t", 1)
        time.sleep(0.02)
        (e / "分镜.md").write_text("y", encoding="utf-8")
        r2 = agentbridge.facts_rev("t", 1)
        self.assertNotEqual(r1, r2)

    def test_rev_stable_without_changes(self):
        e = common.episode_dir("t", 1)
        (e / "分镜.md").write_text("x", encoding="utf-8")
        r1 = agentbridge.facts_rev("t", 1)
        r2 = agentbridge.facts_rev("t", 1)
        self.assertEqual(r1, r2)

    def test_rev_changes_when_script_edited(self):
        (common.project_dir("t") / "剧本.md").write_text("a", encoding="utf-8")
        r1 = agentbridge.facts_rev("t", 1)
        time.sleep(0.02)
        (common.project_dir("t") / "剧本.md").write_text("b", encoding="utf-8")
        self.assertNotEqual(r1, agentbridge.facts_rev("t", 1))


class TestBuildProjectSummary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_summary_contains_blocks_and_counts(self):
        p = common.project_dir("t")
        (p / "剧本.md").write_text("逐集剧本内容", encoding="utf-8")
        e = common.episode_dir("t", 1)
        (e / "分镜.md").write_text(
            "| 镜号 | 景别 |\n|---|---|\n| 1 | wide |\n", encoding="utf-8")
        s = agentbridge.build_project_summary("t", 1)
        self.assertIn("剧本", s)
        self.assertIn("1 镜", s)
        self.assertIn("逐集剧本内容", s)

    def test_summary_handles_empty_project(self):
        s = agentbridge.build_project_summary("empty", 1)
        self.assertIn("empty", s)
        self.assertIn("0 镜", s)

    def test_summary_has_kanban_section_with_marks(self):
        """P4a ③：制作看板状态段——文件存在性/镜数/已选片/ComfyUI 配置。"""
        p = common.project_dir("t")
        (p / ai_writer.BRIEF_FILE).write_text("## 创作简报\n民国", encoding="utf-8")
        (p / ai_writer.NOVEL_FILE).write_text("小说", encoding="utf-8")
        e = common.episode_dir("t", 1)
        (e / "分镜.md").write_text(
            "| 镜号 | 景别 |\n|---|---|\n| 1 | wide |\n| 2 | medium |\n", encoding="utf-8")
        (e / "shots").mkdir(exist_ok=True)
        (e / "shots" / "shot_01.mp4").write_bytes(b"x")
        (e / "shots" / "shot_02.mp4").write_bytes(b"x")
        s = agentbridge.build_project_summary("t", 1)
        self.assertIn("## 制作看板状态", s)
        self.assertIn("✅ 创作简报.md", s)
        self.assertIn("✅ 小说.md", s)
        self.assertIn("⬜ 剧本.md", s)
        self.assertIn("分镜镜数：2 镜", s)
        self.assertIn("已选片：2 个", s)
        self.assertIn("ComfyUI", s)

    def test_kanban_shot_count_ignores_candidates(self):
        e = common.episode_dir("t", 1)
        (e / "分镜.md").write_text(
            "| 镜号 | 景别 |\n|---|---|\n| 1 | wide |\n", encoding="utf-8")
        cand = e / "shots" / ".candidates"
        cand.mkdir(parents=True, exist_ok=True)
        (e / "shots" / "shot_01.mp4").write_bytes(b"x")
        (cand / "shot_01_01.mp4").write_bytes(b"x")   # 候选不计入已选片
        s = agentbridge.build_project_summary("t", 1)
        self.assertIn("已选片：1 个", s)


class TestGetAdapter(unittest.TestCase):
    """spec 10：适配器从 config.yaml agent.adapters 构造（args/skills_dir/timeout）。"""

    def test_kimi_adapter_has_skills_dir(self):
        a = agentbridge.get_adapter("kimi")
        self.assertEqual(a.cli, "kimi")
        self.assertIn("--skills-dir", a.prompt_args)
        self.assertTrue(any("skills" in str(x) for x in a.prompt_args))
        self.assertIn("-m", a.prompt_args)
        self.assertEqual(a.timeout, 1800)

    def test_codex_adapter_exec(self):
        a = agentbridge.get_adapter("codex")
        self.assertEqual(a.cli, "codex")
        self.assertIn("exec", a.prompt_args)

    def test_unknown_adapter_raises(self):
        with self.assertRaises(ValueError):
            agentbridge.get_adapter("nope")


class TestFlowTemplates(unittest.TestCase):
    def test_templates_cover_stages(self):
        keys = [t["key"] for t in agentbridge.flow_templates()]
        for k in ("onboard", "aiwrite", "storyboard", "shotref", "draw", "compose", "polish"):
            self.assertIn(k, keys)

    def test_polish_template_mentions_cli(self):
        t = next(t for t in agentbridge.flow_templates() if t["key"] == "polish")
        self.assertIn("cli.py", t["goal"])


class TestRunLoop(unittest.TestCase):
    """LHH 自动循环（Manager→Executor→Auditor）：状态机与 checkpoint/evidence。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_loop_completes_on_verified_round(self):
        decisions = iter(["任务一", "任务二", "完成"])
        def decide(g, s):
            return next(decisions, "完成")
        def verify(p, ep, rev_before):
            return True, "r1"
        lid, state = agentbridge.run_loop("t", "目标", decide=decide, verify=verify,
                                          max_rounds=8)
        self.assertEqual(state["verified"], [1])
        self.assertEqual(state["rounds"], 1)
        d = agentbridge.common.project_dir("t") / "agent" / "loops" / lid
        self.assertTrue((d / "checkpoint.json").exists())

    def test_loop_evidence_on_failure_then_completes(self):
        calls = {"n": 0}
        def decide(g, s):
            calls["n"] += 1
            return "完成" if calls["n"] > 3 else "任务"
        def verify(p, ep, rev_before):
            return calls["n"] >= 3, "info"
        lid, state = agentbridge.run_loop("t", "目标", decide=decide, verify=verify,
                                          max_rounds=8)
        self.assertEqual(len(state["evidence"]), 2)
        self.assertEqual(state["verified"], [3])
        d = agentbridge.common.project_dir("t") / "agent" / "loops" / lid
        self.assertTrue((d / "evidence.md").exists())

    def test_loop_stops_at_max_rounds(self):
        def decide(g, s):
            return "任务"
        def verify(p, ep, rev_before):
            return False, "x"
        lid, state = agentbridge.run_loop("t", "目标", decide=decide, verify=verify,
                                          max_rounds=3)
        self.assertEqual(state["rounds"], 3)
        self.assertEqual(state["verified"], [])

    def test_loop_breaks_when_done(self):
        def decide(g, s):
            return "完成"
        def verify(p, ep, rev_before):
            return False, "x"
        lid, state = agentbridge.run_loop("t", "目标", decide=decide, verify=verify)
        self.assertEqual(state["rounds"], 0)


class TestBusinessAudits(unittest.TestCase):
    """Auditor 业务校验（分镜可解析/剧本非空/资产完整/成片存在）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_storyboard_parses(self):
        e = common.episode_dir("t", 1)
        (e / "分镜.md").write_text(
            "| 镜号 | 景别 |\n|---|---|\n| 1 | wide |\n", encoding="utf-8")
        ok, info = agentbridge.audit_storyboard_parses("t", 1)
        self.assertTrue(ok)
        self.assertIn("1 镜", info)

    def test_storyboard_missing_fails(self):
        ok, info = agentbridge.audit_storyboard_parses("t", 1)
        self.assertFalse(ok)

    def test_script_present(self):
        common.project_dir("t")
        from pathlib import Path as P
        (P(common.project_dir("t")) / "剧本.md").write_text("剧本", encoding="utf-8")
        ok, info = agentbridge.audit_script_present("t")
        self.assertTrue(ok)

    def test_script_missing(self):
        ok, info = agentbridge.audit_script_present("t")
        self.assertFalse(ok)

    def test_assets_valid_and_composed(self):
        ok, _ = agentbridge.audit_assets_valid("t")
        self.assertTrue(ok)
        ok, _ = agentbridge.audit_composed("t", 1)
        self.assertFalse(ok)
        e = common.episode_dir("t", 1)
        (e / "成片.mp4").write_bytes(b"x")
        ok, _ = agentbridge.audit_composed("t", 1)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
