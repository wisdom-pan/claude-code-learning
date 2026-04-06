# 第十章：Multi-Agent 机制与实现细节

[返回总目录](../README.md)

## 1. 本章导读

这一章直接回答一个问题：

**Claude Code 源码里不但有 multi-agent，而且是三套并存的多 agent 运行模型。**

不是只有“可以开一个后台子任务”这么简单，而是同时存在：

1. 普通 `subagent`
2. `coordinator -> workers` 协调器模式
3. `swarm teammates` 团队协作模式

本章重点讲清楚：

1. 多 agent 在源码里分成哪几种
2. `AgentTool` 是如何决定“这是普通 subagent 还是 teammate”
3. coordinator 模式到底做了什么增强
4. swarm 模式如何完成 team、mailbox、permission、task list 这几条协作链路
5. 这套实现相比“单个 agent + background task”到底多了什么

本章主要依据这些实现：

- [`src/tools/AgentTool/AgentTool.tsx`](../src/tools/AgentTool/AgentTool.tsx)
- [`src/tools/AgentTool/runAgent.ts`](../src/tools/AgentTool/runAgent.ts)
- [`src/tools/AgentTool/forkSubagent.ts`](../src/tools/AgentTool/forkSubagent.ts)
- [`src/coordinator/coordinatorMode.ts`](../src/coordinator/coordinatorMode.ts)
- [`src/tools/shared/spawnMultiAgent.ts`](../src/tools/shared/spawnMultiAgent.ts)
- [`src/utils/swarm/spawnInProcess.ts`](../src/utils/swarm/spawnInProcess.ts)
- [`src/utils/swarm/inProcessRunner.ts`](../src/utils/swarm/inProcessRunner.ts)
- [`src/tasks/InProcessTeammateTask/InProcessTeammateTask.tsx`](../src/tasks/InProcessTeammateTask/InProcessTeammateTask.tsx)
- [`src/utils/teammateMailbox.ts`](../src/utils/teammateMailbox.ts)
- [`src/hooks/useInboxPoller.ts`](../src/hooks/useInboxPoller.ts)
- [`src/tools/SendMessageTool/SendMessageTool.ts`](../src/tools/SendMessageTool/SendMessageTool.ts)
- [`src/tools/TeamCreateTool/TeamCreateTool.ts`](../src/tools/TeamCreateTool/TeamCreateTool.ts)
- [`src/tools/TaskCreateTool/TaskCreateTool.ts`](../src/tools/TaskCreateTool/TaskCreateTool.ts)
- [`src/tools/TaskStopTool/TaskStopTool.ts`](../src/tools/TaskStopTool/TaskStopTool.ts)
- [`src/utils/swarm/leaderPermissionBridge.ts`](../src/utils/swarm/leaderPermissionBridge.ts)

先给结论：

Claude Code 的 multi-agent 不是单一实现，而是一个分层体系：

```text
一、普通 AgentTool 子代理
   - 单个主 agent 派出一个 subagent
   - 可同步、可后台、可 fork

二、Coordinator Mode
   - 主线程变成 coordinator
   - 通过 AgentTool 持续派出多个 worker
   - worker 结果用 task-notification 回流

三、Swarm / Teammates
   - 创建 team
   - 产生 lead + teammates
   - 支持 in-process / tmux / iTerm2 后端
   - 支持 mailbox、权限回流、task list 协作
```

因此，Claude Code 的 multi-agent 不是“加了个 AgentTool”。

更准确地说，它做的是一个小型 agent runtime：

- 有 agent 身份模型
- 有 agent 生成与调度
- 有 agent 间通信
- 有 leader / worker 权限桥接
- 有共享任务平面
- 有 UI 层 task / teammate 可视化

## 2. 总体结构：三种 multi-agent 不是一回事

相关实现：

- [`src/tools/AgentTool/AgentTool.tsx`](../src/tools/AgentTool/AgentTool.tsx)
- [`src/coordinator/coordinatorMode.ts`](../src/coordinator/coordinatorMode.ts)
- [`src/tools/shared/spawnMultiAgent.ts`](../src/tools/shared/spawnMultiAgent.ts)

很多人看到 `AgentTool` 会先得出一个过于简单的结论：

