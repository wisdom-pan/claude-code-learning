"""会话保存 / 恢复。

存到 ~/.minicoder/sessions/<name>.json。文件名做 sanitize,防止路径穿越
(例如 name = "../../etc/passwd" 会被拒绝)。

消息里含 ToolCall dataclass,需在存取时与 dict 互转。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .providers import ToolCall

SESSION_DIR = Path.home() / ".minicoder" / "sessions"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_path(name: str) -> Path:
    """把会话名解析为 SESSION_DIR 下的安全路径,越界即报错。"""
    name = name.strip()
    if not name or not _SAFE_NAME.match(name) or ".." in name:
        raise ValueError(
            f"非法会话名: {name!r}(只允许字母、数字、. _ -,不含 .. 或路径分隔符)"
        )
    path = (SESSION_DIR / f"{name}.json").resolve()
    # 双保险:解析后必须仍在 SESSION_DIR 内
    if SESSION_DIR.resolve() not in path.parents:
        raise ValueError(f"检测到路径穿越: {name!r}")
    return path


def _encode_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    encoded = []
    for m in messages:
        item = dict(m)
        if m.get("tool_calls"):
            item["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in m["tool_calls"]
            ]
        encoded.append(item)
    return encoded


def _decode_messages(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decoded = []
    for m in raw:
        item = dict(m)
        if m.get("tool_calls"):
            item["tool_calls"] = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("arguments") or {})
                for tc in m["tool_calls"]
            ]
        decoded.append(item)
    return decoded


def save_session(name: str, messages: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> Path:
    path = _safe_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "saved_at": time.time(),
        "meta": meta or {},
        "messages": _encode_messages(messages),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_session(name: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = _safe_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"会话不存在: {name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _decode_messages(payload.get("messages", [])), payload.get("meta", {})


def list_sessions() -> list[dict[str, Any]]:
    """返回已保存会话的元信息列表,按保存时间倒序。"""
    if not SESSION_DIR.is_dir():
        return []
    out = []
    for p in SESSION_DIR.glob("*.json"):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(
            {
                "name": p.stem,
                "saved_at": payload.get("saved_at", 0),
                "messages": len(payload.get("messages", [])),
            }
        )
    out.sort(key=lambda x: x["saved_at"], reverse=True)
    return out
