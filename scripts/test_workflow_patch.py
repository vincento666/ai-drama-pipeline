#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workflow_patch 单元测试（TDD · spec: docs/specs/09-agent工作台.md P1 写盘核心）。

seams：patch_shot / patch_script_block / patch_ref_prompt / parse_edit_action / apply_patch。
运行：
  python -m unittest scripts.test_workflow_patch -v      # 从项目根
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common            # noqa: E402
import workflow_patch    # noqa: E402
import ai_writer         # noqa: E402
import refs              # noqa: E402
from gen_storyboard import load_storyboard  # noqa: E402


def _seed_board(project="t", episode=1):
    """种子分镜：两行，表头含注释行。"""
    e = common.episode_dir(project, episode)
    e.mkdir(parents=True, exist_ok=True)
    text = (
        "# E01 分镜（t）\n"
        "> 由 AI（LLM）按剧本生成\n\n"
        "| 镜号 | 景别 | 机位运动 | 时长 | 角色 | 场景 | 灯光 | 对白/音效 | 备注 |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| 1 | close-up | push in | 4 | C01 | S01 | golden hour | 对白：你好 | 开场 |\n"
        "| 2 | wide | static | 5 | C02 | S02 | night | 音效：风声 | 结尾 |\n"
    )
    (e / "分镜.md").write_text(text, encoding="utf-8")


class TestPatchShot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)
        _seed_board()

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_patch_shot_field_persisted(self):
        r = workflow_patch.patch_shot("t", 1, 1, "light", "夜景")
        self.assertEqual(r["field"], "light")
        rows = load_storyboard(common.episode_dir("t", 1) / "分镜.md")
        self.assertEqual(rows[0]["light"], "夜景")
        self.assertEqual(rows[1]["light"], "night")     # 其他行不动

    def test_patch_shot_preserves_header(self):
        workflow_patch.patch_shot("t", 1, 2, "note", "改过的备注")
        text = (common.episode_dir("t", 1) / "分镜.md").read_text(encoding="utf-8")
        self.assertIn("# E01 分镜（t）", text)
        self.assertIn("> 由 AI（LLM）按剧本生成", text)

    def test_patch_shot_missing_shot_raises(self):
        with self.assertRaises(ValueError):
            workflow_patch.patch_shot("t", 1, 9, "light", "x")


class TestParseEditAction(unittest.TestCase):
    def test_parse_shot_light(self):
        self.assertEqual(workflow_patch.parse_edit_action("把镜3的灯光改为夜景"),
                         [{"op": "shot", "shot": 3, "field": "light", "value": "夜景"}])

    def test_parse_shot_dialogue_with_colon(self):
        self.assertEqual(workflow_patch.parse_edit_action("第 5 镜对白改成：你走吧"),
                         [{"op": "shot", "shot": 5, "field": "dialogue", "value": "你走吧"}])

    def test_parse_unresolvable_empty(self):
        self.assertEqual(workflow_patch.parse_edit_action("今天天气不错"), [])


class TestScriptAndRef(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_patch_script_block(self):
        ai_writer.write_script("t", "旧剧本")
        r = workflow_patch.patch_script_block("t", "script", "新剧本")
        self.assertEqual(r["block"], "script")
        self.assertEqual(ai_writer.read_script("t"), "新剧本")

    def test_patch_script_block_brief(self):
        ai_writer.write_brief("t", "旧简报")
        workflow_patch.patch_script_block("t", "brief", "新简报")
        self.assertEqual(ai_writer.read_brief("t"), "新简报")

    def test_patch_ref_prompt(self):
        r = workflow_patch.patch_ref_prompt("t", 1, 3, "新提示词")
        self.assertEqual(refs.load_ref_prompt("t", 1, 3), "新提示词")
        self.assertEqual(r["shot"], 3)


class TestApplyPatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)
        _seed_board()

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_apply_multi_changes(self):
        result = workflow_patch.apply_patch("t", [
            {"op": "shot", "shot": 1, "field": "light", "value": "夜景"},
            {"op": "shot", "shot": 2, "field": "note", "value": "新备注"},
        ], episode=1)
        self.assertEqual(len(result["applied"]), 2)
        self.assertEqual(result["errors"], [])
        rows = load_storyboard(common.episode_dir("t", 1) / "分镜.md")
        self.assertEqual(rows[0]["light"], "夜景")
        self.assertEqual(rows[1]["note"], "新备注")

    def test_apply_bad_change_reports_error(self):
        result = workflow_patch.apply_patch("t", [
            {"op": "shot", "shot": 99, "field": "light", "value": "x"},
        ], episode=1)
        self.assertEqual(result["applied"], [])
        self.assertEqual(len(result["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