“Claude Code 只是支持开 subagent。”

这不对。

源码里至少有下面三种不同层级的多 agent：

### 2.1 普通 subagent

这是最基础的一层：

- 主 agent 调 `AgentTool`
- 创建一个新的 agent 会话
- 子 agent 继承部分上下文与工具池
- 完成后把结果回传给主线程

这一层更像“后台 worker”。

### 2.2 coordinator mode

这一层不是“多开几个 subagent”那么简单，而是把主线程角色改写成 coordinator。

在 [`src/coordinator/coordinatorMode.ts`](../src/coordinator/coordinatorMode.ts) 中，`getCoordinatorSystemPrompt()` 直接把主线程定义为：

```typescript
You are Claude Code, an AI assistant that orchestrates software engineering tasks across multiple workers.
```

也就是说：

- 主线程不再主要负责自己写代码
- 主线程负责调度多个 worker
- worker 负责 research / implementation / verification
- 主线程负责综合结果、继续派工、对用户汇报

这是一个真正的 orchestrator 模式。

### 2.3 swarm teammates

swarm 则更进一步。

它不是“临时起几个 worker”，而是显式创建一个 team：

- 有 `team_name`
- 有 lead agent
- 有 teammate roster
- 有 inbox / mailbox
- 有共享 task list
- 有面向 teammate 的权限回流机制

这一层已经接近一个轻量“agent 组织系统”。

## 3. `AgentTool` 是多 agent 的统一入口

相关实现：

- [`src/tools/AgentTool/AgentTool.tsx`](../src/tools/AgentTool/AgentTool.tsx)

### 3.1 输入 schema 直接暴露了多 agent 能力

`AgentTool` 的 schema 里有一组非常关键的字段：

```typescript
const baseInputSchema = z.object({
  description: z.string(),
  prompt: z.string(),
  subagent_type: z.string().optional(),
  model: z.enum(['sonnet', 'opus', 'haiku']).optional(),
  run_in_background: z.boolean().optional(),
})

const multiAgentInputSchema = z.object({
  name: z.string().optional(),
  team_name: z.string().optional(),
  mode: permissionModeSchema().optional(),
})
```

这组字段已经说明它不是单纯“开一个执行任务”：

- `subagent_type` 决定 agent 类型
- `run_in_background` 决定同步还是异步
- `name` 让 agent 可被后续寻址
- `team_name` 让 agent 进入 swarm / teammate 路径
- `mode` 让 spawned teammate 继承 plan 等权限模式

### 3.2 `AgentTool` 如何判断是不是 teammate

`call()` 里的核心分支非常关键：

```typescript
if (teamName && name) {
  const result = await spawnTeammate({
    name,
    prompt,
    description,
    team_name: teamName,
    use_splitpane: true,
    plan_mode_required: spawnMode === 'plan',
    model: model ?? agentDef?.model,
    agent_type: subagent_type,
    invokingRequestId: assistantMessage?.requestId
  }, toolUseContext);
}
```

这段逻辑说明：

- 当只有 `subagent_type` / `prompt` 时，它走普通子代理路径
- 当同时带 `teamName + name` 时，它走 `spawnTeammate()` 路径

也就是说，**同一个 AgentTool 同时承担了普通 subagent 和 teammate spawn 的入口角色。**

### 3.3 对 teammate 的限制也写在这里

同一函数里还有几条非常工程化的约束：

```typescript
if (isTeammate() && teamName && name) {
  throw new Error('Teammates cannot spawn other teammates ...')
}

if (isInProcessTeammate() && teamName && run_in_background === true) {
  throw new Error('In-process teammates cannot spawn background agents ...')
}
```

这说明作者不是简单堆功能，而是在约束多 agent 拓扑：

- teammate 不能无限嵌套 teammate
- in-process teammate 不能再启动自己的 background agent

否则 agent graph 很容易失控。

## 4. 普通 subagent：本质是“主会话的侧链”

相关实现：

- [`src/tools/AgentTool/runAgent.ts`](../src/tools/AgentTool/runAgent.ts)
- [`src/tools/AgentTool/forkSubagent.ts`](../src/tools/AgentTool/forkSubagent.ts)

