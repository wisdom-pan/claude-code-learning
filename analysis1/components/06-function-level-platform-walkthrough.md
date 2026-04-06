# 组件体系详解（六）：平台控制面函数级实现拆解

[返回总目录](../../README.md)

[上一章：核心组件函数级实现拆解](./05-function-level-core-walkthrough.md)

## 1. 本章导读

本章继续把粒度维持在函数级，不过对象换成平台控制面：

- permissions
- tasks
- agents
- mcp
- teams
- memory
- skills
- hooks
- design-system

重点不是“它们属于哪个目录”，而是“具体哪个函数在负责映射、切换、聚合、下发和同步”。

## 2. permissions：从工具类型映射到审批 UI

位置：

- [`src/components/permissions/PermissionRequest.tsx`](../../src/components/permissions/PermissionRequest.tsx)

### 2.1 `permissionComponentForTool(tool)`

实现职责：

- 把具体 `Tool` 类型映射到具体审批组件
- 例如：
  - `FileEditTool -> FileEditPermissionRequest`
  - `BashTool -> BashPermissionRequest`
  - `WebFetchTool -> WebFetchPermissionRequest`
  - `GlobTool/GrepTool/FileReadTool -> FilesystemPermissionRequest`
- feature-gated 工具若缺实现，则回退到 `FallbackPermissionRequest`

这说明权限 UI 的分发依据不是字符串，而是工具类对象本身。

### 2.2 `getNotificationMessage(toolUseConfirm)`

实现职责：

- 通过 `tool.userFacingName(input)` 取用户可读的工具名
- 对 enter/exit plan mode、review artifact 等特殊工具返回专门文案
- 若拿不到工具名，则退回通用提示

它负责权限弹窗的通知语义，而不是审批本身。

### 2.3 `PermissionRequest(...)`

实现职责：

- 构造拒绝链：
  - `onDone()`
  - `onReject()`
  - `toolUseConfirm.onReject()`
- 绑定 `app:interrupt`
- 调用 `useNotifyAfterTimeout(notificationMessage, 'permission_prompt')`
- 根据 `toolUseConfirm.tool` 选出实际审批组件
- 把 `toolUseConfirm / toolUseContext / verbose / workerBadge / setStickyFooter` 下发

它本质上是“统一审批入口 + 工具审批组件路由器”。

## 3. tasks：后台任务工作台的函数级实现

位置：

- [`src/components/tasks/BackgroundTasksDialog.tsx`](../../src/components/tasks/BackgroundTasksDialog.tsx)

### 3.1 `getSelectableBackgroundTasks(tasks, foregroundedTaskId)`

实现职责：

- 先过滤出 `isBackgroundTask`
- 再排除当前 foreground 的 `local_agent`

这样做的目的，是避免一个已经在主界面查看的 agent 同时又在任务对话框里出现一次。

### 3.2 `BackgroundTasksDialog(...)`

实现职责：

- 从 `AppState` 取 `tasks`、`foregroundedTaskId`、`expandedView`
- 根据 `initialDetailTaskId` 或“仅剩一个任务”决定初始 viewState
- 通过 `useRegisterOverlay('background-tasks-dialog')` 阻止上层 Chat 快捷键泄漏
- 用 `useMemo` 把所有后台任务转成列表项并排序、分组：
  - bash
  - remote agent
  - local agent
  - teammates
  - workflows
  - MCP monitors
  - dream
- 用 `useKeybindings` 把 `confirm:previous/next/yes` 绑定到列表导航

它的核心不是展示，而是“把多种后台执行体归一化成统一导航列表”。

### 3.3 `toListItem(task)`

实现职责：

- 按 task.type 统一映射为 `ListItem`
- 为每类任务提取最合适的 label：
  - shell 用 `command` 或 `description`
  - remote agent 用 `title`
  - local agent 用 `description`
  - teammate 用 `@agentName`
  - workflow 用 `summary ?? description`

这一步把后端任务状态模型转换成前端可展示模型。

