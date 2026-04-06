# 第四章：Agent Memory 机制是怎么做的

[返回总目录](../README.md)

## 1. 本章导读

这一章不再只讲“memory 有哪些种类”，而是把实现链路拆开讲清楚：

1. memory 到底存在哪里
2. 什么时候写入
3. 什么时候被召回
4. Agent Memory 和 Auto / Session / Team Memory 的边界是什么
5. agent 真正运行时，是怎么把 memory 接到 prompt、tools、snapshot 和 UI 上的

本章主要依据这些实现：

- [`src/memdir/memdir.ts`](../src/memdir/memdir.ts)
- [`src/memdir/paths.ts`](../src/memdir/paths.ts)
- [`src/memdir/findRelevantMemories.ts`](../src/memdir/findRelevantMemories.ts)
- [`src/services/SessionMemory/sessionMemory.ts`](../src/services/SessionMemory/sessionMemory.ts)
- [`src/services/SessionMemory/sessionMemoryUtils.ts`](../src/services/SessionMemory/sessionMemoryUtils.ts)
- [`src/tools/AgentTool/agentMemory.ts`](../src/tools/AgentTool/agentMemory.ts)
- [`src/tools/AgentTool/loadAgentsDir.ts`](../src/tools/AgentTool/loadAgentsDir.ts)
- [`src/tools/AgentTool/agentMemorySnapshot.ts`](../src/tools/AgentTool/agentMemorySnapshot.ts)
- [`src/components/memory/MemoryFileSelector.tsx`](../src/components/memory/MemoryFileSelector.tsx)

先给结论：

这个项目没有把 memory 做成单一数据库，也没有做成隐蔽的内部 KV 存储，而是做成了“多层文件化记忆系统”。其中 Agent Memory 只是其中一层，但它和 agent 定义、agent prompt、agent 工具权限、snapshot 初始化、UI 文件选择器都耦合在一起，所以它不是一个附属功能，而是 agent runtime 的组成部分。

总图如下：

```text
会话 transcript / 当前 query
  ├─> Auto Memory 提取
  │     ├─> MEMORY.md 索引
  │     ├─> topic memories/*.md
  │     └─> relevant recall 选出少量文件回灌本轮上下文
  │
  ├─> Session Memory
  │     └─> 当前会话摘要 markdown
  │
  ├─> Agent Memory
  │     ├─> user scope
  │     ├─> project scope
  │     └─> local scope
  │          └─> 在 agent system prompt 中直接注入
  │
  └─> Team Memory
        └─> 团队同步的共享记忆

另外还有：
  └─> Agent Memory Snapshot
        ├─> 初始化本地 agent memory
        └─> 提示本地记忆有新版 snapshot 可同步
```

## 2. 总体设计：为什么它不是一个单库

相关实现：

- [`src/memdir/memdir.ts`](../src/memdir/memdir.ts)
- [`src/memdir/paths.ts`](../src/memdir/paths.ts)

这一套 memory 设计，核心不是“把内容记住”，而是“把不同生命周期、不同作用域、不同可见性的内容分开保存”。

从实现上看，至少分成四层：

1. `Auto Memory`
   面向整个用户和项目协作过程的长期记忆，存放在统一 memory 目录中。
2. `Session Memory`
   面向当前会话的摘要文件，目标是辅助 compact 和长会话持续运行。
3. `Agent Memory`
   面向某个 agent 类型的持久记忆，和 agent 定义直接绑定。
4. `Team Memory`
   面向团队共享的 repo 级知识同步。

它们没有被硬塞进一套 schema，而是各自有独立目录、独立 prompt、独立更新策略。

这带来三个直接好处：

- 透明：用户可以直接打开目录看 markdown 文件
- 可治理：不同 memory 可以单独开关、单独同步、单独约束
- 可组合：Auto / Session / Agent / Team Memory 可以同时存在，但职责不同

## 3. 底层存储模型：文件夹 + `MEMORY.md` 索引

相关实现：

- [`src/memdir/memdir.ts`](../src/memdir/memdir.ts)

### 3.1 基本约定

memory 的最底层是目录，不是数据库。

在 [`src/memdir/memdir.ts`](../src/memdir/memdir.ts) 里可以看到几个关键常量：

- `ENTRYPOINT_NAME = 'MEMORY.md'`
- `MAX_ENTRYPOINT_LINES = 200`
- `MAX_ENTRYPOINT_BYTES = 25_000`

这说明系统把 `MEMORY.md` 当成入口索引文件，而不是正文存储文件。

