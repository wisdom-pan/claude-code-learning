# 第一章：软件架构与程序入口

[返回总目录](../README.md)

---

## 1. 导读与结论

本章回答两个问题：

1. 这个项目从哪里启动，主链路如何流转。
2. 它的整体架构是怎样分层的，各层分别承担什么职责。

**结论先行**：这个项目不是单纯的命令行聊天程序，而是一套本地 agent 平台。它采用"CLI 引导层 → TUI/REPL 交互层 → Query/Agent 执行内核 → Tool/Permission 层 → Memory/Persistence 层 → MCP/Remote/Swarm 扩展层"的六层分层结构。

---

## 2. 总体结构图

### 2.1 分层架构图

```text
+------------------------------+
| CLI 引导层                   |
| entrypoints/cli.tsx          |
| main.tsx                     |
+------------------------------+
               |
               v
+------------------------------+
| 初始化层                     |
| entrypoints/init.ts          |
| setup.ts                     |
+------------------------------+
      |                  |
      v                  v
+------------------+   +------------------------------+
| 控制面 / 命令层  |   | TUI / REPL 层                |
| commands.ts      |-->| replLauncher.tsx / REPL.tsx  |
| slash/menu       |   +------------------------------+
+------------------+                  |
                                      v
                         +------------------------------+
                         | 执行内核                     |
                         | query.ts / QueryEngine.ts    |
                         +------------------------------+
                           |            |            |
                           v            v            v
                 +---------------+ +-----------------+ +------------------+
                 | Tool/Perm 层  | | Memory/Persist  | | 扩展层           |
                 | Tool.ts       | | sessionStorage  | | MCP/Plugin/      |
                 | orchestration | | memdir/SM       | | Remote/Swarm     |
                 +---------------+ +-----------------+ +------------------+
```

### 2.2 默认交互主链路

```text
entrypoints/cli.tsx
  -> main.tsx
  -> init.ts + setup.ts
  -> launchRepl()
  -> App + REPL
  -> PromptInput / slash command / footer 菜单
  -> query()
     -> services/api/claude.ts
     -> runTools() / StreamingToolExecutor
     -> sessionStorage / SessionMemory / compact / hooks
     -> 返回到 query 主循环
```

---

## 3. 程序入口

### 3.1 轻量入口：`cli.tsx` 做早期分流

**文件**：[`src/entrypoints/cli.tsx`](../src/entrypoints/cli.tsx)

这一层是"入口分流器"，不是完整应用。职责是：识别快路径并提前退出，避免启动完整应用。

**伪代码（基于源文件结构）**：

```typescript
// src/entrypoints/cli.tsx 结构伪代码
async function main() {
  const argv = parseArgs(process.argv)

  // 快路径分流 —— 命中则执行并退出，不进入 main.tsx
  if (argv['--version']) {
    console.log(version); process.exit(0)
  }
  if (argv['--dump-system-prompt']) {
    await dumpSystemPrompt(); process.exit(0)
  }
  if (argv['remote-control']) {
    return runRemoteControl(argv)
  }
  if (argv['daemon'] || argv['bg'] || argv['runner']) {
    return runDaemonOrBackground(argv)
  }

  // 兜底：进入完整主启动器
  await import('./main.tsx').then(m => m.main(argv))
}
```

这种设计的好处：普通快速命令不需要加载整个应用（React、Ink、MCP 等），启动速度快且副作用少。

---

### 3.2 主启动器：`main.tsx` 是系统编排中心

**文件**：[`src/main.tsx`](../src/main.tsx)

`main.tsx` 实际上是 **总控入口**，负责所有主路径初始化。从其 import 列表可以直接推断职责范围（以下是源码 import 的精简摘录）：

