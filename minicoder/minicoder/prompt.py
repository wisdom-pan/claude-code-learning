"""System prompt 构建 + 运行环境上下文采集。

对标 Claude Code 的 context 系统(docs/03):在对话开始时把 git 状态、当前目录、
日期、可选的 AGENTS.md/CLAUDE.md 注入 system prompt。极简版:同步、无 memoize。
"""

from __future__ import annotations

import datetime
import subprocess
from pathlib import Path

SYSTEM_PROMPT = """你是 minicoder,一个运行在用户终端里的 AI 编程助手。

你可以调用工具来读写文件、执行 shell 命令、搜索代码。工作准则:

- 动手前先用 read_file / grep / glob 了解现有代码,不要凭空假设。
- 修改文件用 edit_file(基于唯一文本匹配替换),新建文件才用 write_file。
- 只做用户要求的事,保持改动最小,遵循已有代码风格。
- shell 命令要谨慎;破坏性操作(删除、覆盖)先说明再执行。
- 完成后简明汇报你做了什么;不确定时如实说明,不要编造。

一次可以并行发起多个只读工具调用(read/grep/glob),写操作会串行执行。
""".strip()


def _run_git(args: list[str], cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_context(cwd: Path) -> str:
    """采集 git 状态(分支 / 简短 status / 最近提交),对标 docs/03 的做法。"""
    if not (cwd / ".git").exists():
        return ""
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    status = _run_git(["status", "--short"], cwd)
    log = _run_git(["log", "--oneline", "-n", "5"], cwd)
    if not (branch or status or log):
        return ""
    parts = ["# Git 状态(对话开始时的快照)"]
    if branch:
        parts.append(f"当前分支: {branch}")
    if status:
        # 截断,避免超长 status 占满上下文
        status = status[:2000]
        parts.append(f"改动:\n{status}")
    if log:
        parts.append(f"最近提交:\n{log}")
    return "\n".join(parts)


def _project_memory(cwd: Path) -> str:
    """加载项目级说明文件(AGENTS.md / CLAUDE.md),类似 Claude Code 的 CLAUDE.md。"""
    for name in ("AGENTS.md", "CLAUDE.md"):
        p = cwd / name
        if p.is_file():
            return f"# 项目说明({name})\n{p.read_text(encoding='utf-8')[:8000]}"
    return ""


def build_system_prompt(cwd: Path | None = None) -> str:
    """组装完整 system prompt:基础指令 + 环境上下文。"""
    cwd = cwd or Path.cwd()
    today = datetime.date.today().isoformat()
    sections = [
        SYSTEM_PROMPT,
        f"# 环境\n工作目录: {cwd}\n今天的日期: {today}",
    ]
    git = _git_context(cwd)
    if git:
        sections.append(git)
    memory = _project_memory(cwd)
    if memory:
        sections.append(memory)
    return "\n\n".join(sections)
