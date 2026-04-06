# 第九章：Prompt 管理机制与实现细节

[返回总目录](../README.md)

## 1. 本章导读

这一章直接回答一个核心问题：

**Claude Code 的 prompt 不是一段固定字符串，而是一套分层拼装、可缓存、可覆盖、可观测的 prompt 管理系统。**

本章主要分析四件事：

1. 默认 system prompt 到底从哪里来
2. 自定义 prompt、agent prompt、append prompt 是怎么覆盖和叠加的
3. 哪些上下文其实不在 `prompts.ts`，而是运行时单独注入
4. compact、session memory、memory extraction 这些“专项 prompt”是如何和主 prompt 系统并存的

本章主要依据这些实现：

- [`src/constants/prompts.ts`](../src/constants/prompts.ts)
- [`src/utils/systemPrompt.ts`](../src/utils/systemPrompt.ts)
- [`src/screens/REPL.tsx`](../src/screens/REPL.tsx)
- [`src/utils/queryContext.ts`](../src/utils/queryContext.ts)
- [`src/context.ts`](../src/context.ts)
- [`src/constants/systemPromptSections.ts`](../src/constants/systemPromptSections.ts)
- [`src/main.tsx`](../src/main.tsx)
- [`src/services/compact/prompt.ts`](../src/services/compact/prompt.ts)
- [`src/services/SessionMemory/prompts.ts`](../src/services/SessionMemory/prompts.ts)
- [`src/services/extractMemories/prompts.ts`](../src/services/extractMemories/prompts.ts)
- [`src/services/api/dumpPrompts.ts`](../src/services/api/dumpPrompts.ts)

先给结论：

这个项目没有把 prompt 管理做成“一个 system prompt 文件 + 若干 if else”，而是拆成了 6 层：

```text
1. 默认主系统提示
   src/constants/prompts.ts

2. 有效 system prompt 组装器
   src/utils/systemPrompt.ts
   - override
   - coordinator
   - agent
   - custom
   - append

3. 运行时上下文注入
   src/context.ts
   - CLAUDE.md
   - currentDate
   - git status
   - cache breaker

4. 启动期附加指令入口
   src/main.tsx
   - --system-prompt
   - --append-system-prompt
   - systemPromptFile / appendSystemPromptFile
   - proactive / chrome / teammate addendum

5. Prompt 缓存与失效管理
   src/constants/systemPromptSections.ts
   - section cache
   - dynamic boundary
   - cache break

6. 专项 prompt 家族
   compact / session memory / extract memories / hooks / insights 等
```

所以这里真正管理的不是“prompt 文本”，而是：

- 哪些 prompt 属于主循环
- 哪些 prompt 属于子任务
- 哪些内容要长期缓存
- 哪些内容必须逐轮重算
- 哪些内容允许外部覆盖
- 哪些内容可以被导出和审计

## 2. 总体设计：这不是单 prompt，而是 prompt runtime

相关实现：

- [`src/constants/prompts.ts`](../src/constants/prompts.ts)
- [`src/utils/systemPrompt.ts`](../src/utils/systemPrompt.ts)
- [`src/context.ts`](../src/context.ts)

如果只看文件名，很容易以为 `src/constants/prompts.ts` 就是“完整 prompt”。

实际上不是。

真正送进模型前，大致流程如下：

```text
启动参数 / mode / agent / mcp / settings
                |
                v
getSystemPrompt() 生成默认 system prompt 数组
                |
                v
buildEffectiveSystemPrompt() 处理优先级覆盖
                |
                +---- userContext
                |       - CLAUDE.md
                |       - currentDate
                |
                +---- systemContext
                        - git status
                        - cacheBreaker
                |
                v
Query / REPL / Compact / Subagent 调用 API
```

也就是说，这个项目里的 “prompt” 至少分成三类：

1. `system prompt`
   定义 agent 的身份、规则、工具使用方式和会话级策略。
2. `userContext / systemContext`
   属于额外上下文，不直接写死在 `prompts.ts` 主模板里。
3. `task-specific prompts`
   专门用于 compact、memory extraction、session memory 更新等后台任务。

这一拆分很关键，因为它说明 Claude Code 不是把所有规则都塞进一个超长 system prompt，而是把**常驻规则**、**会话上下文**、**专项任务说明**分开治理。

