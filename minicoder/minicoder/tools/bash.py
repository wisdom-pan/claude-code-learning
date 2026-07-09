"""bash —— 执行 shell 命令(写操作,串行),带危险命令正则门控。

对标 Claude Code 权限系统(docs/05)的极简版:一批高危模式硬拦截,命中即拒绝并说明原因。
这不是完整沙箱,只是防手滑/防模型误伤的第一道闸。
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from .base import Tool

DEFAULT_TIMEOUT = 120  # 秒

# 高危命令模式:命中即拒绝执行(fail-closed)
_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*(-[a-zA-Z]*r[a-zA-Z]*\s+)*.*\s+/(\s|$)"), "递归删除根目录"),
    (re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f|\brm\s+-[a-zA-Z]*f[a-zA-Z]*r"), "rm -rf 强制递归删除"),
    (re.compile(r":\(\)\s*\{.*\|.*&\s*\}\s*;"), "fork bomb"),
    (re.compile(r"\bdd\b.*\bof=/dev/"), "dd 覆盖磁盘设备"),
    (re.compile(r">\s*/dev/(sd|hd|nvme|disk)"), "重定向覆盖磁盘设备"),
    (re.compile(r"\bmkfs\b"), "格式化文件系统"),
    (re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"), "关机/重启"),
    (re.compile(r"\bchmod\s+-R\s+0*7{3}\s+/"), "递归 chmod 777 根目录"),
    (re.compile(r"curl.*\|\s*(sudo\s+)?(ba)?sh"), "管道执行远程脚本"),
    (re.compile(r"wget.*\|\s*(sudo\s+)?(ba)?sh"), "管道执行远程脚本"),
]


def check_dangerous(command: str) -> str | None:
    """命中危险模式则返回原因,否则返回 None。"""
    for pattern, reason in _DANGEROUS_PATTERNS:
        if pattern.search(command):
            return reason
    return None


class BashTool(Tool):
    name = "bash"
    description = "执行 shell 命令并返回 stdout/stderr。高危命令(如 rm -rf /)会被拦截。"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "timeout": {"type": "integer", "description": f"超时秒数(默认 {DEFAULT_TIMEOUT})"},
        },
        "required": ["command"],
    }

    def run(self, args: dict[str, Any]) -> str:
        command = args["command"]
        reason = check_dangerous(command)
        if reason:
            return f"已拒绝执行:检测到危险操作({reason})。如确需执行,请手动在终端运行。"

        timeout = args.get("timeout") or DEFAULT_TIMEOUT
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"错误:命令超时({timeout}s)"
        except OSError as e:
            return f"错误:{e}"

        parts = []
        if proc.stdout:
            parts.append(proc.stdout.rstrip())
        if proc.stderr:
            parts.append(f"[stderr]\n{proc.stderr.rstrip()}")
        if proc.returncode != 0:
            parts.append(f"[exit code: {proc.returncode}]")
        return "\n".join(parts) if parts else "(命令执行完成,无输出)"
