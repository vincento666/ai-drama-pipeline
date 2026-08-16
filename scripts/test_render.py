#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render 工作流模板模式单元测试（TDD · spec: docs/specs/07-comfyui对接.md）。

seams：ui_to_api / load_template / inject_params / resolve_workflow。
运行：
  python -m unittest scripts.test_render -v      # 从项目根
  python scripts/test_render.py                   # 直接运行
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common        # noqa: E402
import render        # noqa: E402

UI_WF = {
    "6": {
        "class_type": "MiniMaxH3AudioConditioningT8",
        "inputs": {"clip": ["3", 0], "video_vae": ["1", 0]},
        "widgets_values": ["a cinematic shot", 1024, 576, 124],
        "input_order": ["prompt", "width", "height", "length"],
        "_meta": {"title": "H3 条件"},
    },
    "8": {"class_type": "RandomNoise",
          "inputs": {"noise_seed": 1, "denoise": 1.0},
          "_meta": {"title": "噪声"}},
}


class TestUiToApi(unittest.TestCase):
    def test_widgets_to_inputs_and_meta_stripped(self):
        wf = render.ui_to_api(UI_WF)
        self.assertNotIn("_meta", wf["6"])
        self.assertNotIn("widgets_values", wf["6"])
        self.assertEqual(wf["6"]["inputs"]["prompt"], "a cinematic shot")
        self.assertEqual(wf["6"]["inputs"]["width"], 1024)
        self.assertEqual(wf["6"]["inputs"]["length"], 124)
        self.assertEqual(wf["8"]["inputs"]["noise_seed"], 1)

    def test_plain_api_format_passthrough(self):
        api_wf = {"1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}}}
        wf = render.ui_to_api(api_wf)
        self.assertEqual(wf["1"]["inputs"]["image"], "a.png")


class TestInjectParams(unittest.TestCase):
    def test_inject_sets_mapped_slots(self):
        wf = render.ui_to_api(UI_WF)
        out = render.inject_params(wf, {"prompt": "6.inputs.prompt",
                                        "seed": "8.inputs.noise_seed"},
                                   {"prompt": "new prompt", "seed": 42})
        self.assertEqual(out["6"]["inputs"]["prompt"], "new prompt")
        self.assertEqual(out["8"]["inputs"]["noise_seed"], 42)

    def test_missing_slot_raises(self):
        wf = render.ui_to_api(UI_WF)
        with self.assertRaises(ValueError):
            render.inject_params(wf, {"prompt": "99.inputs.prompt"}, {"prompt": "x"})

    def test_unmapped_param_ignored(self):
        wf = render.ui_to_api(UI_WF)
        out = render.inject_params(wf, {}, {"whatever": 1})
        self.assertEqual(out["8"]["inputs"]["noise_seed"], 1)


class TestResolveWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_builtin_mode_returns_builder_output(self):
        cfg = common.Config({"h3": {"diffusion_model": "m", "video_vae": "v",
                                    "audio_vae": "a", "text_encoder": "t"},
                             "workflow": {"mode": "builtin"}})
        wf = render.resolve_workflow(cfg, prompt="p", width=512, height=288,
                                     frames=22, steps=2, seed=1, prefix="x")
        self.assertIn("6", wf)
        self.assertEqual(wf["6"]["inputs"]["prompt"], "p")

    def test_template_mode_loads_and_injects(self):
        tpl = Path(self.tmp.name) / "wf.json"
        tpl.write_text(json.dumps(UI_WF), encoding="utf-8")
        cfg = common.Config({"workflow": {
            "mode": "template", "template": str(tpl),
            "mapping": {"prompt": "6.inputs.prompt", "seed": "8.inputs.noise_seed"}}})
        wf = render.resolve_workflow(cfg, prompt="tmpl prompt", seed=7)
        self.assertEqual(wf["6"]["inputs"]["prompt"], "tmpl prompt")
        self.assertEqual(wf["8"]["inputs"]["noise_seed"], 7)

    def test_template_missing_file_raises_config_error(self):
        cfg = common.Config({"workflow": {"mode": "template",
                                          "template": str(Path(self.tmp.name) / "nope.json"),
                                          "mapping": {}}})
        with self.assertRaises(common.ConfigError):
            render.resolve_workflow(cfg, prompt="p")


class TestH3ShotPrompt(unittest.TestCase):
    """seam: render.build_h3_shot —— 官方 MiniMax H3 三段式规范（prompts/h3-shot-prompt.md）。"""

    SHOT = {"shot": "1", "frame": "close-up", "camera": "push in", "dur": "4s",
            "chars": "C01、C02", "scene": "S01", "light": "golden hour",
            "dialogue": "对白：你终于回来了", "note": "开场"}

    def test_three_sections_present(self):
        p = render.build_h3_shot(self.SHOT, 1, 0, "水墨")
        self.assertIn("integrated_multimodal_description:", p)
        self.assertIn("overall_soundscape:", p)
        self.assertIn("non_diegetic_music:", p)

    def test_dialogue_wrapped_with_speaker_and_lang(self):
        p = render.build_h3_shot(self.SHOT, 1, 0, "")
        self.assertIn("(S1) says: <d>[Chinese] 你终于回来了</d>", p)

    def test_camera_motion_three_dimension_sentence(self):
        p = render.build_h3_shot(self.SHOT, 1, 0, "")
        self.assertIn("The camera pushes in with small amplitude at slow speed", p)

    def test_assets_names_injected(self):
        assets = {"C01": {"name": "林小满"}, "C02": {"name": "爷爷"}}
        p = render.build_h3_shot(self.SHOT, 1, 0, "", assets=assets)
        self.assertIn("C01(林小满)", p)
        self.assertIn("C02(爷爷)", p)

    def test_sfx_goes_to_both_desc_and_soundscape(self):
        shot = dict(self.SHOT, dialogue="音效：心跳")
        p = render.build_h3_shot(shot, 1, 0, "")
        self.assertIn("The sound of 心跳", p)
        self.assertNotIn("<d>[Chinese]", p)

    def test_no_music_note_yields_na(self):
        shot = dict(self.SHOT, note="静音片段")
        p = render.build_h3_shot(shot, 1, 0, "")
        self.assertIn("non_diegetic_music: N/A", p)

    def test_style_prefix_prepended(self):
        p = render.build_h3_shot(self.SHOT, 1, 0, "水墨")
        self.assertTrue(p.startswith("integrated_multimodal_description: 水墨."))


if __name__ == "__main__":
    unittest.main()
