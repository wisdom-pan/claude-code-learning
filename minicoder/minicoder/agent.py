"""Agent Loop —— minicoder 的心脏。

对标本仓库 docs/02-core-engine.md:
- while 循环:发消息 → 若有 tool_use 则执行并回填结果 → 再发,直到无 tool_use
- 读写分离并发(partitionToolCalls):连续只读工具并发执行,写工具串行
- 轮数上限防跑飞;Ctrl+C 取消当前轮
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .context import compact_if_needed
from .providers import Provider, Reply, ToolCall
from .tools.base import Tool

MAX_CONCURRENCY = 8  # 只读工具组的最大并发(对标 CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY)


class Agent:
    def __init__(
        self,
        provider: Provider,
        config: Any,
        tools: list[Tool],
        system_prompt: str,
        stream: bool = True,
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.tools = tools
        self.tools_by_name = {t.name: t for t in tools}
        self.system_prompt = system_prompt
        self.stream = stream
        self.messages: list[dict[str, Any]] = messages or []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        # UI 回调(CLI 注入):流式文本、通知、工具开始
        self.on_text: Callable[[str], None] | None = None
        self.on_notice: Callable[[str], None] | None = None
        self.on_tool_start: Callable[[ToolCall], None] | None = None
        self.on_tool_result: Callable[[ToolCall, str], None] | None = None

    # ---- 单次用户输入 → 跑完整个 agent turn,返回最终文本 ----
    def chat(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        tool_schemas = [t.schema() for t in self.tools]

        for _ in range(self.config.max_rounds):
            # 每轮 API 调用前按需压缩上下文(docs/03)
            self.messages = compact_if_needed(
                self.messages, self.provider, self.config.model, on_notice=self._notice
            )

            reply = self.provider.chat(
                messages=self.messages,
                tools=tool_schemas,
                system=self.system_prompt,
                model=self.config.model,
                stream=self.stream,
                on_text=self.on_text if self.stream else None,
            )
            self.total_input_tokens += reply.input_tokens
            self.total_output_tokens += reply.output_tokens

            # 非流式:文本没通过 on_text 输出过,补一次
            if not self.stream and reply.text and self.on_text:
                self.on_text(reply.text)

            self.messages.append(self._assistant_msg(reply))

            if not reply.tool_calls:
                return reply.text

            results = self._run_tools(reply.tool_calls)
            self.messages.extend(results)

        self._notice(f"已达最大轮数 {self.config.max_rounds},停止。")
        return "(已达最大轮数限制)"

    @staticmethod
    def _assistant_msg(reply: Reply) -> dict[str, Any]:
        return {"role": "assistant", "content": reply.text, "tool_calls": reply.tool_calls}

    def _notice(self, msg: str) -> None:
        if self.on_notice:
            self.on_notice(msg)

    # ---- 读写分离执行(docs/02 的 partitionToolCalls) ----
    def _run_tools(self, tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
        """把工具调用分区成批次:连续只读 → 并发;写工具 → 各自串行。
        返回顺序与输入顺序严格一致(tool_result 必须对齐 tool_call)。"""
        results_by_id: dict[str, str] = {}

        for batch in self._partition(tool_calls):
            if len(batch) > 1:  # 只读并发批
                with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
                    for tc, out in zip(batch, pool.map(self._exec_one, batch)):
                        results_by_id[tc.id] = out
            else:  # 单个(写工具或落单的只读)串行
                tc = batch[0]
                results_by_id[tc.id] = self._exec_one(tc)

        return [
            {"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": results_by_id[tc.id]}
            for tc in tool_calls
        ]

    def _partition(self, tool_calls: list[ToolCall]) -> list[list[ToolCall]]:
        """连续的并发安全(只读)工具归为一个并发批;其余各自单独成批。"""
        batches: list[list[ToolCall]] = []
        for tc in tool_calls:
            tool = self.tools_by_name.get(tc.name)
            safe = bool(tool and tool.is_concurrency_safe())
            if safe and batches and self._batch_is_safe(batches[-1]):
                batches[-1].append(tc)
            else:
                batches.append([tc])
        return batches

    def _batch_is_safe(self, batch: list[ToolCall]) -> bool:
        tool = self.tools_by_name.get(batch[0].name)
        return bool(tool and tool.is_concurrency_safe())

    def _exec_one(self, tc: ToolCall) -> str:
        if self.on_tool_start:
            self.on_tool_start(tc)
        tool = self.tools_by_name.get(tc.name)
        if tool is None:
            out = f"错误:未知工具 {tc.name!r}"
        else:
            try:
                out = tool.run(tc.arguments)
            except Exception as e:  # noqa: BLE001 —— 工具错误回填给模型,不炸循环
                out = f"错误:工具 {tc.name} 执行失败: {type(e).__name__}: {e}"
        if self.on_tool_result:
            self.on_tool_result(tc, out)
        return out
