#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P7b 测试（docs/13 §3 P7b）：素材生成引擎语义适配层。

测试对象：
  scripts/wf_adapter.py     analyze_workflow / suggest_mapping / llm_suggest_mapping /
                            litegraph_to_api / 引擎注册表（engine_from_workflow / changed / 校验）
  scripts/render.py         resolve_workflow(engine_id) 注入 + litegraph 模板加载
  web/server.py             /api/engines 端点模块级实现（list/scan/adapt/register/delete）
  web/agent_manager.py      wf 分支意图分派

运行：
  python -m pytest scripts/test_p7b.py -q -s      # 从项目根
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "web"))

import common                    # noqa: E402
import render                    # noqa: E402
import wf_adapter                # noqa: E402
import server                    # noqa: E402
import agent_manager             # noqa: E402

AIDEN = Path(r"S:/Develop/AIGC/ComfyUI/workflows/"
             r"1-Aiden-minimax-H3长视频上下文自动循环工作流测试！！！8.13.json")

FAKE_PROVIDER = {"provider": "fake", "base": "http://127.0.0.1:1/v1",
                 "model": "m", "api_key": "k"}

# 经典 UI 格式工作流（与 test_render.UI_WF 同构）
UI_WF = {
    "6": {"class_type": "MiniMaxH3AudioConditioningT8",
          "inputs": {"clip": ["3", 0], "video_vae": ["1", 0]},
          "widgets_values": ["a cinematic shot", 1024, 576, 124],
          "input_order": ["prompt", "width", "height", "length"]},
    "8": {"class_type": "RandomNoise",
          "inputs": {"noise_seed": 1, "denoise": 1.0}},
}

# 新版 LiteGraph 格式工作流（nodes 数组 + links）
LITE_WF = {
    "nodes": [
        {"id": 1, "type": "LoadImage", "inputs": [],
         "widgets_values": ["char.png", "image"], "outputs": [{"name": "IMAGE", "type": "IMAGE"}]},
        {"id": 2, "type": "MiniMaxH3AudioConditioningT8",
         "inputs": [{"name": "prompt", "type": "STRING", "widget": {"name": "prompt"}, "link": None},
                    {"name": "width", "type": "INT", "widget": {"name": "width"}, "link": None},
                    {"name": "height", "type": "INT", "widget": {"name": "height"}, "link": None},
                    {"name": "length", "type": "INT", "widget": {"name": "length"}, "link": None},
                    {"name": "clip", "type": "CLIP", "link": 9}],
         "widgets_values": ["a cinematic shot", 1024, 576, 124],
         "outputs": [{"name": "positive", "type": "CONDITIONING"}]},
        {"id": 3, "type": "CLIPLoader", "inputs": [],
         "widgets_values": ["qwen.clip.safetensors", "minimax"], "outputs": [{"name": "CLIP", "type": "CLIP"}]},
    ],
    "links": [[9, 3, 0, 2, 4, "CLIP"]],
}


def _write(tmp, name, obj):
    p = Path(tmp) / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


class TestAnalyzeWorkflow(unittest.TestCase):
    def test_classic_ui_format_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(tmp, "classic.json", UI_WF)
            a = wf_adapter.analyze_workflow(f)
        self.assertEqual(a["name"], "classic.json")
        self.assertTrue(a["hash"])
        self.assertEqual(len(a["nodes"]), 2)
        cap = a["capability"]
        self.assertEqual(cap["kinds"][0]["kind"], "video")
        self.assertGreaterEqual(cap["kinds"][0]["confidence"], 0.9)
        self.assertFalse(cap["chain"])
        self.assertFalse(cap["ref_input"])
        self.assertTrue(cap["audio"])          # MiniMaxH3AudioConditioningT8
        n6 = next(n for n in a["nodes"] if n["id"] == "6")
        names = [i["name"] for i in n6["inputs"]]
        self.assertIn("prompt", names)
        self.assertIn("length", names)

    def test_litegraph_format_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(tmp, "lite.json", LITE_WF)
            a = wf_adapter.analyze_workflow(f)
        cap = a["capability"]
        self.assertEqual(cap["kinds"][0]["kind"], "video")
        self.assertTrue(cap["ref_input"])       # LoadImage
        n2 = next(n for n in a["nodes"] if n["id"] == "2")
        ins = {i["name"]: i["value"] for i in n2["inputs"]}
        self.assertEqual(ins["prompt"], "a cinematic shot")      # widget 对齐
        self.assertEqual(ins["clip"], [3, 0])                     # 链接解析
        n1 = next(n for n in a["nodes"] if n["id"] == "1")
        ins1 = {i["name"]: i["value"] for i in n1["inputs"]}
        self.assertEqual(ins1["image"], "char.png")               # LoadImage 名称表

    def test_aiden_workflow_capability(self):
        if not AIDEN.is_file():
            self.skipTest("Aiden 8.13.json 不存在（验收真案例）")
        a = wf_adapter.analyze_workflow(AIDEN)
        self.assertEqual(len(a["nodes"]), 70)
        cap = a["capability"]
        self.assertEqual(cap["kinds"][0]["kind"], "video")
        self.assertGreaterEqual(cap["kinds"][0]["confidence"], 0.9)
        self.assertTrue(cap["chain"])           # MiniMaxH3Chain* 节点族
        self.assertTrue(cap["ref_input"])       # LoadImage / 参考视频
        self.assertTrue(cap["audio"])           # LoadAudio / H3 音频
        self.assertTrue(a["summary"])
        # 生成节点槽位落位
        n214 = next(n for n in a["nodes"] if n["id"] == "214")
        ins = {i["name"] for i in n214["inputs"]}
        for want in ("prompt", "width", "height", "length"):
            self.assertIn(want, ins)


