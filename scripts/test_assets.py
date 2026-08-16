#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asset_manager 单元测试（TDD · 资产删除，本轮整改）。

seam：asset_manager.remove_asset。
运行：
  python -m unittest scripts.test_assets -v      # 从项目根
  python scripts/test_assets.py                   # 直接运行
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common                # noqa: E402
import asset_manager as am   # noqa: E402


class TestRemoveAsset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = am.ASSETS                       # asset_manager 内部绑定，patch 它
        am.ASSETS = Path(self.tmp.name) / "assets"

    def tearDown(self):
        am.ASSETS = self.old
        self.tmp.cleanup()

    def _mk_asset(self, code, name, with_image=True, with_bible=False):
        prefix = code[0]
        folder = am.ASSETS / am.FOLDER_BY_PREFIX[prefix]
        folder.mkdir(parents=True, exist_ok=True)
        reg = am.ASSETS / ".registry" / ("%s.md" % code)
        reg.parent.mkdir(parents=True, exist_ok=True)
        reg.write_text("# %s\nname: %s\n" % (code, name), encoding="utf-8")
        if with_image:
            (folder / ("%s_%s.png" % (code, name))).write_bytes(b"img")
        if with_bible:
            b = am.ASSETS / "bible"
            b.mkdir(parents=True, exist_ok=True)
            (b / ("%s_%s.md" % (code, name))).write_text("# bible", encoding="utf-8")

    def test_remove_deletes_registry_image_and_bible(self):
        self._mk_asset("C01", "少年", with_image=True, with_bible=True)
        result = am.remove_asset("C01")
        self.assertEqual(len(result["removed"]), 3)
        self.assertFalse((am.ASSETS / ".registry" / "C01.md").exists())
        self.assertFalse(list((am.ASSETS / "characters").glob("C01_*")))
        self.assertFalse(list((am.ASSETS / "bible").glob("C01_*")))

    def test_remove_only_target_code(self):
        self._mk_asset("C01", "少年")
        self._mk_asset("C02", "师父")
        am.remove_asset("C01")
        self.assertFalse((am.ASSETS / ".registry" / "C01.md").exists())
        self.assertTrue((am.ASSETS / ".registry" / "C02.md").exists())
        self.assertTrue(list((am.ASSETS / "characters").glob("C02_*")))

    def test_remove_missing_is_noop(self):
        result = am.remove_asset("P99")
        self.assertEqual(result["removed"], [])

    def test_remove_invalid_code_raises(self):
        with self.assertRaises(ValueError):
            am.remove_asset("X1")


if __name__ == "__main__":
    unittest.main()
