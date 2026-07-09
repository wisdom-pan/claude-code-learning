"""会话持久化单测:保存/恢复往返、ToolCall 序列化、路径穿越防护。"""

from __future__ import annotations

import pytest

from minicoder import session as session_mod
from minicoder.providers import ToolCall


@pytest.fixture(autouse=True)
def _tmp_session_dir(tmp_path, monkeypatch):
    # 把会话目录重定向到临时目录,避免污染 ~/.minicoder
    monkeypatch.setattr(session_mod, "SESSION_DIR", tmp_path / "sessions")


def test_save_load_roundtrip():
    messages = [
        {"role": "user", "content": "做点事"},
        {
            "role": "assistant",
            "content": "好的",
            "tool_calls": [ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "文件内容"},
    ]
    session_mod.save_session("test1", messages, {"model": "gpt-4o"})
    loaded, meta = session_mod.load_session("test1")

    assert meta["model"] == "gpt-4o"
    assert loaded[0]["content"] == "做点事"
    tc = loaded[1]["tool_calls"][0]
    assert isinstance(tc, ToolCall)
    assert tc.id == "c1" and tc.name == "read_file" and tc.arguments == {"path": "a.py"}
    assert loaded[2]["tool_call_id"] == "c1"


def test_list_sessions():
    session_mod.save_session("s1", [{"role": "user", "content": "a"}])
    session_mod.save_session("s2", [{"role": "user", "content": "b"}])
    names = {s["name"] for s in session_mod.list_sessions()}
    assert names == {"s1", "s2"}


def test_path_traversal_blocked():
    with pytest.raises(ValueError):
        session_mod.save_session("../../etc/passwd", [])
    with pytest.raises(ValueError):
        session_mod.save_session("a/b", [])
    with pytest.raises(ValueError):
        session_mod.load_session("..")


def test_load_missing():
    with pytest.raises(FileNotFoundError):
        session_mod.load_session("does-not-exist")