class TestSuggestMapping(unittest.TestCase):
    def _analysis(self, wf):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(tmp, "wf.json", wf)
            return wf_adapter.analyze_workflow(f)

    def test_classic_mapping(self):
        a = self._analysis(UI_WF)
        m = wf_adapter.suggest_mapping(a, "video")
        self.assertEqual(m["mapping"]["prompt"], "6.inputs.prompt")
        self.assertEqual(m["mapping"]["width"], "6.inputs.width")
        self.assertEqual(m["mapping"]["frames"], "6.inputs.length")
        self.assertEqual(m["mapping"]["seed"], "8.inputs.noise_seed")
        self.assertIn("notes", m)
        self.assertIsInstance(m["unclassified"], list)

    def test_unclassified_when_no_slot(self):
        a = self._analysis(UI_WF)
        m = wf_adapter.suggest_mapping(a, "video", params_spec=["prompt", "nope_param"])
        self.assertIn("nope_param", m["unclassified"])

    def test_aiden_mapping_hits_core_slots(self):
        if not AIDEN.is_file():
            self.skipTest("Aiden 8.13.json 不存在")
        a = wf_adapter.analyze_workflow(AIDEN)
        m = wf_adapter.suggest_mapping(a, "video")
        for p in ("prompt", "width", "height", "frames", "steps", "seed",
                  "ref_image", "audio"):
            self.assertIn(p, m["mapping"], "参数 %s 应命中槽位" % p)
        self.assertEqual(m["mapping"]["prompt"], "214.inputs.prompt")
        self.assertEqual(m["mapping"]["frames"], "214.inputs.length")
        for p, slot in m["mapping"].items():
            self.assertTrue(wf_adapter._slot_ok(a, slot))


class TestLlmSuggestMapping(unittest.TestCase):
    def _llm(self, chat_return):
        return mock.patch("wf_adapter.agent.chat", return_value=chat_return), \
               mock.patch("wf_adapter.agent.resolve_provider", return_value=FAKE_PROVIDER)

    def _analysis(self, wf):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(tmp, "wf.json", wf)
            return wf_adapter.analyze_workflow(f)

    def test_chat_error_falls_back_to_rule(self):
        a = self._analysis(UI_WF)
        with mock.patch("wf_adapter.agent.chat", side_effect=Exception("down")), \
                mock.patch("wf_adapter.agent.resolve_provider", return_value=FAKE_PROVIDER):
            m = wf_adapter.llm_suggest_mapping(a, "video", "参考图", cfg=common.Config({}))
        self.assertEqual(m["mode"], "rule")
        self.assertIn("prompt", m["mapping"])

    def test_garbage_output_falls_back_to_rule(self):
        a = self._analysis(UI_WF)
        with self._llm("完全不是 JSON")[0], self._llm("完全不是 JSON")[1]:
            m = wf_adapter.llm_suggest_mapping(a, "video", "", cfg=common.Config({}))
        self.assertEqual(m["mode"], "rule")

    def test_llm_merges_unclassified(self):
        a = self._analysis(UI_WF)
        rule = wf_adapter.suggest_mapping(a, "video", params_spec=["prompt", "extra_param"])
        self.assertIn("extra_param", rule["unclassified"])
        out = json.dumps({"mapping": {"extra_param": "8.inputs.noise_seed"},
                          "notes": {"extra_param": "随机种子即抽卡随机性"}}, ensure_ascii=False)
        with self._llm(out)[0], self._llm(out)[1]:
            m = wf_adapter.llm_suggest_mapping(a, "video", "", cfg=common.Config({}), rule=rule)
        self.assertEqual(m["mode"], "llm")
        self.assertEqual(m["mapping"]["extra_param"], "8.inputs.noise_seed")
        self.assertNotIn("extra_param", m["unclassified"])

    def test_llm_invalid_slot_discarded(self):
        a = self._analysis(UI_WF)
        rule = wf_adapter.suggest_mapping(a, "video", params_spec=["prompt", "extra_param"])
        out = json.dumps({"mapping": {"extra_param": "99.inputs.nope"}}, ensure_ascii=False)
        with self._llm(out)[0], self._llm(out)[1]:
            m = wf_adapter.llm_suggest_mapping(a, "video", "", cfg=common.Config({}), rule=rule)
        self.assertIn("extra_param", m["unclassified"])     # 非法槽位被丢弃