### 4.1 `runAgent()` 才是真正的 agent 执行器

`AgentTool` 更像入口和路由层，真正跑 agent 的是 `runAgent()`。

从实现可以看到几个关键点：

- 它会初始化 agent-specific MCP servers
- 会构造子 agent 的 `ToolUseContext`
- 会执行 `executeSubagentStartHooks()`
- 会把 transcript 写到 sidechain
- 最后调用 `query()`

从源码引用可以看出这条链路：

```typescript
for await (const hookResult of executeSubagentStartHooks(...)) { ... }

const agentToolUseContext = createSubagentContext(toolUseContext, { ... })

void recordSidechainTranscript(initialMessages, agentId)
void writeAgentMetadata(agentId, { ... })

for await (const message of query({ ... })) { ... }
```

这说明普通 subagent 不是“主线程里跑个函数”，而是完整复用了 query runtime。

### 4.2 fork subagent 是特殊变体

[`src/tools/AgentTool/forkSubagent.ts`](../src/tools/AgentTool/forkSubagent.ts) 明确写了 fork 模式的规则：

- `subagent_type` 省略时触发 implicit fork
- child 继承 parent 的完整 conversation context
- child 继承 parent 的 rendered system prompt
- 所有 fork child 默认后台运行

核心注释已经把设计目的说得很明白：

```typescript
When enabled:
- Omitting `subagent_type` triggers an implicit fork
- the child inherits the parent's full conversation context and system prompt
- All agent spawns run in the background
```

### 4.3 为什么 fork 要保留父 prompt 的原始字节

这是一个很重要的技术点。

`FORK_AGENT` 的注释写到：

```typescript
The getSystemPrompt here is unused: the fork path passes
`override.systemPrompt` with the parent's already-rendered system prompt bytes ...
Reconstructing by re-calling getSystemPrompt() can diverge ... and bust the prompt cache
```

也就是说，fork child 不是重新生成 system prompt，而是直接拿父会话已经渲染好的 prompt 字节。

这样做的目的不是逻辑正确性，而是**prompt cache 命中稳定性**。

这表明 multi-agent 实现和 prompt/caching 基础设施是深度耦合的。

## 5. Coordinator Mode：把主线程变成调度器

相关实现：

- [`src/coordinator/coordinatorMode.ts`](../src/coordinator/coordinatorMode.ts)

### 5.1 coordinator 模式不是工具，而是模式切换

`isCoordinatorMode()` 的判断来自环境变量：

```typescript
export function isCoordinatorMode(): boolean {
  if (feature('COORDINATOR_MODE')) {
    return isEnvTruthy(process.env.CLAUDE_CODE_COORDINATOR_MODE)
  }
  return false
}
```

这意味着它不是一个普通 slash command，而是运行模式。

### 5.2 coordinator system prompt 直接重写主线程身份

它最关键的部分不是函数逻辑，而是 system prompt：

```typescript
You are Claude Code, an AI assistant that orchestrates software engineering tasks across multiple workers.
```

随后又给出一套明确操作规范：

- 用 `Agent` spawn worker
- 用 `SendMessage` 继续已有 worker
- 用 `TaskStop` 停止 worker
- 不要让一个 worker 去检查另一个 worker
- 要并行 launch 独立 worker
- 写操作按文件集串行，研究任务可并行

这说明 coordinator 不是“主 agent 自己决定多派几个 subagent”，而是 prompt 层已经把其角色切成 dispatcher。

### 5.3 worker 结果不是 assistant 消息，而是 task notification

同文件里定义了 worker 结果回流格式：

```xml
<task-notification>
<task-id>{agentId}</task-id>
<status>completed|failed|killed</status>
<summary>...</summary>
<result>...</result>
<usage>...</usage>
</task-notification>
```

这点很关键：

- worker 结果被包装成 user-role message
- coordinator 必须识别 `<task-notification>`
- coordinator 不能把它当成“普通用户在说话”

所以 coordinator-worker 模式本质上是事件驱动的。

### 5.4 coordinator 的工作流是显式分相的

源码把工作流直接定义成：

