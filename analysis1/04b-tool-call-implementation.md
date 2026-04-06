# 第四章补充：Tool Call 机制实现细节

[返回总目录](../README.md)

---

## 导读

第三部分如果只讲 memory，还不够完整。这个项目的另一个核心能力，是把“模型发起 tool_use”变成一条工程上可控、可并发、可审计、可回流到下一轮对话的执行链。

这一章重点解释：

1. tool 在代码里是怎么定义的
2. 工具池是怎么组装出来的
3. tool_use 到底怎么执行
4. 权限、Hook、并发调度、tool_result 是怎么衔接的
5. query 主循环如何把工具结果回流到下一轮模型调用

**主要相关源码**：
- [`src/Tool.ts`](../src/Tool.ts)
- [`src/tools.ts`](../src/tools.ts)
- [`src/services/tools/toolOrchestration.ts`](../src/services/tools/toolOrchestration.ts)
- [`src/services/tools/StreamingToolExecutor.ts`](../src/services/tools/StreamingToolExecutor.ts)
- [`src/services/tools/toolExecution.ts`](../src/services/tools/toolExecution.ts)
- [`src/query.ts`](../src/query.ts)

> **写给新手的提示**：本章将深入 Claude Code 这一 Agent 平台的执行引擎。我们会把原本黑盒的“大模型工具调用”拆解为清晰的流水线，并结合具体的源代码向你展示它是如何被实现为一套严谨的系统设计的。

---

## 第一节：总链路：从 `tool_use` 到 `tool_result`

**相关源码**：
- [`src/query.ts`](../src/query.ts)
- [`src/services/tools/toolExecution.ts`](../src/services/tools/toolExecution.ts)

先看完整链路：

```text
模型输出 assistant message
  │
  ▼ 含一个或多个 tool_use blocks
  │
query.ts 收集这些 tool_use
  │
  ▼ 选择 streaming executor 或普通 runTools()
  │
toolOrchestration.ts 按并发安全性分批
  │
  ▼
toolExecution.ts 对每个 tool_use 逐个执行
     ├─ 1. schema 校验
     ├─ 2. validateInput
     ├─ 3. pre-tool hooks
     ├─ 4. permission / ask / deny
     ├─ 5. tool.call()
     └─ 6. 生成 tool_result / attachment / progress
  │
  ▼ 把结果规范化为 user-side tool_result messages
  │
下一轮 API 调用时把这些结果带回去 (回流 transcript)
```

**最关键的一点是**：tool call 并非“模型直接调函数”，而是被拆成了多层 Runtime Pipeline。

---

## 第二节：`Tool` 抽象：工具统一协议

**相关源码**：
- [`src/Tool.ts`](../src/Tool.ts)

### 2.1 `Tool` 接口包含什么

**真实源码** ([`src/Tool.ts:362`](../src/Tool.ts)):

```typescript
export type Tool<
  Input extends AnyObject = AnyObject,
  Output = unknown,
  P extends ToolProgressData = ToolProgressData,
> = {
  aliases?: string[]
  searchHint?: string
  call(
    args: z.infer<Input>,
    context: ToolUseContext,
    canUseTool: CanUseToolFn,
    parentMessage: AssistantMessage,
    onProgress?: ToolCallProgress<P>,
  ): Promise<ToolResult<Output>>
  // ... 其他属性和方法 ...
}
```

在 `src/Tool.ts` 中，`Tool` 接口远不止 `call()` 一个函数。它至少覆盖这些方面的运行时协议：

- **能力描述**: `name`, `description()`, `prompt()`, `searchHint`
- **输入输出**: `inputSchema`, `outputSchema`, `mapToolResultToToolResultBlockParam()`
- **安全属性**: `isConcurrencySafe()`, `isReadOnly()`, `isDestructive()`, `checkPermissions()`, `preparePermissionMatcher()`
- **语义校验**: `validateInput()`
- **UI 表现**: `renderToolUseMessage()`, `renderToolResultMessage()`, `renderToolUseRejectedMessage()`, `renderToolUseErrorMessage()`
- **运行控制**: `interruptBehavior()`, `requiresUserInteraction()`, `backfillObservableInput()`

