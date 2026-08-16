#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compose_order 单元测试（docs/13 §3 P6a 4：成片顺序 E{n}/compose.order.json）。

seams：read_order / write_order / validate_order / resolve_order / apply_natural_order。
运行：
  python -m unittest scripts.test_compose_order -v      # 从项目根
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common          # noqa: E402
import compose_order   # noqa: E402


def _seed_board(project="t", episode=1, shots=(1, 2, 3)):
    e = common.episode_dir(project, episode)
    e.mkdir(parents=True, exist_ok=True)
    lines = ["# E01 分镜", "",
             "| 镜号 | 景别 | 机位运动 | 时长 | 角色 | 场景 | 灯光 | 对白/音效 | 备注 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for n in shots:
        lines.append("| %d | medium | static | 5 | C01 | S01 | day | | |" % n)
    (e / "分镜.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestValidateOrder(unittest.TestCase):
    def test_valid_order(self):
        self.assertEqual(compose_order.validate_order([1, 3, 2]), (True, ""))

    def test_rejects_duplicates(self):
        ok, err = compose_order.validate_order([1, 1, 2])
        self.assertFalse(ok)
        self.assertIn("重复", err)

    def test_rejects_non_int(self):
        self.assertFalse(compose_order.validate_order([1, "2"])[0])
        self.assertFalse(compose_order.validate_order([1, 2.5])[0])

    def test_rejects_out_of_range(self):
        ok, err = compose_order.validate_order([1, 99], valid={1, 2, 3})
        self.assertFalse(ok)
        self.assertIn("超出", err)

    def test_empty_rejected(self):
        self.assertFalse(compose_order.validate_order([])[0])


class TestReadWriteOrder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)
        _seed_board()

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_absent_returns_none(self):
        self.assertIsNone(compose_order.read_order("t", 1))

    def test_write_then_read(self):
        r = compose_order.write_order("t", 1, [1, 3, 2])
        self.assertTrue(r["ok"])
        self.assertEqual(compose_order.read_order("t", 1), [1, 3, 2])
        p = common.episode_dir("t", 1) / "compose.order.json"
        self.assertTrue(p.exists())

    def test_write_invalid_not_persisted(self):
        r = compose_order.write_order("t", 1, [1, 99])
        self.assertFalse(r["ok"])
        self.assertIsNone(compose_order.read_order("t", 1))

    def test_write_out_of_range_validated_against_board(self):
        # 不传 valid → 自动用分镜行镜号校验
        r = compose_order.write_order("t", 1, [1, 5])
        self.assertFalse(r["ok"])

    def test_clear_order(self):
        compose_order.write_order("t", 1, [1, 3, 2])
        self.assertTrue(compose_order.clear_order("t", 1))
        self.assertIsNone(compose_order.read_order("t", 1))

    def test_resolve_default_is_storyboard_order(self):
        order, source = compose_order.resolve_order("t", 1)
        self.assertEqual(order, [1, 2, 3])
        self.assertEqual(source, "storyboard")


class TestApplyNaturalOrder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)
        _seed_board()

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_move_before(self):
        r = compose_order.apply_natural_order("t", 1, "把镜3放到镜1前面")
        self.assertTrue(r["ok"])
        self.assertEqual(r["order"], [3, 1, 2])

    def test_move_after(self):
        r = compose_order.apply_natural_order("t", 1, "把镜1放到镜3后面")
        self.assertTrue(r["ok"])
        self.assertEqual(r["order"], [2, 3, 1])

    def test_swap(self):
        r = compose_order.apply_natural_order("t", 1, "交换镜1和镜3")
        self.assertTrue(r["ok"])
        self.assertEqual(r["order"], [3, 2, 1])

    def test_explicit_list(self):
        r = compose_order.apply_natural_order("t", 1, "调整顺序为 2,3,1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["order"], [2, 3, 1])

    def test_unrecognized(self):
        r = compose_order.apply_natural_order("t", 1, "随便弄弄")
        self.assertFalse(r["ok"])
        self.assertIn("未识别", r["error"])


if __name__ == "__main__":
    unittest.main()