| 阶段 | 执行者 | 目的 |
|------|--------|------|
| Research | Workers | 找文件、理解问题 |
| Synthesis | Coordinator | 汇总研究结果、设计实现方案 |
| Implementation | Workers | 按 spec 实施修改 |
| Verification | Workers | 跑验证 |

这说明它不是完全自由分工，而是显式鼓励“研究并行、综合集中、实现分派、验证独立”。

## 6. Swarm 模式：真正的 team-based multi-agent

相关实现：

- [`src/tools/TeamCreateTool/TeamCreateTool.ts`](../src/tools/TeamCreateTool/TeamCreateTool.ts)
- [`src/tools/shared/spawnMultiAgent.ts`](../src/tools/shared/spawnMultiAgent.ts)

### 6.1 team 是一个显式实体

`TeamCreateTool` 会创建真正的 team file：

```typescript
const teamFile: TeamFile = {
  name: finalTeamName,
  description: _description,
  createdAt: Date.now(),
  leadAgentId,
  leadSessionId: getSessionId(),
  members: [
    {
      agentId: leadAgentId,
      name: TEAM_LEAD_NAME,
      agentType: leadAgentType,
      model: leadModel,
      ...
    },
  ],
}

await writeTeamFileAsync(finalTeamName, teamFile)
```

同时它还会：

- 重置并创建 task list 目录
- 设置 leader team name
- 更新 AppState 中的 `teamContext`

因此 swarm 不是“临时内存态”。

它至少有三份状态：

1. `team file`
2. `task list`
3. `AppState.teamContext`

### 6.2 `spawnTeammate()` 是 teammate 生成主入口

[`src/tools/shared/spawnMultiAgent.ts`](../src/tools/shared/spawnMultiAgent.ts) 暴露了：

```typescript
export async function spawnTeammate(
  config: SpawnTeammateConfig,
  context: ToolUseContext,
): Promise<{ data: SpawnOutput }> {
  return handleSpawn(config, context)
}
```

这说明 teammate spawn 已经被抽成共享模块，既能被专门的 team 工具调用，也能被 `AgentTool` 复用。

从工程上看，这是把“spawn multi-agent”升级成平台能力，而不是局部逻辑。

## 7. in-process teammate：同进程多 agent

相关实现：

- [`src/utils/swarm/spawnInProcess.ts`](../src/utils/swarm/spawnInProcess.ts)
- [`src/tasks/InProcessTeammateTask/InProcessTeammateTask.tsx`](../src/tasks/InProcessTeammateTask/InProcessTeammateTask.tsx)
- [`src/utils/swarm/inProcessRunner.ts`](../src/utils/swarm/inProcessRunner.ts)

### 7.1 它不是开新进程，而是用 `AsyncLocalStorage` 隔离上下文

`spawnInProcess.ts` 文件头就写得很明确：

```typescript
Creates and registers an in-process teammate task.
Unlike process-based teammates (tmux/iTerm2), in-process teammates
run in the same Node.js process using AsyncLocalStorage for context isolation.
```

这是 Claude Code multi-agent 实现里非常有特色的一点。

不是所有 teammate 都要 tmux pane，也不是都得起子进程。

系统支持：

- 同一进程里并发多个 teammate
- 每个 teammate 有独立 identity / context / abortController
- UI 层把它们当成独立 task 展示

### 7.2 spawn 时注册的是一个独立 task state

`spawnInProcessTeammate()` 的核心逻辑可以概括为：

```text
生成 agentId / taskId
  -> 创建 abortController
  -> 创建 teammate identity
  -> 创建 teammateContext
  -> 构造 InProcessTeammateTaskState
  -> registerTask(taskState)
```

源码片段：

```typescript
const agentId = formatAgentId(name, teamName)
const taskId = generateTaskId('in_process_teammate')

const teammateContext = createTeammateContext({ ... })

const taskState: InProcessTeammateTaskState = {
  type: 'in_process_teammate',
  status: 'running',
  identity,
  prompt,
  model,
  abortController,
  pendingUserMessages: [],
  messages: [],
}

registerTask(taskState, setAppState)
```

说明它在调度系统里的地位和 shell task、local agent task 是同级的。

### 7.3 teammate 自己也有生命周期与消息队列

`InProcessTeammateTask.tsx` 提供了几类关键操作：

