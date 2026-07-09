"""Agent Loop 单测:用脚本化的假 provider 驱动循环,验证工具调用回填、
读写分离分区、轮数上限、子 agent 禁递归。全程不触真实 API。"""

from __future__ import annotations

from pathlib import Path

from minicoder.agent import Agent
from minicoder.providers import Reply, ToolCall
from minicoder.tools import build_tools
from minicoder.tools.base import Tool


class ScriptedProvider:
    """按预设脚本逐轮返回 Reply。记录每次收到的 messages 以便断言。"""

    def __init__(self, replies: list[Reply]):
        self._replies = list(replies)
        self.seen_messages: list[list[dict]] = []

    def chat(self, messages, tools, system, model=None, stream=True, on_text=None):
        self.seen_messages.append([dict(m) for m in messages])
        reply = self._replies.pop(0)
        if reply.text and on_text and stream:
            on_text(reply.text)
        return reply


class Cfg:
    def __init__(self, max_rounds=10, model="fake"):
        self.max_rounds = max_rounds
        self.model = model
        self.provider = "openai"


def _agent(provider, tools, stream=False, max_rounds=10):
    return Agent(
        provider=provider, config=Cfg(max_rounds=max_rounds), tools=tools,
        system_prompt="sys", stream=stream,
    )


def test_plain_text_reply():
    provider = ScriptedProvider([Reply(text="你好")])
    agent = _agent(provider, [])
    assert agent.chat("hi") == "你好"
    # user + assistant
    assert agent.messages[0]["role"] == "user"
    assert agent.messages[-1]["role"] == "assistant"


def test_tool_call_then_finish(tmp_path: Path):
    f = tmp_path / "out.txt"
    provider = ScriptedProvider([
        Reply(tool_calls=[ToolCall(id="1", name="write_file",
                                   arguments={"path": str(f), "content": "hi"})]),
        Reply(text="完成"),
    ])
    tools = build_tools(provider, Cfg())
    agent = _agent(provider, tools)
    result = agent.chat("写个文件")
    assert result == "完成"
    assert f.read_text() == "hi"
    # 第二轮的 messages 里应含 tool 结果
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1 and tool_msgs[0]["tool_call_id"] == "1"


def test_max_rounds_guard():
    # provider 永远返回工具调用 → 必须被轮数上限截断
    def endless():
        while True:
            yield Reply(tool_calls=[ToolCall(id="x", name="noop", arguments={})])

    class Endless:
        def chat(self, *a, **k):
            return Reply(tool_calls=[ToolCall(id="x", name="noop", arguments={})])

    class Noop(Tool):
        name = "noop"
        description = "no-op"
        def run(self, args):
            return "ok"

    agent = _agent(Endless(), [Noop()], max_rounds=3)
    result = agent.chat("go")
    assert "最大轮数" in result
    # 3 轮,每轮 1 个 assistant + 1 个 tool 结果
    assert sum(1 for m in agent.messages if m["role"] == "assistant") == 3


def test_partition_reorders_into_batches():
    """连续只读工具应归入一个并发批,写工具单独成批;结果顺序与调用顺序一致。"""
    provider = ScriptedProvider([Reply(text="done")])
    tools = build_tools(provider, Cfg())
    agent = _agent(provider, tools)
    calls = [
        ToolCall(id="1", name="read_file", arguments={"path": "/nope1"}),
        ToolCall(id="2", name="grep", arguments={"pattern": "x", "path": "."}),
        ToolCall(id="3", name="write_file", arguments={"path": "/tmp/zzz_mc_test", "content": "a"}),
        ToolCall(id="4", name="glob", arguments={"pattern": "*.none"}),
    ]
    batches = agent._partition(calls)
    # [read, grep] 并发批,[write] 单独,[glob] 单独
    assert [len(b) for b in batches] == [2, 1, 1]
    assert [tc.id for tc in batches[0]] == ["1", "2"]

    results = agent._run_tools(calls)
    # 结果顺序严格对齐输入顺序
    assert [r["tool_call_id"] for r in results] == ["1", "2", "3", "4"]


def test_subagent_excludes_agent_tool():
    """子 agent 的工具集不含 agent 工具,禁止递归 spawn。"""
    provider = ScriptedProvider([])
    full = build_tools(provider, Cfg(), include_agent=True)
    child = build_tools(provider, Cfg(), include_agent=False)
    assert any(t.name == "agent" for t in full)
    assert not any(t.name == "agent" for t in child)


def test_unknown_tool_returns_error():
    provider = ScriptedProvider([
        Reply(tool_calls=[ToolCall(id="1", name="ghost", arguments={})]),
        Reply(text="收到"),
    ])
    agent = _agent(provider, [])
    agent.chat("go")
    tool_msg = [m for m in agent.messages if m.get("role") == "tool"][0]
    assert "未知工具" in tool_msg["content"]
