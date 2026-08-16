#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skill 管理工具（P6d ③）：列出 / 安装 / 创建 .agents/skills/ 下的 skill。仅标准库。

设计（docs/13 §2 能力矩阵 + .agents/skills/skill-create/SKILL.md 元 skill）：
  - list_skills()       扫描 .agents/skills/*/SKILL.md → [{name, description, path}]
  - parse_github_url()  GitHub URL → (repo, ref, path)；支持 /tree/<ref>[/子目录]
  - install_from_url()  解析 URL → install_github_repo.install_repo（api+raw 链路，import 复用）
                        → 校验 frontmatter → {ok, name, target, files, errors, frontmatter}
  - create_skill()      name+description → LLM 按 skill-create 规范生成 SKILL.md（复用 agent.chat，
                        系统提示词内嵌 skill 制作规范 = skill-create/SKILL.md 内容）
                        → 写盘 → 校验 frontmatter
  - validate_skill_name / validate_skill_file   frontmatter 校验（create/install 共用）

注意：github.com 直连超时、codeload 不通，只有 api.github.com + raw.githubusercontent.com 可用
（install_github_repo 已实现该链路）；本模块不 git clone。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for _p in (str(SCRIPTS),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common                       # noqa: E402  配置（load_config）
import agent                        # noqa: E402  resolve_provider + chat（OpenAI 兼容）
import install_github_repo          # noqa: E402  安装底层（api trees + raw 批量拉取，import 复用）

SKILLS_ROOT = ROOT / ".agents" / "skills"
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


# ============ 列表 ============

def list_skills():
    """扫描 .agents/skills/*/SKILL.md → [{name, description, path}]（frontmatter 解析，缺省回退目录名）。

    目录不存在返回空列表（契约要求，不报错）。
    """
    if not SKILLS_ROOT.is_dir():
        return []
    out = []
    for sub in sorted(SKILLS_ROOT.iterdir()):
        if not sub.is_dir():
            continue
        sk = sub / "SKILL.md"
        if not sk.is_file():
            continue
        name, desc = sub.name, ""
        try:
            text = sk.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
        if m:
            fm = m.group(1)
            nm = re.search(r"^name:\s*(.+?)\s*$", fm, re.M)
            if nm:
                name = nm.group(1).strip().strip("\"'")
            dm = re.search(r"^description:\s*(.+?)\s*$", fm, re.M)
            if dm:
                desc = dm.group(1).strip().strip("\"'")
        out.append({"name": name, "description": desc, "path": str(sk)})
    return out


# ============ GitHub URL 解析 ============

def parse_github_url(url):
    """GitHub URL → (repo, ref, path)。

    支持：
      https://github.com/owner/repo
      https://github.com/owner/repo/tree/<ref>
      https://github.com/owner/repo/tree/<ref>/<子目录...>
    ref 缺省 main；非法 URL / 缺 repo → ValueError。
    """
    u = (url or "").strip()
    if not u.startswith(("https://github.com/", "http://github.com/")):
        raise ValueError("仅支持 github.com URL（api+raw 链路，不支持 git clone）：%s" % url)
    rest = u.split("github.com/", 1)[1].strip("/")
    rest = rest.split("?")[0].split("#")[0]
    parts = [p for p in rest.split("/") if p]
    if len(parts) < 2:
        raise ValueError("URL 缺少 owner/repo：%s" % url)
    repo = "/".join(parts[:2]).rstrip(".git")
    ref, path = "main", ""
    if len(parts) > 2:
        if parts[2] in ("tree", "blob"):
            ref = parts[3] if len(parts) > 3 else "main"
            path = "/".join(parts[4:]) if len(parts) > 4 else ""
        else:
            raise ValueError("无法解析 URL：%s（支持 /tree/<ref>[/子目录]）" % url)
    return repo, ref, path


# ============ 校验 ============

def validate_skill_name(name):
    """skill 目录名合法性：小写字母/数字开头，仅 [a-z0-9-]。返回 (ok, error)。"""
    name = (name or "").strip()
    if not name:
        return False, "skill 名称不能为空"
    if not SKILL_NAME_RE.match(name):
        return False, ("skill 名称须为小写字母/数字/连字符（如 h3-prompt-writing），当前: %r" % name)
    return True, ""


def validate_skill_file(path):
    """校验 SKILL.md：frontmatter（--- 段）+ name + description 非空。返回 (ok, error)。

    description 须含触发词（供 harness 识别何时调用该 skill）——由 LLM/编写者保证，
    这里只校验非空与 frontmatter 结构合法。
    """
    p = Path(path)
    if not p.is_file():
        return False, "SKILL.md 不存在: %s" % p
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as ex:
        return False, "读取失败: %s" % ex
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return False, "缺少 frontmatter（文件须以 --- 段开头：name + description）"
    fm = m.group(1)
    if not re.search(r"^name:\s*\S", fm, re.M):
        return False, "frontmatter 缺少 name（如 name: my-skill）"
    if not re.search(r"^description:\s*\S", fm, re.M):
        return False, "frontmatter 缺少 description（描述须含触发词，供识别何时调用）"
    return True, ""


# ============ 安装（import 复用 install_github_repo.install_repo） ============

def install_from_url(url, only=None, target=None, ref=None):
    """从 GitHub URL 安装 skill（api+raw 链路）→ 校验 frontmatter。

    返回 {ok, name, target, files, errors, frontmatter}：
      - name   = 目标 skill 目录名（only 末段 > URL path 末段 > 仓库名）
      - files  = 本次成功拉取文件数（断点续传：已存在文件跳过不计）
      - errors = [(path, error)] 拉取失败清单
      - frontmatter = 「✓」或「✗ 原因」（SKILL.md 存在时校验）
    """
    repo, url_ref, path = parse_github_url(url)
    ref = ref or url_ref
    only = (only or "").strip("/")
    if not only and path:
        only = path
    name = (only or "").rstrip("/").split("/")[-1] or repo.split("/")[-1]
    target = Path(target) if target else SKILLS_ROOT / name
    target.mkdir(parents=True, exist_ok=True)
    ok_count, fail = install_github_repo.install_repo(
        repo, target, ref=ref, only=only, verbose=False)
    sk = target / "SKILL.md"
    valid, verr = True, ""
    if sk.is_file():
        valid, verr = validate_skill_file(sk)
    ok = (not fail) and (ok_count > 0 or sk.is_file())
    return {"ok": ok, "name": name, "target": str(target), "files": ok_count,
            "errors": fail,
            "frontmatter": "✓" if valid else ("✗ " + verr),
            "error": None if ok else "拉取失败 %d 个文件（可重试，断点续传）" % len(fail)}


# ============ 创建（LLM 按 skill-create 规范生成） ============

def _create_system_prompt():
    """skill 制作规范 = .agents/skills/skill-create/SKILL.md 内容（缺失时内嵌兜底规范）。"""
    p = SKILLS_ROOT / "skill-create" / "SKILL.md"
    try:
        spec = p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else ""
    except Exception:
        spec = ""
    return (
        "你是 skill 制作专家。按以下规范生成一个 skill 的 SKILL.md 全文。\n"
        "只输出 SKILL.md 文件内容本身（含 frontmatter），不要解释、不要代码块包裹、不要多余空行。\n\n"
        "===== skill 制作规范（skill-create） =====\n%s"
        % (spec or ("frontmatter：name（小写连字符）+ description（含触发词，说明何时使用）；"
                    "正文：分节（What / When to use / Steps / Output / 校验），可操作、避免废话，"
                    "中英描述均可。")))


def _generate_skill_md(name, desc, cfg, timeout=120):
    """LLM 按描述生成 SKILL.md 全文；失败返回 ""（调用方给错误引导）。"""
    cfg = cfg or common.load_config()
    try:
        prov = agent.resolve_provider(cfg)
        user = (
            "skill 名称：%s\nskill 描述（用途/触发场景）：%s\n\n"
            "请生成该 skill 的 SKILL.md 全文：frontmatter（name: %s，description 用上面的描述并含触发词）"
            "+ 分节正文（What / When to use / Steps / Output / 校验），要求可操作、避免废话。"
            % (name, desc, name))
        return agent.chat(prov["base"], prov["model"], prov["api_key"],
                          [{"role": "system", "content": _create_system_prompt()},
                           {"role": "user", "content": user}],
                          temperature=0.5, timeout=timeout)
    except Exception:
        return ""


def create_skill(name, description, content=None, cfg=None, timeout=120):
    """创建 skill：content 为空 → LLM 按 skill-create 规范生成 SKILL.md；写盘 + 校验 frontmatter。

    返回 {ok, name, path?, error?}。名称非法 / 描述为空 / 目标已存在 → 直接拒绝不写盘。
    """
    ok, err = validate_skill_name(name)
    if not ok:
        return {"ok": False, "name": name, "error": err}
    desc = (description or "").strip()
    if not desc:
        return {"ok": False, "name": name,
                "error": "description 不能为空（描述须含触发词，供 harness 识别何时调用）"}
    target = SKILLS_ROOT / name
    if target.exists() and any(target.iterdir()):
        return {"ok": False, "name": name,
                "error": "已存在同名 skill 目录（%s），请换名或先清理" % target}
    content = (content or "").strip()
    if not content:
        content = _generate_skill_md(name, desc, cfg, timeout)
        if not content:
            return {"ok": False, "name": name,
                    "error": "LLM 生成失败（检查 llm 配置/连通性后重试）"}
    target.mkdir(parents=True, exist_ok=True)
    sk = target / "SKILL.md"
    sk.write_text(content, encoding="utf-8")
    valid, verr = validate_skill_file(sk)
    if not valid:
        return {"ok": False, "name": name, "path": str(sk),
                "error": "frontmatter 校验失败：%s（已写盘，可手动修正后重试）" % verr}
    return {"ok": True, "name": name, "path": str(sk)}