**新手解读**：这说明在该系统里的 Tool 不是简单的“函数映射”，而是一种标准化的**运行时协议对象**。它从代码层面强迫每个工具编写者考虑并发、安全、呈现形式和中断补偿。

### 2.2 `buildTool()` 的默认值策略

**真实源码** ([`src/Tool.ts:757`](../src/Tool.ts)):

```typescript
const TOOL_DEFAULTS = {
  isEnabled: () => true,
  isConcurrencySafe: (_input?: unknown) => false,
  isReadOnly: (_input?: unknown) => false,
  isDestructive: (_input?: unknown) => false,
  checkPermissions: (
    input: { [key: string]: unknown },
    _ctx?: ToolUseContext,
  ): Promise<PermissionResult> =>
    Promise.resolve({ behavior: 'allow', updatedInput: input }),
  toAutoClassifierInput: (_input?: unknown) => '',
  userFacingName: (_input?: unknown) => '',
}

export function buildTool<D extends AnyToolDef>(def: D): BuiltTool<D> {
  return {
    ...TOOL_DEFAULTS,
    userFacingName: () => def.name,
    ...def,
  } as BuiltTool<D>
}
```

所有工具都必须通过 `buildTool()` 构造。该默认值策略体现了一个**系统级保守原则 (Fail-Closed)**：

- 并发默认不安全 (`isConcurrencySafe: false`)
- 写操作默认存在风险 (非只读 `isReadOnly: false`)
- 安全相关能力必须显式声明（安全分类器默认短路拦截 `toAutoClassifierInput: ''`）

**通俗解释**：框架宁可错杀也不放过，所有新建工具都会被假定为“有风险的”、“不可并发的”，除非开发者显式声明。这就规避了后续二次开发时的安全盲点。

### 2.3 `ToolUseContext` 是执行时上下文总线

`ToolUseContext` 里挂载了丰富的运行时状态：
- 当前工具池与权限上下文 (permission context)
- app state 与 MCP clients / resources
- 文件缓存、主动阻断控制 (abortController) 与当前消息序列

这代表着，工具的执行深度依赖**整个系统的会话运行时**，而不仅是孤立的传参。

---

## 第三节：工具池是怎么组装的

**相关源码**：
- [`src/tools.ts`](../src/tools.ts)

### 3.1 `getAllBaseTools()` 是内建工具总表

**真实源码** ([`src/tools.ts:193`](../src/tools.ts)):

```typescript
export function getAllBaseTools(): Tools {
  return [
    AgentTool,
    TaskOutputTool,
    BashTool,
    ...
    FileEditTool,
    WebFetchTool,
    ...(isEnvTruthy(process.env.ENABLE_LSP_TOOL) ? [LSPTool] : []),
    ...(isWorktreeModeEnabled() ? [EnterWorktreeTool, ExitWorktreeTool] : []),
    ...(isToolSearchEnabledOptimistic() ? [ToolSearchTool] : []),
  ]
}
```

这个列表里可以看到几类来源：
- 始终存在的基础工具：如 `BashTool`、`FileEditTool`
- Feature Flag 或环境变量条件启用的工具：如 `LSPTool`、`WorkflowTool`
- Ant 内部用户专属工具：如 `ConfigTool`

**结论**：系统的所有工具都是按需动态装载配置生成的。

### 3.2 `assembleToolPool()`：原生工具与 MCP 融合点

**真实源码** ([`src/tools.ts:345`](../src/tools.ts)):

```typescript
export function assembleToolPool(
  permissionContext: ToolPermissionContext,
  mcpTools: Tools,
): Tools {
  const builtInTools = getTools(permissionContext)
  // 过滤出未被拦截的 MCP Server 工具
  const allowedMcpTools = filterToolsByDenyRules(mcpTools, permissionContext)

  const byName = (a: Tool, b: Tool) => a.name.localeCompare(b.name)
  // 合并、排序、并在名字冲突时优先保留内建的工具
  return uniqBy(
    [...builtInTools].sort(byName).concat(allowedMcpTools.sort(byName)),
    'name',
  )
}
```

