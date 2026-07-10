# minicoder

> 一个极简、可读、可 fork 的终端 AI coding agent —— 把 Claude Code 的核心思想用 ~1300 行纯 Python 写出来。

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Tests" src="https://img.shields.io/badge/tests-26%20passing-brightgreen">
  <img alt="Deps" src="https://img.shields.io/badge/deps-httpx-lightgrey">
</p>

灵感来自极简教学型 coding agent("the nanoGPT of coding agents")的思路,并结合对 Claude Code 源码的架构分析。目标是**教学与可 hack**,而非生产级 —— 每一行都能在一个下午读完,每个设计决策都能追溯到具体代码。

**特点一览:**

- 🔁 完整的 **Agent Loop** —— 发消息 → 执行工具 → 回填结果 → 循环,直到任务完成
- ⚡ **读写分离并发** —— 连续的只读工具并行执行,写工具串行,避免竞态
- 🗜️ **三层上下文压缩** —— 窗口快满时按成本从低到高逐级压缩,尽量不丢早期决策
- 🔌 **双后端可配置** —— 同时支持 Anthropic 与任意 OpenAI 兼容 API(OpenAI / DeepSeek / Ollama / Kimi / Qwen …)
- 🛡️ **fail-closed 安全默认** + bash 危险命令门控
- 💾 会话保存 / 恢复,流式输出,REPL + 斜杠命令
- 🧪 **零重依赖**(仅 `httpx`),26 个单测全程 mock,不触真实 API

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

## 快速开始

```bash
git clone git@github.com:wisdom-pan/minicoder.git
cd minicoder
pip install -e .                 # 或 pip install -e ".[dev]" 装测试依赖

export OPENAI_API_KEY=sk-xxx     # 见下方「配置」
minicoder                        # 进入 REPL,输入你的需求
```

## 核心设计(对应 Claude Code 的架构分层)

| 模块 | 对应 Claude Code 设计 | 说明 |
|------|----------------------|------|
| `agent.py` | 核心引擎 | Agent Loop(send→tool→回填→循环)+ **读写分离并发**:连续只读工具并发,写工具串行 |
| `context.py` | 上下文系统 | **三层压缩**:50% 裁剪 / 70% 摘要旧轮 / 90% 紧急压缩 |
| `tools/base.py` | 工具系统 | **fail-closed** 默认:工具默认不并发、不只读,要放宽须显式声明 |
| `tools/bash.py` | 权限系统 | 危险命令正则门控(`rm -rf /`、fork bomb、`dd` 覆盖磁盘…) |
| `providers.py` | 服务层 API 客户端 | 多 Provider 抽象 + 指数退避重试(对应 `client.ts` 多后端 / `withRetry.ts`):**同时支持 Anthropic 与 OpenAI 兼容** |
| `session.py` | Transcript 持久化 | 会话保存/恢复,落盘崩溃安全(对应 QueryEngine 的 `recordTranscript()`)+ 路径穿越防护 |

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

| 环境变量 | 作用 | 默认 |
|---------|------|------|
| `MINICODER_PROVIDER` | `openai` 或 `anthropic` | `openai` |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | OpenAI 兼容后端凭据与地址 | — / 官方地址 |
| `ANTHROPIC_API_KEY` | Anthropic 凭据 | — |
| `MINICODER_MODEL` | 模型覆盖 | 按 provider 给默认 |
| `MINICODER_MAX_ROUNDS` | 单次对话最大轮数(防跑飞) | `50` |

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

[MIT](LICENSE)
