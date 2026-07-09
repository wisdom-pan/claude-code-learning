"""agent —— 子 agent(写操作,串行)。

对标 Claude Code 的 AgentTool(docs/06):把一个独立子任务委托给一个隔离的子 agent。
关键约束:子 agent 的工具集里**移除 agent 工具本身**,禁止递归 spawn(防止无限嵌套)。
"""

from __future__ import annotations

from typing import Any

from .base import Tool


class AgentTool(Tool):
    name = "agent"
    description = (
        "把一个独立、明确的子任务委托给子 agent(拥有除本工具外的所有工具)。"
        "适合需要多步探索/搜索的封闭任务。返回子 agent 的最终文本结论。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "交给子 agent 的完整任务描述"},
        },
        "required": ["task"],
    }

    def __init__(self, provider: Any, config: Any) -> None:
        # 由注册表在装配时注入 provider 与 config
        self._provider = provider
        self._config = config

    def run(self, args: dict[str, Any]) -> str:
        # 延迟导入,打破 agent <-> tools 的循环依赖(见 docs/02 的 lazy-require 模式)
        from ..agent import Agent
        from . import build_tools

        # 子 agent 的工具集:排除 agent 工具本身 → 禁止递归
        child_tools = build_tools(self._provider, self._config, include_agent=False)
        child = Agent(
            provider=self._provider,
            config=self._config,
            tools=child_tools,
            system_prompt="你是一个子 agent,专注完成被交付的单一任务,完成后用简洁文本汇报结论。",
            stream=False,  # 子 agent 静默运行,不抢主输出
        )
        return child.chat(args["task"])
