#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P6d 测试（docs/13 §2 + .agents/skills/skill-create）：skill 自动加载 / skill_mgr / manager skill 分支 / 端点。

测试对象：
  scripts/h3_prompt_enhance.py   load_skill_texts / loaded_skill_names / skill_receipt /
                                 build_system_prompt / enhance（系统提示词拼 skill）
  scripts/skill_mgr.py            list_skills / parse_github_url / validate_skill_name /
                                 validate_skill_file / create_skill / install_from_url（install_repo 复用）
  web/agent_manager.py            dispatch_intent skill 分支（最前，含 skill/技能 才命中）
  web/server.py                   api_skills / api_skills_install / api_skills_create

运行：
  python -m pytest scripts/test_p6d.py -q -s      # 从项目根
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

import common                     # noqa: E402
import h3_prompt_enhance          # noqa: E402
import skill_mgr                  # noqa: E402
import agent_manager              # noqa: E402
import server                     # noqa: E402

FAKE_PROVIDER = {"provider": "fake", "base": "http://127.0.0.1:1/v1",
                 "model": "m", "api_key": "k"}
GOOD_SKILL_MD = ("---\nname: demo-skill\ndescription: 演示 skill，分镜审校时使用。\n"
                 "compatibility: 仅标准库\n---\n\n# Demo\n\n## Steps\n1. do it.\n")


def _make_skills_root(tmp, skills=None):
    """在 tmp 下构造 .agents/skills/<name>/SKILL.md 树（skills: {name: content}）。"""
    root = Path(tmp) / ".agents" / "skills"
    for name, content in (skills or {}).items():
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(content, encoding="utf-8")
    return root