## 3. 默认 system prompt 的源头：`getSystemPrompt()`

相关实现：

- [`src/constants/prompts.ts`](../src/constants/prompts.ts)

### 3.1 它返回的不是字符串，而是字符串数组

`getSystemPrompt()` 的签名是：

```typescript
export async function getSystemPrompt(
  tools: Tools,
  model: string,
  additionalWorkingDirectories?: string[],
  mcpClients?: MCPServerConnection[],
): Promise<string[]>
```

这件事本身就说明设计意图：

- system prompt 被拆成多个 section
- 每个 section 可以单独缓存、单独插拔、单独统计 token
- 后续还能在 section 级别做 cache boundary 和动态失效

### 3.2 主体结构：静态段 + 动态段

`getSystemPrompt()` 最重要的返回结构如下：

```typescript
return [
  getSimpleIntroSection(outputStyleConfig),
  getSimpleSystemSection(),
  outputStyleConfig === null ||
  outputStyleConfig.keepCodingInstructions === true
    ? getSimpleDoingTasksSection()
    : null,
  getActionsSection(),
  getUsingYourToolsSection(enabledTools),
  getSimpleToneAndStyleSection(),
  getOutputEfficiencySection(),
  ...(shouldUseGlobalCacheScope() ? [SYSTEM_PROMPT_DYNAMIC_BOUNDARY] : []),
  ...resolvedDynamicSections,
].filter(s => s !== null)
```

这段代码非常重要，因为它揭示了主 prompt 的基本工程策略：

- 前半段是**静态主干**
- 中间插一个 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY`
- 后半段是**动态 section**

换句话说，Claude Code 不是只在“内容层面”写 prompt，而是在“缓存层面”设计 prompt。

### 3.3 默认 prompt 的静态主干长什么样

例如最开头的身份段 `getSimpleIntroSection()` 会返回：

```typescript
return `
You are an interactive agent that helps users ...

${CYBER_RISK_INSTRUCTION}
IMPORTANT: You must NEVER generate or guess URLs for the user unless ...
`
```

`getSimpleSystemSection()` 又会追加一组基础规则，例如：

- 输出给用户的文字如何呈现
- 工具调用被拒绝后不能原样重试
- 外部 tool result 可能存在 prompt injection
- hooks 反馈要视作用户输入
- 上下文会被自动压缩

`getSimpleDoingTasksSection()` 则是更偏 coding agent 的工作规则，例如：

- 不要过度设计
- 不要额外加注释和类型
- 读文件后再改代码
- 遇到失败先诊断再换策略
- 避免引入安全漏洞

也就是说，默认 system prompt 不是一个短小的身份声明，而是一个非常完整的“执行政策包”。

### 3.4 动态段是什么

`resolvedDynamicSections` 来自这几个 section：

```typescript
const dynamicSections = [
  systemPromptSection('session_guidance', ...),
  systemPromptSection('memory', ...),
  systemPromptSection('ant_model_override', ...),
  systemPromptSection('env_info_simple', ...),
  systemPromptSection('language', ...),
  systemPromptSection('output_style', ...),
  DANGEROUS_uncachedSystemPromptSection('mcp_instructions', ...),
  systemPromptSection('scratchpad', ...),
  systemPromptSection('frc', ...),
  systemPromptSection('summarize_tool_results', ...),
]
```

这些 section 和静态主干不同，它们更依赖运行态：

- 当前启用的 tools
- 当前 settings 里的语言偏好
- 当前模型
- 当前 mcp server 的 instructions
- 当前 memory / scratchpad / output style

这说明 prompt 系统不是“读取模板并替换变量”，而是“运行时装配一组 section”。

## 4. 有效 system prompt 的组装器：`buildEffectiveSystemPrompt()`

相关实现：

- [`src/utils/systemPrompt.ts`](../src/utils/systemPrompt.ts)

真正决定“最后发给模型的 system prompt 长什么样”的，不是 `getSystemPrompt()`，而是 `buildEffectiveSystemPrompt()`。

它的注释已经把优先级写得很清楚：

```typescript
/**
 * 0. Override system prompt
 * 1. Coordinator system prompt
 * 2. Agent system prompt
 * 3. Custom system prompt
 * 4. Default system prompt
 * Plus appendSystemPrompt is always added at the end
 */