```typescript
// src/main.tsx —— 关键 import 反映职责范围
import { init, initializeTelemetryAfterTrust } from './entrypoints/init.js'
import { launchRepl } from './replLauncher.js'
import { fetchBootstrapData } from './services/api/bootstrap.js'
import { getMcpToolsCommandsAndResources } from './services/mcp/client.js'
import { getTools } from './tools.js'
import { getAgentDefinitionsWithOverrides } from './tools/AgentTool/loadAgentsDir.js'
import { initBundledSkills } from './skills/bundled/index.js'
import { showSetupScreens, exitWithError } from './interactiveHelpers.js'
import { settingsChangeDetector } from './utils/settings/changeDetector.js'
// ... 还有约 80 个 import
```

**主流程伪代码**：

```typescript
// src/main.tsx 主流程（伪代码）
export async function main(argv: ParsedArgs) {
  // 1. 早期初始化（不依赖 trust）
  await init(argv)

  // 2. 解析 CLI 参数 -> 确定 permission mode、模型、工具等
  const permissionMode = initialPermissionModeFromCLI(argv)
  const model = resolveModel(argv)

  // 3. 条件分支：选择执行路径
  if (argv['--print'] || argv['--sdk']) {
    return runHeadless(argv, model, permissionMode)
  }
  if (argv['bridge']) {
    return runBridge(argv)
  }
  if (argv['remote']) {
    return runRemote(argv)
  }

  // 4. 默认路径：初始化完整运行时后进入 REPL
  const bootstrap = await fetchBootstrapData()          // 拉取远端配置
  const mcpTools  = await getMcpToolsCommandsAndResources() // 连接 MCP
  const tools     = getTools(permissionContext)          // 组装工具池
  const skills    = initBundledSkills()                  // 加载内置技能
  const agents    = getAgentDefinitionsWithOverrides()   // 加载 agent 定义

  await initializeTelemetryAfterTrust()                 // trust 后才启动 telemetry

  settingsChangeDetector.start()                        // 监听配置文件热更新

  // 5. 进入 REPL
  await launchRepl(root, appProps, replProps, renderAndRun)
}
```

---

### 3.3 初始化层：`init.ts` 与 `setup.ts` 职责分离

项目把初始化分成逻辑独立的两部分：

**`init.ts`**：[`src/entrypoints/init.ts`](../src/entrypoints/init.ts) — **逻辑初始化**

```typescript
// src/entrypoints/init.ts 结构伪代码
export async function init(argv) {
  applySafeEnvironmentVariables()    // 只应用安全的 env var（trust 前）
  initializeCertificates()           // 证书与 HTTPS 代理
  initializeHttpAgent()              // HTTP agent 配置
  initTelemetrySkeleton()            // 注册 telemetry sink，但不发事件
  // Note: initializeTelemetryAfterTrust() 在 trust 建立后由 main.tsx 调用
}

export async function initializeTelemetryAfterTrust() {
  applyFullEnvironmentVariables()    // trust 通过后才应用全部 env var
  attachAnalyticsSink()              // 开始处理 telemetry 事件队列
}
```

**`setup.ts`**：[`src/setup.ts`](../src/setup.ts) — **运行环境初始化**

```typescript
// src/setup.ts 结构伪代码
export async function setup(argv, permissionContext) {
  setCwd(resolvedWorkingDir)         // 设置工作目录
  startHooksWatcher()                // 监听 hooks 配置变化
  initWorktreeSnapshot()             // tmux/worktree 快照
  initSessionMemory()                // 初始化 session memory 系统
  startTeamMemoryWatcher()           // 启动 team memory 文件监听
}
```

**设计意图**：trust 建立前只应用安全的环境变量，防止"配置文件/includes 本身是攻击面"的风险（详见 `06-extra-findings.md` 第 2 节）。

---

## 4. 运行形态

系统支持多种运行形态，共用同一套执行内核。

### 4.1 默认 REPL/TUI 形态

关键函数：

```typescript
// src/replLauncher.tsx
export async function launchRepl(
  root: Root,
  appProps: AppWrapperProps,
  replProps: REPLProps,
  renderAndRun: (root: Root, element: React.ReactNode) => Promise<void>
): Promise<void>
```

