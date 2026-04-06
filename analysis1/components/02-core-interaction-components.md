# 组件体系详解（二）：核心交互组件与消息/输入主链路

[返回总目录](../../README.md)

[上一章：组件总览、分层与依赖主干](./01-component-architecture-overview.md)

[下一章：平台能力组件](./03-platform-components.md)

## 1. 本章导读

本章聚焦最核心的用户交互主链路，也就是用户每次真正看到、滚动、输入和确认的那一条链：

`App -> Messages -> VirtualMessageList -> MessageRow -> Message -> messages/*`

以及：

`PromptInput -> footer / suggestions / dialogs / queued commands / history / typeahead`

结论先行：这里不是“一个聊天面板 + 一个输入框”，而是“一个消息工作台 + 一个输入编排器”。

## 2. App：根组件只做 Provider 装配

[`src/components/App.tsx`](../../src/components/App.tsx) 的设计非常克制。

它主要做三件事：

- 用 `AppStateProvider` 提供全局状态
- 用 `StatsProvider` 提供统计
- 用 `FpsMetricsProvider` 提供性能度量

这意味着根组件本身不承担业务分发，业务编排被刻意下放到工作台组件，利于：

- 根节点稳定
- 初始化与渲染边界清楚
- 将同一套状态树复用到不同入口

## 3. Messages：消息工作台的总编排器

主入口是 [`src/components/Messages.tsx`](../../src/components/Messages.tsx)。

### 3.1 它负责的不是单纯渲染，而是消息预处理

从导入与实现可以看出，`Messages` 在真正渲染前会完成多轮整理：

- 规范化消息
- UI 重排
- read/search 折叠
- hook 摘要折叠
- teammate shutdown 折叠
- 后台 bash 通知折叠
- grouped tool use 合并
- brief 模式过滤

也就是说，`Messages` 既是渲染组件，也是 transcript 视图转换器。

### 3.2 它维护的是多视图，而不是单一列表

`Messages` 同时要适配：

- fullscreen 模式
- transcript 模式
- brief-only 模式
- 普通 prompt 屏
- remote 模式下的特殊显示逻辑

因此它内部不能简单把 `messages[]` 直接传给子组件，而要先决定“当前用户应该看到什么消息集合”。

### 3.3 它有明显的性能中心意识

`Messages` 中有几个关键性能点：

- 前置的 `LogoHeader` 单独 memo，避免头部节点拖慢整屏 blit
- 长列表时交给 [`src/components/VirtualMessageList.tsx`](../../src/components/VirtualMessageList.tsx)
- 每行再交给 [`src/components/MessageRow.tsx`](../../src/components/MessageRow.tsx)
- 离屏冻结通过 [`src/components/OffscreenFreeze.tsx`](../../src/components/OffscreenFreeze.tsx)

这说明作者将消息区视为全应用最重的渲染热点。

## 4. VirtualMessageList：长 transcript 的性能核心

[`src/components/VirtualMessageList.tsx`](../../src/components/VirtualMessageList.tsx) 是整个消息系统里技术含量最高的组件之一。

### 4.1 它解决的不是“滚动”，而是“可搜索的虚拟滚动”

这个组件同时承担：

- 虚拟列表
- 高度测量与缓存
- transcript 搜索
- 跳转到匹配项
- sticky prompt 跟踪
- 键盘滚动与程序化滚动的分离

对应的对外句柄 `JumpHandle` 直接说明了这一点：它支持 `nextMatch`、`prevMatch`、`setAnchor`、`warmSearchIndex`、`disarmSearch`。

### 4.2 它有终端特有的设计

该组件不是浏览器虚拟列表的直接搬运，有几个明显终端化实现：

- 需要测量消息在终端中的真实高度
- 搜索命中位置依赖屏幕渲染后的行坐标
- sticky prompt 需要根据滚动位置推断“哪个用户输入正停留在顶部”
- 高度缓存必须与 `columns` 联动，否则终端换宽导致换行变化后会错位