```

### 4.1 覆盖优先级

可以把它翻译成下面这段伪代码：

```text
if overrideSystemPrompt:
    final = [overrideSystemPrompt]
else if coordinator mode:
    final = [coordinatorPrompt] + [appendPrompt?]
else:
    base =
      agentPrompt
      or customSystemPrompt
      or defaultSystemPrompt

    if proactive mode and agentPrompt exists:
        final = defaultSystemPrompt + ["# Custom Agent Instructions" + agentPrompt]
    else:
        final = [base]

    if appendSystemPrompt:
        final += [appendSystemPrompt]
```

这里最值得注意的是两点：

1. `customSystemPrompt` **不会 append 到默认 prompt 后面**，而是直接替代默认 prompt。
2. `appendSystemPrompt` 不管前面是什么来源，基本都会被挂到最后。

这两条规则决定了 Claude Code 对“覆写”和“加尾注”的工程区分是很严格的。

### 4.2 真实函数

下面是核心逻辑的原始函数片段：

```typescript
export function buildEffectiveSystemPrompt({
  mainThreadAgentDefinition,
  toolUseContext,
  customSystemPrompt,
  defaultSystemPrompt,
  appendSystemPrompt,
  overrideSystemPrompt,
}): SystemPrompt {
  if (overrideSystemPrompt) {
    return asSystemPrompt([overrideSystemPrompt])
  }

  if (feature('COORDINATOR_MODE') &&
      isEnvTruthy(process.env.CLAUDE_CODE_COORDINATOR_MODE) &&
      !mainThreadAgentDefinition) {
    return asSystemPrompt([
      getCoordinatorSystemPrompt(),
      ...(appendSystemPrompt ? [appendSystemPrompt] : []),
    ])
  }

  const agentSystemPrompt = mainThreadAgentDefinition
    ? mainThreadAgentDefinition.getSystemPrompt(...)
    : undefined

  if (agentSystemPrompt && proactiveActive) {
    return asSystemPrompt([
      ...defaultSystemPrompt,
      `\n# Custom Agent Instructions\n${agentSystemPrompt}`,
      ...(appendSystemPrompt ? [appendSystemPrompt] : []),
    ])
  }

  return asSystemPrompt([
    ...(agentSystemPrompt
      ? [agentSystemPrompt]
      : customSystemPrompt
        ? [customSystemPrompt]
        : defaultSystemPrompt),
    ...(appendSystemPrompt ? [appendSystemPrompt] : []),
  ])
}
```

这说明 agent prompt 在普通模式下甚至会**取代默认 prompt**，而不是“在默认 prompt 上加一点 agent 设定”。这是一种很强的角色切换。

## 5. 主 prompt 之外的上下文注入：`getUserContext()` 与 `getSystemContext()`

相关实现：

- [`src/context.ts`](../src/context.ts)
- [`src/utils/queryContext.ts`](../src/utils/queryContext.ts)

Prompt 管理里一个非常容易被忽略的点是：

**有些内容不是 system prompt section，而是单独的 context。**

### 5.1 `getUserContext()`：用户级上下文

`getUserContext()` 返回的内容主要有两个：

1. `claudeMd`
2. `currentDate`

源码逻辑大致如下：

```typescript
const claudeMd = shouldDisableClaudeMd
  ? null
  : getClaudeMds(filterInjectedMemoryFiles(await getMemoryFiles()))

