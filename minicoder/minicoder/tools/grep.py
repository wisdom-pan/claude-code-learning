"""grep —— 按正则搜索文件内容(只读,并发安全)。

优先用系统 ripgrep(rg),没有则回退到纯 Python 遍历,保证零依赖也能用。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import Tool

MAX_LINES = 200
_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


class GrepTool(Tool):
    name = "grep"
    description = "在文件内容中按正则搜索,返回匹配的 文件:行号:内容。可用 glob 限定文件范围。"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "path": {"type": "string", "description": "搜索根目录(默认当前目录)"},
            "glob": {"type": "string", "description": "只搜匹配此 glob 的文件,如 *.py(可选)"},
        },
        "required": ["pattern"],
    }

    def is_read_only(self) -> bool:
        return True

    def run(self, args: dict[str, Any]) -> str:
        pattern = args["pattern"]
        root = args.get("path") or "."
        file_glob = args.get("glob")

        if shutil.which("rg"):
            return self._run_rg(pattern, root, file_glob)
        return self._run_python(pattern, root, file_glob)

    def _run_rg(self, pattern: str, root: str, file_glob: str | None) -> str:
        cmd = ["rg", "--line-number", "--no-heading", "--color=never", "-e", pattern]
        if file_glob:
            cmd += ["--glob", file_glob]
        cmd.append(root)
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as e:
            return f"错误:ripgrep 执行失败: {e}"
        if out.returncode not in (0, 1):  # 1 = 无匹配
            return f"错误:{out.stderr.strip() or 'ripgrep 返回非零'}"
        lines = out.stdout.splitlines()
        if not lines:
            return "(无匹配)"
        truncated = len(lines) > MAX_LINES
        body = "\n".join(lines[:MAX_LINES])
        return body + (f"\n... (已截断到 {MAX_LINES} 行)" if truncated else "")

    def _run_python(self, pattern: str, root: str, file_glob: str | None) -> str:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"错误:无效正则: {e}"
        root_path = Path(root).expanduser()
        results: list[str] = []
        paths = root_path.rglob(file_glob) if file_glob else root_path.rglob("*")
        for p in paths:
            if not p.is_file() or any(part in _IGNORE_DIRS for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    results.append(f"{p}:{i}:{line}")
                    if len(results) >= MAX_LINES:
                        return "\n".join(results) + f"\n... (已截断到 {MAX_LINES} 行)"
        return "\n".join(results) if results else "(无匹配)"