### 3.4 `Item(...)`

实现职责：

- 根据终端宽度计算 `maxActivityWidth`
- 根据 `isCoordinatorMode()` 决定选中指针是否用灰色
- 若 `item.type === 'leader'`，直接显示 `@TEAM_LEAD_NAME`
- 否则交给 `BackgroundTaskComponent`

它是任务列表项的统一渲染器。

### 3.5 `TeammateTaskGroups(...)`

实现职责：

- 把 `leader` 和 `in_process_teammate` 分开
- 再按 `teamName` 分组 teammate
- 生成按 team 分块的列表

这说明任务对话框里并不是把 teammate 当作普通任务平铺，而是保留了团队语义。

## 4. agents：agent 创建与浏览的函数级实现

位置：

- [`src/components/agents/AgentsMenu.tsx`](../../src/components/agents/AgentsMenu.tsx)
- [`src/components/agents/AgentDetail.tsx`](../../src/components/agents/AgentDetail.tsx)
- [`src/components/agents/new-agent-creation/CreateAgentWizard.tsx`](../../src/components/agents/new-agent-creation/CreateAgentWizard.tsx)

### 4.1 `AgentsMenu(...)`

实现职责：

- 从 `AppState` 中读取 `agentDefinitions`、`mcpTools`、`toolPermissionContext`
- 调用 `useMergedTools(tools, mcpTools, toolPermissionContext)` 形成完整工具集
- 按来源切分 `allAgents`：
  - built-in
  - userSettings
  - projectSettings
  - policySettings
  - localSettings
  - flagSettings
  - plugin
- 用 `resolveAgentOverrides(...)` 得到最终生效的 resolved agents
- 处理创建、删除、详情、编辑、wizard 等模式切换

这个函数是 agent 控制面的总状态机。

### 4.2 `AgentDetail(...)`

实现职责：

- 调用 `resolveAgentTools(agent, tools, false)` 计算合法/非法 tools
- 用 `getActualRelativeAgentFilePath(agent)` 算出文件来源
- 用 `getAgentColor(agent.agentType)` 决定颜色展示
- 通过 `getAgentModelDisplay(agent.model)` 展示模型
- 通过 `getMemoryScopeDisplay(agent.memory)` 展示 memory scope
- 对非 built-in agent 再渲染 `agent.getSystemPrompt()`

这个函数的重点是“把 agent 定义对象展开成用户可审阅的配置单元”。

### 4.3 `CreateAgentWizard(...)`

实现职责：

- 动态拼出 wizard steps 数组
- 把 `TypeStep` 和 `ToolsStep` 包成带 props 的闭包 step
- 仅在 `isAutoMemoryEnabled()` 时插入 `MemoryStep`
- 最后一页使用 `ConfirmStepWrapper`
- 把这些步骤交给 `WizardProvider`

关键设计是：创建 agent 的流程不是写死页面，而是“步骤数组驱动”。

## 5. mcp：MCP 面板的函数级实现

位置：

- [`src/components/mcp/MCPSettings.tsx`](../../src/components/mcp/MCPSettings.tsx)

### 5.1 `MCPSettings(...)`

实现职责：

- 从 `AppState` 读取 `mcp` 与 `agentDefinitions`
- 调用 `extractAgentMcpServers(agentDefinitions.allAgents)` 取出 agent 绑定的 MCP server
- 过滤 `mcp.clients`，保留可展示客户端
- 在 effect 中执行 `prepareServers()`：
  - 遍历每个 client
  - 判断 transport 是 `sse/http/stdio/claudeai-proxy`
  - 对 `sse/http` 使用 `ClaudeAuthProvider(...).tokens()` 探测认证状态
  - 综合 session ingress token 与“已连通且有 tools”来推断 `isAuthenticated`
  - 最终写入 `servers`
- 若 `servers` 和 `agentMcpServers` 都为空，则 `onComplete(...)` 给出空配置提示
- 再通过 `viewState.type` 在 list / server-menu / server-tools 等视图间切换