return {
  ...(claudeMd && { claudeMd }),
  currentDate: `Today's date is ${getLocalISODate()}.`,
}
```

这说明：

- `CLAUDE.md` 并不是 `prompts.ts` 里写死的一段模板
- 它是运行时扫描、读取、拼接后作为 user context 注入
- 日期也不是主 prompt 文本的一部分，而是独立字段

因此，研究 Claude Code 的 prompt 不能只看 `constants/prompts.ts`，还必须把 `context.ts` 算进去。

### 5.2 `getSystemContext()`：系统级上下文

`getSystemContext()` 主要会追加：

- git status 快照
- cache breaker 注入项

核心逻辑：

```typescript
return {
  ...(gitStatus && { gitStatus }),
  ...(feature('BREAK_CACHE_COMMAND') && injection
    ? { cacheBreaker: `[CACHE_BREAKER: ${injection}]` }
    : {}),
}
```

这说明 system context 的职责不是“身份描述”，而是提供**本轮推理必须知道的系统状态**。

尤其是 `gitStatus` 这项，非常像“给 coding agent 的环境前情摘要”。

## 6. 运行时入口：外部 prompt 是怎么进入系统的

相关实现：

- [`src/main.tsx`](../src/main.tsx)

这一部分决定了 Claude Code 为什么不只是“内置 prompt”，而是“可外部编排的 prompt runtime”。

### 6.1 CLI 显式入口

`main.tsx` 会读取：

- `--system-prompt`
- `--system-prompt-file`
- `--append-system-prompt`
- `--append-system-prompt-file`

例如：

```typescript
let appendSystemPrompt = options.appendSystemPrompt;
if (options.appendSystemPromptFile) {
  if (options.appendSystemPrompt) {
    process.stderr.write(chalk.red('Error: Cannot use both ...'));
    process.exit(1);
  }
  const filePath = resolve(options.appendSystemPromptFile);
  appendSystemPrompt = readFileSync(filePath, 'utf8');
}
```

这意味着用户或上层产品可以：

- 完全替换默认 system prompt
- 或只在默认 prompt 尾部追加一层策略

这是两种完全不同的控制力度。

### 6.2 启动期自动 addendum

除了 CLI 参数，系统还会在启动过程中继续往 `appendSystemPrompt` 里塞内容：

- tmux teammate addendum
- Claude in Chrome system prompt
- Claude in Chrome skill hint
- proactive mode prompt
- assistant addendum
- teammate custom agent instructions

例如 proactive mode 会直接追加：

```typescript
const proactivePrompt = `
# Proactive Mode

You are in proactive mode. Take initiative — explore, act, and make progress without waiting for instructions.

Start by briefly greeting the user.
...`
appendSystemPrompt = appendSystemPrompt
  ? `${appendSystemPrompt}\n\n${proactivePrompt}`
  : proactivePrompt
```

所以 `appendSystemPrompt` 在工程上并不是“用户偶尔手动加一句”，而是一个正式的**追加指令总线**。

## 7. Prompt 缓存工程：为什么要分 section、为什么要有 boundary

相关实现：

- [`src/constants/systemPromptSections.ts`](../src/constants/systemPromptSections.ts)
- [`src/constants/prompts.ts`](../src/constants/prompts.ts)

这一套实现最有工程味的地方，就是它把 prompt 当成缓存对象治理。

### 7.1 `systemPromptSection()`：可缓存 section

```typescript
export function systemPromptSection(
  name: string,
  compute: ComputeFn,
): SystemPromptSection {
  return { name, compute, cacheBreak: false }
}
```

### 7.2 `DANGEROUS_uncachedSystemPromptSection()`：显式声明会打断缓存

```typescript
export function DANGEROUS_uncachedSystemPromptSection(
  name: string,
  compute: ComputeFn,
  _reason: string,
): SystemPromptSection {
  return { name, compute, cacheBreak: true }
}
```

这类接口设计的意义很直接：

- 默认 section 都应该缓存
- 如果你要让某段 prompt 每轮重算，就必须显式声明“这是危险操作”

这是一种非常明确的 prompt cache discipline。

### 7.3 解析逻辑

```typescript
export async function resolveSystemPromptSections(
  sections: SystemPromptSection[],
): Promise<(string | null)[]> {
  const cache = getSystemPromptSectionCache()

  return Promise.all(
    sections.map(async s => {
      if (!s.cacheBreak && cache.has(s.name)) {
        return cache.get(s.name) ?? null
      }
      const value = await s.compute()
      setSystemPromptSectionCacheEntry(s.name, value)
      return value
    }),
  )
}
```

也就是说，这里缓存的是**section 结果**，不是整个大 prompt 字符串。

### 7.4 `SYSTEM_PROMPT_DYNAMIC_BOUNDARY`

`prompts.ts` 里专门定义了：

```typescript
export const SYSTEM_PROMPT_DYNAMIC_BOUNDARY =
  '__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__'
