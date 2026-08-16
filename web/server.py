#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前端桥：标准库 http.server，提供静态文件 + REST API。

启动：  python web/server.py [--port 8189]
打开：  http://127.0.0.1:8189

设计：桥只做路由与序列化，业务逻辑全部复用 scripts/ 下现有脚本
（common / gen_storyboard / render / compose），前端不复制任何逻辑。

API：
  GET  /api/projects                         项目列表
  GET  /api/project/<name>                   幕分段树 + 集列表
  GET  /api/project/<name>/episode/<n>/storyboard   分镜表 JSON
  PUT  /api/project/<name>/episode/<n>/storyboard   保存分镜表
  GET  /api/assets /api/vocab                资产 / 词表
  POST /api/asset                           登记资产 {code,name,image,ext}
  DELETE /api/asset/<code>                  删除资产（登记痕迹+图片+圣经）
  GET  /api/prompt/<name>/<ep>/<shot>        单镜完整 H3 三段式
  POST /api/render                           起后台抽卡任务 {project,episode,only,shots,...}
  GET  /api/render/status/<job>              抽卡任务状态
  GET  /api/jobs                              全局任务队列（全部 job）
  GET  /api/candidates/<name>/<ep>/<shot>    某镜候选视频列表
  GET  /api/review/<name>/<ep>              候选自动质检报告（FR3，带缓存）
  POST /api/review                          强制重新质检 {project,episode}
  GET  /api/selection-notes/<name>/<ep>     选中原因记录（FR4）
  POST /api/select                           选中候选 → 规范化为 shot_XX.mp4
  POST /api/compose                          拼接成片
  GET  /api/episode-status/<name>/<ep>       选中状态 / 成片状态
  GET  /api/wizard/<name>                  创作向导 7 步状态
  POST /api/novel/<name>                   保存小说源 {novel}
  POST /api/ai-write/<name>                AI 编剧：{novel,title} → 剧本草稿或 Agent 指令
  GET  /video/<name>/<episode>/<file>        视频文件（shots/ 或 成片.mp4，支持 Range）
  GET  /api/shot-ref/<name>/<ep>/<shot>      分镜参考图状态 {shot,prompt,image}
  POST /api/shot-ref/<name>/<ep>/<shot>      生成/刷新参考图提示词（LLM）→ E<n>/refs/shot_XX.prompt.md
  GET  /refs/<name>/<episode>/<file>         参考图静态文件（E<n>/refs/）
  GET  /api/canvas/<name>/<ep>               画布聚合包（剧本四块+资产+分镜+参考图+选中/成片状态+选中原因）
  POST /api/agent-command                    AgentBar 指令拆解 {command} → {actions}（dry-run，spec 06 §4）
  POST /api/onboard/<name>                   AI 访谈：{description,answers,want} → questions 追问 / brief 创作简报
