#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心逻辑单元测试（TDD，标准库 unittest，无第三方依赖）。

覆盖：质检判定(review) / 分镜解析与提示词(gen_storyboard) / 拼接排序(compose) / 公共工具(common)。
运行：
  python -m unittest scripts.test_core -v      # 从项目根
  python scripts/test_core.py                   # 直接运行
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common          # noqa: E402
import compose         # noqa: E402
import gen_storyboard  # noqa: E402
import review          # noqa: E402
import ai_writer       # noqa: E402


def make_rec(**kw):
    base = {"file": "shot_01_01.mp4", "shot": 1, "candidate": 1,
            "target_dur": 5.0, "error": "", "duration": 5.0, "width": 512,
            "height": 288, "fps": 24.0, "audio": True, "audio_desc": "aac",
            "video_codec": "h264", "first_luma": 128, "last_luma": 128}
    base.update(kw)
    return base


class TestReviewFlags(unittest.TestCase):
    """FR3 质检判定：flags + verdict。"""

    def test_ok(self):
        rec = make_rec()
        flags = review._flags(rec)
        self.assertEqual(flags, [])
        self.assertEqual(review._verdict(set(flags)), "ok")

    def test_no_audio_reject(self):
        flags = review._flags(make_rec(audio=False))
        self.assertIn("no_audio", flags)
        self.assertEqual(review._verdict(set(flags)), "reject")

    def test_black_first_reject(self):
        flags = review._flags(make_rec(first_luma=5))
        self.assertIn("black_first", flags)
        self.assertEqual(review._verdict(set(flags)), "reject")

    def test_white_last_reject(self):
        flags = review._flags(make_rec(last_luma=250))
        self.assertIn("white_last", flags)
        self.assertEqual(review._verdict(set(flags)), "reject")

    def test_short_warn(self):
        flags = review._flags(make_rec(duration=2.0))   # < 5*0.7=3.5
        self.assertIn("short", flags)
        self.assertEqual(review._verdict(set(flags)), "warn")

    def test_long_warn(self):
        flags = review._flags(make_rec(duration=8.0))   # > 5*1.3=6.5
        self.assertIn("long", flags)
        self.assertEqual(review._verdict(set(flags)), "warn")

    def test_probe_error_reject(self):
        flags = review._flags(make_rec(error="boom", audio=False))
        self.assertIn("probe_error", flags)
        self.assertEqual(review._verdict(set(flags)), "reject")

    def test_boundary_luma_not_flagged(self):
        # 边界值：BLACK_LUMA=12 及以上、WHITE_LUMA=243 及以下不应判废
        flags = review._flags(make_rec(first_luma=12, last_luma=243))
        self.assertNotIn("black_first", flags)
        self.assertNotIn("white_last", flags)


class TestStoryboard(unittest.TestCase):
    """分镜解析与提示词生成。"""

    SAMPLE = (
        "| 镜号 | 景别 | 机位运动 | 时长 | 角色 | 场景 | 灯光 | 对白/音效 | 备注 |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
        "| 1 | wide | push in | 5 | C01 | S01 | golden hour | 对白：谁在那里 | 开场 |\n"
        "| 2 | close-up | static | 3 | C01 | S01 | golden hour | 音效：心跳 | 情绪 |\n"
    )

    def test_parse_markdown_table(self):
        rows = gen_storyboard.parse_markdown_table(self.SAMPLE)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["shot"], "1")
        self.assertEqual(rows[0]["frame"], "wide")
        self.assertEqual(rows[1]["dur"], "3")

    def test_classify_audio_dialogue(self):
        d, sfx = gen_storyboard.classify_audio("对白：谁在那里")
        self.assertEqual(d, "谁在那里")
        self.assertEqual(sfx, "")

    def test_classify_audio_sfx(self):
        d, sfx = gen_storyboard.classify_audio("音效：心跳")
        self.assertEqual(d, "")
        self.assertEqual(sfx, "心跳")

    def test_classify_audio_default_dialogue(self):
        d, sfx = gen_storyboard.classify_audio("随便一句话")
        self.assertEqual(d, "随便一句话")
        self.assertEqual(sfx, "")

    def test_shot_h3_contains_core(self):
        shot = {"frame": "wide", "camera": "push in", "scene": "S01", "chars": "C01",
                "light": "golden hour", "dialogue": "对白：你好", "note": "开场"}
        desc = gen_storyboard.shot_h3(shot, 1, 0)
        self.assertIn("wide", desc)
        self.assertIn("push in", desc)
        self.assertIn("[Chinese] 你好", desc)

    def test_parse_dur_tolerant(self):
        self.assertEqual(gen_storyboard.parse_dur("4s"), 4.0)
        self.assertEqual(gen_storyboard.parse_dur("4秒"), 4.0)
        self.assertEqual(gen_storyboard.parse_dur("4"), 4.0)
        self.assertEqual(gen_storyboard.parse_dur("3-6"), 3.0)   # 范围取首数
        self.assertEqual(gen_storyboard.parse_dur(""), 5.0)      # 默认
        self.assertEqual(gen_storyboard.parse_dur("abc"), 5.0)


