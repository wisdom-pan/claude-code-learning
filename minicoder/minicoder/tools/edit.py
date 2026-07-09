"""edit_file —— 基于唯一文本匹配的替换(写操作,串行)。

对标 CoreCoder / Claude Code 的 Edit:不用脆弱的行号,而是要求 old_string 在文件中
唯一出现,再替换成 new_string。唯一性保证了替换位置无歧义。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool


class EditFileTool(Tool):
    name = "edit_file"
    description = (
        "通过唯一文本匹配替换文件内容。old_string 必须在文件中恰好出现一次"
        "(可包含足够的上下文以保证唯一)。设 replace_all=true 可替换全部出现。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "old_string": {"type": "string", "description": "要被替换的原文本"},
            "new_string": {"type": "string", "description": "替换后的新文本"},
            "replace_all": {"type": "boolean", "description": "替换所有出现(默认 false)"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    def run(self, args: dict[str, Any]) -> str:
        path = Path(args["path"]).expanduser()
        old = args["old_string"]
        new = args["new_string"]
        replace_all = bool(args.get("replace_all", False))

        if not path.is_file():
            return f"错误:文件不存在: {path}"
        if old == new:
            return "错误:old_string 与 new_string 相同,无需修改。"

        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            return "错误:未找到 old_string,请核对文本(含空格/缩进)是否完全一致。"
        if count > 1 and not replace_all:
            return (
                f"错误:old_string 出现了 {count} 次,不唯一。"
                "请补充上下文使其唯一,或设 replace_all=true。"
            )

        updated = text.replace(old, new)
        path.write_text(updated, encoding="utf-8")
        return f"已修改 {path}(替换 {count if replace_all else 1} 处)"