- `requestTeammateShutdown()`
- `appendTeammateMessage()`
- `injectUserMessageToTeammate()`
- `findTeammateTaskByAgentId()`

这说明 teammate 不只是一次性执行器，而是一个可持续交互对象：

- 可以继续发消息
- 可以切换到 transcript view
- 可以 shutdown
- 可以从 `agentId` 反查 task

## 8. 通信机制：mailbox + direct resume 双轨制

相关实现：

- [`src/utils/teammateMailbox.ts`](../src/utils/teammateMailbox.ts)
- [`src/tools/SendMessageTool/SendMessageTool.ts`](../src/tools/SendMessageTool/SendMessageTool.ts)
- [`src/hooks/useInboxPoller.ts`](../src/hooks/useInboxPoller.ts)

Claude Code 里的 agent 间通信并不是单一路径，而是至少有两条：

1. mailbox 文件通信
2. 本地 task / transcript resume

### 8.1 mailbox：swarm 的文件式 inbox

`teammateMailbox.ts` 文件头直接写明：

```typescript
Teammate Mailbox - File-based messaging system for agent swarms
Each teammate has an inbox file at .claude/teams/{team_name}/inboxes/{agent_name}.json
```

它提供的核心能力是：

- `readMailbox()`
- `readUnreadMessages()`
- `writeToMailbox()`
- `markMessageAsReadByIndex()`

其中 `writeToMailbox()` 还带锁文件：

```typescript
release = await lockfile.lock(inboxPath, {
  lockfilePath: lockFilePath,
  ...LOCK_OPTIONS,
})
```

这说明 mailbox 不是玩具实现，而是考虑了多 agent 并发写入。

### 8.2 `SendMessageTool` 既能发给 teammate，也能继续已有 subagent

`SendMessageTool` 有两种重要路由：

第一种，继续已有 subagent：

```typescript
const registered = appState.agentNameRegistry.get(input.to)
const agentId = registered ?? toAgentId(input.to)
...
if (task.status === 'running') {
  queuePendingMessage(agentId, input.message, ...)
}
...
const result = await resumeAgentBackground({
  agentId,
  prompt: input.message,
  ...
})
```

第二种，发到 swarm mailbox：

```typescript
await writeToMailbox(
  recipientName,
  {
    from: senderName,
    text: content,
    summary,
    timestamp: new Date().toISOString(),
    color: senderColor,
  },
  teamName,
)
```

这说明 `SendMessage` 并不是“统一消息 API”，而是一个**消息路由器**：

- 如果目标是本地 agentId，就走本地队列或 resume
- 如果目标是 teammate，就走 mailbox
- 如果目标是 `*`，还支持 broadcast

### 8.3 `useInboxPoller()` 负责把 unread mailbox 消息回灌到执行流

`useInboxPoller()` 会周期性：

```typescript
const unread = await readUnreadMessages(agentName, teamName)
```

然后按消息类型拆分：

- permission request
- permission response
- shutdown request / approval
- plan approval request / response
- regular teammate messages

这说明 mailbox 传的不是纯文本，而是 agent 协作协议消息。

## 9. 权限机制：leader 为 teammate 兜底

相关实现：

- [`src/utils/swarm/leaderPermissionBridge.ts`](../src/utils/swarm/leaderPermissionBridge.ts)
- [`src/utils/swarm/inProcessRunner.ts`](../src/utils/swarm/inProcessRunner.ts)
- [`src/hooks/useInboxPoller.ts`](../src/hooks/useInboxPoller.ts)

### 9.1 in-process teammate 不是自己弹权限框

这点很关键。

`leaderPermissionBridge.ts` 提供了 module-level bridge：

```typescript
let registeredSetter: SetToolUseConfirmQueueFn | null = null
let registeredPermissionContextSetter: SetToolPermissionContextFn | null = null
```

它允许 REPL 把 leader 的权限 UI setter 暴露出来，供 teammate 使用。

### 9.2 teammate 权限请求会优先借用 leader 的标准权限弹窗

`inProcessRunner.ts` 里 `createInProcessCanUseTool()` 的逻辑很清楚：

