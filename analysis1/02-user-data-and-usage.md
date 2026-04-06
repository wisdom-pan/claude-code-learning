# 第二章：从用户角度看，项目收集了哪些信息，以及如何使用

[返回总目录](../README.md)

## 1. 本章导读

本章只站在用户视角，不站在开发者视角，回答两个问题：

1. 系统实际会接触哪些用户信息。
2. 这些信息分别被拿去做什么。

结论先行：最值得警惕的并不只是 telemetry，而是“会进入模型上下文的源码与工作信息”以及“长期持久化的 transcript/memory”。

## 2. 进入模型 API 的信息

相关实现：

- [`src/services/api/claude.ts`](../src/services/api/claude.ts)
- [`src/context.ts`](../src/context.ts)
- [`src/utils/queryContext.ts`](../src/utils/queryContext.ts)
- [`src/utils/attachments.ts`](../src/utils/attachments.ts)

会进入模型上下文的内容包括：

- 用户输入
- 历史对话
- 工具执行结果
- 文件片段、代码片段、命令输出
- `CLAUDE.md` 与 memory 文件
- Git 状态快照
- 图片、文档等附件
- MCP 资源返回内容
- 计划、任务、诊断信息

这些信息的用途是：

- 生成回答
- 决策下一步是否调用工具
- 指导编辑代码
- 做 compact 和摘要
- 派生 subagent 的上下文

从敏感性排序看，这部分风险通常高于普通 analytics。

## 3. 本地持久化的信息

相关实现：

- [`src/utils/sessionStorage.ts`](../src/utils/sessionStorage.ts)
- [`src/utils/settings/types.ts`](../src/utils/settings/types.ts)

本地默认会保存：

- transcript JSONL
- session metadata
- agent transcript
- subagent metadata
- 本地用户配置、项目配置
- OAuth 账户缓存信息
- memory 文件

具体用途：

- `--resume` 恢复会话
- 会话搜索、标题、标签
- compact 后恢复上下文连续性
- 提供 memory 提取原料
- 让子 agent 状态可追溯

特别值得注意：

- `cleanupPeriodDays` 默认保留 transcript
- 设置为 `0` 表示不保留 transcript，并清理已有 transcript

## 4. Memory 相关信息

相关实现：

- [`src/memdir/memdir.ts`](../src/memdir/memdir.ts)
- [`src/memdir/paths.ts`](../src/memdir/paths.ts)
- [`src/services/extractMemories/extractMemories.ts`](../src/services/extractMemories/extractMemories.ts)
- [`src/services/SessionMemory/sessionMemory.ts`](../src/services/SessionMemory/sessionMemory.ts)
- [`src/tools/AgentTool/agentMemory.ts`](../src/tools/AgentTool/agentMemory.ts)

系统会沉淀的 memory 类型包括：

- 用户偏好
- 用户角色和背景
- 项目事实
- 参考信息
- 当前会话摘要
- agent 角色记忆
- team 共享记忆

这些信息会被用于：

- 后续 prompt 注入
- 相关 memory 检索
- compact 后补偿长历史
- agent 长期行为一致性
- 团队共享项目知识

从用户角度，这等于系统在持续形成“长期协作画像”。

## 5. Analytics / Telemetry 收集的信息

相关实现：

- [`src/services/analytics/index.ts`](../src/services/analytics/index.ts)
- [`src/services/analytics/config.ts`](../src/services/analytics/config.ts)
- [`src/services/analytics/metadata.ts`](../src/services/analytics/metadata.ts)
- [`src/services/analytics/sink.ts`](../src/services/analytics/sink.ts)
- [`src/services/analytics/datadog.ts`](../src/services/analytics/datadog.ts)
- [`src/utils/user.ts`](../src/utils/user.ts)
- [`src/utils/fileOperationAnalytics.ts`](../src/utils/fileOperationAnalytics.ts)

