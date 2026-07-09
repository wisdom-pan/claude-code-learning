"""工具注册表 —— 装配可用工具集。

对标 Claude Code 的 tools.ts(docs/04):集中组装工具池。极简版只保留 7 个核心工具。
agent 工具需要 provider/config 才能派生子 agent,因此在装配时注入。
"""

from __future__ import annotations

from typing import Any

from .agent import AgentTool
from .base import Tool
from .bash import BashTool
from .edit import EditFileTool
from .glob_tool import GlobTool
from .grep import GrepTool
from .read import ReadFileTool
from .write import WriteFileTool

__all__ = [
    "Tool",
    "BashTool",
    "ReadFileTool",
    "WriteFileTool",
    "EditFileTool",
    "GlobTool",
    "GrepTool",
    "AgentTool",
    "build_tools",
]


def build_tools(provider: Any, config: Any, include_agent: bool = True) -> list[Tool]:
    """装配工具列表。

    include_agent=False 用于子 agent —— 移除 agent 工具以禁止递归 spawn。
    """
    tools: list[Tool] = [
        BashTool(),
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        GlobTool(),
        GrepTool(),
    ]
    if include_agent:
        tools.append(AgentTool(provider=provider, config=config))
    return tools
