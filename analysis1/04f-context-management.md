# 第八章：Context 上下文管理机制

[返回总目录](../README.md)

---

## 1. 导读

在长生命周期的对话与自动化任务中，LLM 的上下文窗口（Context Window）始终是稀缺资源。Claude Code 并非简单地采用“超过截断点就丢弃历史”的暴力做法，而是构建了一整套复杂的监控、预测和自动压缩（Auto-Compact）机制。

本章将深入解析系统如何动态计算 Context 消耗、如何在恰当的时机触发自动压缩，以及在压缩时如何保留关键状态并在极端情况下（如 Prompt Too Long 死锁）进行自我熔断与降级。

---

## 2. 上下文额度的分配与基线

### 2.1 动态 Context 窗口边界

系统并不是将所有的模型 Context 窗口都开放给 Agent 自由写入，而是会进行严格的预留扣减。

**真实源码**（[`src/utils/context.ts:18`](../src/utils/context.ts) 及 [`src/services/compact/autoCompact.ts:33`](../src/services/compact/autoCompact.ts)）：

```typescript
// 默认上下文窗口设为 200k（Claude 3 系默认值）
export const MODEL_CONTEXT_WINDOW_DEFAULT = 200_000

// 针对 [1m] 或特性开启的模型使用百万级上下文
export function has1mContext(model: string): boolean {
  return /\[1m\]/i.test(model)
}

// src/services/compact/autoCompact.ts
// 预留给 Summary API 的最大输出 Token 数
const MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000

// 计算有效可用窗口：总窗口 - 为 Summary 预留的 token
export function getEffectiveContextWindowSize(model: string): number {
  const reservedTokensForSummary = Math.min(
    getMaxOutputTokensForModel(model),
    MAX_OUTPUT_TOKENS_FOR_SUMMARY,
  )
  let contextWindow = getContextWindowForModel(model)

  // 支持环境变量硬覆盖
  const autoCompactWindow = process.env.CLAUDE_CODE_AUTO_COMPACT_WINDOW
  // ...
  return contextWindow - reservedTokensForSummary
}
```

**设计要点**：
为了确保当模型需要触发压缩（Auto Compact）时，API 还有足够的空间能够塞下原本的历史对话和用于生成 Summary 的提示词，系统会从总上下文（如 200k）中划走最高 20k 的预算空间（`MAX_OUTPUT_TOKENS_FOR_SUMMARY`）。

### 2.2 最大输出 Token (Max Output Tokens) 的效率优化

系统在向 API 发送请求时，为了提升服务集群的利用率和优化排队速度（Slot Reservation），对 `max_tokens` 做了专门的限制设计。

```typescript
// src/utils/context.ts:18
// Capped default for slot-reservation optimization. BQ p99 output = 4,911
// tokens, so 32k/64k defaults over-reserve 8-16× slot capacity. With the cap
// enabled, <1% of requests hit the limit; those get one clean retry at 64k
export const CAPPED_DEFAULT_MAX_TOKENS = 8_000
export const ESCALATED_MAX_TOKENS = 64_000
```

这里揭示了一个非常工程化的细节：虽然 Claude 3.5 Sonnet 支持 8k 的原生输出甚至配置可达更长，但实际分析表明业务的 99 分位数输出在 4,911 个 token 左右。因此即使模型能力超过 32k 输出，系统默认也会卡在 `8_000`，此举可极大地节约 API 层的 Slot 预约开销，遇到截断再触发 64k 的干净重试。

---

## 3. Auto-Compact 触发策略

通过每轮 API 调用获取的 token 消耗计数，系统会维护并监控一个“到达阈值即触发精简”的循环。

**真实源码**（[`src/services/compact/autoCompact.ts:241`](../src/services/compact/autoCompact.ts)）：

```typescript
export async function autoCompactIfNeeded(
  messages: Message[],
  toolUseContext: ToolUseContext,
  cacheSafeParams: CacheSafeParams,
  querySource?: QuerySource,
  tracking?: AutoCompactTrackingState,
  snipTokensFreed?: number,
): Promise<{ wasCompacted: boolean; compactionResult?: CompactionResult }> {
  
  // 熔断器：如果连续 compaction 失败达到 3 次，就完全停发该会话的 autocompact 请求。
  // 防止一些不可恢复的大小超限反复徒劳请求并浪费大量 API 额度
  if (tracking?.consecutiveFailures !== undefined &&
      tracking.consecutiveFailures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES) {
    return { wasCompacted: false }
  }

  const model = toolUseContext.options.mainLoopModel
  const shouldCompact = await shouldAutoCompact(messages, model, querySource, snipTokensFreed)

  if (!shouldCompact) {
    return { wasCompacted: false }
  }

  try {
    const compactionResult = await compactConversation(
      messages,
      toolUseContext,
      cacheSafeParams,
      true, // suppressFollowUpQuestions
    )
    return { wasCompacted: true, compactionResult, consecutiveFailures: 0 }
  } catch (error) {
    // 捕获失败，更新连续失败记录触发 Circuit Breaker
    const nextFailures = (tracking?.consecutiveFailures ?? 0) + 1
    return { wasCompacted: false, consecutiveFailures: nextFailures }
  }
}
```