设计意图很明确：

- 每条 memory 应该单独写成一个 markdown 文件
- `MEMORY.md` 只维护索引链接和一行描述
- agent / model 在 prompt 里默认只保证看到 `MEMORY.md`
- 需要更细节时，再去读具体 memory 文件

这比“把所有记忆堆在一个大文件里”更稳，因为大文件很容易造成：

- prompt 爆炸
- 更新冲突
- 历史垃圾无法治理
- 单条错误记忆污染整份上下文

### 3.2 `buildMemoryLines()` 给模型的真实约束

**真实源码** ([`src/memdir/memdir.ts:199`](../src/memdir/memdir.ts)):

```typescript
export function buildMemoryLines(
  displayName: string,
  memoryDir: string,
  extraGuidelines?: string[],
  skipIndex = false,
): string[] {
  const lines: string[] = [
    `# ${displayName}`,
    '',
    // DIR_EXISTS_GUIDANCE = "This directory already exists - write to it directly..."
    // 避免模型浪费一轮对话去 ls/mkdir 确认目录
    `You have a persistent, file-based memory system at ${"`"}${memoryDir}${"`"}. ${DIR_EXISTS_GUIDANCE}`,
    '',
    ...TYPES_SECTION_INDIVIDUAL,    // 记忆类型分类
    ...WHAT_NOT_TO_SAVE_SECTION,    // 禁止保存的内容（可从代码推导的、重复的）
    '',
    ...howToSave,   // 双步法：先写 topic 文件，再在 MEMORY.md 添加索引行
    '',
    ...(extraGuidelines ?? []),     // agent 专属额外规则（scope 说明等）
  ]
  lines.push(...buildSearchingPastContextSection(memoryDir))
  return lines
}
```

模型被要求像维护小型知识库一样操作 memory 目录：独立文件存储每条记忆、维护索引、更新过时记忆、避免重复。

### 3.3 `buildMemoryPrompt()` 如何装配上下文

**真实源码** ([`src/memdir/memdir.ts:272`](../src/memdir/memdir.ts)):

```typescript
export function buildMemoryPrompt(params: {
  displayName: string
  memoryDir:   string
  extraGuidelines?: string[]
}): string {
  const entrypoint = params.memoryDir + ENTRYPOINT_NAME  // <dir>/MEMORY.md

  // 同步读取（某些调用来自 React render 路径，不能 await）
  let entrypointContent = ''
  try {
    entrypointContent = fs.readFileSync(entrypoint, { encoding: 'utf-8' })
  } catch { /* 文件不存在时静默忽略 */ }

  const lines = buildMemoryLines(params.displayName, params.memoryDir, params.extraGuidelines)

  if (entrypointContent.trim()) {
    const t = truncateEntrypointContent(entrypointContent)  // 硬截断保护
    logMemoryDirCounts(params.memoryDir, {
      content_length: t.byteCount, line_count: t.lineCount,
      was_truncated:  t.wasLineTruncated,
      // 类型标注防止 PII 误上报
      memory_type: memoryType as AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS,
    })
    lines.push(`## ${ENTRYPOINT_NAME}`, '', t.content)
  } else {
    lines.push(
      `## ${ENTRYPOINT_NAME}`, '',
      `Your ${ENTRYPOINT_NAME} is currently empty. When you save new memories, they will appear here.`,
    )
  }
  return lines.join('\n')
}
```

**两个关键实现细节**：
1. **同步读取**：`getSystemPrompt()` 存在于同步调用路径，不能使用 `await`
2. **硬截断保护**：`truncateEntrypointContent()` 将 MEMORY.md 限制在 200 行 / 25KB，防止 prompt 爆炸

## 4. Auto Memory：通用持久记忆层

相关实现：

- [`src/memdir/paths.ts`](../src/memdir/paths.ts)
- [`src/memdir/memdir.ts`](../src/memdir/memdir.ts)
- [`src/services/extractMemories/extractMemories.ts`](../src/services/extractMemories/extractMemories.ts)

### 4.1 存储位置

Auto Memory 的目录不是写死的，而是通过 [`src/memdir/paths.ts`](../src/memdir/paths.ts) 计算出来。

大致规则如下：

```text
优先级从高到低：

1. CLAUDE_COWORK_MEMORY_PATH_OVERRIDE
2. settings.json 中可信来源的 autoMemoryDirectory
3. <memoryBase>/projects/<sanitized-git-root>/memory/

