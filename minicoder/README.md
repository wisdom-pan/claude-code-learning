# minicoder

> 一个极简、可读、可 fork 的终端 AI coding agent —— 把 [Claude Code](../README.md) 的核心思想用 ~1300 行纯 Python 写出来。

灵感来自极简教学型 coding agent("the nanoGPT of coding agents")的思路,并结合本仓库对 Claude Code 源码的架构分析([docs/](../docs/))。目标是**教学与可 hack**,而非生产级。

## 它做什么

给它一句话需求,它会调用工具去读写文件、执行 shell、搜索代码,循环往复直到完成,然后向你汇报。

```
› 把 utils.py 里的 print 都换成 logging
⚙ grep  print
  utils.py:12:    print(f"start {name}")
  ...
⚙ edit_file  utils.py
  已修改 utils.py(替换 3 处)
已把 3 处 print 替换为 logging.info,并在文件顶部补了 import logging。
```

## 核心设计(对应本仓库文档)

| 模块 | 对应 Claude Code 分析 | 说明 |
|------|----------------------|------|
| `agent.py` | [docs/02 核心引擎](../docs/02-core-engine.md) | Agent Loop(send→tool→回填→循环)+ **读写分离并发**:连续只读工具并发,写工具串行 |
| `context.py` | [docs/03 上下文系统](../docs/03-context-system.md) | **三层压缩**:50% 裁剪 / 70% 摘要旧轮 / 90% 紧急压缩 |
| `tools/base.py` | [docs/04 工具系统](../docs/04-tool-system.md) | **fail-closed** 默认:工具默认不并发、不只读,要放宽须显式声明 |
| `tools/bash.py` | [docs/05 权限系统](../docs/05-permission-system.md) | 危险命令正则门控(`rm -rf /`、fork bomb、`dd` 覆盖磁盘…) |
| `providers.py` | — | Provider 抽象:**同时支持 Anthropic 与 OpenAI 兼容**后端 |
| `session.py` | — | 会话保存/恢复 + 路径穿越防护 |

## 安装

```bash
cd minicoder
pip install -e .          # 或 pip install -e ".[dev]" 装测试依赖
```

## 配置

复制 `.env.example` 为 `.env` 并填写,或直接用环境变量:

```bash
# OpenAI 兼容(OpenAI / DeepSeek / Ollama / Kimi / Qwen ...)
export MINICODER_PROVIDER=openai
export OPENAI_API_KEY=sk-xxx
export OPENAI_BASE_URL=https://api.openai.com/v1   # 换后端只改这里

# 或 Anthropic
export MINICODER_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-xxx
```

本地跑 Ollama:`OPENAI_BASE_URL=http://localhost:11434/v1`,API key 随便填。

## 使用

```bash
minicoder                        # 进入 REPL
minicoder -p "创建 hello.py 打印 hello"   # 无头模式,执行单条后退出
minicoder --provider anthropic --model claude-sonnet-4-5
```

REPL 斜杠命令:

| 命令 | 作用 |
|------|------|
| `/model [名称]` | 查看或切换模型 |
| `/compact` | 立即压缩上下文 |
| `/tokens` | token 用量与成本估算 |
| `/diff` | git 改动概览 |
| `/save [名称]` `/sessions` `/load <名称>` | 会话保存 / 列表 / 恢复 |
| `/help` · `quit`/`exit` | 帮助 / 退出(对话中 Ctrl+C 取消当前轮) |

## 内置工具(7 个)

`bash` · `read_file` · `write_file` · `edit_file`(唯一文本匹配替换)· `glob` · `grep` · `agent`(子 agent,禁止递归)

## 测试

```bash
pip install -e ".[dev]"
pytest          # 26 个单测,全程 mock provider,不触真实 API
ruff check .
```

## 目录结构

```
minicoder/
├── config.py       # 环境变量 + .env 加载
├── prompt.py       # system prompt + git/项目上下文
├── providers.py    # Provider 抽象(OpenAI 兼容 + Anthropic),流式,重试
├── context.py      # 三层上下文压缩
├── session.py      # 会话持久化 + 路径防护
├── agent.py        # Agent Loop + 读写分离并发
├── cli.py          # REPL + 斜杠命令
└── tools/          # base + bash/read/write/edit/glob/grep/agent
```

## 刻意的非目标(fork 时可填的坑)

为保持极简,以下 Claude Code 有、这里没做:MCP、Hook 系统、多 provider fallback 链、
Textual TUI、插件、team/swarm、LSP、web 工具、prompt 缓存优化、精确 token 计数(现用字符数/4 估算)。

## License

MIT