这个函数本质上是 MCP 控制台的状态机构建器与 server metadata 聚合器。

## 6. teams：多 agent 协作控制面的函数级实现

位置：

- [`src/components/teams/TeamsDialog.tsx`](../../src/components/teams/TeamsDialog.tsx)

### 6.1 `TeamsDialog(...)`

实现职责：

- 注册 `useRegisterOverlay('teams-dialog')`
- 用 `dialogLevel` 区分 `teammateList` 与 `teammateDetail`
- 用 `getTeammateStatuses(dialogLevel.teamName)` 和轮询 `refreshKey` 刷新状态
- 用 `handleCycleMode` 实现：
  - detail 页只循环单个 teammate
  - list 页批量循环全部 teammate
- 用 `useInput(...)` 直接处理：
  - 左右/上下导航
  - Enter 深钻或跳转 pane
  - `k` kill
  - `s` graceful shutdown
  - `h/H` hide/show
  - `p` prune idle teammates

它是 swarm 控制台的主状态机。

### 6.2 `sendModeChangeToTeammate(teammateName, teamName, targetMode)`

实现职责：

- 先调用 `setMemberMode(...)` 直接改配置，保证 UI 立即可见
- 再构造 `createModeSetRequestMessage(...)`
- 通过 `writeToMailbox(...)` 发给 teammate

这是一种“双写”策略：先改本地配置，再发 mailbox 通知远端 agent 更新运行态。

### 6.3 `cycleTeammateMode(teammate, teamName, isBypassAvailable)`

实现职责：

- 从 teammate 当前 mode 构造最小 `ToolPermissionContext`
- 调用 `getNextPermissionMode(context)` 算出下一档模式
- 再调用 `sendModeChangeToTeammate(...)`

### 6.4 `cycleAllTeammateModes(teammates, teamName, isBypassAvailable)`

实现职责：

- 先收集所有 teammate 当前模式
- 若模式不一致，则统一重置为 `default`
- 若一致，则统一切换到下一模式
- 用 `setMultipleMemberModes(teamName, modeUpdates)` 批量写配置
- 再逐个 teammate 发 mailbox 消息

这解决的是多 agent 协作中最典型的一类一致性问题：团队 permission mode 要么一起重置，要么一起进入下一档。

## 7. memory / skills / hooks：知识与配置面板的函数级实现

### 7.1 `MemoryFileSelector(...)`

位置：

- [`src/components/memory/MemoryFileSelector.tsx`](../../src/components/memory/MemoryFileSelector.tsx)

实现职责：

- 用 `use(getMemoryFiles())` 读取 memory 文件树
- 手动补全 user/project 根 `CLAUDE.md`，即使文件还不存在也会放入候选
- 依据 `parent` 构造 depth，生成嵌套 label
- 根据 git 仓库状态决定 project memory 描述是 “Checked in at ./CLAUDE.md” 还是 “Saved in ./CLAUDE.md”
- 若开启 auto-memory，再增加：
  - auto-memory folder
  - team-memory folder
  - 各 agent memory folder
- 用 `lastSelectedPath` 保留上次选中项
- 同时维护 `autoMemoryOn`、`autoDreamOn`、`lastDreamAt`

这个函数实际上把分散在文件系统各处的记忆入口统一成了一个“memory 资源选择器”。

### 7.2 `getSourceTitle(source)` / `getSourceSubtitle(source, skills)`

位置：

- [`src/components/skills/SkillsMenu.tsx`](../../src/components/skills/SkillsMenu.tsx)

实现职责：

- `getSourceTitle` 把 `plugin`、`mcp`、各 setting source 转成用户文案
- `getSourceSubtitle`：
  - 对 `mcp` skills 提取 server 名称
  - 对文件型 skills 展示对应路径
  - 若存在旧 `commands_DEPRECATED` 形式，则同时展示 commands 路径

### 7.3 `SkillsMenu(...)`

实现职责：