其中 memoryBase =
  - CLAUDE_CODE_REMOTE_MEMORY_DIR
  - 否则 ~/.claude
```

这说明 Auto Memory 从一开始就兼容三类部署形态：

- 本地默认安装
- 配置文件定制目录
- remote / cowork 之类带挂载盘的环境

### 4.2 开关控制

`isAutoMemoryEnabled()` 的优先级也很工程化：

1. `CLAUDE_CODE_DISABLE_AUTO_MEMORY`
2. `CLAUDE_CODE_SIMPLE`
3. remote 模式但没有持久目录时关闭
4. `settings.autoMemoryEnabled`
5. 默认开启

所以 Agent Memory 虽然是单独目录，但是否启用，实际上复用了 Auto Memory 的总开关逻辑。

### 4.3 写入方式

Auto Memory 的更新不是靠当前主线程 agent 每次都手动完成，而是可以由后台提取流程补全。

它的目标是把长期有效的信息沉淀成 durable memories，例如：

- 用户长期偏好
- 项目外部上下文
- 非代码内生知识
- 需要跨会话延续的协作约束

这一层是“全局持久记忆基座”，而 Agent Memory 更像“某个 agent 的专属长期记忆”。

## 5. Relevant Memory Recall：不是全塞 prompt，而是做选择

相关实现：

- [`src/memdir/findRelevantMemories.ts`](../src/memdir/findRelevantMemories.ts)

很多系统一旦有 memory，就会把所有历史记忆都塞进 prompt。这个项目不是这样做的。

`findRelevantMemories()` 的工作方式是：

```text
memoryDir
  -> scanMemoryFiles() 扫描文件头
  -> 过滤掉 alreadySurfaced 的文件
  -> formatMemoryManifest() 生成“文件名 + 描述”清单
  -> sideQuery(...) 调一个轻量模型做选择
  -> 最多选 5 个 memory 文件
  -> 返回绝对路径和 mtimeMs
```

实现上有几个细节很值得注意：

- 被选的是文件名，不是整段正文
- 选择器只看 header / manifest，不先把所有正文塞进去
- `MEMORY.md` 本身不在这里选，因为它已经单独注入 system prompt
- `recentTools` 会影响选择，避免当前正活跃使用的工具文档被重复召回
- `alreadySurfaced` 会过滤之前已展示过的 memory，避免每轮都选同一批文件

所以这一层其实是“轻量检索器”，而不是“全文向量库”。

## 6. Session Memory：当前会话摘要层

相关实现：

- [`src/services/SessionMemory/sessionMemory.ts`](../src/services/SessionMemory/sessionMemory.ts)
- [`src/services/SessionMemory/sessionMemoryUtils.ts`](../src/services/SessionMemory/sessionMemoryUtils.ts)

Session Memory 不是 Agent Memory，但它非常重要，因为它说明作者把“当前会话摘要”和“长期 agent 记忆”分开了。

### 6.1 触发阈值

默认阈值在 [`src/services/SessionMemory/sessionMemoryUtils.ts`](../src/services/SessionMemory/sessionMemoryUtils.ts) 中写得很明确：

- `minimumMessageTokensToInit = 10000`
- `minimumTokensBetweenUpdate = 5000`
- `toolCallsBetweenUpdates = 3`

含义是：

- 会话没长到一定程度，不启用 Session Memory
- 即便已经启用，也不会每轮都更新
- 工具调用次数和 token 增长都要参与判断

### 6.2 何时认为“值得提取”

**真实源码** ([`src/services/SessionMemory/sessionMemory.ts:134`](../src/services/SessionMemory/sessionMemory.ts)):

```typescript
export function shouldExtractMemory(messages: Message[]): boolean {
  const currentTokenCount = tokenCountWithEstimation(messages)

  if (!isSessionMemoryInitialized()) {
    if (!hasMetInitializationThreshold(currentTokenCount)) return false
    markSessionMemoryInitialized()
  }

  const hasMetTokenThreshold    = hasMetUpdateThreshold(currentTokenCount)
  const hasMetToolCallThreshold =
    countToolCallsSince(messages, lastMemoryMessageUuid) >= getToolCallsBetweenUpdates()
  const hasToolCallsInLastTurn  = hasToolCallsInLastAssistantTurn(messages)

  // token 阈值始终必要；在自然断点（无 tool_use）或双阈值都满足时才触发
  const shouldExtract =
    (hasMetTokenThreshold && hasMetToolCallThreshold) ||
    (hasMetTokenThreshold && !hasToolCallsInLastTurn)

  if (shouldExtract) {
    lastMemoryMessageUuid = messages[messages.length - 1]?.uuid
    return true
  }
  return false
}
```

`!hasToolCallsInLastTurn` 寻找自然断点，防止在 tool_use 链中间截断生成孤立摘要。

### 6.3 存储与权限

Session Memory 文件以严格权限创建（[`src/services/SessionMemory/sessionMemory.ts:183`](../src/services/SessionMemory/sessionMemory.ts)）：

```typescript
async function setupSessionMemoryFile(ctx) {
  const sessionMemoryDir = getSessionMemoryDir()
  await fs.mkdir(sessionMemoryDir, { mode: 0o700 })  // 目录：只有属主可读写执行

  const memoryPath = getSessionMemoryPath()
  await writeFile(memoryPath, '', {
    mode: 0o600,   // 文件：只有属主可读写
    flag: 'wx',    // O_CREAT|O_EXCL：文件不存在时才创建，防止覆盖已有记忆
  })
}
```

`0o700` + `0o600` 说明 Session Memory 被视为敏感本地状态，而不是普通缓存文件。

### 6.4 更新方式：后台 forked subagent

调度链路：

```text
主会话 shouldExtractMemory() == true
  -> registerPostSamplingHook 触发
  -> setupSessionMemoryFile()            // 创建 0o600 文件，目录 0o700
  -> buildSessionMemoryUpdatePrompt()    // 构造摘要指令
  -> runForkedAgent({ canUseTool: createMemoryFileCanUseTool(memoryPath) })
