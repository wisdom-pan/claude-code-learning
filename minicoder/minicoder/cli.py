"""CLI / REPL —— 交互入口与斜杠命令。

对标 CoreCoder 的 cli.py:REPL + 斜杠命令 + 一次性无头模式(-p/--print)。
斜杠命令:/model /compact /tokens /diff /save /sessions /help,以及 quit/exit。
Ctrl+C 取消当前一轮,回到提示符。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .agent import Agent
from .config import Config
from .context import DEFAULT_CONTEXT_WINDOW, compact_if_needed, total_tokens
from .prompt import build_system_prompt
from .providers import ToolCall, get_provider
from .session import list_sessions, load_session, save_session
from .tools import build_tools

# 简单价格表(美元/百万 token),仅估算用,可按需修改
_PRICE = {
    "default": (2.5, 10.0),
}


def _fmt_cost(inp: int, out: int, model: str) -> str:
    price_in, price_out = _PRICE.get(model, _PRICE["default"])
    cost = inp / 1e6 * price_in + out / 1e6 * price_out
    return f"输入 {inp} tok / 输出 {out} tok ≈ ${cost:.4f}"


class Repl:
    def __init__(self, agent: Agent, config: Config) -> None:
        self.agent = agent
        self.config = config
        self._wire_callbacks()

    def _wire_callbacks(self) -> None:
        self.agent.on_text = lambda t: (sys.stdout.write(t), sys.stdout.flush())
        self.agent.on_notice = lambda m: print(f"\n\033[2m· {m}\033[0m")
        self.agent.on_tool_start = self._print_tool_start
        self.agent.on_tool_result = self._print_tool_result

    def _print_tool_start(self, tc: ToolCall) -> None:
        summary = _tool_summary(tc)
        print(f"\n\033[36m⚙ {tc.name}\033[0m {summary}")

    def _print_tool_result(self, tc: ToolCall, out: str) -> None:
        preview = out if len(out) <= 500 else out[:500] + f" … (+{len(out) - 500} 字符)"
        indented = "\n".join(f"  {line}" for line in preview.splitlines())
        print(f"\033[2m{indented}\033[0m")

    # ---- 主循环 ----
    def run(self) -> None:
        print(f"minicoder v{__version__} · provider={self.config.provider} · model={self.config.model}")
        print("输入你的需求,或 /help 看命令,quit 退出。\n")
        while True:
            try:
                line = input("\033[1m›\033[0m ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见。")
                return
            if not line:
                continue
            if line.startswith("/") or line in ("quit", "exit"):
                if self._handle_command(line):
                    return
                continue
            self._run_turn(line)

    def _run_turn(self, text: str) -> None:
        try:
            result = self.agent.chat(text)
            if not self.agent.stream:
                print(result)
            print()  # 收尾换行
        except KeyboardInterrupt:
            print("\n\033[33m已取消当前轮。\033[0m")
        except Exception as e:  # noqa: BLE001
            print(f"\n\033[31m错误:{type(e).__name__}: {e}\033[0m")

    # ---- 斜杠命令,返回 True 表示应退出 ----
    def _handle_command(self, line: str) -> bool:
        parts = line.split(maxsplit=1)
        cmd = parts[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("quit", "exit", "/quit", "/exit"):
            print("再见。")
            return True
        if cmd == "/help":
            _print_help()
        elif cmd == "/model":
            if arg:
                self.config.model = arg
                self.agent.config.model = arg
                print(f"已切换模型: {arg}")
            else:
                print(f"当前模型: {self.config.model}")
        elif cmd == "/tokens":
            ctx = total_tokens(self.agent.messages)
            print(f"当前上下文 ≈ {ctx} tok ({ctx / DEFAULT_CONTEXT_WINDOW:.0%} 窗口)")
            print("累计 " + _fmt_cost(self.agent.total_input_tokens, self.agent.total_output_tokens, self.config.model))
        elif cmd == "/compact":
            before = len(self.agent.messages)
            self.agent.messages = compact_if_needed(
                self.agent.messages, self.agent.provider, self.config.model,
                context_window=1,  # 强制触发最激进层
                on_notice=self.agent.on_notice,
            )
            print(f"压缩:{before} → {len(self.agent.messages)} 条消息")
        elif cmd == "/diff":
            _show_git_diff()
        elif cmd == "/save":
            name = arg or f"session-{int(time.time())}"
            try:
                path = save_session(name, self.agent.messages, {"model": self.config.model})
                print(f"已保存: {path}")
            except ValueError as e:
                print(f"错误:{e}")
        elif cmd == "/sessions":
            self._list_sessions()
        elif cmd == "/load":
            self._load_session(arg)
        else:
            print(f"未知命令: {cmd}(/help 查看可用命令)")
        return False

    def _list_sessions(self) -> None:
        sessions = list_sessions()
        if not sessions:
            print("(暂无已保存会话)")
            return
        for s in sessions:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["saved_at"]))
            print(f"  {s['name']:<24} {s['messages']:>4} 条消息  {when}")
        print("用 /load <名称> 恢复。")

    def _load_session(self, name: str) -> None:
        if not name:
            print("用法: /load <会话名>")
            return
        try:
            messages, meta = load_session(name)
        except (FileNotFoundError, ValueError) as e:
            print(f"错误:{e}")
            return
        self.agent.messages = messages
        if meta.get("model"):
            self.config.model = meta["model"]
            self.agent.config.model = meta["model"]
        print(f"已恢复会话 {name}({len(messages)} 条消息)")


def _tool_summary(tc: ToolCall) -> str:
    a = tc.arguments
    for key in ("path", "pattern", "command", "task"):
        if key in a:
            val = str(a[key])
            return val if len(val) <= 80 else val[:80] + "…"
    return ""


def _show_git_diff() -> None:
    try:
        out = subprocess.run(
            ["git", "diff", "--stat"], capture_output=True, text=True, timeout=5
        )
        print(out.stdout.strip() or "(本次会话无 git 改动)")
    except (OSError, subprocess.SubprocessError):
        print("(无法获取 git diff)")


def _print_help() -> None:
    print(
        """可用命令:
  /model [名称]    查看或切换模型
  /compact         立即压缩上下文
  /tokens          查看 token 用量与成本估算
  /diff            查看 git 改动(git diff --stat)
  /save [名称]     保存当前会话
  /sessions        列出已保存会话
  /load <名称>     恢复某个会话
  /help            显示本帮助
  quit / exit      退出(对话中 Ctrl+C 取消当前轮)"""
    )


def _build_agent(config: Config, stream: bool) -> Agent:
    provider = get_provider(config)
    tools = build_tools(provider, config)
    system_prompt = build_system_prompt(Path.cwd())
    return Agent(
        provider=provider, config=config, tools=tools,
        system_prompt=system_prompt, stream=stream,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="minicoder", description="极简终端 AI coding agent")
    parser.add_argument("-p", "--print", dest="prompt", help="无头模式:执行单条指令后退出")
    parser.add_argument("--provider", help="覆盖 provider(openai|anthropic)")
    parser.add_argument("--model", help="覆盖模型")
    parser.add_argument("-v", "--version", action="version", version=f"minicoder {__version__}")
    args = parser.parse_args(argv)

    try:
        config = Config.load()
    except ValueError as e:
        print(f"配置错误:{e}", file=sys.stderr)
        return 2
    if args.provider:
        import os
        os.environ["MINICODER_PROVIDER"] = args.provider
        config = Config.load()
    if args.model:
        config.model = args.model

    try:
        config.require_api_key()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2

    if args.prompt:  # 无头模式
        agent = _build_agent(config, stream=False)
        try:
            print(agent.chat(args.prompt))
        except Exception as e:  # noqa: BLE001
            print(f"错误:{type(e).__name__}: {e}", file=sys.stderr)
            return 1
        return 0

    Repl(_build_agent(config, stream=True), config).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
