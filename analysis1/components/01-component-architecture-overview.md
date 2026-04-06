# 组件体系详解（一）：组件总览、分层与依赖主干

[返回总目录](../../README.md)

[下一章：核心交互组件](./02-core-interaction-components.md)

## 1. 本章导读

这一组章节不再从“执行内核”出发，而是专门从 `src/components/` 的角度，回答三个问题：

1. 组件树是如何分层的，哪些组件是真正的中枢。
2. 各组件族之间的依赖方向是什么，子组件如何被上层编排。
3. 组件实现中有哪些共性设计手法。

结论先行：这个项目的组件体系不是“页面 + 若干按钮”的前端结构，而是一个围绕终端 agent 工作台组织起来的 TUI 组件平台。它的典型路径是：

`App -> REPL/FullscreenLayout -> Messages + PromptInput -> 能力弹层/能力面板 -> services/state/hooks/tools/tasks`

其中真正的双中枢是：

- [`src/components/Messages.tsx`](../../src/components/Messages.tsx)
- [`src/components/PromptInput/PromptInput.tsx`](../../src/components/PromptInput/PromptInput.tsx)

前者负责“展示已经发生了什么”，后者负责“组织下一步要做什么”。

先给出组件主干图：

```text
App
  -> REPL / FullscreenLayout
     -> Messages
     |    -> VirtualMessageList
     |         -> MessageRow / Message / messages/*
     |
     -> PromptInput
          -> Footer / Suggestions / Notifications
          -> QuickOpen / Search / Tasks / Teams / Bridge / ModelPicker

Messages 与 PromptInput 都向下依赖：
  -> AppState
  -> hooks
  -> services
```

## 2. 组件分层

### 2.1 Provider 与根包装层

根包装组件是 [`src/components/App.tsx`](../../src/components/App.tsx)。

它本身不做复杂 UI，而是负责把交互会话需要的上下文先挂起来：

- [`src/state/AppState.tsx`](../../src/state/AppState.tsx) 提供全局状态仓库
- [`src/context/stats.tsx`](../../src/context/stats.tsx) 提供统计上下文
- [`src/context/fpsMetrics.tsx`](../../src/context/fpsMetrics.tsx) 提供渲染性能度量

这说明该项目的组件树一开始就不是“无状态展示树”，而是“带运行时状态、统计、性能采样的工作台树”。

### 2.2 会话工作台层

会话工作台层的职责是把消息区、输入区、滚动区、状态条、弹层组合起来。核心文件包括：

- [`src/components/FullscreenLayout.tsx`](../../src/components/FullscreenLayout.tsx)
- [`src/components/Messages.tsx`](../../src/components/Messages.tsx)
- [`src/components/PromptInput/PromptInput.tsx`](../../src/components/PromptInput/PromptInput.tsx)
- [`src/components/ScrollKeybindingHandler.tsx`](../../src/components/ScrollKeybindingHandler.tsx)
- [`src/hooks/useGlobalKeybindings.tsx`](../../src/hooks/useGlobalKeybindings.tsx)

这一层是真正的“终端工作台壳层”。它负责：

- 把 transcript 和输入框装配到同一个交互平面
- 管理全局快捷键、滚动、搜索、转录模式、brief 模式
- 给各种对话框和面板提供挂载位置

### 2.3 会话渲染层

会话渲染层由以下组件链构成：

- [`src/components/Messages.tsx`](../../src/components/Messages.tsx)
- [`src/components/VirtualMessageList.tsx`](../../src/components/VirtualMessageList.tsx)
- [`src/components/MessageRow.tsx`](../../src/components/MessageRow.tsx)
- [`src/components/Message.tsx`](../../src/components/Message.tsx)
- [`src/components/messages`](../../src/components/messages)

这一层的职责不是“简单 map 一组消息”，而是：

- 归一化消息
- 对工具调用、read/search、hook、后台 bash 通知做折叠与分组
- 根据 fullscreen/transcript/brief 模式走不同渲染路径
- 在长会话下通过虚拟列表与 offscreen freeze 降低重绘成本

### 2.4 输入编排层

输入编排层以 [`src/components/PromptInput/PromptInput.tsx`](../../src/components/PromptInput/PromptInput.tsx) 为主入口，向下拆成：

