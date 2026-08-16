#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P6c 测试（docs/13 §3 ②③）：H3 提示词 LLM 反推回退 / /api/workflows / /api/config-section 白名单。

测试对象：
  scripts/h3_prompt_enhance.py   enhance / repair / split_sections / generate_shot_prompt
  web/server.py                   workflow_status / workflow_available / write_workflow_cfg /
                                  config_section_error / write_config_section / CONFIG_SECTIONS

运行：
  python -m pytest scripts/test_p6c.py -q -s      # 从项目根
"""
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "web"))

import common                    # noqa: E402
import render                    # noqa: E402
import h3_prompt_enhance         # noqa: E402
import server                    # noqa: E402

SHOT = {"shot": "1", "frame": "close-up", "camera": "push in", "dur": "4s",
        "chars": "C01、C02", "scene": "S01", "light": "golden hour",
        "dialogue": "对白：你终于回来了", "note": "开场"}
ASSETS = {"C01": {"name": "林小满", "type": "C"}, "C02": {"name": "爷爷", "type": "C"}}
FAKE_PROVIDER = {"provider": "fake", "base": "http://127.0.0.1:1/v1",
                 "model": "m", "api_key": "k"}


def _llm_patch(chat_return):
    """mock agent 层上下文：resolve_provider 返回假 provider，chat 返回给定值。"""
    @contextmanager
    def _cm():
        with ExitStack() as st:
            st.enter_context(mock.patch("h3_prompt_enhance.agent.chat",
                                        return_value=chat_return))
            st.enter_context(mock.patch("h3_prompt_enhance.agent.resolve_provider",
                                        return_value=FAKE_PROVIDER))
            yield
    return _cm()


class TestEnhanceFallback(unittest.TestCase):
    """LLM 失败/输出不可识别 → 回退 build_h3_shot（rule 模式）。"""

    def test_chat_error_falls_back_to_rule(self):
        with mock.patch("h3_prompt_enhance.agent.chat", side_effect=Exception("boom")), \
                mock.patch("h3_prompt_enhance.agent.resolve_provider",
                           return_value=FAKE_PROVIDER):
            text, mode = h3_prompt_enhance.enhance(SHOT, 1, 0, "水墨", ASSETS, "夜雨", cfg=common.Config({}))
        self.assertEqual(mode, "rule")
        self.assertEqual(text, render.build_h3_shot(SHOT, 1, 0, "水墨", assets=ASSETS))

    def test_unparseable_output_falls_back_to_rule(self):
        with mock.patch("h3_prompt_enhance.agent.chat", return_value="完全不是三段式"), \
                mock.patch("h3_prompt_enhance.agent.resolve_provider",
                           return_value=FAKE_PROVIDER):
            text, mode = h3_prompt_enhance.enhance(SHOT, 1, 0, "", {}, "x", cfg=common.Config({}))
        self.assertEqual(mode, "rule")
        self.assertIn("integrated_multimodal_description:", text)

    def test_missing_sections_filled_with_na(self):
        out = "integrated_multimodal_description: [Shot 1] Live-action, cinematic, a close-up shot."
        with _llm_patch(out):
            text, mode = h3_prompt_enhance.enhance(SHOT, 1, 0, "", {}, "", cfg=common.Config({}))
        self.assertEqual(mode, "llm")
        self.assertIn("overall_soundscape: N/A", text)
        self.assertIn("non_diegetic_music: N/A", text)

    def test_full_three_sections_kept(self):
        out = ("integrated_multimodal_description: [Shot 1] Live-action, cinematic, a close-up shot.\n\n"
               "overall_soundscape: Rainy night ambience.\n\n"
               "non_diegetic_music: Low piano at 60 BPM.")
        with _llm_patch(out):
            text, mode = h3_prompt_enhance.enhance(SHOT, 1, 0, "", {}, "赛博朋克夜雨", cfg=common.Config({}))
        self.assertEqual(mode, "llm")
        for a in ("integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:"):
            self.assertIn(a, text)
        self.assertIn("Rainy night ambience.", text)


class TestGenerateShotPromptDispatch(unittest.TestCase):
    """h3.prompt_enhance 开关分发：rule（默认）→ 规则组装；llm → enhance。"""

    def _cfg(self, mode):
        return common.Config({"h3": {"prompt_enhance": mode}})

    def test_rule_mode_default(self):
        text, mode = h3_prompt_enhance.generate_shot_prompt(
            SHOT, 1, 0, "水墨", ASSETS, "夜雨", cfg=common.Config({}))
        self.assertEqual(mode, "rule")
        self.assertEqual(text, render.build_h3_shot(SHOT, 1, 0, "水墨", assets=ASSETS))

    def test_llm_mode_goes_through_enhance(self):
        out = ("integrated_multimodal_description: [Shot 1] ...\n\n"
               "overall_soundscape: ...\n\nnon_diegetic_music: ...")
        with _llm_patch(out):
            text, mode = h3_prompt_enhance.generate_shot_prompt(
                SHOT, 1, 0, "", {}, "夜雨", cfg=self._cfg("llm"))
        self.assertEqual(mode, "llm")
        self.assertIn("integrated_multimodal_description:", text)

    def test_llm_failure_falls_back_rule(self):
        with mock.patch("h3_prompt_enhance.agent.chat", side_effect=Exception("down")), \
                mock.patch("h3_prompt_enhance.agent.resolve_provider",
                           return_value=FAKE_PROVIDER):
            text, mode = h3_prompt_enhance.generate_shot_prompt(
                SHOT, 1, 0, "", {}, "", cfg=self._cfg("llm"))
        self.assertEqual(mode, "rule")
        self.assertIn("non_diegetic_music:", text)


class TestWorkflowsEndpoint(unittest.TestCase):
    """GET/PUT /api/workflows 的模块级实现（workflow_status / write_workflow_cfg）。"""

    def test_workflow_status_shape(self):
        st = server.workflow_status()
        self.assertTrue(st["ok"])
        self.assertIn(st["mode"], ("builtin", "template"))
        self.assertIn("template", st)
        self.assertIsInstance(st["available"], list)
        self.assertTrue(st["desc"])
        for item in st["available"]:
            self.assertIn("name", item)
            self.assertIn("path", item)
            self.assertIn("mtime", item)

    def test_write_workflow_template_then_builtin(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.local.json"
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                r = server.write_workflow_cfg("template", "S:/wf/export.json")
                self.assertEqual(r["mode"], "template")
                self.assertEqual(r["template"], "S:/wf/export.json")
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(data["workflow"]["mode"], "template")
                self.assertEqual(data["workflow"]["template"], "S:/wf/export.json")
                # 切回 builtin：保留模板值但 mode=builtin（resolve_workflow 忽略 template）
                r2 = server.write_workflow_cfg("builtin", "")
                self.assertEqual(r2["mode"], "builtin")
                data2 = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(data2["workflow"]["mode"], "builtin")

    def test_empty_template_coerced_to_builtin(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.local.json"
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                r = server.write_workflow_cfg("template", "  ")
                self.assertEqual(r["mode"], "builtin")

    def test_preserves_existing_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.local.json"
            cfg_path.write_text(json.dumps(
                {"workflow": {"mode": "template", "template": "old.json",
                              "mapping": {"prompt": "6.inputs.prompt"}}}), encoding="utf-8")
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                r = server.write_workflow_cfg("template", "new.json")
                self.assertEqual(r["template"], "new.json")
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(data["workflow"]["mapping"], {"prompt": "6.inputs.prompt"})


class TestConfigSection(unittest.TestCase):
    """PUT /api/config-section 白名单 + 写盘（CONFIG_SECTIONS / config_section_error / write_config_section）。"""

    def test_whitelist_sections(self):
        # P7b：白名单加入 engines（引擎注册表段，config.local.json）
        self.assertEqual(server.CONFIG_SECTIONS,
                         ("image", "workflow", "h3", "comfyui", "engines"))

    def test_whitelist_error(self):
        self.assertIsNone(server.config_section_error("image", {"base": "x"}))
        self.assertIsNone(server.config_section_error("workflow", {"mode": "builtin"}))
        self.assertIsNotNone(server.config_section_error("nope", {"a": 1}))
        self.assertIsNotNone(server.config_section_error("image", "not-a-dict"))

    def test_write_image_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.local.json"
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                server.write_config_section(
                    "image", {"provider": "p", "base": "https://x/v1",
                              "model": "m", "api_key": "sk"})
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(data["image"]["model"], "m")
                self.assertEqual(data["image"]["api_key"], "sk")
                # 二次写覆盖 + 保留既有其他段
                server.write_config_section("image", {"model": "m2"})
                data2 = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(data2["image"]["model"], "m2")
                self.assertEqual(data2["image"]["base"], "https://x/v1")

    def test_write_preserves_other_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.local.json"
            cfg_path.write_text(json.dumps({"agent": {"default": "kimi"}}), encoding="utf-8")
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                server.write_config_section("h3", {"prompt_enhance": "llm"})
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(data["agent"]["default"], "kimi")
                self.assertEqual(data["h3"]["prompt_enhance"], "llm")


if __name__ == "__main__":
    unittest.main()
