# 组件体系详解（三）：平台能力组件与控制面实现

[返回总目录](../../README.md)

[上一章：核心交互组件](./02-core-interaction-components.md)

[下一章：组件索引](./04-component-index.md)

## 1. 本章导读

如果说上一章分析的是“会话主干”，这一章分析的就是这套 agent 平台暴露给用户的能力控制面。

核心结论是：这个项目的多数复杂组件，并不在消息展示层，而在“权限、agent、任务、MCP、团队、设置、memory、skills、hooks、sandbox”这些面板里。它们一起把执行内核包装成了可操控的平台。

先给出平台控制面总图：

```text
PromptInput / slash command / footer
  ├─> permissions
  ├─> tasks
  ├─> agents
  ├─> mcp
  ├─> teams
  ├─> Settings
  └─> memory / skills / hooks / sandbox

上述控制面统一向下依赖：
  -> AppState / Context / hooks
  -> services / tools / swarm / mcp / permissions / fs
```

## 2. permissions：权限组件族是最重的控制面

权限组件在 [`src/components/permissions`](../../src/components/permissions) 下，文件量是整个组件目录里最多的一组。

### 2.1 总入口

总入口是 [`src/components/permissions/PermissionRequest.tsx`](../../src/components/permissions/PermissionRequest.tsx)。

这个组件的实现方式很直接：根据工具类型，把审批渲染分发给对应子组件。

它能分发到的子组件包括：

- `FileEditPermissionRequest`
- `FileWritePermissionRequest`
- `BashPermissionRequest`
- `PowerShellPermissionRequest`
- `WebFetchPermissionRequest`
- `NotebookEditPermissionRequest`
- `SkillPermissionRequest`
- `AskUserQuestionPermissionRequest`
- `FilesystemPermissionRequest`
- plan mode enter/exit 对应的 permission request

### 2.2 设计特点

这一层的亮点在于：

- 权限逻辑不是写死在工具里，而是由权限组件族承接最终交互
- 同一个 `ToolUseConfirm` 协议可以被多个子组件消费
- sticky footer、reject/allow、用户交互检测、classifier auto-approve 等都被纳入统一接口

这使 permission mode 真正成为系统级机制，而不是“弹个确认框”。

### 2.3 子组件结构

该目录下还有几类重要子组件：

- 文件相关 UI：`FilePermissionDialog/*`
- 规则相关 UI：`permissions/rules/*`
- 计划审批：`EnterPlanModePermissionRequest`、`ExitPlanModePermissionRequest`
- 专项工具审批：如 bash、web fetch、skill、notebook edit

这组组件体现了一个原则：权限审批是场景化 UI，而不是统一模板硬套所有工具。

## 3. tasks：后台任务工作台

核心文件在 [`src/components/tasks`](../../src/components/tasks)。

### 3.1 总入口

[`src/components/tasks/BackgroundTasksDialog.tsx`](../../src/components/tasks/BackgroundTasksDialog.tsx) 是任务面板的总入口。

它会从 `AppState.tasks` 中拿到后台任务，并进一步区分：

- local bash
- remote agent
- local agent
- in-process teammate
- local workflow
- monitor MCP
- dream

这说明“任务”在该项目里不是单一类型，而是统一抽象之上的多后端状态集合。

### 3.2 详情子组件

任务详情分别交给：

- `AsyncAgentDetailDialog`
- `ShellDetailDialog`
- `RemoteSessionDetailDialog`
- `InProcessTeammateDetailDialog`
- `DreamDetailDialog`
- workflow/monitor 的 feature-gated detail dialog

也就是说，`BackgroundTasksDialog` 是状态机与列表视图控制器，具体任务说明则交由各自 detail 组件负责。

### 3.3 任务组件的设计含义

这类组件把“后台执行体”正式纳入 UI：用户不是只能等待模型回答，而是可以查看 agent、shell、workflow、MCP monitor 的异步状态。

## 4. agents：agent 生命周期管理界面

核心目录是 [`src/components/agents`](../../src/components/agents)。

### 4.1 总入口

[`src/components/agents/AgentsMenu.tsx`](../../src/components/agents/AgentsMenu.tsx) 是 agent 管理总控。

它负责：

- 汇总各来源 agent 定义
- 按 source 分组展示
- 合并 MCP tools 与本地 tools
- 在列表、详情、编辑、创建向导之间切换
- 删除 agent 后刷新 `AppState.agentDefinitions`