class TestEnhanceSkillLoading(unittest.TestCase):
    """P6d ①：_load_skill_texts 按优先级加载已装 skill → 拼入系统提示词 + 事件回执。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_load_skill_texts_skips_missing(self):
        root = _make_skills_root(self.tmp.name, {
            "h3-prompt-writing": GOOD_SKILL_MD,
            "htv-h3-prompt": GOOD_SKILL_MD,
        })
        # 官方 skill 附 references/base-en.txt
        ref = root / "h3-prompt-writing" / "references"
        ref.mkdir()
        (ref / "base-en.txt").write_text("# Video Prompt Writing Guide\n", encoding="utf-8")
        # minimax-h3-prompt-skill-T8 只有 .git（残缺）→ 静默跳过
        (root / "minimax-h3-prompt-skill-T8").mkdir()
        with mock.patch("h3_prompt_enhance.SKILLS_ROOT", root):
            texts = h3_prompt_enhance.load_skill_texts()
        labels = [label for label, _ in texts]
        self.assertIn("h3-prompt-writing/SKILL.md", labels)
        self.assertIn("h3-prompt-writing/references/base-en.txt", labels)
        self.assertIn("htv-h3-prompt/SKILL.md", labels)
        self.assertNotIn("minimax-h3-prompt-skill-T8/SKILL.md", labels)

    def test_loaded_skill_names_and_receipt(self):
        root = _make_skills_root(self.tmp.name, {
            "h3-prompt-writing": GOOD_SKILL_MD,
            "htv-h3-prompt": GOOD_SKILL_MD,
        })
        with mock.patch("h3_prompt_enhance.SKILLS_ROOT", root):
            self.assertEqual(h3_prompt_enhance.loaded_skill_names(),
                             ["h3-prompt-writing", "htv-h3-prompt"])
            self.assertEqual(h3_prompt_enhance.skill_receipt(),
                             "已加载 skill：h3-prompt-writing、htv-h3-prompt")
        # 无 skill → 内置公式兜底
        empty = Path(self.tmp.name) / "empty-skills"
        empty.mkdir()
        with mock.patch("h3_prompt_enhance.SKILLS_ROOT", empty):
            self.assertEqual(h3_prompt_enhance.skill_receipt(),
                             "无已装 skill，使用内置公式")
            self.assertEqual(h3_prompt_enhance.load_skill_texts(), [])

    def test_build_system_prompt_contains_skill_and_builtin(self):
        root = _make_skills_root(self.tmp.name, {"h3-prompt-writing": GOOD_SKILL_MD})
        with mock.patch("h3_prompt_enhance.SKILLS_ROOT", root):
            sp = h3_prompt_enhance.build_system_prompt()
        self.assertIn(h3_prompt_enhance.SYSTEM_PROMPT[:30], sp)   # 内置公式保留兜底
        self.assertIn("===== 已加载 skill 文件：h3-prompt-writing/SKILL.md =====", sp)
        self.assertIn("## Steps", sp)

    def test_enhance_passes_skill_augmented_system_prompt(self):
        root = _make_skills_root(self.tmp.name, {"htv-h3-prompt": GOOD_SKILL_MD})
        captured = {}
        out = ("integrated_multimodal_description: [Shot 1] ...\n\n"
               "overall_soundscape: ...\n\nnon_diegetic_music: ...")

        def _chat(base, model, key, messages, **kw):
            captured["system"] = messages[0]["content"]
            return out

        shot = {"shot": "1", "frame": "medium", "camera": "static", "dur": "5",
                "chars": "C01", "scene": "S01", "light": "day"}
        with mock.patch("h3_prompt_enhance.SKILLS_ROOT", root), \
                mock.patch("h3_prompt_enhance.agent.chat", side_effect=_chat), \
                mock.patch("h3_prompt_enhance.agent.resolve_provider",
                           return_value=FAKE_PROVIDER):
            text, mode = h3_prompt_enhance.enhance(shot, 1, 0, "", {}, "",
                                                   cfg=common.Config({}))
        self.assertEqual(mode, "llm")
        self.assertIn("===== 已加载 skill 文件：htv-h3-prompt/SKILL.md =====",
                      captured["system"])
        self.assertIn(h3_prompt_enhance.SYSTEM_PROMPT[:30], captured["system"])


class TestSkillMgrList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_list_skills_parses_frontmatter(self):
        root = _make_skills_root(self.tmp.name, {
            "h3-prompt-writing": GOOD_SKILL_MD,
            "plain-dir": "no frontmatter here",          # 无 frontmatter → 回退目录名
        })
        with mock.patch("skill_mgr.SKILLS_ROOT", root):
            items = skill_mgr.list_skills()
        self.assertEqual(len(items), 2)
        by_name = {i["name"]: i for i in items}
        self.assertEqual(by_name["demo-skill"]["description"], "演示 skill，分镜审校时使用。")
        demo_path = Path(by_name["demo-skill"]["path"])
        self.assertEqual(demo_path.name, "SKILL.md")
        self.assertEqual(demo_path.parent.name, "h3-prompt-writing")
        self.assertIn("plain-dir", by_name)
        self.assertEqual(by_name["plain-dir"]["description"], "")

    def test_list_skills_missing_root_returns_empty(self):
        with mock.patch("skill_mgr.SKILLS_ROOT", Path(self.tmp.name) / "nope"):
            self.assertEqual(skill_mgr.list_skills(), [])


class TestSkillMgrParseUrl(unittest.TestCase):
    def test_repo_only(self):
        self.assertEqual(skill_mgr.parse_github_url("https://github.com/MiniMax-AI/MiniMax-H3"),
                         ("MiniMax-AI/MiniMax-H3", "main", ""))

    def test_tree_ref(self):
        self.assertEqual(skill_mgr.parse_github_url(
            "https://github.com/MiniMax-AI/MiniMax-H3/tree/v1.0"),
            ("MiniMax-AI/MiniMax-H3", "v1.0", ""))

    def test_tree_ref_with_subdir(self):
        self.assertEqual(skill_mgr.parse_github_url(
            "https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/h3-prompt-writing"),
            ("MiniMax-AI/MiniMax-H3", "main", "skills/h3-prompt-writing"))

    def test_git_suffix_and_query_stripped(self):
        repo, ref, path = skill_mgr.parse_github_url(
            "https://github.com/owner/repo.git/tree/dev/sub?x=1")
        self.assertEqual(repo, "owner/repo")
        self.assertEqual(ref, "dev")
        self.assertEqual(path, "sub")

    def test_invalid_raises(self):
        for bad in ("", "https://example.com/x/y", "https://github.com/onlyowner"):
            with self.assertRaises(ValueError):
                skill_mgr.parse_github_url(bad)


class TestSkillMgrValidation(unittest.TestCase):
    def test_validate_skill_name(self):
        self.assertTrue(skill_mgr.validate_skill_name("h3-prompt-writing")[0])
        self.assertTrue(skill_mgr.validate_skill_name("a1")[0])
        self.assertFalse(skill_mgr.validate_skill_name("")[0])
        self.assertFalse(skill_mgr.validate_skill_name("Bad_Name")[0])
        self.assertFalse(skill_mgr.validate_skill_name("-lead")[0])

    def test_validate_skill_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "SKILL.md"
            p.write_text(GOOD_SKILL_MD, encoding="utf-8")
            self.assertTrue(skill_mgr.validate_skill_file(p)[0])
            p.write_text("# no frontmatter\n", encoding="utf-8")
            self.assertFalse(skill_mgr.validate_skill_file(p)[0])
            p.write_text("---\nname: x\n---\n", encoding="utf-8")   # 缺 description
            self.assertFalse(skill_mgr.validate_skill_file(p)[0])
            self.assertFalse(skill_mgr.validate_skill_file(Path(tmp) / "missing.md")[0])


class TestSkillMgrCreate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_create_llm_generates_and_validates(self):
        root = _make_skills_root(self.tmp.name, {})
        gen = GOOD_SKILL_MD
        with mock.patch("skill_mgr.SKILLS_ROOT", root), \
                mock.patch("skill_mgr.agent.chat", return_value=gen), \
                mock.patch("skill_mgr.agent.resolve_provider", return_value=FAKE_PROVIDER):
            res = skill_mgr.create_skill("shot-review", "分镜审校工具，抽卡后逐镜质检")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["name"], "shot-review")
        sk = root / "shot-review" / "SKILL.md"
        self.assertEqual(res["path"], str(sk))
        self.assertTrue(sk.is_file())
        self.assertIn("name: demo-skill", sk.read_text(encoding="utf-8"))

    def test_create_rejects_bad_name_and_empty_desc(self):
        with mock.patch("skill_mgr.SKILLS_ROOT", _make_skills_root(self.tmp.name, {})):
            self.assertFalse(skill_mgr.create_skill("Bad Name", "x")["ok"])
            self.assertFalse(skill_mgr.create_skill("ok-name", "  ")["ok"])
            self.assertFalse(skill_mgr.create_skill("", "x")["ok"])

    def test_create_rejects_existing_dir(self):
        root = _make_skills_root(self.tmp.name, {"taken": GOOD_SKILL_MD})
        with mock.patch("skill_mgr.SKILLS_ROOT", root):
            res = skill_mgr.create_skill("taken", "描述")
        self.assertFalse(res["ok"])
        self.assertIn("已存在", res["error"])

    def test_create_llm_failure_returns_error(self):
        root = _make_skills_root(self.tmp.name, {})
        with mock.patch("skill_mgr.SKILLS_ROOT", root), \
                mock.patch("skill_mgr.agent.chat", side_effect=Exception("down")), \
                mock.patch("skill_mgr.agent.resolve_provider", return_value=FAKE_PROVIDER):
            res = skill_mgr.create_skill("shot-review", "分镜审校")
        self.assertFalse(res["ok"])
        self.assertIn("LLM 生成失败", res["error"])

    def test_create_explicit_content_bypasses_llm(self):
        root = _make_skills_root(self.tmp.name, {})
        with mock.patch("skill_mgr.SKILLS_ROOT", root):
            res = skill_mgr.create_skill("fixed-skill", "描述", content=GOOD_SKILL_MD)
        self.assertTrue(res["ok"])
        self.assertTrue((root / "fixed-skill" / "SKILL.md").is_file())


class TestSkillMgrInstall(unittest.TestCase):
    """install_from_url：URL 解析 + target 推导 + install_repo 复用（mock api/raw，不触网络）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_target_from_only_last_segment(self):
        root = _make_skills_root(self.tmp.name, {})
        with mock.patch("skill_mgr.SKILLS_ROOT", root), \
                mock.patch("skill_mgr.install_github_repo.install_repo",
                           return_value=(3, [])) as inst:
            res = skill_mgr.install_from_url(
                "https://github.com/MiniMax-AI/MiniMax-H3", only="skills/h3-prompt-writing")
        self.assertEqual(res["name"], "h3-prompt-writing")
        self.assertEqual(res["files"], 3)
        self.assertTrue(res["ok"])
        self.assertEqual(inst.call_args[0][0], "MiniMax-AI/MiniMax-H3")
        self.assertEqual(inst.call_args[1]["ref"], "main")
        self.assertEqual(inst.call_args[1]["only"], "skills/h3-prompt-writing")
        self.assertTrue(str(inst.call_args[0][1]).endswith("h3-prompt-writing"))

    def test_target_from_url_path_or_repo_name(self):
        root = _make_skills_root(self.tmp.name, {})
        with mock.patch("skill_mgr.SKILLS_ROOT", root), \
                mock.patch("skill_mgr.install_github_repo.install_repo", return_value=(1, [])):
            res = skill_mgr.install_from_url(
                "https://github.com/a/b/tree/main/pack/skill-x")          # URL path 末段
            self.assertEqual(res["name"], "skill-x")
            res2 = skill_mgr.install_from_url("https://github.com/a/b")   # 仓库名
            self.assertEqual(res2["name"], "b")

    def test_install_repo_reuse_with_local_fake_tree(self):
        """真正走 install_github_repo.install_repo（api+raw 被 mock 成本地文件），验证 import 复用。"""
        root = _make_skills_root(self.tmp.name, {})

        def _fake_tree(url):
            return {"tree": [
                {"path": "skills/demo-skill/SKILL.md", "type": "blob", "sha": "a"},
                {"path": "skills/demo-skill/references/notes.txt", "type": "blob", "sha": "b"},
                {"path": "skills/demo-skill/LICENSE", "type": "blob", "sha": "c"},
            ], "truncated": False}

        def _fake_raw(url):
            if url.endswith("SKILL.md"):
                return GOOD_SKILL_MD.encode("utf-8")
            if url.endswith("notes.txt"):
                return b"reference notes\n"
            return b"license text\n"

        with mock.patch("skill_mgr.SKILLS_ROOT", root), \
                mock.patch("skill_mgr.install_github_repo.api_get", side_effect=_fake_tree), \
                mock.patch("skill_mgr.install_github_repo.raw_get", side_effect=_fake_raw):
            res = skill_mgr.install_from_url(
                "https://github.com/T8mars/minimax-h3-prompt-skill-T8",
                only="skills/demo-skill")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["name"], "demo-skill")
        self.assertEqual(res["files"], 3)
        self.assertEqual(res["frontmatter"], "✓")
        sk = root / "demo-skill" / "SKILL.md"
        self.assertTrue(sk.is_file())
        self.assertTrue((root / "demo-skill" / "references" / "notes.txt").is_file())
        # only 前缀剥离：LICENSE 落在目标根（不带 skills/demo-skill 前缀）
        self.assertTrue((root / "demo-skill" / "LICENSE").is_file())

    def test_install_error_propagates(self):
        root = _make_skills_root(self.tmp.name, {})
        with mock.patch("skill_mgr.SKILLS_ROOT", root), \
                mock.patch("skill_mgr.install_github_repo.install_repo",
                           return_value=(0, [("SKILL.md", "timeout")])):
            res = skill_mgr.install_from_url("https://github.com/a/b")
        self.assertFalse(res["ok"])
        self.assertIn("断点续传", res["error"])