```

**`createMemoryFileCanUseTool()` 真实源码** ([`src/services/SessionMemory/sessionMemory.ts:460`](../src/services/SessionMemory/sessionMemory.ts)):

```typescript
export function createMemoryFileCanUseTool(memoryPath: string): CanUseToolFn {
  return async (tool: Tool, input: unknown) => {
    if (
      tool.name === FILE_EDIT_TOOL_NAME &&
      typeof input === 'object' && input !== null &&
      'file_path' in input &&
      typeof input.file_path === 'string' &&
      input.file_path === memoryPath    // 精确路径匹配，不允许路径穿越
    ) {
      return { behavior: 'allow' as const, updatedInput: input }
    }
    return {
      behavior: 'deny' as const,
      message: `only ${FILE_EDIT_TOOL_NAME} on ${memoryPath} is allowed`,
      decisionReason: { type: 'other', reason: `only ${FILE_EDIT_TOOL_NAME} on ${memoryPath} is allowed` },
    }
  }
}
```

Session Memory 提取 subagent 是严密沙箱化的摘要代理：只有 `FileEditTool`，且只能操作精确路径，连 `FileReadTool` 和 `FileWriteTool` 都被 deny。

## 7. Agent Memory：真正和 agent 绑定的持久记忆

相关实现：

- [`src/tools/AgentTool/agentMemory.ts`](../src/tools/AgentTool/agentMemory.ts)
- [`src/tools/AgentTool/loadAgentsDir.ts`](../src/tools/AgentTool/loadAgentsDir.ts)
- [`src/tools/AgentTool/agentMemorySnapshot.ts`](../src/tools/AgentTool/agentMemorySnapshot.ts)
- [`src/components/memory/MemoryFileSelector.tsx`](../src/components/memory/MemoryFileSelector.tsx)

这一节是本章重点。

### 7.1 Agent Memory 的定位

Agent Memory 和 Auto Memory 的区别在于：

- Auto Memory 是“用户 / 项目维度”的长期记忆
- Agent Memory 是“某种 agent 类型”的长期记忆

也就是说，它不是“当前会话记住什么”，而是“这个 agent 以后应该长期知道什么”。

这使得 agent 不再只是一个静态 prompt 模板，而是：

```text
agent =
  静态角色 prompt
  + memory scope
  + memory 目录
  + 可写 memory tools
  + snapshot 初始化能力
```

### 7.2 三种 scope

在 [`src/tools/AgentTool/agentMemory.ts`](../src/tools/AgentTool/agentMemory.ts) 中，`AgentMemoryScope` 明确只有三种：

- `user`
- `project`
- `local`

含义分别是：

- `user`
  跨项目复用的 agent 长期记忆
- `project`
  当前项目内共享的 agent 记忆
- `local`
  当前项目、当前机器或当前挂载环境的本地 agent 记忆

### 7.3 真实目录布局

`getAgentMemoryDir(agentType, scope)` 的目录解析规则很清晰：

```text
user:
  <memoryBase>/agent-memory/<agentType>/

