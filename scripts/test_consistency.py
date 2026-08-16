#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P6a 数据一致性测试（docs/12 §5 / docs/13 §3 P6a 3-5）。

- selected 幽灵过滤（/api/episode-status 与 /api/canvas 共用 server.selected_shot_files）
- render 硬前置（server.render_precheck：refs/*.prompt.md 缺失 → 拒绝）
运行：
  python -m unittest scripts.test_consistency -v      # 从项目根
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "web"))

import common          # noqa: E402
import server          # noqa: E402  复用 selected_shot_files / render_precheck


def _seed_board(project="t", episode=1, shots=(1, 2)):
    e = common.episode_dir(project, episode)
    e.mkdir(parents=True, exist_ok=True)
    lines = ["# E01 分镜", "",
             "| 镜号 | 景别 | 机位运动 | 时长 | 角色 | 场景 | 灯光 | 对白/音效 | 备注 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for n in shots:
        lines.append("| %d | medium | static | 5 | C01 | S01 | day | | |" % n)
    (e / "分镜.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_selected(project="t", episode=1, nums=(1, 2, 3)):
    d = common.episode_dir(project, episode) / "shots"
    d.mkdir(parents=True, exist_ok=True)
    for n in nums:
        (d / ("shot_%02d.mp4" % n)).write_bytes(b"x")


class TestSelectedGhostFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_keeps_only_existing_storyboard_shots(self):
        _seed_board(shots=(1, 2))
        _seed_selected(nums=(1, 2, 3))      # shot_03.mp4 是幽灵（分镜无第 3 镜）
        self.assertEqual(server.selected_shot_files("t", 1), ["shot_01.mp4", "shot_02.mp4"])

    def test_storyboard_row_deleted_filters_selected(self):
        _seed_board(shots=(1, 2, 3))
        _seed_selected(nums=(1, 2, 3))
        # 删除第 2 镜（重写分镜表）
        _seed_board(shots=(1, 3))
        self.assertEqual(server.selected_shot_files("t", 1), ["shot_01.mp4", "shot_03.mp4"])

    def test_no_storyboard_filters_all(self):
        _seed_selected(nums=(1, 2))
        self.assertEqual(server.selected_shot_files("t", 1), [])

    def test_no_selected_returns_empty(self):
        _seed_board(shots=(1, 2))
        self.assertEqual(server.selected_shot_files("t", 1), [])


class TestRenderPrecheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)
        _seed_board(shots=(1, 2))

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def _mk_prompt(self, shot):
        p = common.episode_dir("t", 1) / "refs" / ("shot_%02d.prompt.md" % shot)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("integrated_multimodal_description: x", encoding="utf-8")

    def test_missing_all_rejected(self):
        ok, missing = server.render_precheck("t", 1)
        self.assertFalse(ok)
        self.assertEqual(missing, [1, 2])

    def test_partial_missing(self):
        self._mk_prompt(1)
        ok, missing = server.render_precheck("t", 1)
        self.assertFalse(ok)
        self.assertEqual(missing, [2])

    def test_only_filter(self):
        self._mk_prompt(2)
        ok, missing = server.render_precheck("t", 1, only="2")
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_only_as_list(self):
        # /api/render 的 only 字段可能是 JSON 数组（前端传 [1,2]）
        self._mk_prompt(2)
        ok, missing = server.render_precheck("t", 1, only=[1, 2])
        self.assertFalse(ok)
        self.assertEqual(missing, [1])

    def test_all_present_passes(self):
        self._mk_prompt(1)
        self._mk_prompt(2)
        ok, missing = server.render_precheck("t", 1)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_no_storyboard_returns_none_semantics(self):
        (common.episode_dir("t", 1) / "分镜.md").unlink()
        ok, missing = server.render_precheck("t", 1)
        self.assertFalse(ok)
        self.assertEqual(missing, [])   # 空 = 缺分镜，调用方给「先生成分镜」引导


if __name__ == "__main__":
    unittest.main()