- 从 `commands` 过滤出技能命令
- 按 `policy/user/project/local/flag/plugin/mcp` 分组
- 每组内排序
- 无技能时展示空态对话框
- 有技能时逐组渲染，并显示总 skill 数

这说明 skills UI 并不是直接列命令，而是把 skill 当作一个按来源聚合的资产目录。

### 7.4 `HooksConfigMenu(...)`

位置：

- [`src/components/hooks/HooksConfigMenu.tsx`](../../src/components/hooks/HooksConfigMenu.tsx)

实现职责：

- 维护 `modeState`：
  - `select-event`
  - `select-matcher`
  - `select-hook`
  - `view-hook`
- 通过 `useSettingsChange(...)` 感知 policySettings 是否：
  - `disableAllHooks`
  - `allowManagedHooksOnly`
- 把 `toolNames + mcp.tools.map(name)` 合并成 `combinedToolNames`
- 调用 `groupHooksByEventAndMatcher(appStateStore.getState(), combinedToolNames)`
- 再用 `getSortedMatchersForEvent(...)`、`getHooksForMatcher(...)` 推导当前层级数据
- 给每一层分别绑定 `confirm:no` 返回逻辑

这使 hooks 配置浏览器成为一个明显的分层状态机，而不是简单折叠列表。

## 8. design-system：通用交互基座的函数级实现

### 8.1 `Dialog(...)`

位置：

- [`src/components/design-system/Dialog.tsx`](../../src/components/design-system/Dialog.tsx)

实现职责：

- 处理默认 color 和 `isCancelActive`
- 调用 `useExitOnCtrlCDWithKeybindings(...)` 构造 `exitState`
- 用 `useKeybinding('confirm:no', onCancel, { context: 'Confirmation', isActive: isCancelActive })`
- 若用户已经按过一次退出键，则显示 “Press {keyName} again to exit”
- 否则显示标准操作提示：
  - Enter confirm
  - Esc cancel
- `hideBorder` 为真时只返回内容，否则包一层 `Pane`

这个函数把终端对话框的“取消、退出、边框、输入指南”全部统一了。

### 8.2 `ThemeProvider(...)`

位置：

- [`src/components/design-system/ThemeProvider.tsx`](../../src/components/design-system/ThemeProvider.tsx)

实现职责：

- 维护：
  - `themeSetting`
  - `previewTheme`
  - `systemTheme`
- 通过 `activeSetting = previewTheme ?? themeSetting` 决定当前生效设置
- 若 `feature('AUTO_THEME')` 且 `activeSetting === 'auto'`，动态加载 `watchSystemTheme(...)`
- 通过 `useMemo` 输出一组主题控制函数：
  - `setThemeSetting(newSetting)`
  - `setPreviewTheme(newSetting)`
  - `savePreview()`
  - `cancelPreview()`
- `useTheme()` 返回 `[currentTheme, setThemeSetting]`
- `useThemeSetting()` 返回原始 setting
- `usePreviewTheme()` 返回 preview 控制器

这套函数把主题系统明确拆成“持久设置、临时预览、系统解析”三层。

## 9. 本章小结

平台控制面下钻到函数级后，可以看到：

- `PermissionRequest` 通过函数映射把工具审批路由到专用 UI。
- `BackgroundTasksDialog` 通过 `getSelectableBackgroundTasks`、`toListItem` 和分组逻辑，把多后端任务统一成任务面板。
- `AgentsMenu`、`CreateAgentWizard`、`AgentDetail` 分别覆盖 agent 管理、创建流程和配置展开。
- `MCPSettings` 通过 `prepareServers()` 式逻辑聚合 MCP transport 与认证状态。
- `TeamsDialog` 通过 mailbox 和配置双写函数实现 teammate mode 同步。
- `MemoryFileSelector`、`SkillsMenu`、`HooksConfigMenu` 则分别把 memory、skills、hooks 变成真正可浏览的控制面资源。

也就是说，这些“平台能力组件”真正复杂的地方，不在 UI 壳，而在函数级的映射、聚合、同步和状态机实现。
