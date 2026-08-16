#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LHH 复用桥（可选依赖 lh_harness · spec 10 对齐 LongHorizon-Harness）。

复用边界（Windows 实测结论）：
  LHH 的 manager.run 全循环依赖 POSIX 专属安全文件原语（O_NOFOLLOW / dir_fd / killpg），
  Windows 上无法直接运行其存储层；逐层垫片 = 重写其控制总线，违背"直接复用"且脆弱。

  因此复用其【纯逻辑】组件，循环驱动用本项目同构的 stdlib run_loop：
  - DeepSeekHarnessAdapter：官方 dsh 适配器（deepseek-v4-flash，可角色分离）——dsh CLI 可用时可直接充当 Executor
  - parse_audit_report / audit_report_from_episode_result：Auditor 报告结构化解析
  - build_role_manager/executor/auditor_prompt：角色提示词模板（参考）
  - HarnessConfig / EpisodeBudget：轮数与预算设置模型（参考）
"""
import json
import subprocess
import sys
from pathlib import Path

import common

# LHH 官方仓库 submodule（vendor/longhorizon-harness，git pull 同步接口不变即复用）。
# 优先 vendor 路径，回退 pip 安装的 lh-harness。
VENDOR_LHH = common.ROOT / "vendor" / "longhorizon-harness" / "src"
if VENDOR_LHH.exists():
    sys.path.insert(0, str(VENDOR_LHH))

try:
    from lh_harness.adapters import DeepSeekHarnessAdapter
    from lh_harness.manager import (parse_audit_report, audit_report_from_episode_result,
                                     HarnessConfig, EpisodeBudget)
    LHH_AVAILABLE = True
    LHH_SOURCE = "vendor" if VENDOR_LHH.exists() else "pip"
    _LHH_IMPORT_ERR = None
except Exception as exc:          # noqa: BLE001 —— 可选依赖，缺失时优雅降级
    LHH_AVAILABLE = False
    LHH_SOURCE = None
    _LHH_IMPORT_ERR = str(exc)
    parse_audit_report = audit_report_from_episode_result = None
    DeepSeekHarnessAdapter = HarnessConfig = EpisodeBudget = None


def parse_auditor_report(raw, round_index=1):
    """复用 LHH Auditor 报告解析（不可用/解析失败时返回兜底结构）。"""
    if not LHH_AVAILABLE or parse_audit_report is None:
        return {"status": "unknown", "report_text": raw or "", "round_id": str(round_index)}
    try:
        rep = parse_audit_report(raw or "", round_index)
        return {"status": getattr(rep, "status", "unknown"),
                "report_text": getattr(rep, "report_text", ""),
                "state_summary": getattr(rep, "state_summary", ""),
                "completed": getattr(rep, "completed", []),
                "round_id": getattr(rep, "round_id", str(round_index))}
    except Exception:
        return {"status": "unknown", "report_text": raw or "", "round_id": str(round_index)}


def dsh_adapter_available():
    """dsh CLI（DeepSeek Harness）是否可用；可用时 executor 可选官方适配器。"""
    return LHH_AVAILABLE and _which("dsh") is not None


def make_dsh_adapter(workspace_path, role="cli_executor", model="deepseek-v4-flash"):
    """LHH 官方 DeepSeekHarnessAdapter（角色可分离：manager/auditor/cli_executor）。"""
    if not LHH_AVAILABLE:
        raise RuntimeError("lh_harness 未安装（pip install lh-harness）")
    return DeepSeekHarnessAdapter(workspace_path=workspace_path, role=role, model=model)


def lhh_status():
    """LHH 可用性与配置摘要（供设置界面 /api/config-agent）。"""
    return {"available": LHH_AVAILABLE,
            "error": _LHH_IMPORT_ERR,
            "version": "0.1.5 (submodule af17ce8)",
            "source": LHH_SOURCE,
            "win_loop": "stdlib run_loop（LHH manager.run 依赖 POSIX 原语，Windows 不适用）",
            "reused": ["DeepSeekHarnessAdapter", "parse_audit_report",
                       "audit_report_from_episode_result", "HarnessConfig", "EpisodeBudget"],
            "sync": "git submodule update --remote vendor/longhorizon-harness（接口不变即可）",
            "dsh_cli": dsh_adapter_available()}


def _which(cmd):
    import shutil
    return shutil.which(cmd)
