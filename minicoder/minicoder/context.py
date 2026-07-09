"""三层上下文压缩 —— 对标 CoreCoder 与本仓库 docs/03-context-system.md。

窗口快满时,先用最便宜的手段:
| 层 | 阈值 | 动作                                  | 调 LLM |
|----|------|---------------------------------------|--------|
| 1  | 50%  | 就地裁剪过长的 tool 输出               | 否     |
| 2  | 70%  | 把较旧的轮次摘要成一段,近期保留原样    | 是     |
| 3  | 90%  | 紧急:摘要 + 近期一起压到最紧凑         | 是     |

原则(docs/03):粗暴截断往往丢掉长任务最依赖的早期决策,所以优先摘要而非删除。

token 估算用启发式(字符数 / 4),count_tokens 留作可替换点。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .providers import Provider

# 默认上下文窗口(token)。可按模型调,这里给一个通用值。
DEFAULT_CONTEXT_WINDOW = 128_000

TIER1_RATIO = 0.50
TIER2_RATIO = 0.70
TIER3_RATIO = 0.90

TOOL_OUTPUT_MAX_CHARS = 4_000  # tier1 裁剪单条 tool 结果的上限
KEEP_RECENT_MESSAGES = 6  # tier2/3 保留的近期消息数


def count_tokens(text: str) -> int:
    """启发式 token 估算。替换点:接入 tiktoken 等可提升精度。"""
    return max(1, len(text) // 4)


def _message_text(m: dict[str, Any]) -> str:
    parts = [str(m.get("content") or "")]
    for tc in m.get("tool_calls") or []:
        parts.append(str(getattr(tc, "arguments", "")))
    return " ".join(parts)


def total_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(count_tokens(_message_text(m)) for m in messages)


def _tier1_trim(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """就地裁剪过长的 tool 结果,不调 LLM。返回新列表。"""
    out = []
    for m in messages:
        if m.get("role") == "tool" and len(m.get("content", "")) > TOOL_OUTPUT_MAX_CHARS:
            content = m["content"]
            head = content[: TOOL_OUTPUT_MAX_CHARS // 2]
            tail = content[-TOOL_OUTPUT_MAX_CHARS // 2 :]
            trimmed = f"{head}\n\n... [已裁剪 {len(content) - TOOL_OUTPUT_MAX_CHARS} 字符] ...\n\n{tail}"
            out.append({**m, "content": trimmed})
        else:
            out.append(m)
    return out


def _summarize(
    provider: Provider,
    messages: list[dict[str, Any]],
    model: str,
    tight: bool,
) -> str:
    """用 LLM 把给定消息摘要成一段文字。"""
    transcript_parts = []
    for m in messages:
        role = m["role"]
        text = m.get("content") or ""
        for tc in m.get("tool_calls") or []:
            text += f"\n[调用工具 {tc.name}({tc.arguments})]"
        transcript_parts.append(f"{role}: {text}")
    transcript = "\n".join(transcript_parts)

    instruction = (
        "把下面的对话压缩成最紧凑的要点,只保留后续任务必需的信息:目标、关键决策、"
        "已修改的文件、未完成事项。丢弃寒暄与冗余。"
        if tight
        else "把下面较早的对话摘要成一段简洁文字,保留目标、关键决策、已改动的文件和待办。"
    )
    reply = provider.chat(
        messages=[{"role": "user", "content": f"{instruction}\n\n---\n{transcript}"}],
        tools=[],
        system="你是一个对话摘要器,只输出摘要文本,不做其他事。",
        model=model,
        stream=False,
    )
    return reply.text.strip() or "(摘要为空)"


def compact_if_needed(
    messages: list[dict[str, Any]],
    provider: Provider,
    model: str,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    on_notice: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """在每轮 API 调用前检查并按需压缩。返回(可能压缩后的)消息列表。

    始终保留第一条消息(通常是最初的用户请求,承载任务目标)。
    """
    used = total_tokens(messages)
    ratio = used / max(1, context_window)

    if ratio < TIER1_RATIO or len(messages) <= KEEP_RECENT_MESSAGES + 1:
        return messages

    def notice(msg: str) -> None:
        if on_notice:
            on_notice(msg)

    # Tier 1:就地裁剪(便宜,先做)
    messages = _tier1_trim(messages)
    if total_tokens(messages) / max(1, context_window) < TIER2_RATIO:
        notice("上下文压缩:裁剪过长工具输出(tier1)")
        return messages

    # Tier 2 / 3:摘要较旧轮次
    tight = ratio >= TIER3_RATIO
    first = messages[0]
    recent = messages[-KEEP_RECENT_MESSAGES:]
    older = messages[1 : -KEEP_RECENT_MESSAGES] if len(messages) > KEEP_RECENT_MESSAGES + 1 else []
    if not older:
        return messages

    summary_text = _summarize(provider, older, model, tight=tight)
    summary_msg = {
        "role": "user",
        "content": f"[早前对话摘要]\n{summary_text}",
    }
    notice(f"上下文压缩:摘要 {len(older)} 条历史消息({'tier3 紧急' if tight else 'tier2'})")
    return [first, summary_msg, *recent]
