#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""image_gen 单元测试（docs/13 §3 P6a 2：外部生图 API 抽象 + 资产注入）。

seams：available / generate / inject_asset_image / friendly_error。
运行：
  python -m unittest scripts.test_image_gen -v      # 从项目根
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "web"))

import common        # noqa: E402
import image_gen     # noqa: E402


class TestAvailability(unittest.TestCase):
    def test_unconfigured_unavailable(self):
        cfg = common.Config({})
        self.assertFalse(image_gen.available(cfg))

    def test_partial_config_unavailable(self):
        cfg = common.Config({"image": {"base": "http://x", "api_key": ""}})
        self.assertFalse(image_gen.available(cfg))

    def test_full_config_available(self):
        cfg = common.Config({"image": {"base": "http://x", "api_key": "k", "model": "m"}})
        self.assertTrue(image_gen.available(cfg))

    def test_friendly_error_mentions_settings(self):
        msg = image_gen.friendly_error(common.Config({}))
        self.assertIn("设置页", msg)
        self.assertIn("config.local.json", msg)


class TestGenerateNotConfigured(unittest.TestCase):
    def test_generate_raises_friendly(self):
        with self.assertRaises(image_gen.ImageGenError) as cm:
            image_gen.generate("prompt", out_path=Path("x.png"),
                               cfg=common.Config({}))
        self.assertIn("设置页", str(cm.exception))

    def test_inject_unconfigured_raises(self):
        with self.assertRaises(image_gen.ImageGenError):
            image_gen.inject_asset_image("t", "C01", "古装书生",
                                         cfg=common.Config({}))


class TestInjectAssetImage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_assets = image_gen.common.ASSETS
        image_gen.common.ASSETS = Path(self.tmp.name) / "assets"
        self.old_avail = image_gen.available
        self.old_gen = image_gen.generate
        image_gen.available = lambda cfg=None: True

        def fake_generate(prompt, size=None, out_path=None, cfg=None):
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"\x89PNG-fake")
            return Path(out_path)

        image_gen.generate = fake_generate

    def tearDown(self):
        image_gen.generate = self.old_gen
        image_gen.available = self.old_avail
        image_gen.common.ASSETS = self.old_assets
        self.tmp.cleanup()

    def test_inject_writes_png_and_type_dir(self):
        rec = image_gen.inject_asset_image("t", "C01", "古装书生",
                                           cfg=common.Config({}))
        p = image_gen.common.ASSETS / "characters" / "C01.png"
        self.assertEqual(rec["code"], "C01")
        self.assertEqual(rec["type_name"], "角色")
        self.assertTrue(p.exists())
        self.assertEqual(p.read_bytes(), b"\x89PNG-fake")

    def test_scene_asset_goes_to_scenes_dir(self):
        image_gen.inject_asset_image("t", "S01", "竹林", cfg=common.Config({}))
        self.assertTrue((image_gen.common.ASSETS / "scenes" / "S01.png").exists())

    def test_inject_invalid_code_raises(self):
        with self.assertRaises(ValueError):
            image_gen.inject_asset_image("t", "X01", "x", cfg=common.Config({}))


if __name__ == "__main__":
    unittest.main()