- `PromptInputFooter`
- `PromptInputFooterLeftSide`
- `PromptInputFooterSuggestions`
- `PromptInputModeIndicator`
- `PromptInputQueuedCommands`
- `PromptInputStashNotice`
- `Notifications`
- 若干 `use*` 辅助 hooks

这一层负责把用户真实输入、补全建议、历史检索、图片粘贴、mode 切换、后台任务入口、团队/bridge/quick open/global search 等统一起来。

### 2.5 能力面板与能力弹层层

这一层是“控制面 UI”，组件分布最广，主要包括：

- agents：[`src/components/agents`](../../src/components/agents)
- permissions：[`src/components/permissions`](../../src/components/permissions)
- tasks：[`src/components/tasks`](../../src/components/tasks)
- mcp：[`src/components/mcp`](../../src/components/mcp)
- Settings：[`src/components/Settings`](../../src/components/Settings)
- teams：[`src/components/teams`](../../src/components/teams)
- hooks：[`src/components/hooks`](../../src/components/hooks)
- memory：[`src/components/memory`](../../src/components/memory)
- skills：[`src/components/skills`](../../src/components/skills)
- sandbox：[`src/components/sandbox`](../../src/components/sandbox)

这些组件不直接驱动 query 主循环，但它们决定了工作台如何暴露 agent 平台能力。

### 2.6 设计系统与通用构件层

这一层主要在：

- [`src/components/design-system`](../../src/components/design-system)
- [`src/components/ui`](../../src/components/ui)
- [`src/components/wizard`](../../src/components/wizard)
- [`src/components/CustomSelect`](../../src/components/CustomSelect)

它们提供了终端 UI 的复用基础件，例如：

- `Dialog`
- `Pane`
- `Tabs`
- `ListItem`
- `ThemedText`
- `TreeSelect`
- `WizardProvider`
- `Select`

项目并没有依赖一个外部成熟终端设计系统，而是在 Ink 之上自己长出了一层组件基座。

## 3. 组件族分布

按目录统计，`src/components/` 的主要组件族如下：

| 组件族 | 文件量 | 说明 |
| --- | ---: | --- |
| `permissions` | 51 | 权限请求、文件对比、规则与审批 UI |
| `messages` | 41 | 消息类型渲染与 tool result 子组件 |
| `agents` | 26 | agent 列表、详情、编辑、创建向导 |
| `PromptInput` | 21 | 输入框、建议、通知、footer、mode |
| `design-system` | 16 | 终端 UI 基础组件 |
| `mcp` | 13 | MCP 服务与工具视图 |
| `tasks` | 12 | 后台任务列表、详情、进度视图 |
| `Spinner` | 12 | 各类状态 spinner 变体 |
| `FeedbackSurvey` | 9 | 调研/反馈 UI |
| `CustomSelect` | 10 | 下拉、选择器、光标移动逻辑 |

这组统计非常说明问题：在该项目里，“权限、消息、agent、输入、MCP、任务”才是组件设计的真正重心。

## 4. 依赖主干

### 4.1 主干依赖关系

从高到低，可以把组件依赖关系概括为：

1. `App` 先建立 Provider。
2. 工作台层将 `Messages` 与 `PromptInput` 并列挂载。
3. `Messages` 将消息继续拆到 `VirtualMessageList -> MessageRow -> Message -> messages/*`。
4. `PromptInput` 将输入与面板继续拆到 footer、suggestions、dialogs、task/team/bridge/search 等子组件。
5. 面板类组件再向下依赖 `state/context/hooks/services/tools/tasks`。

这种依赖方向有两个特点：

- 交互主干非常清晰，主链路没有被“设置页”之类的边缘能力污染。
- 能力面板不直接互相依赖，而是共同依赖 `AppState`、hooks 和 services，所以横向耦合可控。

也可以用“编排层 -> 渲染层 -> 状态/服务层”的形式理解：

```text
编排层
  - App
  - REPL
  - Messages
  - PromptInput
    |
    +--> 渲染层
    |      - message leaves
    |      - dialog leaves
    |      - select leaves
    |
    +--> 能力面板层
           - permissions
           - agents
           - mcp
           - tasks
           - teams

渲染层 / 能力面板层
  -> 状态与上下文
     - AppState
     - overlay
     - notifications
  -> hooks / services / tools / tasks
```

