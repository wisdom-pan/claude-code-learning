"""Provider 抽象层 —— 统一 chat 接口,支持 OpenAI 兼容与 Anthropic。

对标 Claude Code 的服务层 API 客户端(docs/13-services.md):
- `client.ts` 多 Provider 支持(Direct API / Bedrock / Vertex / Foundry)——这里抽象一层
  Provider,让 Agent Loop 与具体后端解耦,同时支持 OpenAI 兼容 API 与 Anthropic。
- `withRetry.ts` 指数退避重试 —— 见下方 `_with_retry`。

## 归一化的内部消息格式(Agent 层使用)
- {"role": "user", "content": str}
- {"role": "assistant", "content": str, "tool_calls": [ToolCall, ...]}
- {"role": "tool", "tool_call_id": str, "name": str, "content": str}

各 Provider 负责把这套格式翻译成自己的 wire 格式,并把响应翻译回统一的 Reply。

## 为什么 llm 层最复杂(见 docs/02)
流式响应会把每个 tool_call 的 arguments 切成碎片,必须按 index 重新拼接;provider 偶尔
返回半个 JSON 或空 usage;429/超时/5xx 都要退避重试。这些都在本文件里处理。
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


# 网络/服务端瞬时错误:退避重试
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 4


def _with_retry(fn: Callable[[], httpx.Response]) -> httpx.Response:
    """对可重试错误做指数退避(1s,2s,4s,8s)。"""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = fn()
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
        else:
            if resp.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES - 1:
                time.sleep(2**attempt)
                continue
            return resp
        if attempt < _MAX_RETRIES - 1:
            time.sleep(2**attempt)
    if last_exc:
        raise last_exc
    raise RuntimeError("重试耗尽")


class Provider(ABC):
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
        model: str | None = None,
        stream: bool = True,
        on_text: Callable[[str], None] | None = None,
    ) -> Reply:
        """发起一次补全。stream=True 时,每收到一段文本就调用 on_text 回调。"""
        raise NotImplementedError


# ----------------------------------------------------------------------------
# OpenAI 兼容(OpenAI / DeepSeek / Ollama / Kimi / Qwen ...)
# ----------------------------------------------------------------------------
class OpenAIProvider(Provider):
    def _tools_payload(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]

    def _messages_payload(
        self, messages: list[dict[str, Any]], system: str
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            role = m["role"]
            if role == "assistant" and m.get("tool_calls"):
                out.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                                },
                            }
                            for tc in m["tool_calls"]
                        ],
                    }
                )
            elif role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m["tool_call_id"],
                        "content": m["content"],
                    }
                )
            else:
                out.append({"role": role, "content": m.get("content", "")})
        return out

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
        model: str | None = None,
        stream: bool = True,
        on_text: Callable[[str], None] | None = None,
    ) -> Reply:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": self._messages_payload(messages, system),
            "stream": stream,
        }
        if tools:
            payload["tools"] = self._tools_payload(tools)
        if stream:
            payload["stream_options"] = {"include_usage": True}

        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/chat/completions"

        if not stream:
            resp = _with_retry(
                lambda: httpx.post(url, json=payload, headers=headers, timeout=300)
            )
            resp.raise_for_status()
            return self._parse_nonstream(resp.json())
        return self._parse_stream(url, payload, headers, on_text)

    def _parse_nonstream(self, data: dict[str, Any]) -> Reply:
        choice = data["choices"][0]["message"]
        reply = Reply(text=choice.get("content") or "")
        for tc in choice.get("tool_calls") or []:
            fn = tc["function"]
            reply.tool_calls.append(
                ToolCall(id=tc["id"], name=fn["name"], arguments=_safe_json(fn.get("arguments", "")))
            )
        usage = data.get("usage") or {}
        reply.input_tokens = usage.get("prompt_tokens", 0) or 0
        reply.output_tokens = usage.get("completion_tokens", 0) or 0
        return reply

    def _parse_stream(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        on_text: Callable[[str], None] | None,
    ) -> Reply:
        reply = Reply()
        # tool_calls 按 index 累积:{index: {"id","name","args_str"}}
        acc: dict[int, dict[str, str]] = {}

        with httpx.Client(timeout=300) as client:
            with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    self._consume_chunk(chunk, reply, acc, on_text)

        # 拼装累积的 tool_calls(按 index 顺序)
        for idx in sorted(acc):
            item = acc[idx]
            reply.tool_calls.append(
                ToolCall(
                    id=item.get("id") or f"call_{idx}",
                    name=item.get("name", ""),
                    arguments=_safe_json(item.get("args", "")),
                )
            )
        return reply

    def _consume_chunk(
        self,
        chunk: dict[str, Any],
        reply: Reply,
        acc: dict[int, dict[str, str]],
        on_text: Callable[[str], None] | None,
    ) -> None:
        usage = chunk.get("usage")
        if usage:
            reply.input_tokens = usage.get("prompt_tokens", 0) or reply.input_tokens
            reply.output_tokens = usage.get("completion_tokens", 0) or reply.output_tokens
        choices = chunk.get("choices") or []
        if not choices:
            return
        delta = choices[0].get("delta") or {}
        if delta.get("content"):
            reply.text += delta["content"]
            if on_text:
                on_text(delta["content"])
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            slot = acc.setdefault(idx, {"id": "", "name": "", "args": ""})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] += fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]


# ----------------------------------------------------------------------------
# Anthropic (Messages API)
# ----------------------------------------------------------------------------
class AnthropicProvider(Provider):
    _API_VERSION = "2023-06-01"
    _MAX_TOKENS = 8192

    def _tools_payload(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
            for t in tools
        ]

    def _messages_payload(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m["role"]
            if role == "assistant" and m.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    blocks.append(
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                    )
                out.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m["tool_call_id"],
                                "content": m["content"],
                            }
                        ],
                    }
                )
            else:
                out.append({"role": role, "content": m.get("content", "")})
        return out

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str,
        model: str | None = None,
        stream: bool = True,
        on_text: Callable[[str], None] | None = None,
    ) -> Reply:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": self._MAX_TOKENS,
            "system": system,
            "messages": self._messages_payload(messages),
            "stream": stream,
        }
        if tools:
            payload["tools"] = self._tools_payload(tools)

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self._API_VERSION,
            "content-type": "application/json",
        }
        url = f"{self.base_url}/v1/messages"

        if not stream:
            resp = _with_retry(
                lambda: httpx.post(url, json=payload, headers=headers, timeout=300)
            )
            resp.raise_for_status()
            return self._parse_nonstream(resp.json())
        return self._parse_stream(url, payload, headers, on_text)

    def _parse_nonstream(self, data: dict[str, Any]) -> Reply:
        reply = Reply()
        for block in data.get("content", []):
            if block["type"] == "text":
                reply.text += block["text"]
            elif block["type"] == "tool_use":
                reply.tool_calls.append(
                    ToolCall(id=block["id"], name=block["name"], arguments=block.get("input") or {})
                )
        usage = data.get("usage") or {}
        reply.input_tokens = usage.get("input_tokens", 0) or 0
        reply.output_tokens = usage.get("output_tokens", 0) or 0
        return reply

    def _parse_stream(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        on_text: Callable[[str], None] | None,
    ) -> Reply:
        reply = Reply()
        # content_block 按 index 累积;tool_use 的 input 以 partial_json 分片到达
        blocks: dict[int, dict[str, Any]] = {}

        with httpx.Client(timeout=300) as client:
            with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[len("data:"):].strip())
                    except json.JSONDecodeError:
                        continue
                    self._consume_event(event, reply, blocks, on_text)

        for idx in sorted(blocks):
            b = blocks[idx]
            if b.get("type") == "tool_use":
                reply.tool_calls.append(
                    ToolCall(id=b["id"], name=b["name"], arguments=_safe_json(b.get("json", "")))
                )
        return reply

    def _consume_event(
        self,
        event: dict[str, Any],
        reply: Reply,
        blocks: dict[int, dict[str, Any]],
        on_text: Callable[[str], None] | None,
    ) -> None:
        etype = event.get("type")
        if etype == "content_block_start":
            idx = event["index"]
            cb = event["content_block"]
            if cb["type"] == "tool_use":
                blocks[idx] = {"type": "tool_use", "id": cb["id"], "name": cb["name"], "json": ""}
            else:
                blocks[idx] = {"type": "text"}
        elif etype == "content_block_delta":
            idx = event["index"]
            delta = event["delta"]
            if delta["type"] == "text_delta":
                reply.text += delta["text"]
                if on_text:
                    on_text(delta["text"])
            elif delta["type"] == "input_json_delta":
                blocks.setdefault(idx, {"type": "tool_use", "json": ""})
                blocks[idx]["json"] += delta.get("partial_json", "")
        elif etype == "message_start":
            usage = (event.get("message") or {}).get("usage") or {}
            reply.input_tokens = usage.get("input_tokens", 0) or reply.input_tokens
        elif etype == "message_delta":
            usage = event.get("usage") or {}
            reply.output_tokens = usage.get("output_tokens", 0) or reply.output_tokens


def _safe_json(s: str) -> dict[str, Any]:
    """容错解析 arguments;空串或半个 JSON 都退化为 {}。"""
    s = (s or "").strip()
    if not s:
        return {}
    try:
        result = json.loads(s)
        return result if isinstance(result, dict) else {"value": result}
    except json.JSONDecodeError:
        return {}


def get_provider(config: Any) -> Provider:
    """工厂:按 config.provider 选择实现。"""
    if config.provider == "anthropic":
        return AnthropicProvider(config.api_key, config.base_url, config.model)
    return OpenAIProvider(config.api_key, config.base_url, config.model)
