"""write_file —— 创建或覆盖文件(写操作,串行)。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool


class WriteFileTool(Tool):
    name = "write_file"
    description = "创建新文件或覆盖已有文件。修改已有文件优先用 edit_file。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "完整文件内容"},
        },
        "required": ["path", "content"],
    }

    def run(self, args: dict[str, Any]) -> str:
        path = Path(args["path"]).expanduser()
        content = args["content"]
        existed = path.is_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        action = "覆盖" if existed else "创建"
        return f"已{action}文件 {path}({len(content)} 字符)"