project:
  <cwd>/.claude/agent-memory/<agentType>/

local:
  默认:
    <cwd>/.claude/agent-memory-local/<agentType>/
  若设置 CLAUDE_CODE_REMOTE_MEMORY_DIR:
    <remoteMemoryDir>/projects/<sanitized-git-root>/agent-memory-local/<agentType>/
```

其中还有两个实现细节：

1. `agentType` 会先做路径清洗  
   `:` 会被替换成 `-`，因为插件命名空间可能长成 `my-plugin:my-agent`，但这在某些平台文件名不安全。
2. `local` scope 在 remote 环境下并不是真的“只在本地磁盘”  
   它会重定位到远端 memory mount 的 project namespace 中。

### 7.4 为什么要做 `isAgentMemoryPath()`

`isAgentMemoryPath()` 会把候选路径 normalize 后，再判断它是否属于三类 agent memory 目录之一。

这不是一个普通 util，它背后的意义是：

- 防止 `..` 之类路径穿越绕过 memory 边界判断
- 让权限系统知道“这是 agent memory 文件”
- 让 UI 或工具层能做特殊处理

也就是说，Agent Memory 在系统里不是“普通文件夹”，而是被识别为一种特殊存储边界。

### 7.5 Agent Memory 的入口文件

`getAgentMemoryEntrypoint()` 直接返回：

```text
<agent-memory-dir>/MEMORY.md
```

这说明 Agent Memory 没有独立于 memdir 体系的新协议，它是直接复用整个 memory 文件系统设计的。

也就是说，Agent Memory 不是另起炉灶，而是：

- 目录结构沿用 memdir
- prompt 构造沿用 `buildMemoryPrompt()`
- 记忆治理规则也沿用 typed memory instructions

### 7.6 agent 定义里如何声明 memory

agent 定义加载逻辑在 [`src/tools/AgentTool/loadAgentsDir.ts`](../src/tools/AgentTool/loadAgentsDir.ts)。

无论是 JSON agent 还是 Markdown agent，只要定义里带了 `memory` 字段，系统都会做两件事：

1. 自动把 memory prompt 拼接到 agent system prompt 后面
2. 自动把 `Write / Edit / Read` 三个文件工具注入到 agent 的工具列表里

这两步缺一不可。

如果只注入 prompt，不注入文件工具，agent 看得到规则却没法落盘。  
如果只注入文件工具，不注入 prompt，agent 有写权限却不知道 memory 的目录和治理方式。

### 7.7 `getSystemPrompt()` 如何拼上 Agent Memory

在 `parseAgentFromJson()` 和 `parseAgentFromMarkdown()` 两条路径里，都有这样的逻辑：

```text
if (isAutoMemoryEnabled() && parsed.memory) {
  return systemPrompt + '\n\n' + loadAgentMemoryPrompt(agentType, parsed.memory)
}
```

所以 Agent Memory 的注入时机很早：

- 不是 agent 运行中动态附加
- 不是工具调用后再补
- 而是在构造 agent system prompt 时直接固定进去

这意味着 agent 从第一轮开始就知道：

- 自己的 memory 目录在哪里
- 该怎么写 memory
- `MEMORY.md` 当前有哪些索引

### 7.8 `loadAgentMemoryPrompt()` 做了什么

`loadAgentMemoryPrompt(agentType, scope)` 这一层又做了几件非常关键的事：

```text
loadAgentMemoryPrompt()
  -> 根据 scope 生成 scopeNote
  -> 算出 memoryDir
  -> fire-and-forget ensureMemoryDirExists(memoryDir)
  -> buildMemoryPrompt({
       displayName: 'Persistent Agent Memory',
       memoryDir,
       extraGuidelines: [scopeNote, ...可能的环境附加规则]
     })