class TestEngineRegistry(unittest.TestCase):
    def test_engine_from_workflow_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.local.json"
            f = _write(tmp, "wf.json", UI_WF)
            eng = wf_adapter.engine_from_workflow(str(f), "video", "经典H3", {"prompt": "6.inputs.prompt"})
            self.assertTrue(eng["id"].startswith("eng"))
            self.assertEqual(eng["provider"], "comfyui")
            self.assertEqual(eng["kind"], "video")
            self.assertTrue(eng["hash"])
            self.assertTrue(eng["enabled"])
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                wf_adapter.save_engines([eng])
                loaded = wf_adapter.load_engines()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["id"], eng["id"])
            self.assertEqual(wf_adapter.find_engine(loaded, eng["id"])["name"], "经典H3")

    def test_engine_changed_detects_file_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(tmp, "wf.json", UI_WF)
            eng = wf_adapter.engine_from_workflow(str(f), "video", "x", {})
            self.assertFalse(wf_adapter.engine_changed(eng))
            f.write_text(json.dumps({"1": {"class_type": "X", "inputs": {}}}), encoding="utf-8")
            self.assertTrue(wf_adapter.engine_changed(eng))

    def test_validate_register(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(tmp, "wf.json", UI_WF)
            ok, err = wf_adapter.validate_register("n", "video", str(f),
                                                   {"prompt": "6.inputs.prompt"})
            self.assertTrue(ok, err)
            ok2, err2 = wf_adapter.validate_register("n", "video", str(f),
                                                     {"prompt": "99.inputs.nope"})
            self.assertFalse(ok2)
            ok3, _ = wf_adapter.validate_register("n", "badkind", str(f), {})
            self.assertFalse(ok3)
            ok4, _ = wf_adapter.validate_register("n", "video", str(Path(tmp) / "nope.json"), {})
            self.assertFalse(ok4)

    def test_builtin_engine_summary(self):
        b = wf_adapter.builtin_engine()
        self.assertEqual(b["id"], "builtin")
        self.assertEqual(b["provider"], "builtin")
        self.assertTrue(b["builtin"])


class TestResolveWorkflowEngine(unittest.TestCase):
    def test_engine_id_injects_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            tpl = _write(tmp, "tpl.json", UI_WF)
            cfg_path = Path(tmp) / "config.local.json"
            eng = wf_adapter.engine_from_workflow(
                str(tpl), "video", "engA", {"prompt": "6.inputs.prompt",
                                            "seed": "8.inputs.noise_seed"})
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                wf_adapter.save_engines([eng])
                cfg = common.Config({})
                wf = render.resolve_workflow(cfg, engine_id=eng["id"],
                                             prompt="engine prompt", seed=42)
            self.assertEqual(wf["6"]["inputs"]["prompt"], "engine prompt")
            self.assertEqual(wf["8"]["inputs"]["noise_seed"], 42)

    def test_engine_litegraph_template_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            tpl = _write(tmp, "lite.json", LITE_WF)
            wf = render.load_template(str(tpl))
            self.assertEqual(wf["2"]["inputs"]["prompt"], "a cinematic shot")
            self.assertEqual(wf["2"]["inputs"]["clip"], [3, 0])

    def test_engine_missing_raises_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.local.json"
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                with self.assertRaises(common.ConfigError):
                    render.resolve_workflow(common.Config({}), engine_id="eng-none",
                                            prompt="p")

    def test_engine_api_provider_not_implemented(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.local.json"
            eng = {"id": "engapi", "kind": "video", "name": "api引擎",
                   "provider": "api", "workflow": "", "mapping": {}}
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                wf_adapter.save_engines([eng])
                with self.assertRaises(common.ConfigError) as cm:
                    render.resolve_workflow(common.Config({}), engine_id="engapi", prompt="p")
            self.assertIn("在线 API 引擎尚未接入", str(cm.exception))

    def test_no_engine_config_keeps_builtin(self):
        cfg = common.Config({"h3": {"diffusion_model": "m", "video_vae": "v",
                                    "audio_vae": "a", "text_encoder": "t"},
                             "workflow": {"mode": "builtin"}})
        wf = render.resolve_workflow(cfg, prompt="p", width=512, height=288,
                                     frames=22, steps=2, seed=1, prefix="x")
        self.assertEqual(wf["6"]["inputs"]["prompt"], "p")       # 现状行为不变


class TestEnginesEndpoints(unittest.TestCase):
    def test_engines_list_shape(self):
        r = server.api_engines_list()
        self.assertTrue(r["ok"])
        self.assertEqual(r["engines"][0]["id"], "builtin")
        self.assertEqual([k["kind"] for k in r["kinds"]],
                         ["refimg", "storyframe", "video"])

    def test_engines_scan_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(tmp, "wf.json", UI_WF)
            r = server.api_engines_scan({"path": str(f)})
        self.assertTrue(r["ok"])
        self.assertEqual(r["count"], 1)
        it = r["items"][0]
        self.assertEqual(it["name"], "wf.json")
        self.assertEqual(it["capability"]["kinds"][0]["kind"], "video")
        self.assertTrue(it["summary"])

    def test_engines_scan_missing_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = server.api_engines_scan({"path": str(Path(tmp) / "nope.json")})
        self.assertTrue(r["ok"])
        self.assertIn("error", r["items"][0])

    def test_engines_adapt_draft_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(tmp, "wf.json", UI_WF)
            cfg_path = Path(tmp) / "config.local.json"
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                r = server.api_engines_adapt({"path": str(f), "kind": "video"})
            self.assertTrue(r["ok"])
            d = r["engine_draft"]
            self.assertEqual(d["kind"], "video")
            self.assertEqual(d["mapping"]["prompt"], "6.inputs.prompt")
            self.assertIn("notes", d)
            self.assertIn("unclassified", d)
            self.assertEqual(len(wf_adapter.load_engines()), 0)   # 未写入

    def test_engines_register_then_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(tmp, "wf.json", UI_WF)
            cfg_path = Path(tmp) / "config.local.json"
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                r = server.api_engines_register(
                    {"name": "经典H3", "kind": "video", "path": str(f),
                     "mapping": {"prompt": "6.inputs.prompt"}})
                self.assertTrue(r["ok"], r.get("error"))
                eng = r["engine"]
                self.assertEqual(eng["name"], "经典H3")
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(len(data["engines"]), 1)          # config.local.json 写入
                # 列表可见（builtin + 已注册）
                lst = server.api_engines_list()
                self.assertEqual(len(lst["engines"]), 2)
                # 删除还原：engines 段从 config.local.json 移除（彻底还原未配置状态）
                r2 = server.api_engines_delete(eng["id"])
                self.assertTrue(r2["ok"])
                data2 = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertNotIn("engines", data2)
                self.assertEqual(len(server.api_engines_list()["engines"]), 1)

    def test_engines_register_invalid_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write(tmp, "wf.json", UI_WF)
            cfg_path = Path(tmp) / "config.local.json"
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                r = server.api_engines_register(
                    {"name": "x", "kind": "video", "path": str(f),
                     "mapping": {"prompt": "99.inputs.nope"}})
            self.assertFalse(r["ok"])
            self.assertIn("映射槽位无效", r["error"])

    def test_config_section_engines_read_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.local.json"
            with mock.patch("common.LOCAL_OVERRIDES", cfg_path):
                self.assertIsNone(server.config_section_error("engines", {"a": 1}))
                server.write_config_section("engines", [{"id": "e1", "kind": "video"}])
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(data["engines"][0]["id"], "e1")


class TestManagerWfBranch(unittest.TestCase):
    def test_dispatch_wf_intents(self):
        for t in ("扫描工作流", "对接工作流A视频", "用工作流X抽卡", "注册引擎",
                  "这个工作流能做什么", "把工作流A对接成视频引擎"):
            self.assertEqual(agent_manager.dispatch_intent(t), "wf", t)

    def test_dispatch_unrelated_unchanged(self):
        self.assertEqual(agent_manager.dispatch_intent("抽卡"), "render")
        self.assertEqual(agent_manager.dispatch_intent("拆分镜"), "storyboard")
        self.assertEqual(agent_manager.dispatch_intent("写剧本"), "aiwrite")
        self.assertEqual(agent_manager.dispatch_intent("创建 skill shot-review 描述 x"), "skill")


if __name__ == "__main__":
    unittest.main()