"""
import argparse
import io
import json
import re
import shutil
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # 项目根
SCRIPTS = ROOT / "scripts"
WEB = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import common                      # noqa: E402
import compose as compose_mod      # noqa: E402
import render as render_mod        # noqa: E402
import taste                        # noqa: E402  品味学习（采集反馈）
import ai_writer                     # noqa: E402  AI 编剧（小说→剧本）
import review as review_mod          # noqa: E402  候选自动质检（FR3）
import agent                         # noqa: E402  生成 Agent（shot_ref 提示词）
import refs as refs_mod              # noqa: E402  分镜参考图存储层（M1）
import asset_manager                 # noqa: E402  资产库（删除资产，本轮整改）
import workflow_patch                # noqa: E402  agent 写盘核心（spec 09，所改即所得）
import agentbridge as agentbridge_mod  # noqa: E402  外部 harness 适配 + 事实源 rev（spec 09 v2）
import lhh as lhh_mod                # noqa: E402  LHH 官方包纯逻辑复用（spec 10）
from gen_storyboard import (CAMERA_VOCAB, FRAME_VOCAB, classify_audio,  # noqa: E402
                            load_storyboard, shot_h3)

COLS = [("shot", "镜号"), ("frame", "景别"), ("camera", "机位运动"),
        ("dur", "时长"), ("chars", "角色"), ("scene", "场景"),
        ("light", "灯光"), ("dialogue", "对白/音效"), ("note", "备注")]
NAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
SHOT_FILE_RE = re.compile(r"^shot_(\d{2})_(\d{2})\.mp4$")   # 候选
SHOT_FINAL_RE = re.compile(r"^shot_(\d{2})\.mp4$")          # 规范化选中

RENDER_JOBS = {}     # job_id -> {status, message, started}
REVIEW_CACHE = {}    # (project, episode, sig) -> review JSON（候选变化自动失效）
_ACP_SESSIONS = {}   # project -> AcpAdapter（交互式 ACP 会话，spec 11）
_JOB_LOCK = threading.Lock()
_job_seq = [0]


def _new_job(meta=None):
    with _JOB_LOCK:
        _job_seq[0] += 1
        jid = "job%04d" % _job_seq[0]
        RENDER_JOBS[jid] = {"status": "running", "message": "排队中",
                            "started": time.time(), "finished": None,
                            "meta": meta or {}}
        return jid


def _finish_job(jid, status, message):
    with _JOB_LOCK:
        if jid in RENDER_JOBS:
            up = {"status": status, "message": message}
            if status != "running":   # running 只是进度更新，finished 保持 None
                up["finished"] = time.time()
            RENDER_JOBS[jid].update(**up)


def list_jobs():
    """全部任务（含完成），倒序：运行中在前、按开始时间新→旧。"""
    with _JOB_LOCK:
        jobs = []
        for jid, j in RENDER_JOBS.items():
            item = dict(j)
            item["id"] = jid
            if item.get("started") and item.get("finished"):
                item["elapsed"] = round(item["finished"] - item["started"], 1)
            elif item.get("started"):
                item["elapsed"] = round(time.time() - item["started"], 1)
            jobs.append(item)
        jobs.sort(key=lambda x: (0 if x["status"] == "running" else 1,
                                 -(x.get("started") or 0)))
        return jobs


def run_render_job(jid, kwargs):
    try:
        _finish_job(jid, "running", "模型加载/生成中…")
        ok = render_mod.render(**kwargs)
        _finish_job(jid, "done" if ok else "error",
                    "完成" if ok else "生成失败，见桥日志")
        if ok:  # 抽卡完成后自动质检（FR3），供前端候选徽标 + Agent 自动淘汰废片
            try:
                get_review(kwargs["project"], kwargs["episode"], force=True)
            except Exception:
                pass
    except Exception as ex:
        _finish_job(jid, "error", "异常: %s" % ex)


def run_storyboard_gen_job(jid, name, episode):
    """后台跑 剧本→分镜：LLM 优先（系统提示词+表格），失败回退解析器。"""
    try:
        if not ai_writer.read_script(name):
            _finish_job(jid, "error", "缺剧本.md（先 AI 编剧生成剧本）")
            return
        cfg = common.load_config()
        try:
            ok, _b = ai_writer.llm_available(cfg)
        except Exception:
            ok = False
        dest, method = None, "parser"
        if ok:
            _finish_job(jid, "running", "AI 按剧本拆分镜中…")
            try:
                dest = ai_writer.llm_storyboard(name, episode)
            except Exception:
                dest = None
            if dest is not None:
                method = "llm"
        if dest is None:
            _finish_job(jid, "running", "回退解析器：从剧本镜头序列提取分镜…")
            dest = ai_writer.storyboard_from_script(name, episode)
        with _JOB_LOCK:
            RENDER_JOBS[jid]["result"] = {"ok": True, "path": str(dest), "method": method}
        _finish_job(jid, "done",
                    "分镜已生成（%s）" % ("AI 拆分" if method == "llm" else "解析器提取"))
    except Exception as ex:
        _finish_job(jid, "error", "分镜生成失败: %s" % ex)


def run_agent_task_job(jid, project, goal, agent_name, context):
    """后台跑外部 harness 任务：工作区 = 项目目录，上下文默认项目文档摘要。

    task_id 在创建时即写入 job（前端可流式拉 transcript）。
    """
    try:
        _finish_job(jid, "running", "委派 %s 执行中…" % agent_name)
        adapter = agentbridge_mod.get_adapter(agent_name)
        ctx = context or agentbridge_mod.build_project_summary(project, 1)
        cwd = common.project_dir(project)   # 工作区 = 项目目录
        tid = agentbridge_mod.create_task(project, goal, ctx)
        with _JOB_LOCK:
            RENDER_JOBS[jid]["task_id"] = tid
        agentbridge_mod.run_task(project, goal, ctx, adapter, cwd=cwd, tid=tid)
        with _JOB_LOCK:
            RENDER_JOBS[jid]["result"] = agentbridge_mod.read_task(project, tid)
        _finish_job(jid, "done", "任务 %s 完成（%s）" % (tid, agent_name))
    except Exception as ex:
        _finish_job(jid, "error", "委派失败: %s" % ex)


def run_agent_chat_job(jid, project, text):
    """交互式 ACP 对话（spec 11）：按项目常驻会话，流式行写入 job.lines。"""
    try:
        _finish_job(jid, "running", "对话中…")
        adapter = _ACP_SESSIONS.get(project)
        if adapter is None:
            adapter = agentbridge_mod.AcpAdapter(
                cwd=str(common.project_dir(project)))
            _ACP_SESSIONS[project] = adapter

        def on_line(line):
            with _JOB_LOCK:
                RENDER_JOBS[jid].setdefault("lines", []).append(line)

        reply, _updates = adapter.chat(text, on_line=on_line)
        with _JOB_LOCK:
            RENDER_JOBS[jid]["lines"] = RENDER_JOBS[jid].get("lines") or []
            RENDER_JOBS[jid]["reply"] = reply
            RENDER_JOBS[jid]["session_id"] = adapter.session_id
        _finish_job(jid, "done", "完成")
    except Exception as ex:
        _finish_job(jid, "error", "对话失败: %s" % ex)


def run_aiwrite_step_job(jid, name, title, novel, mode):
    """后台跑单步 AI 编剧（events/skeleton/script/assets），进度写 job.message。"""
    try:
        if novel and novel.strip():
            ai_writer.write_novel(name, novel)
        if not ai_writer.read_novel(name):
            _finish_job(jid, "error", "缺小说内容（先保存 小说.md）")
            return
        brief = ai_writer.read_brief(name)
        steps = {
            "events":   (ai_writer.events_prompt(ai_writer.read_novel(name), title, brief),
                         ai_writer.EVENTS_FILE, ai_writer.write_events,
                         lambda: ai_writer.agent_events_instruction(name)),
            "skeleton": (ai_writer.skeleton_prompt(ai_writer.read_events(name), title, brief),
                         ai_writer.SKELETON_FILE, ai_writer.write_skeleton,
                         lambda: ai_writer.agent_skeleton_instruction(name)),
            "script":   (ai_writer.script_prompt(ai_writer.read_skeleton(name),
                                                 ai_writer.read_novel(name), title, brief),
                         ai_writer.SCRIPT_FILE, ai_writer.write_script,
                         lambda: ai_writer.agent_script_instruction(name)),
            "assets":   (ai_writer.assets_prompt(ai_writer.read_script(name), title, brief),
                         ai_writer.ASSETS_FILE, ai_writer.write_assets,
                         lambda: ai_writer.agent_assets_instruction(name)),
        }
        prompt, out_file, writer, agent_inst = steps[mode]
        if not prompt or prompt.startswith("【先"):
            _finish_job(jid, "error", "缺前置产物，无法生成 %s" % mode)
            return
        cfg = common.load_config()
        ok, base = ai_writer.llm_available(cfg)
        if not ok:
            with _JOB_LOCK:
                RENDER_JOBS[jid]["result"] = {"mode": "agent", "ok": True,
                                              "kind": mode,
                                              "instruction": agent_inst()}
            _finish_job(jid, "done", "无 LLM，见 Agent 指令")
            return
        _finish_job(jid, "running", "%s 生成中…" % out_file)
        try:
            model = ai_writer.pick_model(cfg, base)
            text = ai_writer.call_llm(base, model, prompt)
            dest = writer(name, text)
            if mode == "assets":
                register_assets_from_list(name)
            with _JOB_LOCK:
                RENDER_JOBS[jid]["result"] = {"mode": "llm", "ok": True,
                                              "kind": mode,
                                              "path": str(dest), "text": text}
            _finish_job(jid, "done", "%s 已生成" % out_file)
        except Exception as ex:
            with _JOB_LOCK:
                RENDER_JOBS[jid]["result"] = {"mode": "agent", "ok": False,
                                              "kind": mode, "error": str(ex),
                                              "instruction": agent_inst()}
            _finish_job(jid, "error", "LLM 生成失败: %s" % ex)
    except Exception as ex:
        _finish_job(jid, "error", "异常: %s" % ex)


def run_aiwrite_job(jid, name, title, novel):
    """后台跑一键 AI 编剧（事件→骨架→剧本→资产→分镜），进度写到 job.message。"""
    try:
        if novel and novel.strip():
            ai_writer.write_novel(name, novel)
        _finish_job(jid, "running", "① 事件图谱生成中…")
        mode, results = ai_writer.chain(name, title)
        if mode != "llm":
            board = None
            if ai_writer.read_script(name):
                try:
                    board = ai_writer.storyboard_from_script(name, 1)
                except Exception:
                    pass
            with _JOB_LOCK:
                RENDER_JOBS[jid]["result"] = {"mode": "agent", "ok": True,
                                              "instructions": results,
                                              "board": str(board) if board else None}
            _finish_job(jid, "done", "已用现有剧本生成分镜" if board else "无 LLM，见 Agent 指令")
            return
        try:
            register_assets_from_list(name)
        except Exception:
            pass
        board = None
        if ai_writer.read_script(name):
            try:
                board = ai_writer.storyboard_from_script(name, 1)
            except Exception:
                pass
        with _JOB_LOCK:
            RENDER_JOBS[jid]["result"] = {"mode": "llm", "ok": True,
                                          "done": results,
                                          "board": str(board) if board else None}
        _finish_job(jid, "done", "剧本与分镜已生成")
    except Exception as ex:
        _finish_job(jid, "error", "异常: %s" % ex)


def shot_prompt_full(shot, shot_no, start_sec, style):
    """单镜完整 H3 三段式（官方规范，预览即所生成——委托 render.build_h3_shot）。"""
    return render_mod.build_h3_shot(shot, shot_no, start_sec, style)


def projects():
    return sorted(d.name for d in common.OUTPUT.iterdir()
                  if d.is_dir() and not d.name.startswith("."))


def episode_numbers(name):
    root = common.project_dir(name)
    return sorted(int(m.group(1)) for d in root.iterdir()
                  if (m := re.fullmatch(r"E(\d+)", d.name)) and d.is_dir())


def script_acts(name):
    """分段：优先 故事骨架.md 的分集决策表（一行一集），回退 剧本.md 的 ## 集 N。"""
    root = common.project_dir(name)
    skel = root / ai_writer.SKELETON_FILE
    if skel.exists():
        text = skel.read_text(encoding="utf-8")
        acts = []
        in_table = False
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("|") and "集标题" in s:
                in_table = True
                continue
            if in_table:
                if not s.startswith("|"):
                    in_table = False
                    continue
                cells = [c.strip() for c in s.strip("|").split("|")]
                if len(cells) >= 6 and cells[0].isdigit():
                    acts.append({"title": "集 %s｜%s" % (cells[0], cells[1]),
                                 "text": "戏剧功能：%s\n场景核心：%s\n集末钩子：%s\n付费点：%s"
                                         % (cells[2], cells[3], cells[4], cells[5])})
        if acts:
            return acts
    p = root / ai_writer.SCRIPT_FILE
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    acts, cur = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            if cur is not None:
                acts.append(cur)
            cur = {"title": line[3:].strip(), "text": ""}
        elif cur is not None:
            cur["text"] += line + "\n"
    if cur is not None:
        acts.append(cur)
    return acts