这个函数动态加载 `App + REPL` 组件后启动 Ink 渲染循环。  
`REPL.tsx` 维护完整的 `AppState`（消息、输入框、权限弹窗、任务、远程状态），用户输入最终通过 `query()` 进入执行内核。

### 4.2 Headless / SDK 形态

关键文件：
- [`src/QueryEngine.ts`](../src/QueryEngine.ts) — 管跨多轮会话状态
- [`src/query.ts`](../src/query.ts) — 管单次 query 循环

`QueryEngine` 是无 UI 的执行引擎，它能被 SDK 直接实例化，不依赖 Ink/React 渲染：

```typescript
// src/QueryEngine.ts 结构伪代码
export class QueryEngine {
  async query(userInput: string): AsyncGenerator<StreamEvent> {
    // 1. 组装 messages + system prompt
    // 2. 调用 claude.ts API
    // 3. 处理 tool_use / tool_result
    // 4. yield 事件给调用方
  }
}
```

### 4.3 MCP Server 形态

**文件**：[`src/entrypoints/mcp.ts`](../src/entrypoints/mcp.ts)

```typescript
// src/entrypoints/mcp.ts 结构伪代码
async function startMcpServer() {
  const server = new McpServer({ name: 'claude-code', version })
  // 把内部 Tool（FileEdit, FileRead, Bash...）重新包装为 MCP tool schema
  for (const tool of getInternalTools()) {
    server.registerTool(tool.name, tool.inputSchema, wrapToolAsMcpHandler(tool))
  }
  await server.connect(new StdioServerTransport())
}
```

这条路径让 Claude Code **既能作为 MCP client 消费外部能力，也能作为 MCP server 对外暴露能力**。

### 4.4 Remote / Bridge 形态

**文件**：[`src/bridge/bridgeMain.ts`](../src/bridge/bridgeMain.ts)

```typescript
// src/bridge/bridgeMain.ts 结构伪代码
async function runBridge(config: BridgeConfig) {
  const ws = connectToRemoteOrchestrator(config.orchestratorUrl)
  ws.on('session-start', (session) => spawnLocalAgent(session))
  ws.on('heartbeat',     ()        => sendHeartbeat())
  ws.on('disconnect',    ()        => scheduleReconnect())
}
```

这使 Claude Code 从"本地终端工具"扩展成"本地与远程混合 agent 平台"。

---

## 5. 架构分层详解

### 5.1 命令与模式分发层

**文件**：[`src/commands.ts`](../src/commands.ts)

```typescript
// src/commands.ts 结构伪代码
// 内部专属命令（构建时从外部产物中剪除）
const INTERNAL_ONLY_COMMANDS = [
  'backfillSessions', 'bughunter', 'commit', 'teleport', 'antTrace', // ...
]

export function getCommands(options: CommandOptions): Command[] {
  const baseCommands = [
    compactCommand, configCommand, doctorCommand, helpCommand, // ...内建命令
    ...(feature('VOICE_MODE')   ? [voiceCommand]   : []),     // 编译期开关
    ...(feature('BUDDY')        ? [buddyCommand]   : []),
    ...(process.env.USER_TYPE === 'ant' ? INTERNAL_ONLY_COMMANDS.map(loadCmd) : []),
  ]
  // 依据 permissionContext / feature gates / 环境过滤
  return baseCommands.filter(cmd => cmd.isEnabled(options))
}
```

### 5.2 TUI 与状态层

**文件**：[`src/screens/REPL.tsx`](../src/screens/REPL.tsx)，[`src/state/AppStateStore.ts`](../src/state/AppStateStore.ts)

`AppState` 是系统的共享状态总线，不是简单的 UI 状态：

