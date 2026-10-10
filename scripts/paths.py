"""工作区与路径约定。

所有产物写在「工作区」，默认 ``~/AutoVideoEditor``，不污染 skill 目录。
换盘：``export AVE_WORKSPACE=/Volumes/xxx/AutoVideoEditor``

注意：本机在沙箱 broker 下写 ``~/`` 时，**目标目录已存在仍会报 EEXIST**
（`mkdir(exist_ok=True)` 不生效），所以一切建目录都走 `ensure_dir()`。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets"
SCRIPTS_DIR = SKILL_DIR / "scripts"
REFERENCES_DIR = SKILL_DIR / "references"


def workspace() -> Path:
    env = os.environ.get("AVE_WORKSPACE")
    root = Path(env).expanduser() if env else Path.home() / "AutoVideoEditor"
    return root


def jobs_root() -> Path:
    return ensure_dir(workspace() / "jobs")


def uploads_root() -> Path:
    return ensure_dir(workspace() / "uploads")


def ensure_dir(p: Path) -> Path:
    """先判断再建，绕开 broker 下 mkdir(exist_ok=True) 的 EEXIST 怪癖。"""
    p = Path(p)
    if not p.exists():
        p.mkdir(parents=True)
    return p


def slug(text: str, fallback: str = "job") -> str:
    text = (text or "").strip()
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:48] or fallback


def new_job(name: str | None = None) -> Path:
    """开一个新任务目录：jobs/<名字>_<MMDD-HHMM>。"""
    stamp = time.strftime("%m%d-%H%M")
    base = slug(name or "", fallback="job")
    return ensure_dir(jobs_root() / f"{base}_{stamp}")


def job_dir(name: str) -> Path:
    return jobs_root() / name


def as_uri(p: Path) -> str:
    """给 Playwright 用的 file:// 地址（中文/空格都安全）。"""
    return Path(p).resolve().as_uri()