def storyboard_json(name, episode):
    p = common.episode_dir(name, episode) / "分镜.md"
    if not p.exists():
        return {"header": None, "rows": [], "path": str(p)}
    shots = load_storyboard(p)
    head = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith(">"):
            head.append(line)
        elif line.strip():
            break
    return {"header": head, "rows": shots, "path": str(p)}


def rows_to_markdown(rows, header):
    head = "\n".join(header) + "\n" if header else ""
    lines = [head, "| " + " | ".join(c[1] for c in COLS) + " |",
             "|" + "---|" * len(COLS)]
    for r in rows:
        cells = [str(r.get(k, "") or "").strip() for k, _ in COLS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def save_storyboard(name, episode, rows, header):
    p = common.episode_dir(name, episode) / "分镜.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(rows_to_markdown(rows, header), encoding="utf-8")
    return str(p)


def shots_dir(name, episode):
    return common.episode_dir(name, episode) / "shots"


def candidates(name, episode, shot_no):
    """某镜的候选视频（shots/.candidates/shot_XX_YY.mp4）列表，按 YY 排序。"""
    d = shots_dir(name, episode) / ".candidates"
    if not d.exists():
        return []
    out = []
    for f in sorted(d.iterdir()):
        m = SHOT_FILE_RE.match(f.name)
        if m and int(m.group(1)) == shot_no:
            out.append({"name": f.name, "size": f.stat().st_size})
    return out


def select_shot(name, episode, shot_no, filename):
    """选中候选 → 复制为 shots/shot_XX.mp4（规范化，compose/verify 逻辑不变）。"""
    m = SHOT_FILE_RE.match(filename)
    if not m or int(m.group(1)) != shot_no:
        raise ValueError("bad candidate filename")
    src = shots_dir(name, episode) / ".candidates" / filename
    if not src.exists():
        raise FileNotFoundError(filename)
    dst = shots_dir(name, episode) / ("shot_%02d.mp4" % shot_no)
    shutil.copy2(src, dst)
    return str(dst)


def selection_notes_path(name, episode):
    return common.episode_dir(name, episode) / "selected-note.md"


def record_selection_note(name, episode, shot_no, filename, note=""):
    """追加选中原因到 selected-note.md（可追溯：供 Agent 复盘与调参）。"""
    p = selection_notes_path(name, episode)
    lines = []
    if p.exists():
        lines = p.read_text(encoding="utf-8").splitlines()
        # 同镜重新选择时替换旧行，避免重复
        lines = [l for l in lines
                 if not (l.startswith("|") and l.split("|")[1].strip() == str(shot_no))]
    if not lines or not (lines and lines[0].startswith("| 镜号")):
        lines = ["# 选中记录（selected-note）",
                 "> 每镜选中原因，供 Agent 复盘与调参（A/B 对比结论写这里）", "",
                 "| 镜号 | 选中文件 | 原因 | 时间 |",
                 "|------|----------|------|------|"]
    lines.append("| %d | %s | %s | %s |"
                 % (shot_no, filename, (note or "-").replace("|", "／"),
                    time.strftime("%Y-%m-%d %H:%M:%S")))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def selection_notes(name, episode):
    """读取 selected-note.md → [{shot, file, note, ts}]。"""
    p = selection_notes_path(name, episode)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "镜号" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 4 and cells[0].isdigit():
            out.append({"shot": int(cells[0]), "file": cells[1],
                        "note": cells[2], "ts": cells[3]})
    return out


def get_review(name, episode, force=False):
    """候选质检（带缓存：候选/分镜变化时自动失效）。"""
    cand_dir = shots_dir(name, episode) / ".candidates"
    sig = 0
    if cand_dir.exists():
        for f in cand_dir.iterdir():
            if SHOT_FILE_RE.match(f.name):
                sig = max(sig, int(f.stat().st_mtime))
    sb = common.episode_dir(name, episode) / "分镜.md"
    if sb.exists():
        sig = max(sig, int(sb.stat().st_mtime))
    key = (name, episode)
    cached = REVIEW_CACHE.get(key)
    if not force and cached and cached.get("sig") == sig:
        return cached["data"]
    data = review_mod.review_episode(name, episode)
    data["sig"] = sig
    REVIEW_CACHE[key] = {"sig": sig, "data": data}
    return data


def register_assets_from_list(name):
    """解析 资产清单.md → 写 assets/.registry/ 登记痕迹（C/S/P）。"""
    text = ai_writer.read_assets(name)
    if not text:
        return
    import re as _re
    root = common.ASSETS / ".registry"
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|") or s.startswith("|---"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) >= 4:
            atype, code, aname = cells[0], cells[1], cells[2]
            m = _re.fullmatch(r"[CSPR]\d{2}", code)
            if m and aname:
                root.mkdir(parents=True, exist_ok=True)
                (root / (code + ".md")).write_text(
                    "# %s\nname: %s\ntype: %s\n" % (code, aname, code[0]),
                    encoding="utf-8")


def register_asset(code, name, image_b64="", image_ext=".png"):
    """登记单个资产（含可选图片上传 base64），复用 asset_manager 目录约定。"""
    import base64
    common.validate_code(code)
    prefix = code[0]
    folder_name = {"C": "characters", "S": "scenes", "P": "props", "R": "refs"}[prefix]
    folder = common.ASSETS / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    name = (name or "").strip() or code
    safe = re.sub(r"[^\w\u4e00-\u9fff-]", "", name)[:20] or code
    img_name = None
    if image_b64:
        try:
            raw = base64.b64decode(image_b64.split(",", 1)[-1])
            img_name = "%s_%s%s" % (code, safe, image_ext if image_ext.startswith(".") else ("." + image_ext))
            (folder / img_name).write_bytes(raw)
        except Exception:
            img_name = None
    reg = common.ASSETS / ".registry" / ("%s.md" % code)
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text("# %s\nname: %s\ntype: %s\n" % (code, name, prefix), encoding="utf-8")
    if prefix == "C":
        bible = common.ASSETS / "bible" / ("%s_%s.md" % (code, safe))
        if not bible.exists():
            bible.parent.mkdir(parents=True, exist_ok=True)
            bible.write_text(
                "# 角色圣经：%s（%s）\n\n> 生成含该角色的镜头前必读，做一致性锚点。\n\n"
                "## 外貌\n- 发型：\n- 五官：\n- 瞳色(hex)：\n- 体型：\n\n"
                "## 服装\n- 主色(hex)：\n- 上身：\n- 下身：\n- 配饰：\n\n"
                "## 声音/口头禅\n- 音色：\n- 语速语气：\n\n"
                "## 禁忌\n- 绝无：\n" % (name, code), encoding="utf-8")
    return {"code": code, "name": name, "image": img_name}


def compose_episode(name, episode):
    e_dir = common.episode_dir(name, episode)
    cfg = common.load_config()
    ffmpeg = cfg.get_path("compose.ffmpeg", "ffmpeg")
    fps = int(cfg.get_path("compose.fps", 24))
    ok = compose_mod.compose(e_dir / "shots", e_dir / "成片.mp4",
                             ffmpeg=ffmpeg, fps=fps, dry_run=False)
    return ok, e_dir / "成片.mp4"


class Handler(BaseHTTPRequestHandler):
    server_version = "AIDramaBridge/0.2"

    # ---------- 工具 ----------
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _err(self, code, msg):
        self._send(code, {"error": msg})

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        return json.loads(body.decode("utf-8"))

    def _path_parts(self):
        return [urllib.parse.unquote(x) for x in self.path.split("?")[0]
                .strip("/").split("/") if x]

    def _check_proj_ep(self, name, ep):
        if not NAME_RE.match(name) or not ep.isdigit():
            return None
        return int(ep)

    # ---------- 静态文件 ----------
    def _static(self, rel):
        # 优先 Vue 构建产物（web/dist/），回退原生前端（web/）
        root = (WEB / "dist") if (WEB / "dist" / "index.html").exists() else WEB
        p = (root / rel).resolve()
        if not str(p).startswith(str(root.resolve())) or not p.is_file():
            return self._err(404, "not found")
        ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8", "png": "image/png",
                 "svg": "image/svg+xml"}.get(p.suffix.lstrip("."), "application/octet-stream")
        self._send(200, p.read_bytes(), ctype)

    # ---------- 视频服务（支持 Range，供 <video> 拖动） ----------
    def _video(self, name, ep, file):
        epn = self._check_proj_ep(name, ep)
        if epn is None or not NAME_RE.match(name):
            return self._err(400, "bad path")
        fname = Path(file).name                       # 防路径穿越
        e_dir = common.episode_dir(name, epn)
        if fname == "成片.mp4":
            p = e_dir / "成片.mp4"
        elif SHOT_FILE_RE.match(fname):
            p = e_dir / "shots" / ".candidates" / fname
        elif SHOT_FINAL_RE.match(fname):
            p = e_dir / "shots" / fname
        else:
            return self._err(403, "forbidden file")
        if not p.exists() or not p.is_file():
            return self._err(404, "no such video")
        size = p.stat().st_size
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if rng and rng.startswith("bytes="):
            try:
                spec = rng.split("=", 1)[1].split(",")[0].strip()
                if spec.startswith("-"):
                    start = size - int(spec[1:])
                elif "-" in spec:
                    a, b = spec.split("-", 1)
                    start = int(a)
                    end = int(b) if b else size - 1
                end = min(end, size - 1)
                code = 206
            except Exception:
                code, start, end = 200, 0, size - 1
        data = None
        with open(p, "rb") as f:
            f.seek(start)
            data = f.read(end - start + 1)
        self.send_response(code)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        self.wfile.write(data)

    # ---------- 质检缩略图（shots/.review/*.png） ----------
    def _review_img(self, name, ep, file):
        epn = self._check_proj_ep(name, ep)
        if epn is None or not NAME_RE.match(name):
            return self._err(400, "bad path")
        fname = Path(file).name                       # 防路径穿越
        if not fname.endswith(".png") or not re.match(r"^shot_\d{2}_\d{2}_(first|last)\.png$", fname):
            return self._err(403, "forbidden file")
        p = shots_dir(name, epn) / ".review" / fname
        if not p.exists() or not p.is_file():
            return self._err(404, "no such image")
        self._send(200, p.read_bytes(), "image/png")

    # ---------- 资产图（assets/{characters,scenes,props,refs}/） ----------
    def _asset_img(self, code):
        if not re.match(r"^[CSPR]\d{2}$", code):
            return self._err(400, "bad asset code")
        asset = next((a for a in common.asset_table() if a["code"] == code), None)
        if not asset or not asset.get("image"):
            return self._err(404, "no image")
        prefix_dir = {"C": "characters", "S": "scenes", "P": "props", "R": "refs"}[code[0]]
        p = common.ASSETS / prefix_dir / asset["image"]
        if not p.exists() or not p.is_file():
            return self._err(404, "missing file")
        ctype = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        self._send(200, p.read_bytes(), ctype)

    # ---------- 分镜参考图（E<n>/refs/） ----------
    def _ref_img(self, name, ep, file):
        epn = self._check_proj_ep(name, ep)
        if epn is None or not NAME_RE.match(name):
            return self._err(400, "bad path")
        fname = Path(file).name                       # 防路径穿越
        if not refs_mod.IMAGE_RE.match(fname.lower()):
            return self._err(403, "forbidden file")
        p = common.episode_dir(name, epn) / "refs" / fname
        if not p.exists() or not p.is_file():
            return self._err(404, "no such ref image")
        ext = fname.lower().rsplit(".", 1)[-1]
        ctype = "image/%s" % ("jpeg" if ext in ("jpg", "jpeg") else ext)
        self._send(200, p.read_bytes(), ctype)

    # ---------- API ----------
    def api_get(self, parts):
        if parts == ["api", "projects"]:
            return self._send(200, {"projects": projects()})
        if parts[:2] == ["api", "project"] and len(parts) == 3:
            name = parts[2]
            if not NAME_RE.match(name):
                return self._err(400, "bad project name")
            return self._send(200, {"name": name, "episodes": episode_numbers(name),
                                    "acts": script_acts(name)})
        if (parts[:2] == ["api", "project"] and len(parts) == 6
                and parts[3] == "episode" and parts[5] == "storyboard"):
            epn = self._check_proj_ep(parts[2], parts[4])
            if epn is None:
                return self._err(400, "bad path")
            return self._send(200, storyboard_json(parts[2], epn))
        if parts == ["api", "assets"]:
            return self._send(200, {"assets": common.asset_table()})
        if parts == ["api", "vocab"]:
            return self._send(200, {"frames": FRAME_VOCAB, "cameras": CAMERA_VOCAB})
        if parts == ["api", "taste"]:
            cfg = common.load_config()
            taste_path = ROOT / "profile" / "taste.md"
            defaults, avoid = {}, []
            if taste_path.exists():
                for line in taste_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip().lstrip("-").strip()   # 容忍 "- 默认景别: x" 列表写法
                    for key, out in (("默认景别:", "frame"), ("默认运镜:", "camera"),
                                     ("偏好时长:", "dur")):
                        if line.startswith(key):
                            defaults[out] = line[len(key):].strip()
                    if line.startswith("避免运镜:"):
                        avoid = [x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()]
            return self._send(200, {"style": cfg.get_path("project.style_prefix", ""),
                                    "defaults": defaults, "avoid": avoid})
        if parts[:2] == ["api", "prompt"] and len(parts) == 5:
            name, ep, shot = parts[2], parts[3], parts[4]
            epn = self._check_proj_ep(name, ep)
            if epn is None or not shot.isdigit():
                return self._err(400, "bad path")
            sb = common.episode_dir(name, epn) / "分镜.md"
            if not sb.exists():
                return self._err(404, "no storyboard")
            shots = load_storyboard(sb)
            i = int(shot)
            if not 1 <= i <= len(shots):
                return self._err(404, "shot out of range")
            cfg = common.load_config()
            style = cfg.get_path("project.style_prefix", "")
            t = 0
            for s in shots[:i - 1]:
                try:
                    t += float(s.get("dur") or 5)
                except ValueError:
                    t += 5
            return self._send(200, {"prompt": shot_prompt_full(shots[i - 1], i, t, style)})
        if parts[:2] == ["api", "render"] and len(parts) == 4 and parts[2] == "status":
            jid = parts[3]
            with _JOB_LOCK:
                job = RENDER_JOBS.get(jid)
            if job is None:
                return self._err(404, "no such job")
            return self._send(200, job)
        if parts == ["api", "jobs"]:
            return self._send(200, {"jobs": list_jobs()})
        if parts[:2] == ["api", "candidates"] and len(parts) == 5:
            name, ep, shot = parts[2], parts[3], parts[4]
            epn = self._check_proj_ep(name, ep)
            if epn is None or not shot.isdigit():
                return self._err(400, "bad path")
            return self._send(200, {"files": candidates(name, epn, int(shot))})
        if parts[:2] == ["api", "review"] and len(parts) == 4:
            name, ep = parts[2], parts[3]
            epn = self._check_proj_ep(name, ep)
            if epn is None:
                return self._err(400, "bad path")
            try:
                data = get_review(name, epn)
            except Exception as ex:
                return self._err(500, "review failed: %s" % ex)
            return self._send(200, data)
        if parts[:2] == ["api", "selection-notes"] and len(parts) == 4:
            name, ep = parts[2], parts[3]
            epn = self._check_proj_ep(name, ep)
            if epn is None:
                return self._err(400, "bad path")
            return self._send(200, {"notes": selection_notes(name, epn)})
        if parts[:2] == ["api", "episode-status"] and len(parts) == 4:
            name, ep = parts[2], parts[3]
            epn = self._check_proj_ep(name, ep)
            if epn is None:
                return self._err(400, "bad path")
            d = shots_dir(name, epn)
            finals = sorted(f.name for f in d.iterdir() if SHOT_FINAL_RE.match(f.name)) if d.exists() else []
            composed = (common.episode_dir(name, epn) / "成片.mp4").exists()
            return self._send(200, {"selected": finals, "composed": composed})
        if parts[:2] == ["api", "wizard"] and len(parts) == 3:
            name = parts[2]
            if not NAME_RE.match(name):
                return self._err(400, "bad project name")
            root = common.project_dir(name)
            steps = []
            novel = root / ai_writer.NOVEL_FILE
            steps.append({"key": "novel", "label": "小说",
                          "done": novel.exists(),
                          "hint": "有 小说.md" if novel.exists() else "缺 小说.md（粘贴/导入原始素材）"})
            steps.append({"key": "events", "label": "事件",
                          "done": (root / ai_writer.EVENTS_FILE).exists(),
                          "hint": "有 小说事件.md" if (root / ai_writer.EVENTS_FILE).exists() else "未提取事件图谱"})
            skel = root / ai_writer.SKELETON_FILE
            steps.append({"key": "skeleton", "label": "骨架",
                          "done": skel.exists(),
                          "hint": "有 故事骨架.md（分集决策）" if skel.exists() else "缺故事骨架（分集决策表）"})
            script = root / ai_writer.SCRIPT_FILE
            steps.append({"key": "script", "label": "剧本",
                          "done": script.exists(),
                          "hint": "有 剧本.md" if script.exists() else "缺剧本.md（逐集剧本）"})
            assets_list = root / ai_writer.ASSETS_FILE
            steps.append({"key": "assets", "label": "资产",
                          "done": assets_list.exists() or len(common.asset_table()) > 0,
                          "count": len(common.asset_table()),
                          "hint": "有 资产清单.md" if assets_list.exists() else "未提取资产"})
            sb = common.episode_dir(name, 1) / "分镜.md"
            n_rows = len(load_storyboard(sb)) if sb.exists() else 0
            steps.append({"key": "board", "label": "分镜",
                          "done": n_rows > 0, "count": n_rows,
                          "hint": "%d 镜" % n_rows if n_rows else "缺分镜.md（由剧本镜头序列生成）"})
            d = shots_dir(name, 1)
            n_cand = len(candidates(name, 1, 1)) if d.exists() else 0
            n_final = len([f for f in (d.iterdir() if d.exists() else []) if SHOT_FINAL_RE.match(f.name)])
            steps.append({"key": "draw", "label": "抽卡",
                          "done": n_cand > 0 or n_final > 0, "count": n_cand,
                          "hint": "%d 候选 / %d 选中" % (n_cand, n_final)})
            steps.append({"key": "pick", "label": "选片",
                          "done": n_final > 0, "count": n_final,
                          "hint": "%d 镜已选" % n_final if n_final else "未选片"})
            composed = (common.episode_dir(name, 1) / "成片.mp4").exists()
            steps.append({"key": "compose", "label": "拼接",
                          "done": composed, "count": 1 if composed else 0,
                          "hint": "有成片" if composed else "未拼接"})
            return self._send(200, {"project": name, "steps": steps,
                                    "novel": (root / ai_writer.NOVEL_FILE).exists()})
        if parts[:2] == ["api", "creative"] and len(parts) == 3:
            name = parts[2]
            if not NAME_RE.match(name):
                return self._err(400, "bad project name")
            root = common.project_dir(name)
            novel = (root / ai_writer.NOVEL_FILE).read_text(encoding="utf-8")                 if (root / ai_writer.NOVEL_FILE).exists() else ""
            script = (root / ai_writer.SCRIPT_FILE).read_text(encoding="utf-8")                 if (root / ai_writer.SCRIPT_FILE).exists() else ""
            events = (root / ai_writer.EVENTS_FILE).read_text(encoding="utf-8") \
                if (root / ai_writer.EVENTS_FILE).exists() else ""
            skeleton = (root / ai_writer.SKELETON_FILE).read_text(encoding="utf-8") \
                if (root / ai_writer.SKELETON_FILE).exists() else ""
            assets = (root / ai_writer.ASSETS_FILE).read_text(encoding="utf-8") \
                if (root / ai_writer.ASSETS_FILE).exists() else ""
            brief = (root / ai_writer.BRIEF_FILE).read_text(encoding="utf-8") \
                if (root / ai_writer.BRIEF_FILE).exists() else ""
            return self._send(200, {"novel": novel, "script": script, "events": events,
                                    "skeleton": skeleton, "assets": assets,
                                    "brief": brief})
        if (parts[:2] == ["api", "shot-ref"] and len(parts) == 5):
            name, ep, shot = parts[2], parts[3], parts[4]
            epn = self._check_proj_ep(name, ep)
            if epn is None or not shot.isdigit():
                return self._err(400, "bad path")
            n = int(shot)
            image = next((r["image"] for r in refs_mod.list_refs(name, epn)
                          if r["shot"] == n), None)
            return self._send(200, {"shot": n,
                                    "prompt": refs_mod.load_ref_prompt(name, epn, n),
                                    "image": image})
        if (parts[:2] == ["api", "canvas"] and len(parts) == 4):
            name, ep = parts[2], parts[3]
            epn = self._check_proj_ep(name, ep)
            if epn is None:
                return self._err(400, "bad path")
            root = common.project_dir(name)

            def _read(f):
                p = root / f
                return p.read_text(encoding="utf-8") if p.exists() else ""

            script = {"novel": _read(ai_writer.NOVEL_FILE),
                      "events": _read(ai_writer.EVENTS_FILE),
                      "skeleton": _read(ai_writer.SKELETON_FILE),
                      "script": _read(ai_writer.SCRIPT_FILE),
                      "assets": _read(ai_writer.ASSETS_FILE)}
            sb = common.episode_dir(name, epn) / "分镜.md"
            rows = load_storyboard(sb) if sb.exists() else []
            d = shots_dir(name, epn)
            finals = sorted(f.name for f in d.iterdir() if SHOT_FINAL_RE.match(f.name)) if d.exists() else []
            composed = (common.episode_dir(name, epn) / "成片.mp4").exists()
            return self._send(200, {
                "project": name, "episode": epn, "script": script,
                "assets": common.asset_table(),
                "storyboard": {"rows": rows, "refs": refs_mod.list_refs(name, epn)},
                "status": {"selected": finals, "composed": composed},
                "notes": selection_notes(name, epn),
                "rev": agentbridge_mod.facts_rev(name, epn),   # 事实源摘要（展示层自动刷新信号）
            })
        if (parts[:2] == ["api", "agent-task"] and len(parts) == 4):
            name, task_id = parts[2], parts[3]
            if not NAME_RE.match(name):
                return self._err(400, "bad project name")
            try:
                task = agentbridge_mod.read_task(name, task_id)
            except Exception as ex:
                return self._err(400, str(ex))
            return self._send(200, task)
        if parts == ["api", "flow-templates"]:
            return self._send(200, {"ok": True,
                                    "templates": agentbridge_mod.flow_templates()})
        if parts == ["api", "config-agent"]:
            cfg = common.load_config().get_path("agent", {}) or {}
            return self._send(200, {"ok": True, "agent": cfg,
                                    "lhh": lhh_mod.lhh_status()})
        if (parts[:2] == ["api", "agent-chat"] and len(parts) == 4
                and parts[2] == "status"):
            jid = parts[3]
            if jid not in RENDER_JOBS:
                return self._err(404, "no such chat job")
            with _JOB_LOCK:
                job = dict(RENDER_JOBS[jid])
            return self._send(200, {"status": job.get("status"),
                                    "message": job.get("message"),
                                    "lines": job.get("lines") or [],
                                    "reply": job.get("reply"),
                                    "session_id": job.get("session_id")})
        return self._err(404, "unknown api: /" + "/".join(parts))

    def api_post(self, parts):
        if parts == ["api", "render"]:
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            name = q.get("project", "")
            epn = self._check_proj_ep(name, str(q.get("episode", "")))
            if epn is None:
                return self._err(400, "bad project/episode")
            only = q.get("only")
            ref_image = None
            ref_code = q.get("ref")
            if ref_code:
                img = next((a.get("image") for a in common.asset_table()
                            if a["code"] == ref_code and a.get("image")), None)
                if not img:
                    return self._err(400, "资产 %s 无参考图" % ref_code)
                prefix_dir = {"C": "characters", "S": "scenes",
                              "P": "props", "R": "refs"}.get(ref_code[0])
                src = common.ASSETS / prefix_dir / img
                if not src.exists():
                    return self._err(400, "资产图不存在: %s" % src)
                cfg = common.load_config()
                in_dir = Path(cfg.get_path("comfyui.input_dir",
                                           r"S:/Develop/AIGC/ComfyUI/ComfyUI_windows_portable/ComfyUI/input"))
                in_dir.mkdir(parents=True, exist_ok=True)
                ref_image = "ref_%s.png" % ref_code
                shutil.copy2(src, in_dir / ref_image)
            kwargs = dict(project=name, episode=epn,
                          shots_per_shot=int(q.get("shots", 3)),
                          width=q.get("width"), height=q.get("height"),
                          frames=q.get("frames"), steps=q.get("steps"),
                          seed=int(q.get("seed", 1)),
                          only=",".join(map(str, only)) if only else None,
                          dry_run=False, timeout=int(q.get("timeout", 1800)),
                          image=q.get("image"), ref_image=ref_image)
            meta = {"project": name, "episode": epn,
                    "only": only or None,
                    "shots": int(q.get("shots", 3)),
                    "mode": "ref" if ref_image else ("i2va" if q.get("image") else "t2va")}
            jid = _new_job(meta)
            t = threading.Thread(target=run_render_job, args=(jid, kwargs), daemon=True)
            t.start()
            return self._send(200, {"job": jid, "status": "running"})
        if parts == ["api", "select"]:
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            name = q.get("project", "")
            epn = self._check_proj_ep(name, str(q.get("episode", "")))
            if epn is None or not str(q.get("shot", "")).isdigit():
                return self._err(400, "bad path")
            try:
                path = select_shot(name, epn, int(q["shot"]), q["file"])
            except Exception as ex:
                return self._err(400, "select failed: %s" % ex)
            note = (q.get("note") or "").strip()
            try:  # 选中原因记录（selected-note.md，供 Agent 复盘/调参）
                if note:
                    record_selection_note(name, epn, int(q["shot"]), q["file"], note)
            except Exception:
                pass
            try:  # 品味采集：选中/淘汰记录（A/B 对比信号）
                others = [f["name"] for f in candidates(name, epn, int(q["shot"]))
                          if f["name"] != q["file"]]
                taste.log_select(name, epn, int(q["shot"]), q["file"], others,
                                 note=note)
                taste.record_stats("select", {"project": name, "episode": epn,
                                              "shot": int(q["shot"]),
                                              "candidates": 1 + len(others)})
            except Exception:
                pass
            try:  # F9：选中片首帧 → 晋升为该镜参考图 refs/shot_XX.png（非致命）
                frame = refs_mod.first_frame_candidate(name, epn, q["file"])
                if frame.is_file():
                    refs_mod.promote_first_frame(name, epn, int(q["shot"]), frame)
            except Exception:
                pass
            return self._send(200, {"ok": True, "path": path})
        if parts == ["api", "review"]:
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            name = q.get("project", "")
            epn = self._check_proj_ep(name, str(q.get("episode", "")))
            if epn is None:
                return self._err(400, "bad project/episode")
            try:
                data = get_review(name, epn, force=True)
            except Exception as ex:
                return self._err(500, "review failed: %s" % ex)
            return self._send(200, data)
        if parts == ["api", "compose"]:
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            name = q.get("project", "")
            epn = self._check_proj_ep(name, str(q.get("episode", "")))
            if epn is None:
                return self._err(400, "bad project/episode")
            try:
                ok, out = compose_episode(name, epn)
            except Exception as ex:
                return self._err(500, "compose failed: %s" % ex)
            return self._send(200, {"ok": ok, "path": str(out),
                                    "size": out.stat().st_size if ok and out.exists() else 0})
        if parts[:2] == ["api", "novel"] and len(parts) == 3:
            name = parts[2]
            if not NAME_RE.match(name):
                return self._err(400, "bad project name")
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            novel_text = q.get("novel", "")
            if not (novel_text or "").strip():  # 空内容不覆盖已有小说
                existing = ai_writer.read_novel(name)
                return self._send(200, {"ok": True, "path": str(common.project_dir(name) / ai_writer.NOVEL_FILE),
                                        "chars": len(existing), "kept": True})
            try:
                dest = ai_writer.write_novel(name, novel_text)
            except Exception as ex:
                return self._err(500, "save novel failed: %s" % ex)
            return self._send(200, {"ok": True, "path": str(dest), "chars": len(novel_text)})
        if parts[:2] == ["api", "ai-write"] and len(parts) == 3:
            name = parts[2]
            if not NAME_RE.match(name):
                return self._err(400, "bad project name")
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            novel = q.get("novel") or ""
            title = q.get("title") or name
            if novel:
                try:
                    ai_writer.write_novel(name, novel)
                except Exception:
                    pass
            mode = q.get("mode") or "events"
            if mode not in ("events", "skeleton", "script", "assets"):
                return self._err(400, "bad mode（events/skeleton/script/assets）")
            if not ai_writer.read_novel(name):
                return self._err(400, "先提供小说内容（novel 字段）")
            # 本轮整改：单步生成改为后台任务（不再同步阻塞 600s），前端轮询进度
            meta = {"project": name, "type": "aiwrite", "title": title, "mode": mode}
            jid = _new_job(meta)
            t = threading.Thread(target=run_aiwrite_step_job,
                                 args=(jid, name, title, novel, mode), daemon=True)
            t.start()
            return self._send(200, {"job": jid, "status": "running", "mode": mode})
        if parts[:2] == ["api", "ai-write-all"] and len(parts) == 3:
            name = parts[2]
            if not NAME_RE.match(name):
                return self._err(400, "bad project name")
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            novel = q.get("novel") or ""
            title = q.get("title") or name
            if not (novel or "").strip() and not ai_writer.read_novel(name):
                return self._err(400, "先提供小说内容（novel 字段）")
            meta = {"project": name, "type": "aiwrite", "title": title}
            jid = _new_job(meta)
            t = threading.Thread(target=run_aiwrite_job, args=(jid, name, title, novel),
                                 daemon=True)
            t.start()
            return self._send(200, {"job": jid, "status": "running"})
        if parts == ["api", "asset"]:
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            code = (q.get("code") or "").strip().upper()
            try:
                common.validate_code(code)
            except Exception as ex:
                return self._err(400, str(ex))
            try:
                rec = register_asset(code, q.get("name", ""),
                                     q.get("image", ""), q.get("ext", "png"))
            except Exception as ex:
                return self._err(500, "asset register failed: %s" % ex)
            return self._send(200, {"ok": True, "asset": rec})
        if parts == ["api", "agent-task"]:
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            name = q.get("project", "")
            if not name or not NAME_RE.match(name):
                return self._err(400, "bad project name")
            goal = (q.get("goal") or "").strip()
            if not goal:
                return self._err(400, "goal 不能为空")
            agent_name = q.get("agent") or "kimi"
            context = q.get("context") or ""
            meta = {"project": name, "type": "agent-task", "agent": agent_name}
            jid = _new_job(meta)
            t = threading.Thread(target=run_agent_task_job,
                                 args=(jid, name, goal, agent_name, context),
                                 daemon=True)
            t.start()
            return self._send(200, {"job": jid, "status": "running"})
        if parts == ["api", "agent-chat"]:
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            name = q.get("project", "")
            if not name or not NAME_RE.match(name):
                return self._err(400, "bad project name")
            text = (q.get("text") or "").strip()
            if not text:
                return self._err(400, "text 不能为空")
            meta = {"project": name, "type": "agent-chat"}
            jid = _new_job(meta)
            t = threading.Thread(target=run_agent_chat_job,
                                 args=(jid, name, text), daemon=True)
            t.start()
            return self._send(200, {"job": jid, "status": "running"})
        if parts == ["api", "agent-edit"]:
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            text = (q.get("text") or "").strip()
            if not text:
                return self._err(400, "text 不能为空")
            changes = workflow_patch.parse_edit_action(text)
            return self._send(200, {"ok": True, "changes": changes})
        if parts == ["api", "patch"]:
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            name = q.get("project", "")
            if not name or not NAME_RE.match(name):
                return self._err(400, "bad project name")
            episode = int(q.get("episode", 1))
            try:
                result = workflow_patch.apply_patch(name, q.get("changes", []), episode)
            except Exception as ex:
                return self._err(500, "apply patch failed: %s" % ex)
            return self._send(200, {"ok": True, "applied": result["applied"],
                                    "errors": result["errors"]})
        if parts[:2] == ["api", "onboard"] and len(parts) == 3:
            name = parts[2]
            if not NAME_RE.match(name):
                return self._err(400, "bad project name")
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            description = (q.get("description") or "").strip()
            if not description:
                return self._err(400, "description 不能为空")
            answers = q.get("answers") or []
            want = q.get("want") or "questions"
            payload = {"description": description, "qa": answers}
            try:
                if want == "brief":
                    text = agent.generate("onboard_brief", payload)
                    dest = ai_writer.write_brief(name, text)
                    return self._send(200, {"ok": True, "brief": text,
                                            "path": str(dest)})
                text = agent.generate("onboard_questions", payload)
                return self._send(200, {"ok": True,
                                        "questions": agent.parse_questions(text)})
            except common.ConfigError as ex:
                return self._err(502, "LLM 配置错误: %s" % ex)
            except agent.AgentError as ex:
                return self._err(502, "模型调用失败: %s" % ex)
        if parts == ["api", "storyboard-gen"]:
            try:
                q = self._read_json()
            except Exception:
                q = {}
            name = q.get("project")
            if not name or not NAME_RE.match(name):
                return self._err(400, "bad project name")
            episode = int(q.get("episode", 1))
            if not ai_writer.read_script(name):
                return self._err(400, "缺剧本.md（先 AI 编剧生成剧本）")
            # 本轮整改：与 ai-write 一致改为后台 job（LLM 拆分耗时较长，同步会阻塞请求）
            meta = {"project": name, "type": "storyboard", "episode": episode}
            jid = _new_job(meta)
            t = threading.Thread(target=run_storyboard_gen_job,
                                 args=(jid, name, episode), daemon=True)
            t.start()
            return self._send(200, {"job": jid, "status": "running"})
        if (parts[:2] == ["api", "shot-ref"] and len(parts) == 5):
            name, ep, shot = parts[2], parts[3], parts[4]
            epn = self._check_proj_ep(name, ep)
            if epn is None or not shot.isdigit():
                return self._err(400, "bad path")
            sb = common.episode_dir(name, epn) / "分镜.md"
            if not sb.exists():
                return self._err(404, "缺分镜.md（先生成分镜）")
            try:
                rows = load_storyboard(sb)
            except Exception as ex:
                return self._err(500, "分镜解析失败: %s" % ex)
            n = int(shot)
            row = next((r for r in rows if str(r.get("shot")) == str(n)), None)
            if row is None:
                return self._err(404, "分镜 %d 不存在" % n)
            try:
                style = common.load_config().get_path("project.style_prefix", "")
                prompt = agent.generate("shot_ref", refs_mod.shot_ref_payload(row, style))
            except common.ConfigError as ex:
                return self._err(502, "LLM 配置错误: %s" % ex)
            except agent.AgentError as ex:
                return self._err(502, "模型调用失败: %s" % ex)
            refs_mod.save_ref_prompt(name, epn, n, prompt)
            image = next((r["image"] for r in refs_mod.list_refs(name, epn)
                          if r["shot"] == n), None)
            return self._send(200, {"shot": n, "prompt": prompt, "image": image})
        if parts == ["api", "agent-command"]:
            try:
                q = self._read_json()
            except Exception:
                return self._err(400, "bad json")
            text = (q.get("command") or "").strip()
            if not text:
                return self._err(400, "command 不能为空")
            actions = agent.parse_command(text)
            return self._send(200, {"ok": True, "executed": False,
                                    "command": text, "actions": actions})
        return self._err(404, "unknown api: /" + "/".join(parts))

    def api_put(self, parts, body):
        if parts == ["api", "config-agent"]:
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                return self._err(400, "bad json")
            agent_cfg = payload.get("agent")
            if not isinstance(agent_cfg, dict):
                return self._err(400, "agent 必须是对象")
            overrides = {"agent": agent_cfg}
            if common.LOCAL_OVERRIDES.exists():
                try:
                    old = json.loads(common.LOCAL_OVERRIDES.read_text(encoding="utf-8"))
                    overrides = common._deep_merge(old or {}, overrides)
                except Exception:
                    pass
            common.LOCAL_OVERRIDES.write_text(
                json.dumps(overrides, ensure_ascii=False, indent=1), encoding="utf-8")
            return self._send(200, {"ok": True,
                                    "agent": common.load_config().get_path("agent", {})})
        if (parts[:2] == ["api", "brief"] and len(parts) == 3):
            name = parts[2]
            if not NAME_RE.match(name):
                return self._err(400, "bad project name")
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                return self._err(400, "bad json")
            try:
                dest = ai_writer.write_brief(name, payload.get("brief", ""))
            except Exception as ex:
                return self._err(500, "save brief failed: %s" % ex)
            return self._send(200, {"ok": True, "path": str(dest)})
        if (parts[:2] == ["api", "project"] and len(parts) == 6
                and parts[3] == "episode" and parts[5] == "storyboard"):
            epn = self._check_proj_ep(parts[2], parts[4])
            if epn is None:
                return self._err(400, "bad path")
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                return self._err(400, "bad json")
            try:
                path = save_storyboard(parts[2], epn, payload.get("rows", []),
                                       payload.get("header", []))
            except Exception as ex:
                return self._err(500, "save failed: %s" % ex)
            try:  # 品味采集：草稿→定稿 diff + 修改率统计（失败不影响主流程）
                sb_path = common.episode_dir(parts[2], epn) / "分镜.md"
                taste.snapshot_and_diff(str(sb_path.relative_to(ROOT)),
                                        sb_path.read_text(encoding="utf-8"))
            except Exception:
                pass
            return self._send(200, {"ok": True, "path": path, "rows": len(payload.get("rows", []))})
        return self._err(404, "unknown api: /" + "/".join(parts))

    # ---------- HTTP 入口 ----------
    def do_GET(self):
        parts = self._path_parts()
        if not parts:
            return self._static("index.html")
        if parts[0] == "api":
            return self.api_get(parts)
        if parts[0] == "video" and len(parts) == 4:
            return self._video(parts[1], parts[2], parts[3])
        if parts[0] == "refs" and len(parts) == 4:
            return self._ref_img(parts[1], parts[2], parts[3])
        if parts[0] == "review-img" and len(parts) == 4:
            return self._review_img(parts[1], parts[2], parts[3])
        if parts[0] == "asset-img" and len(parts) == 2:
            return self._asset_img(parts[1])
        return self._static(self.path.lstrip("/"))

    def do_PUT(self):
        parts = self._path_parts()
        if parts[0] != "api":
            return self._err(404, "not found")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        return self.api_put(parts, body)

    def do_DELETE(self):
        parts = self._path_parts()
        if parts[:2] == ["api", "asset"] and len(parts) == 3:
            code = parts[2].strip().upper()
            try:
                common.validate_code(code)
            except Exception as ex:
                return self._err(400, str(ex))
            try:
                result = asset_manager.remove_asset(code)
            except Exception as ex:
                return self._err(500, "asset delete failed: %s" % ex)
            return self._send(200, {"ok": True, "code": code,
                                    "removed": len(result["removed"])})
        return self._err(404, "unknown api: /" + "/".join(parts))

    def do_POST(self):
        parts = self._path_parts()
        if parts[0] != "api":
            return self._err(404, "not found")
        return self.api_post(parts)

    def log_message(self, fmt, *args):
        sys.stderr.write("[bridge] %s\n" % (fmt % args))


def main():
    ap = argparse.ArgumentParser(description="AI 短剧流水线前端桥")
    ap.add_argument("--port", type=int, default=8189)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print("前端桥: http://%s:%d  (静态目录 %s)" % (a.host, a.port, WEB))
    print("项目根: %s" % ROOT)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