```typescript
const setToolUseConfirmQueue = getLeaderToolUseConfirmQueue()

if (setToolUseConfirmQueue) {
  return new Promise<PermissionDecision>(resolve => {
    setToolUseConfirmQueue(queue => [
      ...queue,
      {
        ...,
        workerBadge: identity.color
          ? { name: identity.agentName, color: identity.color }
          : undefined,
      },
    ])
  })
}
```

也就是说：

- teammate 自己不拥有独立权限 UI
- teammate 的 ask 权限会回到 leader 的 ToolUseConfirmQueue
- UI 上会带 `workerBadge`

这是一种非常务实的实现：

- 避免多份权限 UI
- 保持用户对整个 swarm 的统一控制
- 同时又能知道是谁在请求权限

### 9.3 leader bridge 不可用时，退回 mailbox 权限同步

同一函数注释也说明，如果 bridge 不可用，会退回 mailbox 路径：

- 发 permission request 给 leader inbox
- 等 leader response
- 再应用回 teammate 上下文

这说明权限机制也做了双轨容灾。

## 10. 任务协作平面：不是聊天协作，而是 task list 协作

相关实现：

- [`src/tools/TaskCreateTool/TaskCreateTool.ts`](../src/tools/TaskCreateTool/TaskCreateTool.ts)
- [`src/utils/swarm/inProcessRunner.ts`](../src/utils/swarm/inProcessRunner.ts)
- [`src/tools/TaskStopTool/TaskStopTool.ts`](../src/tools/TaskStopTool/TaskStopTool.ts)

### 10.1 team 创建时就会绑定 task list

`TeamCreateTool` 里很关键的一段：

```typescript
const taskListId = sanitizeName(finalTeamName)
await resetTaskList(taskListId)
await ensureTasksDir(taskListId)
setLeaderTeamName(sanitizeName(finalTeamName))
```

也就是说 team 一建立，就自动绑定了一套共享 task list。

### 10.2 teammate 会主动 claim task

`inProcessRunner.ts` 中有一个关键函数 `tryClaimNextTask()`：

```typescript
const tasks = await listTasks(taskListId)
const availableTask = findAvailableTask(tasks)
...
const result = await claimTask(taskListId, availableTask.id, agentName)
...
await updateTask(taskListId, availableTask.id, { status: 'in_progress' })
```

这意味着 teammate 协作不只是“互相发消息”，而是：

- 有共享任务池
- agent 可以 claim 未分配任务
- claim 后立刻更新任务状态

这是一个真正的 work queue 设计。

### 10.3 teammate 的工具池被强制注入 task 协作工具

`inProcessRunner.ts` 还会把协作必需工具强行塞进 teammate 工具池：

```typescript
tools: agentDefinition?.tools
  ? [
      ...new Set([
        ...agentDefinition.tools,
        SEND_MESSAGE_TOOL_NAME,
        TEAM_CREATE_TOOL_NAME,
        TEAM_DELETE_TOOL_NAME,
        TASK_CREATE_TOOL_NAME,
        TASK_GET_TOOL_NAME,
        TASK_LIST_TOOL_NAME,
        TASK_UPDATE_TOOL_NAME,
      ]),
    ]
  : ['*']
```

这说明 teammate agent 即便是自定义 agent，也会被注入一组 swarm-essential tools。

换句话说，swarm 协作能力属于 runtime contract，不完全由 agent frontmatter 自由决定。

### 10.4 停止任务也是统一平面

`TaskStopTool` 则提供了统一停止入口：

- 输入 `task_id`
- 校验 task 是否存在且仍在 running
- 调 `stopTask()`

这保证了多 agent 并发跑起来后，系统还有统一 kill switch。

## 11. Multi-Agent 主链路流程图

下面给出一个更接近源码实现的主流程图。