**新手解读**：MCP 工具在这是作为同级公民直接注入的！系统使用 `uniqBy` 并且以前置数组（内建工具优先）的方式进行融合，保证了即便外部 MCP 含有与 `BashTool` 同名的恶意组件，也会被稳定拦截和丢弃。

---

## 第四节：调度层：并发不是默认开启的

**相关源码**：
- [`src/services/tools/toolOrchestration.ts`](../src/services/tools/toolOrchestration.ts)

### 4.1 `partitionToolCalls()` 如何分组

`runTools()` 执行多个 `tool_use` 时并非一拥而上，而是依据安全声明分批：

```typescript
// 伪代码：解析模型返回的 tool_uses 列表，按并发安全性分批
function partitionToolCalls(toolUses: ToolUseBlock[], context: ToolUseContext): ToolUseBatch[] {
  const batches: ToolUseBatch[] = [];
  let currentConcurrentBatch: ToolUseBlock[] = [];

  for (const toolUse of toolUses) {
    const tool = findToolByName(context.tools, toolUse.name);
    // 向前看：它并发安全吗？
    const isSafe = tool?.isConcurrencySafe(toolUse.input);

    if (isSafe) {
      currentConcurrentBatch.push(toolUse);
    } else {
      // 收口前面的安全工具
      if (currentConcurrentBatch.length > 0) {
        batches.push({ type: 'concurrent', tools: currentConcurrentBatch });
        currentConcurrentBatch = [];
      }
      // 不安全的工具自己单算作一个阶段
      batches.push({ type: 'sequential', tools: [toolUse] });
    }
  }
  if (currentConcurrentBatch.length > 0) {
    batches.push({ type: 'concurrent', tools: currentConcurrentBatch });
  }
  return batches;
}
```

**举例来说**：如果 LLM 返回 `[A(Read), B(Read), C(Write), D(Read)]`。
由于 Write 会产生状态变异，分批结果将严格变为：
1. `[A, B]` 并发处理
2. `[C]` 串行处理
3. `[D]` 获取剩余算力独占处理

### 4.2 延迟应用 `contextModifier`

对于并发批次，工具返回的上下文修改 (`contextModifier`) 会被押后收集，在批次全部收口后依次应用。这阻止了并行的 Read 进程因为相互的局部存储变量产生读写覆盖问题（竞态污染）。

---

## 第五节：Streaming Tool Executor：边收边跑

**相关源码**：
- [`src/services/tools/StreamingToolExecutor.ts`](../src/services/tools/StreamingToolExecutor.ts)

在特定高速流式场景下，系统并不会等长篇大论的 Assistant Content 彻底接收完才启动工具调频。相反，系统使用状态机追踪每个工具的状态：

维护的状态流转：`queued` -> `executing` -> `completed` -> `yielded`。
1. 并发安全的工具一旦 Zod schema 解析通过，立刻被 Launch 启动。
2. 不安全的兄弟节点进入排队等候独占权。
3. 若某并行工具中途抛错，它可以中断（Cancel）未完兄弟节点，提早返回模型报告异常。

---

## 第六节：`runToolUse()`：真正的执行主干

**相关源码**：
- [`src/services/tools/toolExecution.ts`](../src/services/tools/toolExecution.ts)
- [`src/services/tools/toolHooks.ts`](../src/services/tools/toolHooks.ts)

### 6.1 各处理链路剖析

工具的具体执行过程非常严苛。

- **第一步：Zod schema 校验** (`tool.inputSchema.safeParse`)
  硬约束参数。如果失败不会退出系统，而是把异常栈扔给 LLM 纠正重试。
- **第二步：独立语义校验** (`validateInput()`)
  即使符合 Schema，还要确保语义正确。比如新旧字符串是否相等，是否碰到了黑名单目录等。
- **第三步：Backfill 隐式派生依赖**
  向输入结构深度注射诸如 `expandPath()` 类似的钩子依赖，供后续安全审计审查。

### 6.2 PreToolUse Hooks 和 权限系统

**真实源码** ([`src/services/tools/toolHooks.ts:435`](../src/services/tools/toolHooks.ts)):
```typescript
export async function* runPreToolUseHooks(
  tool: Tool,
  toolUseID: string,
  input: { [key: string]: unknown },
  // ...
): AsyncGenerator<HookProgress | MessageUpdateLazy | StopHookInfo, void> {
   // 按顺序触发前置拦截校验逻辑，甚至可能直接修改传入的 input 结构...
}
```