```

这几个点分别对应不同意图：

- `scopeNote`
  告诉 agent：user scope 要写得更通用，project scope 要面向项目，local scope 要面向当前机器/工作区。
- `ensureMemoryDirExists(memoryDir)`
  prompt 构造时就提前 mkdir，但不阻塞主路径。
- `buildMemoryPrompt(...)`
  让 Agent Memory 复用整套 memdir 规则，而不是写一套单独 prompt。
- `CLAUDE_COWORK_MEMORY_EXTRA_GUIDELINES`
  允许在 cowork 场景额外附加记忆规则。

### 7.9 为什么目录创建是 fire-and-forget

注释里明确解释了原因：

- 这段逻辑运行在同步 `getSystemPrompt()` 回调中
- 某些调用场景来自 React render 路径
- 因此这里不能异步阻塞

于是作者采取了很务实的做法：

- 先异步创建目录
- 即便目录还没创建好，后面的 `FileWriteTool` 自己也会补 mkdir

这就是典型的工程取舍：不为了“理论上更完美”而破坏 prompt 构建路径的同步性。

### 7.10 Agent Memory 的写入能力是怎么给到 agent 的

`loadAgentsDir.ts` 中有一条非常关键的自动注入逻辑：

```text
如果 memory 开启，且 auto memory 开启：
  强制把以下工具加入 agent tools：
    - FileWriteTool
    - FileEditTool
    - FileReadTool
```

这意味着声明了 memory 的 agent，天然获得一套最小闭环：

```text
读索引      -> FileReadTool
新建记忆    -> FileWriteTool
更新记忆    -> FileEditTool
```

从这里也能看出作者的设计立场：

- Agent Memory 不是给“系统后台”偷偷维护的
- 而是让 agent 自己显式读写 markdown 文件

### 7.11 Agent Memory 的典型使用流程

把上面这些机制串起来，实际运行链路大概是：

```text
加载 agent 定义
  -> agent.memory = user / project / local
  -> 自动补 FileRead / FileWrite / FileEdit
  -> getSystemPrompt() 追加 Agent Memory prompt

spawn agent
  -> prompt 中已经包含:
       1. memory 使用规则
       2. memory 目录位置
       3. 当前 MEMORY.md 索引内容

agent 工作中发现需要记住的信息
  -> 先读 MEMORY.md 或已有 memory 文件
  -> 新增或更新某条 memory
  -> 再维护 MEMORY.md 索引

后续再次调用同一 agent
  -> 再次读取同一目录的 MEMORY.md
  -> 获得上次沉淀下来的长期记忆
```

这说明 Agent Memory 的“应用”不是检索外挂，而是直接改变 agent 下一次的 system prompt 起点。

### 7.12 Agent Memory Snapshot：把记忆当成可分发资产

这一块是本章里最有意思的实现之一。

在 [`src/tools/AgentTool/agentMemorySnapshot.ts`](../src/tools/AgentTool/agentMemorySnapshot.ts) 中，snapshot 目录固定在：

```text
<cwd>/.claude/agent-memory-snapshots/<agentType>/
```

其中关键文件有两个：

- `snapshot.json`
  记录 snapshot 的 `updatedAt`
- `.snapshot-synced.json`
  记录本地当前是从哪个 snapshot 时间点同步过来的

### 7.13 snapshot 的三种状态

`checkAgentMemorySnapshot()` 只会返回三种动作：

- `none`
- `initialize`
- `prompt-update`

判定逻辑可以概括成：

```text
如果项目里没有 snapshot.json:
  -> none

如果本地 agent memory 目录里没有任何 .md 文件:
  -> initialize

如果本地已有 memory，但：
  - 没有 .snapshot-synced.json
  - 或 snapshot.updatedAt > syncedFrom
  -> prompt-update

否则:
  -> none
```

这说明 snapshot 不是每次无脑覆盖，而是区分：

- 首次初始化
- 有新版可提示更新
- 已同步无需处理

### 7.14 snapshot 如何初始化本地记忆

`initializeFromSnapshot()` 的逻辑很直接：

```text
snapshot 目录
  -> 复制除 snapshot.json 之外的文件
  -> 写入本地 agent memory 目录
  -> 保存 .snapshot-synced.json
```

而 `replaceFromSnapshot()` 会更激进：

```text
本地 agent memory 目录
  -> 先删除已有 .md 文件
  -> 再复制 snapshot
  -> 再写 synced metadata