class TestManagerSkillBranch(unittest.TestCase):
    """skill 分支放最前：含 skill/技能 才命中（与 patch 的 加/删 区分）。"""

    def test_dispatch_skill_intents(self):
        for text in ("安装skill https://github.com/a/b",
                     "安装技能 https://github.com/a/b",
                     "创建 skill shot-review 描述 分镜审校",
                     "创建技能 xxx",
                     "制作 skill yyy",
                     "列出skill",
                     "skill 列表"):
            self.assertEqual(agent_manager.dispatch_intent(text), "skill", text)

    def test_dispatch_does_not_leak_to_patch(self):
        # 「创建/制作」类不带 skill/技能 → 不命中 skill 分支
        self.assertEqual(agent_manager.dispatch_intent("创建剧本"), "aiwrite")
        self.assertEqual(agent_manager.dispatch_intent("制作视频"), "default")
        self.assertEqual(agent_manager.dispatch_intent("把镜3的灯光改为夜景"), "patch")
        self.assertEqual(agent_manager.dispatch_intent("写剧本"), "aiwrite")

    def test_skill_intent_not_swallowed_by_others(self):
        # 「列出skill」必须命中 skill 而非 storyboard（无 分镜）等
        self.assertEqual(agent_manager.dispatch_intent("列出skill"), "skill")
        self.assertEqual(agent_manager.dispatch_intent("生成分镜提示词"), "prompt")