### 4.3 它的子组件是 VirtualItem

`VirtualItem` 不是业务组件，而是一个稳定包装层。其目标是减少 per-item 闭包分配，降低长会话滚动时的 GC 压力。

这体现了组件实现的一个典型特征：很多代码不是为了功能正确性，而是为了终端高频滚动下的稳定性能。

## 5. MessageRow：消息行级编排器

[`src/components/MessageRow.tsx`](../../src/components/MessageRow.tsx) 的职责是把“一个 renderable message”转成“一个可显示行单元”。

### 5.1 它负责推断消息的动态状态

例如：

- collapsed read/search 组是否仍然活跃
- 当前消息是否应该静态渲染
- 当前消息是否需要动画
- 当前消息是否还有后续真实内容

这里有个很重要的辅助函数：

- `hasContentAfterIndex(...)`

这个函数被单独导出，就是为了在 `Messages` 中一次性预计算，避免给每个 `MessageRow` 传整段历史数组。

### 5.2 它是消息域与渲染域之间的适配器

`MessageRow` 同时知道：

- message 分组/折叠后的形态
- tool 是否进行中
- lookups 中能否查到 sibling/progress/tool use id
- 当前 screen 是 prompt 还是 transcript

所以它本质上是“消息语义”和“显示语义”的交界层。

## 6. Message：真正的消息类型分发器

[`src/components/Message.tsx`](../../src/components/Message.tsx) 负责把一条消息继续拆给最终的子组件。

### 6.1 分发方式

它根据消息类型把渲染下发给：

- `AttachmentMessage`
- `AssistantTextMessage`
- `AssistantThinkingMessage`
- `AssistantToolUseMessage`
- `CollapsedReadSearchContent`
- `GroupedToolUseContent`
- `SystemTextMessage`
- `UserTextMessage`
- `UserImageMessage`
- `UserToolResultMessage`
- 以及 compact、advisor、shell output 等特殊分支

这层的价值是：上游只要把消息规整成统一结构，下游就能用固定组件树消费。

### 6.2 子组件拆得非常细

`src/components/messages/` 目录中的子组件已经覆盖了绝大多数消息亚型，例如：

- `AssistantTextMessage`
- `AssistantThinkingMessage`
- `AssistantRedactedThinkingMessage`
- `PlanApprovalMessage`
- `RateLimitMessage`
- `TaskAssignmentMessage`
- `UserBashInputMessage`
- `UserBashOutputMessage`
- `UserMemoryInputMessage`
- `UserTeammateMessage`
- `UserToolResultMessage/*`

这个目录本质上是一个“消息样式协议层”。新增消息类型时，通常只需补一个 leaf component，而不用重写 `Messages` 总体结构。

## 7. PromptInput：输入编排器，而不是单纯文本框

[`src/components/PromptInput/PromptInput.tsx`](../../src/components/PromptInput/PromptInput.tsx) 是另一条主线的核心。

### 7.1 它覆盖的职责极广

从 import 即可看出它同时吸收了以下能力：

- 输入缓冲与文本编辑
- arrow key history / history search
- prompt suggestion / speculation / typeahead
- slash command、thinking、token budget、ultraplan 等触发器识别
- 图片粘贴与图片缓存
- model 选择、fast mode、permission mode 切换
- quick open、global search、bridge、teams、background tasks 等对话框
- teammate 视角、overlay、notifications、queued commands

这说明 PromptInput 的本质不是 `TextInput`，而是一个会话控制台。

### 7.2 它的子组件分工清楚

`src/components/PromptInput/` 目录下的子组件大体可以分成四类：

第一类，结构组件：

