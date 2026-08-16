#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refs 模块单元测试（TDD · M1 分镜参考图，spec: docs/specs/01-htv对标.md）。

seams：save_ref_prompt / load_ref_prompt / list_refs / shot_ref_payload。
运行：
  python -m unittest scripts.test_refs -v      # 从项目根
  python scripts/test_refs.py                   # 直接运行
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common          # noqa: E402
import refs            # noqa: E402


class TestRefs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_save_and_load_roundtrip(self):
        p = refs.save_ref_prompt("t", 1, 3, "cinematic close-up")
        self.assertTrue(p.exists())
        self.assertEqual(p.name, "shot_03.prompt.md")
        self.assertEqual(refs.load_ref_prompt("t", 1, 3), "cinematic close-up")

    def test_load_missing_is_empty(self):
        self.assertEqual(refs.load_ref_prompt("t", 1, 9), "")

    def test_list_refs_pairs_prompt_and_image(self):
        refs.save_ref_prompt("t", 1, 2, "prompt-2")
        d = common.episode_dir("t", 1) / "refs"
        (d / "shot_02.png").write_bytes(b"x")
        (d / "shot_05.jpg").write_bytes(b"x")
        rows = refs.list_refs("t", 1)
        self.assertEqual([(r["shot"], r["prompt"], r["image"]) for r in rows],
                         [(2, "prompt-2", "shot_02.png"), (5, "", "shot_05.jpg")])

    def test_list_refs_empty_dir(self):
        self.assertEqual(refs.list_refs("t", 1), [])

    def test_shot_ref_payload(self):
        row = {"shot": "1", "scene": "S01", "frame": "close-up", "camera": "push in",
               "chars": "C01", "dialogue": "对白：谁在那里", "note": "开场"}
        p = refs.shot_ref_payload(row, style="水墨")
        self.assertIn("镜1", p["shot"])
        self.assertIn("S01", p["shot"])
        self.assertIn("close-up", p["shot"])
        self.assertIn("谁在那里", p["shot"])
        self.assertEqual(p["style"], "水墨")

    def test_promote_first_frame(self):
        """候选首帧 → refs/shot_XX.png（F9：参考图 = 选中片首帧）。"""
        src_dir = common.episode_dir("t", 1) / "shots" / ".review"
        src_dir.mkdir(parents=True, exist_ok=True)
        src = src_dir / "shot_03_02_first.png"
        src.write_bytes(b"png-bytes")
        dest = refs.promote_first_frame("t", 1, 3, src)
        self.assertEqual(dest.name, "shot_03.png")
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_bytes(), b"png-bytes")

    def test_promote_first_frame_missing_src_raises(self):
        with self.assertRaises(FileNotFoundError):
            refs.promote_first_frame("t", 1, 3, common.episode_dir("t", 1) / "nope.png")

    def test_first_frame_candidate(self):
        """从选中文件名推导候选首帧路径：shot_03_02.mp4 → shot_03_02_first.png。"""
        p = refs.first_frame_candidate("t", 1, "shot_03_02.mp4")
        self.assertEqual(p.name, "shot_03_02_first.png")


if __name__ == "__main__":
    unittest.main()