class TestServerSkillEndpoints(unittest.TestCase):
    def test_api_skills_shape(self):
        r = server.api_skills()
        self.assertTrue(r["ok"])
        self.assertIsInstance(r["skills"], list)
        for s in r["skills"]:
            self.assertIn("name", s)
            self.assertIn("description", s)
            self.assertIn("path", s)
        names = [s["name"] for s in r["skills"]]
        self.assertIn("skill-create", names)   # 本交付创建的元 skill 已在清单

    def test_api_skills_install_validation_and_passthrough(self):
        bad = server.api_skills_install({"url": "  "})
        self.assertFalse(bad["ok"])
        self.assertIn("url 不能为空", bad["error"])
        with mock.patch("server.skill_mgr.install_from_url",
                        return_value={"ok": True, "name": "x", "files": 3,
                                      "frontmatter": "✓", "errors": []}):
            r = server.api_skills_install({"url": "https://github.com/a/b"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["name"], "x")
        self.assertEqual(r["files"], 3)

    def test_api_skills_create_validation_and_passthrough(self):
        self.assertFalse(server.api_skills_create({"name": "", "description": "x"})["ok"])
        self.assertFalse(server.api_skills_create({"name": "x", "description": ""})["ok"])
        with mock.patch("server.skill_mgr.create_skill",
                        return_value={"ok": True, "name": "x", "path": "/p/SKILL.md"}):
            r = server.api_skills_create({"name": "x", "description": "描述"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["path"], "/p/SKILL.md")


if __name__ == "__main__":
    unittest.main()