```typescript
// src/state/AppState.ts 类型结构（简化）
type AppState = {
  messages:              Message[]
  toolPermissionContext: ToolPermissionContext
  mainLoopModel:         string
  mcpClients:            McpClient[]
  plugins:               Plugin[]
  agentRegistry:         AgentDefinition[]
  notifications:         NotificationQueue
  remoteBridgeState:     BridgeState | null
  // ...还有约 20 个字段
}
```

### 5.3 Query / Agent 执行内核

**文件**：[`src/query.ts`](../src/query.ts)，[`src/QueryEngine.ts`](../src/QueryEngine.ts)

`query.ts` 是系统的核心主循环，包含工具调用的完整闭环：

```typescript
// src/query.ts —— 主循环骨架（伪代码）
export async function* query(
  userMessages: Message[],
  systemPrompt: SystemPrompt,
  toolUseContext: ToolUseContext,
  deps: QueryDeps,
): AsyncGenerator<StreamEvent> {
  let messages = userMessages

  while (true) {
    // 1. 组装 context（memory 注入发生在这里）
    const apiMessages = normalizeMessagesForAPI(messages)

    // 2. 调用 Claude API，流式接收
    for await (const event of deps.claudeApi.stream(apiMessages, systemPrompt)) {
      yield event
    }

    // 3. 提取模型输出的 tool_use 列表
    const toolUseBlocks = extractToolUseBlocks(messages)
    if (toolUseBlocks.length === 0) break  // 无工具调用 -> 结束

    // 4. 执行工具（并发 / 串行由 partitionToolCalls 决定）
    const toolResults = []
    for await (const update of runTools(toolUseBlocks, ...)) {
      yield update  // 实时 yield 给 UI
      toolResults.push(update.message)
    }

    // 5. 把工具结果追加到 messages -> 进入下一轮
    messages = [...messages, ...toolResults]

    // 6. compact 检查、hook 执行
    await executePostSamplingHooks(messages, toolUseContext)
    if (shouldCompact(messages)) await compact(messages, toolUseContext)
  }
}
```

### 5.4 Tool 与 Permission 层

**文件**：[`src/Tool.ts`](../src/Tool.ts)，[`src/services/tools/toolOrchestration.ts`](../src/services/tools/toolOrchestration.ts)

`runTools()` 是工具调度核心，其 `partitionToolCalls()` 决定并发与串行分组：

```typescript
// src/services/tools/toolOrchestration.ts（真实源码节选）
export async function* runTools(
  toolUseMessages: ToolUseBlock[],
  assistantMessages: AssistantMessage[],
  canUseTool: CanUseToolFn,
  toolUseContext: ToolUseContext,
): AsyncGenerator<MessageUpdate, void> {
  let currentContext = toolUseContext
  for (const { isConcurrencySafe, blocks } of partitionToolCalls(
    toolUseMessages,
    currentContext,
  )) {
    if (isConcurrencySafe) {
      // 并发批次：先收集 contextModifier，批次完再按序应用
      for await (const update of runToolsConcurrently(blocks, ...)) { yield update }
    } else {
      // 串行批次：每个工具必须等上一个完成
      for await (const update of runToolsSerially(blocks, ...)) { yield update }
    }
  }
}

function partitionToolCalls(toolUseMessages: ToolUseBlock[], ctx: ToolUseContext): Batch[] {
  return toolUseMessages.reduce((acc: Batch[], toolUse) => {
    const tool = findToolByName(ctx.options.tools, toolUse.name)
    const isConcurrencySafe = Boolean(tool?.isConcurrencySafe(parsedInput.data))
    // 若上一批次也是并发安全的，就合入同一批次
    if (isConcurrencySafe && acc[acc.length - 1]?.isConcurrencySafe) {
      acc[acc.length - 1]!.blocks.push(toolUse)
    } else {
      acc.push({ isConcurrencySafe, blocks: [toolUse] })
    }
    return acc
  }, [])
}
```

### 5.5 Persistence / Memory 层

