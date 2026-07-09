"""上下文压缩单测:token 估算、tier1 裁剪、tier2/3 摘要(摘要用假 provider)。"""

from __future__ import annotations

from minicoder.context import (
    TOOL_OUTPUT_MAX_CHARS,
    compact_if_needed,
    count_tokens,
    total_tokens,
)


class FakeProvider:
    """摘要用的假 provider,永远返回固定摘要文本。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools, system, model=None, stream=True, on_text=None):
        self.calls += 1
        from minicoder.providers import Reply

        return Reply(text="SUMMARY")


def test_count_tokens():
    assert count_tokens("") == 1
    assert count_tokens("a" * 400) == 100


def test_no_compact_when_small():
    msgs = [{"role": "user", "content": "hi"}]
    provider = FakeProvider()
    out = compact_if_needed(msgs, provider, "m", context_window=100_000)
    assert out is msgs
    assert provider.calls == 0


def test_tier1_trims_tool_output():
    # 构造:大量消息 + 一条超长 tool 输出,窗口设小以触发压缩但停在 tier1
    big = "x" * (TOOL_OUTPUT_MAX_CHARS * 3)
    msgs = [{"role": "user", "content": "task"}]
    msgs += [{"role": "assistant", "content": "ok"} for _ in range(10)]
    msgs.append({"role": "tool", "tool_call_id": "1", "name": "read", "content": big})
    provider = FakeProvider()
    # 窗口设为刚好让 ratio 落在 tier1~tier2 之间
    window = int(total_tokens(msgs) / 0.55)
    out = compact_if_needed(msgs, provider, "m", context_window=window)
    tool_msgs = [m for m in out if m.get("role") == "tool"]
    assert "已裁剪" in tool_msgs[0]["content"]
    assert provider.calls == 0  # tier1 不调 LLM


def test_tier2_summarizes():
    # 很多消息 + 小窗口 → 触发摘要
    msgs = [{"role": "user", "content": "original task"}]
    msgs += [{"role": "assistant", "content": "step " * 50} for _ in range(20)]
    provider = FakeProvider()
    window = int(total_tokens(msgs) / 0.75)  # ratio ≈ 0.75,落在 tier2
    out = compact_if_needed(msgs, provider, "m", context_window=window)
    assert provider.calls == 1
    assert out[0] == msgs[0]  # 首条(任务目标)保留
    assert any("摘要" in m.get("content", "") for m in out)
    assert len(out) < len(msgs)
