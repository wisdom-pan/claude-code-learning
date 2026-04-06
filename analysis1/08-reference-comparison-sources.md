# 附录A：外部对比资料

[返回总目录](../README.md)

## 1. 本章导读

这一章只记录对比分析使用的外部公开资料，避免把外部资料和源码证据混在一起。

## 2. Codex

- OpenAI Help Center: Using Codex with your ChatGPT plan: <https://help.openai.com/en/articles/11096431>
- OpenAI Help Center（法语镜像，便于交叉核对段落差异）: <https://help.openai.com/fr-fr/articles/11369540-utiliser-codex-avec-votre-offre-chatgpt>
- OpenAI Developers Codex 文档总入口: <https://developers.openai.com/>

用于支撑的判断：

- Codex 已覆盖 CLI、IDE 扩展、web、app、SDK、Slack 等多入口
- Codex 区分 local 与 cloud 权限/治理边界
- Codex 是一条覆盖本地与云端多入口的 coding agent 产品线

## 3. Gemini CLI

- Gemini CLI 官方仓库 README: <https://github.com/google-gemini/gemini-cli>

用于支撑的判断：

- Gemini CLI 是公开开源 CLI agent 的高标准基线
- 其公开能力包括 built-in tools、MCP、checkpointing、sandboxing、trusted folders、telemetry

## 4. Aider

- Aider 首页: <https://aider.chat/>
- Aider 文档总览: <https://aider.chat/docs/>

用于支撑的判断：

- Aider 强调终端 pair programming
- Aider 强调 repo map、git、lint/test 闭环
- Aider 更轻量，平台化程度低于当前项目

## 5. Cursor

- Cursor Background Agents: <https://docs.cursor.com/en/background-agents>
- Cursor MCP: <https://docs.cursor.com/en/context/mcp>
- Cursor CLI MCP: <https://docs.cursor.com/cli/mcp>

用于支撑的判断：

- Cursor 强调 background agents
- Cursor 强调 IDE 协同和远程执行环境
- Cursor 有 MCP 扩展能力

## 6. 使用说明

这些资料只用于做“同类产品公开能力边界对比”，不是用于证明本项目源码细节。源码细节仍以本仓库中的 [`analysis/07-code-evidence-index.md`](./07-code-evidence-index.md) 和对应代码文件为准。

## 7. 本章小结

对比结论的证据来源已经单独分离，便于后续更新或替换同类产品参照物。