源码显示项目在努力避免把“代码正文、文件路径原文”直接打进通用 analytics，但仍会采集较多元数据：

- `deviceId`
- `sessionId`
- app version
- platform / arch / runtime / terminal / CI 环境
- account UUID / organization UUID
- subscriptionType / rateLimitTier
- repo remote hash
- GitHub Actions 元数据
- 工具使用事件、错误事件、compact 事件、bridge 事件、memory 事件
- 文件路径 hash 和内容 hash

主要用途：

- 产品行为分析
- 稳定性与错误监控
- feature gate / 实验分流
- 使用规模统计
- 内部问题诊断

这里要区分：

- 这不等于把用户源码全文上报到 Datadog
- 但确实会形成相当完整的行为元数据画像

## 6. 账户与身份信息

相关实现：

- [`src/utils/user.ts`](../src/utils/user.ts)
- [`src/utils/config.ts`](../src/utils/config.ts)
- [`src/services/oauth`](../src/services/oauth)
- [`src/services/mcp/auth.ts`](../src/services/mcp/auth.ts)

项目会读取或缓存：

- OAuth token
- accountUuid
- organizationUuid
- emailAddress
- organizationName / role
- 套餐、额度与资格信息

用途包括：

- 登录鉴权
- 套餐与配额判断
- Grove、team memory、remote control 等资格校验
- analytics 维度标记

## 7. Team Memory 同步会接触的信息

相关实现：

- [`src/services/teamMemorySync/index.ts`](../src/services/teamMemorySync/index.ts)
- [`src/services/teamMemorySync/watcher.ts`](../src/services/teamMemorySync/watcher.ts)
- [`src/memdir/teamMemPaths.ts`](../src/memdir/teamMemPaths.ts)

当 team memory 开启且用户满足 OAuth 条件时，系统会：

- 按 repo 识别 team memory 空间
- pull 远端 team memory 到本地
- watch 本地目录
- push 本地变更回服务器

上传的不是整个仓库，而是 team memory 目录内的内容。但这些内容可能本身就包含：

- 项目流程
- 内网知识
- 运维路径
- 团队约束
- 特殊规章

虽然项目加了：

- path traversal 防护
- secret scanner

但其本质依然是“组织级知识同步”。

## 8. 用户主动触发的附加上传

### 8.1 Transcript 分享

相关实现：

- [`src/components/FeedbackSurvey/submitTranscriptShare.ts`](../src/components/FeedbackSurvey/submitTranscriptShare.ts)

在反馈场景中，用户可能主动上传：

- transcript
- subagent transcripts
- raw JSONL transcript

代码会做脱敏，但这仍属于“会话内容上传”。

### 8.2 Grove / Help improve Claude

相关实现：

- [`src/services/api/grove.ts`](../src/services/api/grove.ts)
- [`src/components/grove/Grove.tsx`](../src/components/grove/Grove.tsx)

这部分面向用户的含义非常直接：

- 允许使用 chats 和 coding sessions 来训练或改进模型

因此如果用户不希望自己的编码会话进入训练改进流程，就不应开启这项能力。

## 9. Remote / Bridge 场景下的信息

相关实现：

- [`src/bridge/bridgeMain.ts`](../src/bridge/bridgeMain.ts)
- [`src/services/api/sessionIngress.ts`](../src/services/api/sessionIngress.ts)

在远程或 bridge 场景下，系统还会涉及：

- 远程环境标识
- session ingress 日志
- 远程会话元数据
- 桥接状态、心跳与 session ID

这不是普通本地模式的默认数据面，但一旦启用，会显著扩大信息流范围。

## 10. 本章小结

从用户视角，本项目接触信息大致可分三层：

1. 进入模型的工作上下文
2. 本地落盘的 transcript 与 memory
3. 遥测、同步、分享、远程等附加上传

其中最关键的不是某一个日志事件，而是这些能力叠加后形成的“长期、可恢复、可检索、可同步”的用户工作画像。