```

还提供了 `markSnapshotSynced()`：

- 不改正文
- 只更新同步元数据

这通常用于“我知道有新版，但我现在接受当前版本状态”的场景。

### 7.15 snapshot 何时被检查

snapshot 检查逻辑在 [`src/tools/AgentTool/loadAgentsDir.ts`](../src/tools/AgentTool/loadAgentsDir.ts)。

要满足几个条件才会触发：

- `feature('AGENT_MEMORY_SNAPSHOT')`
- `isAutoMemoryEnabled()`
- agent 是 custom agent
- 并且当前实现里只对 `memory === 'user'` 的 agent 执行初始化检查

最后这一点很关键：当前 snapshot 机制主要是给 user-scope 的 agent memory 做初始化和升级提示，不是对所有 scope 一视同仁。

### 7.16 为什么 snapshot 很重要

因为它把 agent memory 从“运行时副产物”提升成了“可分发的角色资产”。

也就是说，一个项目可以不仅定义 agent 的 prompt，还能一起下发：

- 这个 agent 的初始记忆结构
- 这个 agent 已经积累好的协作经验
- 这个 agent 的更新版本

这比单纯 shipping 一个 `prompt.md` 更强，因为它允许项目把 agent 逐步养成熟。

### 7.17 Agent Memory 在 UI 里是可见的

[`src/components/memory/MemoryFileSelector.tsx`](../src/components/memory/MemoryFileSelector.tsx) 会把 agent memory 目录暴露给 UI。

这说明 Agent Memory 不是只给内部逻辑用的隐式存储，而是用户侧可浏览、可打开的文件系统对象。

这和很多“模型有记忆，但用户看不见”产品的思路完全不同。

## 8. Team Memory：共享而不是个人私有

相关实现：

- [`src/services/teamMemorySync/index.ts`](../src/services/teamMemorySync/index.ts)
- [`src/services/teamMemorySync/watcher.ts`](../src/services/teamMemorySync/watcher.ts)
- [`src/memdir/teamMemPaths.ts`](../src/memdir/teamMemPaths.ts)

Team Memory 是另一个维度：它不围绕单个 agent，而是围绕团队共享知识。

从实现看，它不是简单共享目录，而是带有：

- pull / push
- watcher
- checksum
- optimistic locking
- path validation
- secret scanning

所以 Team Memory 的目标不是“帮一个 agent 记住事”，而是“把 repo 级知识做成一套受控同步的团队知识层”。

## 9. Agent Memory 与其他 memory 的分工

把几层 memory 放在一起看，职责边界就更清楚了：

```text
Auto Memory
  解决：用户 / 项目长期协作信息沉淀

Relevant Recall
  解决：本轮只召回少量相关 memory，避免 prompt 污染

Session Memory
  解决：长会话摘要与 compact 稳定性

Agent Memory
  解决：某个 agent 类型的长期专属记忆

Agent Memory Snapshot
  解决：agent 记忆的初始化、分发、升级

Team Memory
  解决：团队共享知识同步
```

所以第四章如果只盯着“Agent Memory 目录在哪里”，其实是不够的。真正的工程设计在于：它被放进了一个分层 memory 体系里，每层负责不同问题。

## 10. 与 agent runtime 的耦合点

相关实现：

- [`src/tools/AgentTool/loadAgentsDir.ts`](../src/tools/AgentTool/loadAgentsDir.ts)
- [`src/tools/AgentTool/runAgent.ts`](../src/tools/AgentTool/runAgent.ts)

Agent Memory 之所以重要，是因为它不在 runtime 之外，而在 runtime 之内。

主要耦合点有四个：

1. `agent 定义阶段`
   `memory` 字段直接影响 agent 解析结果。
2. `system prompt 构造阶段`
   memory prompt 直接拼到 agent 的 system prompt 后面。
3. `tool 能力阶段`
   memory agent 自动获得读写编辑 memory 文件的能力。
4. `snapshot 生命周期阶段`
   agent 定义加载时就会检查 snapshot 初始化或更新状态。

因此，所谓“agent 有记忆”，在这个项目里不是抽象概念，而是：

```text
agent runtime
  = agent definition
  + system prompt
  + tool set
  + permission context
  + memory directory
  + snapshot state
