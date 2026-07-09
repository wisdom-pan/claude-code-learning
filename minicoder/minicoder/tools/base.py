"""Tool 基类 —— fail-closed 默认。

对标 Claude Code 的 TOOL_DEFAULTS(docs/04):最保守的默认值是"不并发、不只读",
子类想放宽必须显式声明。这样新工具默认串行执行,不会因忘记声明而引发并发写冲突。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    #: 给模型看的工具名(function name)
    name: str = ""
    #: 给模型看的用途说明
    description: str = ""
    #: JSON Schema 描述参数(function-calling 的 parameters 字段)
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    # ---- fail-closed 默认:保守起见,默认既不只读也不并发安全 ----
    def is_read_only(self) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        # 默认 False;只读工具应覆写为 True 以进入并发批次
        return self.is_read_only()

    @abstractmethod
    def run(self, args: dict[str, Any]) -> str:
        """执行工具,返回给模型的文本结果。异常由 agent loop 捕获并回填为错误结果。"""
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        """归一化的工具声明,供 provider 转成各自的 function/tool 格式。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
