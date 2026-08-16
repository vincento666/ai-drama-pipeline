#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent_manager P6a 分支测试（docs/13 §3 P6a 1：意图分派 + 新分支辅助函数）。

seams：dispatch_intent / _asset_code / _image_prompt / _parse_restore / _missing_prompts。
运行：
  python -m unittest scripts.test_agent_manager -v      # 从项目根
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "web"))

import common            # noqa: E402
import agent_manager     # noqa: E402


class TestDispatchNewBranches(unittest.TestCase):
    """P6a 新增分支意图分派（含与现有规则不冲突的优先级）。"""

    def test_prompt(self):
        self.assertEqual(agent_manager.dispatch_intent("生成分镜提示词"), "prompt")
        self.assertEqual(agent_manager.dispatch_intent("刷新提示词"), "prompt")

    def test_asset(self):
        self.assertEqual(agent_manager.dispatch_intent("登记资产 C04 名称 林冲"), "asset")
        self.assertEqual(agent_manager.dispatch_intent("删除资产C01"), "asset")
        self.assertEqual(agent_manager.dispatch_intent("添加角色 C02 名称 王五"), "asset")

    def test_image_gen_context(self):
        self.assertEqual(agent_manager.dispatch_intent("给角色 C01 生成一张参考图"), "image_gen")
        self.assertEqual(agent_manager.dispatch_intent("给角色C01出图"), "image_gen")

    def test_image_gen_vs_render(self):
        # 裸「出图/抽卡」→ render（抽卡）；带 角色/资产 语境 → image_gen
        self.assertEqual(agent_manager.dispatch_intent("出图"), "render")
        self.assertEqual(agent_manager.dispatch_intent("抽卡"), "render")
        self.assertEqual(agent_manager.dispatch_intent("抽卡出图"), "render")
        self.assertEqual(agent_manager.dispatch_intent("给角色C01出图"), "image_gen")

    def test_compose_order(self):
        self.assertEqual(agent_manager.dispatch_intent("把镜3放到镜1前面"), "compose_order")
        self.assertEqual(agent_manager.dispatch_intent("调整顺序"), "compose_order")

    def test_reorder_goes_to_patch(self):
        # 「交换镜X和镜Y」「把镜X移到镜Y前/后」→ patch（workflow_patch reorder，改分镜.md）
        self.assertEqual(agent_manager.dispatch_intent("交换镜1和镜2"), "patch")
        self.assertEqual(agent_manager.dispatch_intent("把镜3移到镜1前面"), "patch")

    def test_select(self):
        self.assertEqual(agent_manager.dispatch_intent("自动选片"), "select")
        self.assertEqual(agent_manager.dispatch_intent("选第3镜第2候选"), "select")

    def test_restore(self):
        self.assertEqual(agent_manager.dispatch_intent("回滚分镜到版本3"), "restore")
        self.assertEqual(agent_manager.dispatch_intent("撤销到第2版"), "restore")

    def test_settings_before_patch(self):
        self.assertEqual(agent_manager.dispatch_intent("把默认模型改成deepseek"), "settings")
        self.assertEqual(agent_manager.dispatch_intent("上下文阈值调到20000"), "settings")

    def test_existing_rules_untouched(self):
        self.assertEqual(agent_manager.dispatch_intent("写剧本"), "aiwrite")
        self.assertEqual(agent_manager.dispatch_intent("拆分镜"), "storyboard")
        self.assertEqual(agent_manager.dispatch_intent("拼接成片"), "compose")
        self.assertEqual(agent_manager.dispatch_intent("把镜3的灯光改为夜景"), "patch")
        self.assertEqual(agent_manager.dispatch_intent("今天天气不错"), "default")


class TestHelpers(unittest.TestCase):
    def test_asset_code(self):
        self.assertEqual(agent_manager._asset_code("给角色 C01 生成图"), "C01")
        self.assertEqual(agent_manager._asset_code("给角色C01生成图"), "C01")
        self.assertIsNone(agent_manager._asset_code("没有代号"))

    def test_image_prompt_strips_intent(self):
        p = agent_manager._image_prompt("给角色 C01 生成一张古装书生的参考图", "C01")
        self.assertIn("古装书生", p)
        self.assertNotIn("生成一张", p)
        self.assertNotIn("C01", p)

    def test_parse_restore(self):
        self.assertEqual(agent_manager._parse_restore("回滚分镜到版本3"), ("board", 3))
        self.assertEqual(agent_manager._parse_restore("把剧本撤销到第2版"), ("script", 2))
        self.assertEqual(agent_manager._parse_restore("回滚到版本5"), ("board", 5))
        self.assertIsNone(agent_manager._parse_restore("随便聊聊")[1])

    def test_shot_numbers_single_and_multi(self):
        # P6c：双捕获组 findall 曾返回 tuple 导致 int() 崩溃（prompt 分支「给镜1生成分镜提示词」触发）
        self.assertEqual(agent_manager._shot_numbers("给镜1生成分镜提示词"), [1])
        self.assertEqual(agent_manager._shot_numbers("第3镜"), [3])
        self.assertEqual(agent_manager._shot_numbers("重抽镜2和镜5"), [2, 5])
        self.assertEqual(agent_manager._shot_numbers("生成分镜提示词"), None)
        self.assertEqual(agent_manager._shot_numbers(""), None)

    def test_prompt_desc_strips_command_shell(self):
        # P6c：用户附加描述提取（LLM 反推输入）
        self.assertEqual(agent_manager._prompt_desc("给镜1生成分镜提示词，画面要阴雨赛博朋克"),
                         "阴雨赛博朋克")
        self.assertEqual(agent_manager._prompt_desc("刷新提示词，赛博朋克夜雨"), "赛博朋克夜雨")
        self.assertEqual(agent_manager._prompt_desc("生成分镜提示词"), "")
        self.assertEqual(agent_manager._prompt_desc(""), "")


class TestMissingPrompts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = common.OUTPUT
        common.OUTPUT = Path(self.tmp.name)
        e = common.episode_dir("t", 1)
        e.mkdir(parents=True, exist_ok=True)
        (e / "分镜.md").write_text(
            "# E01\n\n| 镜号 | 景别 | 机位运动 | 时长 | 角色 | 场景 | 灯光 | 对白/音效 | 备注 |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| 1 | medium | static | 5 | C01 | S01 | day | | |\n"
            "| 2 | wide | static | 5 | C02 | S02 | night | | |\n", encoding="utf-8")

    def tearDown(self):
        common.OUTPUT = self.old
        self.tmp.cleanup()

    def test_all_missing(self):
        self.assertEqual(agent_manager._missing_prompts("t", 1), [1, 2])

    def test_only_filter(self):
        p = common.episode_dir("t", 1) / "refs" / "shot_01.prompt.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        self.assertEqual(agent_manager._missing_prompts("t", 1), [2])
        self.assertEqual(agent_manager._missing_prompts("t", 1, only="1"), [])

    def test_no_storyboard_returns_none(self):
        (common.episode_dir("t", 1) / "分镜.md").unlink()
        self.assertIsNone(agent_manager._missing_prompts("t", 1))


if __name__ == "__main__":
    unittest.main()