```

## 11. Memory Compaction：大上下文的自动压缩打薄机制

相关实现：

- [`src/services/compact/compact.ts`](../src/services/compact/compact.ts)
- [`src/services/compact/sessionMemoryCompact.ts`](../src/services/compact/sessionMemoryCompact.ts)

不管引入了多少层的记忆，由于 Agent 对话中伴随着大量读写结果（特别是文件代码输出），模型的 Context Token 极易到达上限。系统为此设计了底层的 `compact`（上下文压缩打薄）逻辑，分为手动 `/compact` 与自动阈值触发。为了不在打薄时丢失 Agent 功能与关键连贯性，它做了严密的技术处理：

### 11.1 预处理与 Token 止损保护

在发起总结摘要请求给模型前，[`stripImagesFromMessages`](../src/services/compact/compact.ts) 和 [`stripReinjectedAttachments`](../src/services/compact/compact.ts) 会被调用来剔除所有的图像输入以及冗长的静态技能清单附件。这是为了防止因总结请求本身体积过大就撞到模型的 Token 墙导致请求死锁（PTL 异常）。万一触发 PTL，[`truncateHeadForPTLRetry`](../src/services/compact/compact.ts) 会回退削减最头部的几次 API Round 保证程序本身能够无阻运作。

### 11.2 Session Memory (SM) 直挂与工具链断点保护

这是本项目 Compaction 中最具亮点的工程设计。若系统已开启并处于一段长会话中，它**不会再去调用额外的 API 浪费 Token 给模型总结大意**，而是直接调用 [`trySessionMemoryCompaction`](../src/services/compact/sessionMemoryCompact.ts)，读取后台提取记忆的子 Agent 最新沉淀的 Session Memory 文件直接充当上下文断点（SummaryMessage）。
更重要的是，在寻找哪部分 Message 该不该丢弃时，由 [`calculateMessagesToKeepIndex`](../src/services/compact/sessionMemoryCompact.ts) 执行精确裁切：
- 必须优先从后向前留足最低限度配置的下限 Token 的原文（默认保留配置约 10K-40K Tokens），配置通过 [`getSessionMemoryCompactConfig`](../src/services/compact/sessionMemoryCompact.ts) 读取。
- 它内置了高度防御的代码逻辑去解决**面条并发问题**：截断时，如果切断位置落在了 `tool_use / tool_result` 执行链的中间，或者碰到了和 Assistant 共享相同 `message.id` 的 Thinking 流，[`adjustIndexToPreserveAPIInvariants`](../src/services/compact/sessionMemoryCompact.ts) 会强制向头部平移 Index 合包这些记录，绝对避免切分出非法的孤立 `tool_result`，从而规避 Anthropic 严格的 API 校验报错。

### 11.3 状态与能力复灌 (Reinjection)

被丢弃打薄的消息转变成了带有 [`SystemCompactBoundaryMessage`](../src/types/message.ts) 且指向 Summary 的短消息，由 [`createCompactBoundaryMessage`](../src/utils/messages.ts) 生成。但这有一个致命的副作用：过去抛出给大模型的那些注册在前的可用能力描述（例如 Tool Schemas 和 MCP 远程工具列表等）会被连带着裁剪遗失。所以 Compact 完成后，[`createPostCompactFileAttachments`](../src/services/compact/compact.ts) 会自动重建 FileAttachments（工作区读取保留）及激活的 Plans 清单，并通过 [`getDeferredToolsDeltaAttachment`](../src/utils/attachments.ts) 重新全量声明当前装载好的外部能力，追加回贴入新的队列中。在模型醒来后的第一回合看，虽然前世细节没有了，但是当前的技能蓝图依然齐装满员。

## 12. 这套实现的优点与代价

### 12.1 优点

1. 透明  
   所有 memory 都是文件，用户可以检查、编辑、删除。
2. 作用域清晰  
   user / project / local 三层 scope 很实用。
3. 检索成本可控  
   不是每轮都灌全部记忆，而是做 relevant recall。
4. agent 能真正“成长”  
   因为记忆和 agent 类型绑定，而不是只绑定单次会话。
5. 可分发  
   snapshot 机制让 agent memory 可以随项目一起发布和升级。

### 12.2 代价

1. 需要治理  
   错误记忆、过时记忆、重复记忆都会持续污染后续 agent 行为。
2. 路径和权限逻辑变复杂  
   user / project / local / remote mount 都要分别处理。
3. prompt 构造更重  
   `MEMORY.md` 每次都要参与 prompt 生成，虽然有截断保护，但仍有成本。
4. 需要模型遵守写入规范  
   系统已经做了不少规则约束，但最终仍依赖 agent 正确维护索引和文件。

## 13. 本章小结

如果只用一句话总结本项目的 Agent Memory：

它不是“给 agent 加一块隐藏缓存”，而是把 agent 的长期记忆做成了文件化、分 scope、可写入、可初始化、可升级、可在 UI 中查看的运行时基础设施。

如果再进一步总结整个 memory 体系：

```text
Auto Memory 管长期协作记忆
Session Memory 管当前会话摘要
Agent Memory 管某类 agent 的专属长期记忆
Team Memory 管团队共享知识
Relevant Recall 负责按需召回
Snapshot 负责 agent 记忆资产化
Compaction 管底层 Token 会话流打薄拦截
```