### 4.2 子组件分工

常规管理子组件：

- [`AgentDetail.tsx`](../../src/components/agents/AgentDetail.tsx)
- [`AgentEditor.tsx`](../../src/components/agents/AgentEditor.tsx)
- [`AgentsList.tsx`](../../src/components/agents/AgentsList.tsx)
- [`AgentNavigationFooter.tsx`](../../src/components/agents/AgentNavigationFooter.tsx)

编辑辅助子组件：

- `ColorPicker`
- `ModelSelector`
- `ToolSelector`
- `validateAgent`
- `agentFileUtils`

创建向导：

- [`new-agent-creation/CreateAgentWizard.tsx`](../../src/components/agents/new-agent-creation/CreateAgentWizard.tsx)
- 以及 `wizard-steps/*`

### 4.3 子组件亮点

[`AgentDetail.tsx`](../../src/components/agents/AgentDetail.tsx) 很有代表性。它不仅展示 agent 名称和描述，还直接展示：

- tools 解析结果
- model
- permission mode
- memory scope
- hooks
- skills
- 颜色
- system prompt

也就是说，agent 在 UI 中被视为一个完整运行时配置单元，而不是一段 prompt 文本。

## 5. mcp：MCP 管理组件族

核心目录是 [`src/components/mcp`](../../src/components/mcp)。

### 5.1 总入口

[`src/components/mcp/MCPSettings.tsx`](../../src/components/mcp/MCPSettings.tsx) 是 MCP 面板总入口。

它会从 `AppState.mcp` 与 `agentDefinitions` 中提取：

- 普通 MCP 客户端
- agent 绑定的 MCP server
- server transport 类型
- 认证状态
- 某 server 下有哪些 tools

### 5.2 视图状态机

`MCPSettings` 内部不是单页面，而是一个带状态机的菜单系统，视图包括：

- list
- server-menu
- agent-server-menu
- server-tools
- tool-detail

对应子组件包括：

- `MCPListPanel`
- `MCPStdioServerMenu`
- `MCPRemoteServerMenu`
- `MCPAgentServerMenu`
- `MCPToolListView`
- `MCPToolDetailView`

把它画成状态机会更直观：

```text
MCPSettings 视图状态机

list
  -> server-menu
     -> server-tools
        -> tool-detail
        -> 返回 server-tools
     -> 返回 list

list
  -> agent-server-menu
     -> server-tools
        -> tool-detail
        -> 返回 server-tools
     -> 返回 list
```

### 5.3 设计评价

MCP 在这里并不是“一个设置项”，而是被当作一级平台能力管理。UI 已经覆盖到：

- transport 区分
- auth 状态
- tool 过滤
- server 级与 tool 级双层浏览

这比很多 CLI 工具只做“列一下 MCP server 名称”要完整得多。

## 6. Settings：状态、配置与用量三分结构

[`src/components/Settings/Settings.tsx`](../../src/components/Settings/Settings.tsx) 的结构很清楚：

- `Status`
- `Config`
- `Usage`
- ant-only 的 `Gates`

它的实现亮点在于：

- 通过 `Tabs` 统一分页
- 通过 `contentHeight` 适配 modal 与 terminal 两种尺寸
- 允许 `Config` / `Gates` 临时接管 Esc，避免搜索态与全局取消键冲突

这说明设置页并不是纯静态表单，而是带内部交互状态的工具面板。

## 7. teams：多 agent 协作视图

[`src/components/teams/TeamsDialog.tsx`](../../src/components/teams/TeamsDialog.tsx) 是 swarm/teammate 视图的 UI 总入口。

### 7.1 双层视图

它只有两个主要层级：

- teammateList
- teammateDetail

但在行为上非常重，支持：

- 查看 teammate 状态
- 切换 permission mode
- kill teammate
- graceful shutdown
- hide/show teammate pane
- 一键 prune idle teammates
- 进入对应输出 pane

### 7.2 依赖的后端很多

这个组件同时联通了：

- teammate mailbox
- swarm backends registry
- team helpers
- tasks 工具
- tmux/IT2 pane backend

所以它其实是“多 agent 协作后端”的终端控制台，而不只是一个列表。

从控制面角度看，tasks / teams / permissions 三者的关系大致如下：