```text
用户 / 主线程
   |
   | AgentTool(description, prompt, subagent_type, name?, team_name?)
   v
AgentTool.call()
   |
   +-- if team_name && name ------------------------------+
   |                                                     |
   |                                                     v
   |                                           spawnTeammate()
   |                                                     |
   |                          +--------------------------+-----------------------+
   |                          |                                                  |
   |                          v                                                  v
   |                 in-process teammate                                 tmux / iTerm2 teammate
   |                          |                                                  |
   |                          v                                                  v
   |              spawnInProcessTeammate()                              pane/backend spawn
   |                          |                                                  |
   |                          v                                                  v
   |                InProcessTeammateTask                             inbox / backend / team file
   |                          |
   |                          v
   |                 inProcessRunner -> runAgent()
   |
   +-- else ----------------------------------------------------------+
                                                                      |
                                                                      v
                                                             runAgent()
                                                                      |
                                                                      v
                                                                    query()
                                                                      |
                                                                      v
                                                        task-notification / transcript
```

再看 swarm 内部协作流程：

```text
TeamCreate
  -> 创建 team file
  -> 创建 task list
  -> 建立 leader teamContext

teammate 运行
  -> claimTask()
  -> 执行任务
  -> SendMessage / writeToMailbox
  -> leader inbox poller 收到消息
  -> leader 决策 / 权限批准 / 继续派工
```

## 12. 伪代码：核心调度逻辑可以怎么理解

### 12.1 `AgentTool` 分流逻辑

```text
function agentToolCall(input):
    resolve permission mode
    resolve teamName

    if current process is teammate and input also wants to spawn teammate:
        reject

    if current process is in-process teammate and asks for background spawn:
        reject

    if input has teamName and name:
        return spawnTeammate(input)

    else:
        return runAgent(input)
```

### 12.2 in-process teammate 权限桥接逻辑

```text
function canUseToolAsTeammate(toolRequest):
    result = hasPermissionsToUseTool(toolRequest)

    if result is allow/deny:
        return result

    if leader permission UI bridge exists:
        enqueue request into leader ToolUseConfirmQueue
        wait for decision
        return decision

    else:
        send permission request via mailbox
        wait for mailbox response
        apply response
        return decision
```

### 12.3 swarm 任务协作逻辑

```text
function teammateLoop():
    while alive:
        msg = nextPendingUserMessage() or tryClaimNextTask()
        if no msg:
            go idle
            wait
        else:
            runAgent(msg)
            update progress
            if done:
                notify leader
```

## 13. 这套 multi-agent 实现的优点与代价

### 13.1 优点

1. **层级清楚**
   普通 subagent、coordinator、swarm teammate 三层能力不是混成一团，而是各有职责。

2. **复用主执行内核**
   大多数 agent 最终仍走 `runAgent()` / `query()`，不会出现多套推理引擎。

3. **通信机制够实用**
   通过 mailbox、resume、task notification、task list，把协作做成了能落地的工程系统。

4. **权限有统一入口**
   teammate 不会偷偷绕过权限体系，而是回流到 leader。

5. **任务视角明确**
   team 不是纯聊天机器人群，而是带 task list 的工作队列。

### 13.2 代价

1. **系统复杂度很高**
   多 agent 已经横跨工具层、任务层、UI 层、权限层、上下文层。

2. **状态面很多**
   transcript、task state、team file、mailbox、AppState、permission queue 都可能参与同一条链路。

3. **调试成本高**
   问题可能出在 spawn、resume、mailbox、inbox poller、permission bridge 任意一层。

4. **模式很多**
   同样叫“agent”，但 subagent、worker、teammate、fork child、coordinator 语义并不相同。

## 14. 本章小结

Claude Code 源码中的 multi-agent 不是一个边缘特性，而是完整的系统能力。

从源码可以看出：

- `AgentTool` 是统一入口
- `runAgent()` 是统一执行器
- `coordinatorMode` 把主线程改造成调度器
- `spawnTeammate()` 和 swarm 目录把 team 协作做成显式实体
- `teammateMailbox`、`useInboxPoller`、`leaderPermissionBridge`、task list 则补齐了 agent 间通信、权限和协作平面

因此更准确的结论是：

**Claude Code 并不是“支持多 agent”，而是已经实现了一套分层的 multi-agent runtime。**

它最重要的工程特点有三点：

1. subagent 与 swarm teammate 并存
2. coordinator 通过 prompt 明确把自己变成 orchestrator
3. 团队协作不仅靠消息，还靠任务、权限和持久状态

这也是为什么它的 multi-agent 实现，明显超出了“后台起几个子任务”的级别。