class TestCompose(unittest.TestCase):
    def test_shot_sort_key(self):
        self.assertEqual(compose.shot_sort_key(Path("shot_03.mp4")), 3)
        self.assertEqual(compose.shot_sort_key(Path("S01_02.mp4")), 1)  # 取第一个数字
        self.assertEqual(compose.shot_sort_key(Path("shot_10.mp4")), 10)
        self.assertEqual(compose.shot_sort_key(Path("无数字.mp4")), 0)


class TestCommon(unittest.TestCase):
    def test_validate_code_ok(self):
        self.assertEqual(common.validate_code("C01"), "C01")
        self.assertEqual(common.validate_code("S12"), "S12")

    def test_validate_code_bad(self):
        for bad in ("c01", "C1", "C001", "X01", "C0A"):
            with self.assertRaises(ValueError):
                common.validate_code(bad)

    def test_parse_yaml_subset(self):
        y = common.parse_yaml_subset(
            "a: 1\n"
            "b: hello # 注释\n"
            "c:\n  d: 2\n  e:\n    - x\n    - y\n"
        )
        self.assertEqual(y["a"], "1")
        self.assertEqual(y["b"], "hello")
        self.assertEqual(y["c"]["d"], "2")
        self.assertEqual(y["c"]["e"], ["x", "y"])

    def test_parse_yaml_quotes_stripped(self):
        y = common.parse_yaml_subset(
            'k1: "hello world"\n'
            "k2: ''\n"
            'k3: "864x1536"\n'
            'k4: "http://x:8080/v1"\n'
        )
        self.assertEqual(y["k1"], "hello world")
        self.assertEqual(y["k2"], "")          # 空串必须真正为空（回退逻辑依赖）
        self.assertEqual(y["k3"], "864x1536")
        self.assertEqual(y["k4"], "http://x:8080/v1")

    def test_deep_merge(self):
        base = {"agent": {"default": "kimi", "adapters": {"kimi": {"cmd": "kimi"}}}, "a": 1}
        over = {"agent": {"default": "dsh"}, "b": 2}
        out = common._deep_merge(base, over)
        self.assertEqual(out["agent"]["default"], "dsh")
        self.assertEqual(out["agent"]["adapters"]["kimi"]["cmd"], "kimi")  # 深层保留
        self.assertEqual(out["a"], 1)
        self.assertEqual(out["b"], 2)


class TestStoryboardFromScript(unittest.TestCase):
    """剧本镜头序列 → 分镜.md，须按集过滤、不跨集串号。"""

    def test_episode_filtering(self):
        import tempfile
        script = (
            "## 集 1｜甲\n**镜头序列：**\n"
            "- 镜1｜场景S01｜景别wide｜运镜static｜角色C01｜动作A｜对白：你好\n"
            "- 镜2｜场景S01｜景别close-up｜运镜push in｜角色C01｜动作B｜(音效)\n"
            "## 集 2｜乙\n**镜头序列：**\n"
            "- 镜1｜场景S02｜景别medium｜运镜pan｜角色C02｜动作C｜(风)\n"
        )
        with tempfile.TemporaryDirectory() as d:
            old = common.OUTPUT
            try:
                common.OUTPUT = Path(d)
                project = "t"
                ai_writer.write_script(project, script)
                dest = ai_writer.storyboard_from_script(project, 1)
                rows = gen_storyboard.load_storyboard(dest)
                # 只应有集 1 的两个镜头
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]["scene"], "S01")
                self.assertEqual(rows[1]["camera"], "push in")
            finally:
                common.OUTPUT = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