```

它的作用不是给模型看的，而是给缓存系统看的：

- boundary 之前尽可能保持稳定
- boundary 之后允许更多 session 级变化

这说明 Claude Code 已经把 prompt prefix cache 当成一级工程问题处理了。

### 7.5 何时失效

`clearSystemPromptSections()` 会在 `/clear`、`/compact`、worktree 切换等路径被调用。

这表示 prompt cache 不是永久缓存，而是和“会话生命周期事件”绑定：

- clear conversation
- compact conversation
- enter / exit worktree
- resume / restore session

## 8. 主会话里 prompt 是怎么实际组装的

相关实现：

- [`src/screens/REPL.tsx`](../src/screens/REPL.tsx)
- [`src/commands/compact/compact.ts`](../src/commands/compact/compact.ts)
- [`src/utils/queryContext.ts`](../src/utils/queryContext.ts)

### 8.1 REPL 主路径

在 REPL 中，可以看到这条关键链路：

```typescript
const [defaultSystemPrompt, userContext, systemContext] = await Promise.all([
  getSystemPrompt(...),
  getUserContext(),
  getSystemContext(),
])
const systemPrompt = buildEffectiveSystemPrompt({
  mainThreadAgentDefinition,
  toolUseContext,
  customSystemPrompt,
  defaultSystemPrompt,
  appendSystemPrompt
})
toolUseContext.renderedSystemPrompt = systemPrompt;
```

这里很关键：

- 默认 prompt 和 user/system context 是并行拉取的
- 最终 system prompt 会被挂到 `toolUseContext.renderedSystemPrompt`
- 这个字段后面还能被 fork / subagent / resume 逻辑复用

也就是说，prompt 不只是“发送前临时拼一下”，而是 runtime 里会被持久引用的一份状态。

### 8.2 compact 路径会重新取一遍 cache-safe prompt

`/compact` 并不是拿当前界面的 prompt 文本直接去总结，而是重新计算：

```typescript
const defaultSysPrompt = await getSystemPrompt(...)
const systemPrompt = buildEffectiveSystemPrompt({
  mainThreadAgentDefinition: undefined,
  toolUseContext: context,
  customSystemPrompt: context.options.customSystemPrompt,
  defaultSystemPrompt: defaultSysPrompt,
  appendSystemPrompt: context.options.appendSystemPrompt,
})
```

这说明 compact 本身也依赖 prompt 系统，而且它要拿的是一份**适合共享 cache key 的 prompt 前缀**。

### 8.3 非交互 / side question 也能重建 prompt

[`src/utils/queryContext.ts`](../src/utils/queryContext.ts) 还提供了 `fetchSystemPromptParts()` 和 `buildSideQuestionFallbackParams()`，说明：

- prompt 构造逻辑被抽到共享 helper
- 即使是 side question / print / SDK resume，也能尽量重建出与主会话一致的 prompt 前缀

所以这里的 prompt 管理已经不是 UI 层逻辑，而是 query infrastructure 的一部分。

## 9. 专项 prompt 家族：主 prompt 之外还有哪些 prompt

相关实现：

- [`src/services/compact/prompt.ts`](../src/services/compact/prompt.ts)
- [`src/services/SessionMemory/prompts.ts`](../src/services/SessionMemory/prompts.ts)
- [`src/services/extractMemories/prompts.ts`](../src/services/extractMemories/prompts.ts)

主会话 prompt 之外，这个项目还有很多“专项 prompt”。

### 9.1 compact prompt：强约束、无工具、只产总结

compact prompt 一上来就先下死命令：

```typescript
const NO_TOOLS_PREAMBLE = `CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn — you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.
`
```

这类 prompt 和主 system prompt 的风格完全不同。

它不是定义长期身份，而是在单次任务里强力约束输出协议：

- 禁止工具
- 限制格式
- 限制轮次
- 强化总结结构

也就是说，Claude Code 里“prompt engineering”并不是只服务主 agent，而是服务后台操作协议。

### 9.2 session memory prompt：要求只用 Edit 工具更新 notes

`SessionMemory/prompts.ts` 的默认 update prompt 也很典型：

```typescript
Your ONLY task is to use the Edit tool to update the notes file, then stop.
Do not call any other tools.
...
- NEVER modify, delete, or add section headers
- NEVER modify or delete the italic _section description_ lines
- ONLY update the actual content that appears BELOW ...
```

这说明 session memory 更新不是“自由总结”，而是“带模板约束的结构化文档维护任务”。

### 9.3 memory extraction prompt：限制工具集合与回合策略

`extractMemories/prompts.ts` 也不是简单地说“帮我提取记忆”，而是明确限制：

- 可用工具只有 Read / Grep / Glob / 只读 Bash / Edit / Write
- 不允许 MCP、Agent、可写 Bash
- 要先并行读，再并行写
- 只能使用最近若干消息
- 禁止再去读源码验证

这意味着后台 memory agent 的行为并不是模型自由发挥，而是被 prompt 写成了一套轻量协议。

## 10. 可观测性：这个项目能把 prompt 导出来看

相关实现：

- [`src/services/api/dumpPrompts.ts`](../src/services/api/dumpPrompts.ts)
- [`src/commands/context/context-noninteractive.ts`](../src/commands/context/context-noninteractive.ts)
- [`src/utils/analyzeContext.ts`](../src/utils/analyzeContext.ts)

### 10.1 `dump-prompts`：把 API 请求落到 JSONL

`createDumpPromptsFetch()` 会拦截请求，把：

- init data
- system update
- user messages
- responses

写到：

```text
~/.claude/dump-prompts/<session-or-agent-id>.jsonl
```

这说明 prompt 不只是内部隐式状态，还能被调试、复盘、审计。

### 10.2 `/context` 可以统计 system prompt sections token

`analyzeContext.ts` 会把 effective system prompt 拆成 named entries：

```typescript
const namedEntries = [
  ...effectiveSystemPrompt
    .filter(content => content.length > 0 &&
      content !== SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
    .map(content => ({ name: extractSectionName(content), content })),
  ...Object.entries(systemContext)
    .filter(([, content]) => content.length > 0)
    .map(([name, content]) => ({ name, content })),
]
```

然后逐段算 token。

这说明 Claude Code 的 prompt 系统有一个很成熟的“运营侧视角”：

- 不是只关心 prompt 对不对
- 还关心 prompt 吃了多少 token
- 哪一段最贵
- 哪些段应该继续缓存

## 11. 这套 prompt 管理实现的优点与代价

### 11.1 优点

1. **可组合**
   默认 prompt、agent prompt、append prompt、userContext、systemContext、专项 prompt 可以并行演进。

2. **可缓存**
   section 化设计 + boundary 让 prompt prefix cache 有工程抓手。

3. **可扩展**
   新功能不必改一个超长字符串，只需要新增 section 或 addendum。

4. **可调试**
   通过 `dump-prompts`、`/context`、token 分析，可以看到 prompt 的真实成本。

5. **可协议化**
   compact、memory update、memory extraction 都被做成了单任务协议，不容易跑偏。

### 11.2 代价

1. **理解门槛高**
   只读 `prompts.ts` 会得出错误结论，必须把 `systemPrompt.ts`、`context.ts`、`main.tsx` 一起看。

2. **覆盖关系复杂**
   `override`、`custom`、`agent`、`append`、`proactive`、`coordinator` 的组合已经比较绕。

3. **调试难点前移**
   prompt 问题不一定是模板问题，也可能是 context 注入、section cache、append addendum 或 mode 切换问题。

4. **行为依赖 mode**
   同一个系统在 REPL、compact、subagent、SDK side-question 下，实际拿到的 prompt 形态并不完全一样。

## 12. 本章小结

如果把 Claude Code 的 prompt 管理只理解成“`prompts.ts` 里的一大段 system prompt”，那会漏掉最关键的工程部分。

更准确的说法是：

- `src/constants/prompts.ts` 负责定义默认主系统提示的 section 集合
- `src/utils/systemPrompt.ts` 负责做最终优先级合成
- `src/context.ts` 负责注入运行态上下文
- `src/main.tsx` 负责接入 CLI 和 feature addendum
- `src/constants/systemPromptSections.ts` 负责缓存和失效
- 多个 `services/*/prompts.ts` 负责后台专项任务的 prompt 协议

所以，Claude Code 的 prompt 不是一个文件，而是一套 runtime。

这也是为什么它能同时做到：

- 主会话可持续运行
- 子任务可切换 prompt 协议
- 上下文成本可控
- prompt 可导出、可缓存、可审计

从工程角度看，这一套实现已经不是“写 prompt”，而是在做 **prompt orchestration**。