**文件**：[`src/utils/sessionStorage.ts`](../src/utils/sessionStorage.ts)，[`src/memdir/memdir.ts`](../src/memdir/memdir.ts)，[`src/services/SessionMemory/sessionMemory.ts`](../src/services/SessionMemory/sessionMemory.ts)

Memory 系统的核心构建函数（见第四章详细分析）：

```typescript
// src/memdir/memdir.ts（真实源码节选）
export const ENTRYPOINT_NAME    = 'MEMORY.md'
export const MAX_ENTRYPOINT_LINES = 200
export const MAX_ENTRYPOINT_BYTES = 25_000

export function buildMemoryPrompt(params: {
  displayName: string
  memoryDir:   string
  extraGuidelines?: string[]
}): string {
  const entrypoint = params.memoryDir + ENTRYPOINT_NAME
  const raw = fs.readFileSync(entrypoint, { encoding: 'utf-8' })  // 同步读取
  const t   = truncateEntrypointContent(raw)                       // 硬截断保护

  const lines = buildMemoryLines(params.displayName, params.memoryDir, ...)
  lines.push(`## ${ENTRYPOINT_NAME}`, '', t.content)
  return lines.join('\n')
}
```

### 5.6 MCP / Plugin / Remote / Swarm 扩展层

**文件**：[`src/services/mcp/client.ts`](../src/services/mcp/client.ts)，[`src/utils/swarm/backends/registry.ts`](../src/utils/swarm/backends/registry.ts)

MCP 工具命名规则：

```typescript
// src/services/mcp/mcpStringUtils.ts
export function buildMcpToolName(serverName: string, toolName: string): string {
  return `mcp__${serverName}__${toolName}`
  // 例：mcp__filesystem__read_file
  //     mcp__puppeteer__screenshot
}
```

Swarm（多 agent）的 backend 注册表是可扩展的：

```typescript
// src/utils/swarm/backends/registry.ts 结构伪代码
const BACKEND_REGISTRY: Record<string, TeammateBackend> = {
  'in-process': InProcessBackend,
  'tmux':       TmuxBackend,
  'iterm2':     ITerm2PaneBackend,
}

export function spawnTeammate(config: TeammateConfig): TeammateHandle {
  const Backend = BACKEND_REGISTRY[config.backendType]
  return new Backend(config).spawn()
}
```

---

## 6. 典型完整链路

把所有环节串起来：

```text
1. 进程启动
   entrypoints/cli.tsx -> 快路径分流 OR main.tsx

2. 初始化
   init.ts -> trust 前初始化
   setup.ts -> 环境、CWD、hooks、memory 启动

3. 能力装配
   getCommands()          -> 命令系统
   getTools()             -> 内建工具池
   getMcpToolsAndResources() -> MCP 工具
   getAgentDefinitions()  -> 自定义 agent
   initBundledSkills()    -> 技能系统

4. REPL 启动
   launchRepl() -> App + REPL.tsx -> PromptInput

5. 用户输入
   query.ts -> normalizeMessagesForAPI() -> claude.ts API

6. 工具执行
   runTools() -> partitionToolCalls() -> runToolsConcurrently / runToolsSerially
   -> toolExecution.ts -> schema 校验 -> 权限 -> tool.call()

7. 结果回流
   tool_result -> messages -> 下一轮 query -> (循环)

8. 会话管理
   sessionStorage -> transcript 落盘
   shouldExtractMemory() -> runForkedAgent() -> Session Memory 更新
   compact() -> context 压缩
```

---

## 7. 本章小结

从架构上，这个项目有三个明确特征：

1. **多入口系统**：cli.tsx 做早期分流，main.tsx 是真正编排中心，两者职责分离清晰。
2. **分层解耦**：UI、执行内核、工具层、memory 层、扩展层各自独立，query.ts 是连接它们的主协调者。
3. **平台化设计**：不只是"聊天工具加壳"，而是一套有独立执行内核、权限系统、memory 体系和多 agent runtime 的本地 agent 平台。