PreToolUse Hooks 极大拓展了框架的动态能力。系统的权限判定（`allow` | `deny` | `ask`）在这一步汇总。

如果拦截发生，程序将停止向该工具发起调用，转向构建并返回异常的 UI 卡片消息。

### 6.3 最终唤起 `tool.call()`

**引用概念 / 伪代码表示**：

```typescript
// 在全部 pre-hooks 跑完且 checkPermissions 通过之后执行：
try {
  const result = await tool.call(
    callInput,
    enrichedToolUseContext,
    canUseTool,
    assistantMessage,
    onProgress
  );
  // 执行成功，准备将结果写入回流消息
  processToolResultBlock(result);
} catch (error) {
  // 拦截工具抛出的异常并标准化包装，返回 tool_use_error 给模型
  yield generateErrorResult(error, toolUse.id);
}
```

只有走完以上种种限制和补完逻辑，动作最终才交由 `Tool.call()` 本尊落地运行。

---

## 第七节：Query 主循环如何接住工具结果

**相关源码**：
- [`src/query.ts`](../src/query.ts)

工具结果回流有两个面向：

1. **面向 UI**：用户立刻看到 progress / result / reject / error。
2. **面向模型**：下一轮模型请求拿到标准化的 `tool_result`。

这一流程依赖一个非常核心的清理器 `normalizeMessagesForAPI()`。它从包含富文本、本地挂载图片、长串打点元数据的混合队列里，剔除多余组件，提炼成标准化 API 可接受的格式后再交回给大模型。

---

## 第八节：具体案例解析：`FileEditTool`

**相关源码**：
- [`src/tools/FileEditTool/FileEditTool.ts`](../src/tools/FileEditTool/FileEditTool.ts)

`FileEditTool` 囊括了接口内近乎所有的能力要求，其内部涵盖：
UNC 文件锁验证、超大实体阻断保护、团队 Secret Key 匹配机制防泄漏，并能够将错误细化到通过提示补漏 `did you mean ...?`。

**分析结论**：“编辑文件”动作从未是粗糙的正则匹配和替换，它底层其实是一套高度自治并且拥有防抖能力的环境治理器。

---

## 第九节：具体案例解析：`AskUserQuestionTool`

**相关源码**：
- [`src/tools/AskUserQuestionTool/AskUserQuestionTool.tsx`](../src/tools/AskUserQuestionTool/AskUserQuestionTool.tsx)

这个工具完美揭示：**Tool 并不一定是后端机器代码操作**！
它配置了：`shouldDefer = true`, `requiresUserInteraction = true`, `isReadOnly = true`。

**通俗解释**：当大模型想向人类了解情况时，这不是什么特殊的“内部系统交互机制”，它本身就被包装成了平起平坐的 Tool。模型通过调用 Tool 的 API 来向开发者屏幕发送提问表单，而其返回的值就是你我在界面上敲下的字！这说明 Tool 调用链路本质是一个宏大的“双边交互抽象隧道”。

---

## 第十节：机制设计特点总结

通过前述源码对照和逻辑图，我们可以看到本机制三个核心亮点：

1. **管线代理模式 (Pipeline)**：工具调用行为被多层管线包装，具备了前置拦截和语义补偿等非功能特征。
2. **Transcript 是唯一交互真理**：一切复杂的 JS 运行状态结果，通通化为 Transcript 对话流文本被记录且传回给大模型。
3. **安全内置于底层接口**：从 `buildTool` 开始约束读取权限和并发限制，从一开始就堵死了任意调用的后患。

---

## 本章小结

如果要用两句话总结 Claude Code 的本地能力实现结构：

- **Memory** 负责长周期和跨会话角色的一致性（静态知识库）。
- **Tool Pipeline** 则构筑了具备边界安全控制、包含错误重试容灾体系的执行路径（动态四肢）。

正是两者的结合，以及 `Query.ts` (主循环调度机制) 的串联，使得这套 CLI 蜕变成为功能成熟完备的 AI Agent 平台。