### 4.2 状态注入方式

组件层没有采用传统 Redux `connect` 式写法，而是大量使用：

- [`src/state/AppState.tsx`](../../src/state/AppState.tsx) 中的 `useAppState`
- `useSetAppState`
- `useAppStateStore`
- context 中的 overlay、notifications、mailbox、modal 等 provider

`useAppState` 的切片订阅设计很关键。它要求 selector 直接返回稳定切片，而不是临时对象，这样组件不会因为全局状态细微变化而整体重渲染。

### 4.3 hooks 驱动而不是类控制器驱动

组件体系大量依赖 hooks 作为行为注入层，典型包括：

- [`src/hooks/useGlobalKeybindings.tsx`](../../src/hooks/useGlobalKeybindings.tsx)
- [`src/hooks/useVirtualScroll.ts`](../../src/hooks/useVirtualScroll.ts)
- [`src/hooks/useArrowKeyHistory.tsx`](../../src/hooks/useArrowKeyHistory.tsx)
- [`src/hooks/useTypeahead.tsx`](../../src/hooks/useTypeahead.tsx)
- [`src/hooks/useCommandQueue.ts`](../../src/hooks/useCommandQueue.ts)
- [`src/hooks/usePromptSuggestion.ts`](../../src/hooks/usePromptSuggestion.ts)

这意味着组件的“显示结构”和“交互行为”被明显拆开，后续新增能力时，优先是新增 hook 或 service，而不是继续把单个组件写得更胖。

## 5. 实现层面的共性设计

### 5.1 明显的 orchestrator / leaf 分层

几乎每个组件族都可以区分出两类组件：

- orchestrator：管理状态、切换视图、调用 hooks 或 services
- leaf：只负责渲染某个具体子块

例如消息链路中：

- orchestrator 是 `Messages`、`MessageRow`、`Message`
- leaf 是 `AssistantTextMessage`、`UserTextMessage`、`RateLimitMessage` 等

例如 agent 组件族中：

- orchestrator 是 `AgentsMenu`
- leaf 是 `AgentDetail`、`AgentEditor`、`ColorPicker`、`ToolSelector`

这种拆法使上层负责编排，下层负责可替换渲染。

### 5.2 为终端性能专门优化

从源码能看到不少不是普通 Web React 项目常见的优化点：

- `VirtualMessageList` 做消息虚拟化与搜索索引
- `OffscreenFreeze` 避免离屏区域重复重绘
- `MessageRow` 预先算 `hasContentAfterIndex`，避免把整个历史数组传给子项
- `Messages` 对 logo header 做 memo，避免前导节点污染整屏 blit

说明作者非常清楚：这个 UI 的瓶颈不是 DOM，而是终端屏幕重绘与超长 transcript。

### 5.3 通过 `feature()` 和按需 `require()` 做编译裁剪

很多组件里出现：

- `feature('...')`
- 条件 `require(...)`

例如权限、workflow、monitor、theme watcher、brief/proactive 等都采用了这类模式。作用是：

- ant-only 或内部门控功能不会泄露到外部构建
- 打包时可以 dead-code eliminate
- 组件不会为不可用功能平白引入依赖

### 5.4 对终端交互细节有系统化抽象

组件层不只是“能显示”，而是系统化抽象了终端交互对象：

- Dialog 与 Confirmation keybinding
- overlay 注册与冲突屏蔽
- sticky footer / modal / fullscreen scroll
- theme preview / auto theme watcher
- text input 与 vim input 的双轨支持

这套抽象说明项目本质上是在做终端 IDE 风格工作台，而不是单页聊天窗口。

## 6. 本章小结

组件体系的总判断是：

- `Messages` 和 `PromptInput` 构成会话工作台的双中枢。
- 其余组件族大多是围绕权限、agent、MCP、任务、团队协作展开的能力控制面。
- 组件设计很强调“上层编排、下层专职渲染”，并且针对终端长会话场景做了大量性能与交互细节优化。

后续两章分别进入两条主线：

- 一条是“消息与输入”这条核心交互主线。
- 一条是“权限、agent、MCP、任务、团队”等平台能力主线。