- [`PromptInputFooter.tsx`](../../src/components/PromptInput/PromptInputFooter.tsx)
- [`PromptInputFooterLeftSide.tsx`](../../src/components/PromptInput/PromptInputFooterLeftSide.tsx)
- [`PromptInputModeIndicator.tsx`](../../src/components/PromptInput/PromptInputModeIndicator.tsx)

第二类，建议与通知组件：

- [`PromptInputFooterSuggestions.tsx`](../../src/components/PromptInput/PromptInputFooterSuggestions.tsx)
- [`Notifications.tsx`](../../src/components/PromptInput/Notifications.tsx)
- [`IssueFlagBanner.tsx`](../../src/components/PromptInput/IssueFlagBanner.tsx)

第三类，输入状态与队列组件：

- [`PromptInputQueuedCommands.tsx`](../../src/components/PromptInput/PromptInputQueuedCommands.tsx)
- [`PromptInputStashNotice.tsx`](../../src/components/PromptInput/PromptInputStashNotice.tsx)
- [`HistorySearchInput.tsx`](../../src/components/PromptInput/HistorySearchInput.tsx)

第四类，行为 hooks 和工具函数：

- [`useMaybeTruncateInput.ts`](../../src/components/PromptInput/useMaybeTruncateInput.ts)
- [`usePromptInputPlaceholder.ts`](../../src/components/PromptInput/usePromptInputPlaceholder.ts)
- [`useShowFastIconHint.ts`](../../src/components/PromptInput/useShowFastIconHint.ts)
- [`useSwarmBanner.ts`](../../src/components/PromptInput/useSwarmBanner.ts)
- [`inputModes.ts`](../../src/components/PromptInput/inputModes.ts)
- [`inputPaste.ts`](../../src/components/PromptInput/inputPaste.ts)

### 7.3 设计亮点

PromptInput 的关键亮点不是“功能多”，而是它把互相冲突的输入行为统一了：

- 普通输入与 vim 输入并存
- 输入编辑与 modal/overlay 的快捷键冲突能被屏蔽
- 输入中的 suggestion 与外部 speculative prompt suggestion 共存
- 用户输入既可以发往主会话，也可以发往队列中的 tool 交互或 teammate 通道

换句话说，它把“终端里所有可能发生的输入行为”尽量纳入同一个协调器。

## 8. GlobalKeybindingHandlers：跨组件的全局控制面

[`src/hooks/useGlobalKeybindings.tsx`](../../src/hooks/useGlobalKeybindings.tsx) 不是视觉组件，但它对组件行为的影响极大。

它统一注册了全局键位，例如：

- transcript 开关
- todo / teammate 面板切换
- brief view 切换
- terminal panel 切换

这意味着工作台不是由某个单独组件“拥有全部快捷键”，而是通过独立全局处理器把跨组件动作集中起来。

## 9. 这一条主链路的结构评价

从实现上看，消息链路与输入链路形成了一个很成熟的双向闭环：

1. 输入由 `PromptInput` 编排、提交。
2. query / tool / task 执行结果变成消息。
3. `Messages` 对消息做语义级重排与折叠。
4. `VirtualMessageList`、`MessageRow`、`Message` 再把它们渲染成终端可消费形态。

这套拆分优于很多同类 CLI agent 的地方在于：

- 消息层与输入层都不是一坨大文件直接画 UI
- transcript 搜索、折叠、虚拟滚动、brief 过滤都被纳入正式架构
- 工具调用、thinking、plan approval、team message 都被视为一等消息类型

## 10. 本章小结

核心交互主线的判断是：

- `Messages` 是 transcript 语义整理器加渲染总管。
- `VirtualMessageList` 是长会话性能与搜索能力的核心。
- `MessageRow` 与 `Message` 是消息语义到显示语义的两级适配层。
- `PromptInput` 是输入编排器，而不是传统意义上的文本输入框。

也正因为这条主线拆得够清楚，后面的权限、agent、MCP、团队等能力才能以面板/弹层形式稳定挂进来，而不会直接污染消息与输入的核心结构。
