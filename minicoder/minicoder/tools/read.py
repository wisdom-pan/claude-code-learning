"""read_file —— 读取文件内容(只读,并发安全)。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool

MAX_BYTES = 256 * 1024  # 单次读取上限,避免超大文件塞满上下文


class ReadFileTool(Tool):
    name = "read_file"
    description = "读取一个文本文件的内容,可选按行范围。返回带行号的内容。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径(相对或绝对)"},
            "offset": {"type": "integer", "description": "起始行(1-based,可选)"},
            "limit": {"type": "integer", "description": "读取行数(可选)"},
        },
        "required": ["path"],
    }

    def is_read_only(self) -> bool:
        return True

    def run(self, args: dict[str, Any]) -> str:
        path = Path(args["path"]).expanduser()
        if not path.is_file():
            return f"错误:文件不存在: {path}"
        data = path.read_bytes()
        if len(data) > MAX_BYTES:
            return f"错误:文件过大({len(data)} 字节 > {MAX_BYTES}),请用 offset/limit 或 grep 局部读取。"
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()

        offset = args.get("offset")
        limit = args.get("limit")
        start = (offset - 1) if isinstance(offset, int) and offset > 0 else 0
        end = (start + limit) if isinstance(limit, int) and limit > 0 else len(lines)
        selected = lines[start:end]
        if not selected:
            return "(文件为空或指定范围无内容)"
        width = len(str(start + len(selected)))
        return "\n".join(f"{start + i + 1:>{width}}  {line}" for i, line in enumerate(selected))
