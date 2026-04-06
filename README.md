# Claude Code 源码深度解读

> 基于对 Claude Code 源码的系统性分析，从 11 个维度拆解其架构设计，涵盖 Agent Loop、Context 管理、Tool 调用、Memory、权限安全、多智能体协作、可观测性等核心模块。

---

## 项目简介

本项目是对 **Claude Code**（Anthropic 的终端 Agent 应用）的源码深度解读。通过系统性的源码分析，揭示其从 Agent Loop 到多智能体编排的完整架构设计。

Claude Code 是一个基于 TypeScript 的终端 Agent 应用，构建在 Bun 运行时之上，采用 React + Ink 渲染 TUI。其架构设计遵循**分层解耦、流式驱动、不可变状态**三大原则。

## 文档导航

### 核心模块解读

| 模块 | 文档 | 说明 |
|------|------|------|
| 整体架构 | [src/README.md](src/README.md) | 源码目录结构与模块概览 |
| 入口层 | [docs/01-entry-layer.md](docs/01-entry-layer.md) | main.tsx、多客户端入口、Feature Flag |
| 核心引擎 | [docs/02-core-engine.md](docs/02-core-engine.md) | Agent Loop、QueryEngine、流式驱动 |
| 上下文系统 | [docs/03-context-system.md](docs/03-context-system.md) | System/User Context、压缩策略 |
| 工具系统 | [docs/04-tool-system.md](docs/04-tool-system.md) | 43 个工具、编排器、读写分离 |
| 权限安全 | [docs/05-permission-system.md](docs/05-permission-system.md) | 五层决策引擎、6 种权限模式 |
| 多智能体 | [docs/06-multi-agent.md](docs/06-multi-agent.md) | Subagent/Coordinator/Swarm/Team |
| 记忆系统 | [docs/07-memory-system.md](docs/07-memory-system.md) | MEMORY.md、Agent 记忆、团队同步 |
| 可观测性 | [docs/08-observability.md](docs/08-observability.md) | 22 种 Hook、遥测、成本追踪 |
| TUI 渲染 | [docs/09-tui-system.md](docs/09-tui-system.md) | Ink 引擎、组件系统 |
| 状态管理 | [docs/10-state-management.md](docs/10-state-management.md) | Bootstrap State、不可变状态 |
| 命令系统 | [docs/11-commands-system.md](docs/11-commands-system.md) | Slash 命令、命令路由 |
| Bridge 系统 | [docs/12-bridge-system.md](docs/12-bridge-system.md) | 远程通信、WebSocket、SSE |
| 服务层 | [docs/13-services.md](docs/13-services.md) | API、MCP、Analytics 等服务 |

### 综合分析

| 文档 | 说明 |
|------|------|
| [claude-code-architecture-analysis.md](claude-code-architecture-analysis.md) | 完整架构分析报告（1233 行） |

## 架构全景

```
┌─────────────────────────────────────────────────────────────┐
│                      入口层 Entry Layer                       │
│   CLI (main.tsx) │ SDK │ VSCode Extension │ Remote Session   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    核心引擎 Core Engine                       │
│        query.ts (Agent Loop) │ QueryEngine.ts │ State        │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────┬───────┴───────┬─────────────┐
        ▼             ▼               ▼             ▼
┌───────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
│ 上下文系统  │ │  工具系统   │ │ 权限系统    │ │ 多智能体    │
│ Context   │ │ Tool(43)   │ │ Permission │ │ Multi-Agent│
└───────────┘ └────────────┘ └────────────┘ └────────────┘
        │             │               │             │
        ▼             ▼               ▼             ▼
┌───────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
│ 记忆系统   │ │  可观测性   │ │ TUI 渲染   │ │ 状态管理    │
│ Memory    │ │ Hooks(22)  │ │ Ink/React  │ │ AppState   │
└───────────┘ └────────────┘ └────────────┘ └────────────┘
```

## 核心设计理念

1. **流式优先**：从 Agent Loop 到 Tool 执行，全部采用 async generator
2. **安全默认**：Tool Builder 的 fail-closed 设计、五层权限决策
3. **不可变状态**：DeepImmutable 类型约束 + 函数式更新
4. **模块化编排**：43 个工具通过统一接口和编排器协同工作
5. **多智能体层次**：从 Subagent 到 Swarm 的渐进式复杂度
6. **可观测性内建**：22 种 Hook + OpenTelemetry + Perfetto
7. **Feature Flag 驱动**：编译时死代码消除 + 灰度发布

## 关键指标

| 指标 | 数值 |
|------|------|
| 工具数量 | 43+ |
| Hook 类型 | 22 |
| 权限模式 | 6 |
| Agent 类型 | 5 |
| 核心文件 | 20+ |
| 总代码行数 | 50,000+ |

## 源码来源

- `src/` - Claude Code 源码副本
- `src.zip` - 源码压缩包
- `analysis/` - 原始分析文档

## 如何使用

1. 从 [整体架构](src/README.md) 开始了解目录结构
2. 按顺序阅读各模块文档，或跳转到感兴趣的模块
3. 参考 [完整分析报告](claude-code-architecture-analysis.md) 获取深度技术细节