系统设置了一个双重保证：
1. **缓冲界限**：在上下文快满时前置 `13_000` 个 tokens (`AUTOCOMPACT_BUFFER_TOKENS`) 触发缩减。
2. **熔断机制**：`MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES` 控制在极端情况下（比如用户的单张超级图片就超过了上下文）不再徒劳压缩发送导致无限报错循环（数据表明这个小判断每天为大盘省下了约 250K 次死锁 API 调用）。

---

## 4. 压缩与上下文反向重建机制

当我们压缩掉前面的 Messages 后，Agent 最害怕的不是遗忘早期的闲聊，而是**丢失了加载到一半的外部资源文件与开放工具**。因此，`compactConversation` 处理了重大的“上下文重建”动作。

### 4.1 清理多媒体与低价值负载

在交付给 Forked Agent 进行总结之前，先脱水非关键素材以确保 Summary API 自己不会由于体积太大而 OOM：

```typescript
// src/services/compact/compact.ts:145
export function stripImagesFromMessages(messages: Message[]): Message[] {
  // 剔除 User 发送的面版图片、Tool 传回的文件等
  // 将所有的 { type: 'image' } / { type: 'document' } 剔除并替换为等效的文本提示 [image] 
}

// 剔除将在紧接着的 post-compact 中全量补偿附加的内容，防止二次总结造成幻觉
export function stripReinjectedAttachments(messages: Message[]): Message[] {
  // 例如剔除 skill_discovery 等 attachment
}
```

### 4.2 API 的 Prompt 缓存复用

这也是极其巧妙的细节。总结是在 Forked Agent 里执行的（和主路经不同），但官方选择开启 prompt 缓存共享。

```typescript
// src/services/compact/compact.ts:435
// Forked Agent 借用主对话上下文的 Prompt Cache。
// 测试（2026年1月）证明这个借用机制能省掉每次压缩所需的极大头部填充 Token 开销
const promptCacheSharingEnabled = getFeatureValue_CACHED_MAY_BE_STALE(
  'tengu_compact_cache_prefix',
  true,
)
```

### 4.3 PTL 防御（Prompt Too Long Fallback）

倘若上述所有措施仍旧让总结服务报 `Prompt Too Long` 错误：

```typescript
// src/services/compact/compact.ts:462
// CC-1180: 若 compact request 本身也超限，则剥洋葱。
// 一次剥掉 20% 旧分组进行重试。这个是最后的“救命稻草”，虽然有损，但能解救被锁死的会话。
const truncated = ptlAttempts <= MAX_PTL_RETRIES
  ? truncateHeadForPTLRetry(messagesToSummarize, summaryResponse)
  : null
```

### 4.4 状态重启点补偿（State Re-injection）

总结一旦完成，原本长长的消息列表被抽成了一条极短的 `Summary Message`。但 Agent 对后续工作的理解不能断裂。

```typescript
// src/services/compact/compact.ts:517
// ===== 保存状态重组补偿区 =====

// 1. 获取并重新添加刚刚通过 FileReadTool 查看并且还没丢掉缓存的文件（带截断上限）
const fileAttachments = createPostCompactFileAttachments(preCompactReadFileState, ...)

// 2. 重新加入之前仍在进行中的 Plan / Skill
const planAttachment = createPlanAttachmentIfNeeded(context.agentId)
const skillAttachment = createSkillAttachmentIfNeeded(context.agentId)

// 3. 把被干掉的 Deferred Delta 工具协议重新用消息发给模型
for (const att of getDeferredToolsDeltaAttachment(...)) {
  postCompactFileAttachments.push(createAttachmentMessage(att))
}
```

**综合起来，上下文平稳度过“压缩”时的真正面貌是：**
`[System 边界宣告]` + `[精简文本摘要]` + `[正在查看的文件内文截取]` + `[正在做的 Plan]` + `[仍然激活的各种 MCP Server 和 Tools 的完整声明]`。

这个机制确保了大模型既释放了冗金庞大的旧文本历史，却依然如同长时程 Agent 那样“身处工作台旁边且手持刚刚用到的工具”，完全无缝连接下一轮输入。