```text
用户操作
  -> BackgroundTasksDialog
     -> AppState.tasks
     -> agent / shell / workflow / remote runtime

  -> TeamsDialog
     -> teammate mailbox / swarm backends / pane state
     -> agent / shell / workflow / remote runtime

  -> PermissionRequest/*
     -> ToolUseConfirm / permission rules / classifier state
     -> agent / shell / workflow / remote runtime
```

## 8. memory、skills、hooks、sandbox：配置与知识层面板

### 8.1 memory

memory 组件主要在 [`src/components/memory`](../../src/components/memory)。

其中：

- [`MemoryFileSelector.tsx`](../../src/components/memory/MemoryFileSelector.tsx) 负责浏览与打开用户、项目、auto-memory、team-memory、agent-memory 的入口
- `MemoryUpdateNotification` 负责在记忆写入后提示用户路径

这组组件很重要，因为它把原本分散在多个目录下的 memory 文件系统，统一映射成用户可见入口。

### 8.2 skills

[`src/components/skills/SkillsMenu.tsx`](../../src/components/skills/SkillsMenu.tsx) 用 source 维度展示 skills：

- policy
- user
- project
- local
- plugin
- mcp

它的价值在于把“技能”从文件系统散点变成了可浏览资产目录。

### 8.3 hooks

[`src/components/hooks/HooksConfigMenu.tsx`](../../src/components/hooks/HooksConfigMenu.tsx) 是 hooks 配置浏览器。

这个菜单刻意做成只读，支持：

- 按 event 浏览
- 按 matcher 浏览
- 再查看具体 hook

这种设计比较务实：避免在终端里重复造一个 settings.json 编辑器。

### 8.4 sandbox

[`src/components/sandbox`](../../src/components/sandbox) 下的组件把 sandbox 拆成：

- `SandboxSettings`
- `SandboxConfigTab`
- `SandboxDependenciesTab`
- `SandboxOverridesTab`
- `SandboxDoctorSection`

这说明 sandbox 在项目里不是一个布尔开关，而是一整组可诊断、可配置、可覆盖的运行环境子系统。

## 9. Grove 与策略/合规类组件

[`src/components/grove/Grove.tsx`](../../src/components/grove/Grove.tsx) 很值得单独点出来。

它处理的是：

- 用户是否看到新 terms / policy notice
- opt-in / opt-out / defer 的交互
- 与 API 的设置同步
- analytics 事件记录

这类组件和 `TrustDialog`、`ManagedSettingsSecurityDialog` 一起，构成了项目中较少见但很重要的一类：合规与策略提示组件。

## 10. design-system：终端设计系统的基座

设计系统目录在 [`src/components/design-system`](../../src/components/design-system)。

### 10.1 关键基础件

最核心的基础件包括：

- [`Dialog.tsx`](../../src/components/design-system/Dialog.tsx)
- [`Pane.tsx`](../../src/components/design-system/Pane.tsx)
- [`Tabs.tsx`](../../src/components/design-system/Tabs.tsx)
- [`ListItem.tsx`](../../src/components/design-system/ListItem.tsx)
- [`ThemeProvider.tsx`](../../src/components/design-system/ThemeProvider.tsx)
- `ThemedBox`
- `ThemedText`
- `KeyboardShortcutHint`
- `Byline`

### 10.2 代表性设计

`Dialog` 的设计显示出这套系统对终端输入冲突非常敏感：

- 内建 `confirm:no`
- 支持 `isCancelActive`
- 支持自定义 input guide
- 支持 Ctrl+C/D 的 pending exit 提示

`ThemeProvider` 则说明主题系统不是简单字符串切换，它支持：

- theme setting 持久化
- preview theme
- auto theme
- 监听终端系统主题变化

这套 design-system 让上层业务组件能在统一交互语义上构建，而不必每个对话框自己处理快捷键和边框。

## 11. 本章小结

平台能力组件的总判断是：

- `permissions` 负责审批控制面。
- `tasks` 负责异步执行工作台。
- `agents` 负责 agent 生命周期管理。
- `mcp` 负责外部能力接入管理。
- `teams` 负责多 agent 协作控制。
- `memory/skills/hooks/sandbox/settings` 负责配置、知识与运行环境的可视化入口。

换句话说，这套组件体系已经远超“聊天 UI”，而是在终端里实现了一套 agent 平台控制台。
