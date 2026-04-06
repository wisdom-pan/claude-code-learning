# 第二章：安全分析

[返回总目录](../README.md)

---

## 导读

本章从安全视角对 Claude Code 进行全方位剖析，回答三个问题：

1. **系统收集了哪些用户信息，如何被利用？**
2. **代码本身存在哪些安全风险点？源码是怎么写的？**
3. **系统为了保护用户的机器都建了哪些防线？**

> **写给新手的提示**：阅读本章不需要任何安全背景。凡是涉及代码的地方，我们都会用通俗语言先解释"这段代码在做什么"，再解释"它为什么与安全有关"。

---

## 第一节：用户信息收集与利用

Claude Code 在运行过程中会接触和记录多种用户数据。我们把它分为三层，从"最隐蔽"到"最明显"逐层展开。

### 1.1 第一层：进入模型的工作上下文（最隐蔽，风险最高）

**相关源码**：
- [`src/services/api/claude.ts`](../src/services/api/claude.ts)
- [`src/context.ts`](../src/context.ts)
- [`src/utils/queryContext.ts`](../src/utils/queryContext.ts)
- [`src/utils/attachments.ts`](../src/utils/attachments.ts)

这一层是最容易被忽视的，但往往风险最高。每次用户和 Claude 对话，以下内容会被打包成"上下文"发送到 Anthropic 的模型 API：

| 内容类型 | 具体包含 | 敏感程度 |
|----------|----------|----------|
| 用户输入 | 所有对话内容 | 高 |
| 历史对话 | 当前 session 的全部来回 | 高 |
| 工具执行结果 | 命令运行输出、文件读取内容 | **极高** |
| 文件与代码片段 | 当前编辑文件内容 | 极高 |
| Git 状态快照 | diff、commit 信息 | 高 |
| `CLAUDE.md` 与 memory 文件 | 用户自定义指令与长期记忆 | 高 |
| 图片、文档附件 | 截图、PDF 等 | 中~高 |
| MCP 资源内容 | 第三方工具返回的结果 | 不确定 |

**通俗解释**：想象你有一个开着麦克风的助理，每次你跟他说话，他不仅记住你说的话，还会把你桌上的文件、电脑屏幕上的代码、你最近运行的终端命令结果一并"报告"给后台服务器。这就是上下文的工作方式。

**为什么这层最危险**：因为用户通常只注意"有没有数据上传"，而忽略了"什么在发送给模型"。Anthropic 的服务器接收的不是某个打点事件，而是包含源码、命令输出、文件内容的完整工作上下文。

---

### 1.2 第二层：本地持久化存储

**相关源码**：
- [`src/utils/sessionStorage.ts`](../src/utils/sessionStorage.ts)
- [`src/utils/settings/types.ts`](../src/utils/settings/types.ts)

系统会在本地磁盘保存大量信息，即使退出程序也不会消失：

- **transcript JSONL**：每次对话的完整逐条记录，类似聊天记录的数据库
- **session metadata**：会话标题、标签、时间等元数据
- **agent transcript**：子 agent 运行的独立记录
- **本地用户配置与项目配置**：你在 `.claude/` 目录下的所有设置
- **OAuth 账户缓存**：已登录的账户凭证
- **memory 文件**：系统从历史对话中提炼的"长期记忆"

**一个重要细节**：配置项 `cleanupPeriodDays` 控制 transcript 保留的时长，**默认不为 0**，意味着历史对话会在本地持续积累。设置为 `0` 才会停止保留并清理已有记录。

对于隐私敏感场景，可以通过 CLI 参数 `--no-session-persistence` 或配置 `cleanupPeriodDays: 0` 来关闭 transcript 持久化。

---

### 1.3 第三层：Memory 长期积累

**相关源码**：
- [`src/memdir/memdir.ts`](../src/memdir/memdir.ts)
- [`src/services/extractMemories/extractMemories.ts`](../src/services/extractMemories/extractMemories.ts)
- [`src/services/SessionMemory/sessionMemory.ts`](../src/services/SessionMemory/sessionMemory.ts)
- [`src/tools/AgentTool/agentMemory.ts`](../src/tools/AgentTool/agentMemory.ts)

这是最"悄无声息"的一层。系统会自动从过去的对话中提炼关键信息，写入 memory 文件，并在未来的每一次对话开始时注入到模型的提示词中。

Memory 的类型包括：

- 用户偏好与习惯
- 用户的身份背景（职位、语言、技术栈）
- 当前项目的关键事实
- 参考信息与约束条件
- 当前会话摘要
- agent 角色记忆
- 团队共享记忆

**通俗类比**：这相当于助理悄悄写了一个"关于你的小本子"，每次你开口前，他都会先翻一遍这个本子，根据以前了解到的你来做出反应。从用户角度，这等于系统在持续构建一个"长期协作画像"，且会跨越 session 延续。

---

### 1.4 第四层：Telemetry 遥测数据

**相关源码**：
- [`src/services/analytics/index.ts`](../src/services/analytics/index.ts)
- [`src/services/analytics/config.ts`](../src/services/analytics/config.ts)
- [`src/services/analytics/metadata.ts`](../src/services/analytics/metadata.ts)
- [`src/services/analytics/sink.ts`](../src/services/analytics/sink.ts)
- [`src/services/analytics/datadog.ts`](../src/services/analytics/datadog.ts)
- [`src/utils/user.ts`](../src/utils/user.ts)

Telemetry（遥测）是指系统主动向外部服务（如 Datadog）发送的使用统计数据。Claude Code 采集的内容包括：

| 字段 | 说明 |
|------|------|
| `deviceId` | 设备唯一标识 |
| `sessionId` | 当次会话标识 |
| app version / platform / arch | 软件与系统版本信息 |
| terminal / CI 环境 | 运行环境类型 |
| account UUID / org UUID | 账户与组织标识 |
| subscriptionType / rateLimitTier | 订阅类型与配额级别 |
| repo remote hash | 远端仓库的哈希标识（非原文） |
| 工具使用事件 | 哪类工具被调用了多少次 |
| 文件路径 hash / 内容 hash | 文件的哈希指纹（非原文） |

**关键设计点**：源码中有一个专门的 TypeScript 类型标记值得注意：

```typescript
// src/services/analytics/index.ts
export type AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS = never
```

这是一个"开发者协议类型"：凡是要上报到遥测后端的字符串，开发者必须在代码里显式做类型转换，写下 `as AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS`，等同于手动签名"我确认这条数据不含代码或文件路径原文"。

这说明工程团队**有意识地**在尝试避免把源码原文打进遥测。但这不等于没有任何敏感元数据——行为统计、哈希指纹、账户标识等依然会持续上报。

---

### 1.5 第五层：Team Memory 同步与上传

**相关源码**：
- [`src/services/teamMemorySync/index.ts`](../src/services/teamMemorySync/index.ts)
- [`src/services/teamMemorySync/watcher.ts`](../src/services/teamMemorySync/watcher.ts)
- [`src/memdir/teamMemPaths.ts`](../src/memdir/teamMemPaths.ts)

当用户启用 Team Memory 功能时，系统会：

1. 按 repo 识别团队 memory 命名空间
2. 从服务器 pull 团队 memory 到本地
3. 监听本地 memory 目录的文件变更
4. 自动 push 本地变更回 Anthropic 服务器

上传的内容不是代码仓库本体，而是团队 memory 目录中的知识条目——但这些条目本身可能包含项目流程、内网知识库、运维路径、团队规章等敏感内容。

系统在这一步加入了客户端密钥扫描（见第三节详解），但本质仍是"组织级知识同步"，启用时请注意信息边界。

---

### 1.6 第六层：用户主动触发的内容上传

**相关源码**：
- [`src/components/FeedbackSurvey/submitTranscriptShare.ts`](../src/components/FeedbackSurvey/submitTranscriptShare.ts)
- [`src/services/api/grove.ts`](../src/services/api/grove.ts)
- [`src/components/grove/Grove.tsx`](../src/components/grove/Grove.tsx)

这部分最透明，但也值得了解：

- **Transcript 分享**：在用户提交反馈时，系统可能将会话记录（含 JSONL 原始数据）上传给 Anthropic，代码会做一定脱敏处理，但仍属于会话内容上传。
- **Grove / "帮助改善 Claude"**：若用户开启此功能，其编码会话和对话可能被用于模型训练与改进。这一功能的收集范围最广，且直接影响模型训练数据，如对隐私敏感应默认关闭。

---

### 1.7 信息利用综合评估

从用户视角，三类被利用的方式如下：

```
┌─────────────────────────────────────────────────────────────────────┐
│  层级        │  信息类型            │  用途                          │
├─────────────────────────────────────────────────────────────────────┤
│  模型上下文   │  源码、命令、文件    │  生成回答、编写代码、决策工具调用 │
│  本地存储     │  transcript、memory  │  会话恢复、长期记忆注入         │
│  遥测         │  行为元数据、哈希    │  产品分析、稳定性监控、实验分流  │
│  云同步       │  团队 memory         │  组织知识共享                  │
│  主动上传     │  transcript、sessions│  模型训练、反馈分析             │
└─────────────────────────────────────────────────────────────────────┘
```

**最关键的结论**：真正的风险不在于某个单点的数据打点，而是"进入模型的工作上下文 + 本地长期 memory + 外部同步能力"三者叠加后形成的**信息发散边界**。

---

## 第二节：软件代码安全分析

本节分析源码中存在的安全风险点，以及攻击者可能的攻击路径。

### 2.1 Prompt Injection（提示词注入）攻击

**风险描述**：Claude Code 能够读取文件、网页、MCP 工具返回的内容，并将这些内容嵌入模型上下文。如果外部内容中包含精心构造的"指令"，模型可能会错误地执行攻击者的命令。

这类攻击被称为 **Prompt Injection**，在 AI coding agent 场景下尤为危险：攻击者可以在一个开源仓库的代码注释里隐藏指令，当用户让 Claude 阅读这段代码时，Claude 可能被诱导执行恶意操作。

**更隐蔽的变种——Unicode 隐写攻击**：攻击者可以使用不可见的 Unicode 字符（用户肉眼看不见，但模型能识别）把指令藏进普通文字中。

**源码的应对方案**：

```typescript
// src/utils/sanitization.ts

export function partiallySanitizeUnicode(prompt: string): string {
  let current = prompt
  let previous = ''
  let iterations = 0
  const MAX_ITERATIONS = 10

  while (current !== previous && iterations < MAX_ITERATIONS) {
    previous = current

    // Step 1: NFKC 规范化，把"看起来像 A 其实是合成字符"的情况统一化
    current = current.normalize('NFKC')

    // Step 2: 删除危险的 Unicode 分类字符  
    current = current.replace(/[\p{Cf}\p{Co}\p{Cn}]/gu, '')

    // Step 3: 显式删除已知危险范围（双重保险）
    current = current
      .replace(/[\u200B-\u200F]/g, '')   // 零宽字符
      .replace(/[\u202A-\u202E]/g, '')   // 方向性格式字符（可用于文字反转欺骗）
      .replace(/[\u2066-\u2069]/g, '')   // 方向隔离字符
      .replace(/[\uFEFF]/g, '')          // BOM（字节顺序标记）
      .replace(/[\uE000-\uF8FF]/g, '')   // 私有使用区字符

    iterations++
  }
  return current
}
```

**新手解读**：
- `\u200B` 这类字符是"零宽字符"，在屏幕上完全不显示但存在于文本数据中
- 攻击者曾用这些字符在 MCP 工具返回的内容里隐藏恶意指令（HackerOne 漏洞报告 #3086545）
- `normalize('NFKC')` 会把"看起来像普通字母但实际上是特殊 Unicode 变体"的字符统一化，防止绕过
- 整个清洗过程循环执行直到文本不再变化（最多 10 次），防止嵌套混淆

这个清洗函数还有一个递归版本 `recursivelySanitizeUnicode`，能处理 JSON 对象、数组等嵌套结构中的所有字符串字段，确保 MCP 工具的任何返回值都经过清洗。

---

### 2.2 Shell 命令注入

**风险描述**：Claude Code 可以执行 Bash/PowerShell 命令。如果攻击者能让模型生成含有恶意载荷的命令字符串，就可能劫持宿主机。

**源码的应对方案——危险模式黑名单**：

```typescript
// src/utils/permissions/dangerousPatterns.ts

export const DANGEROUS_BASH_PATTERNS: readonly string[] = [
  // 代码解释器（可运行任意代码）
  'python', 'python3', 'node', 'deno', 'ruby', 'perl', 'php',
  // 包运行器
  'npx', 'bunx', 'npm run', 'yarn run',
  // Shell
  'bash', 'sh', 'zsh', 'fish',
  // 危险操作符
  'eval', 'exec', 'env', 'xargs', 'sudo',
  // 远程执行
  'ssh',
]
```

这个"危险模式"列表的作用是：在 **Auto Mode**（自动批准模式）下，如果权限规则配置为 `Bash(python:*)` 或 `Bash(node:*)` 这类宽泛授权，系统会自动撤销这些规则。原因是这类规则等于"允许 AI 无限制运行任意 Python/Node 脚本"，其危险程度等同于系统管理员权限。

相应的检测函数：

```typescript
// src/utils/permissions/permissionSetup.ts

export function isDangerousBashPermission(
  toolName: string,
  ruleContent: string | undefined,
): boolean {
  if (toolName !== BASH_TOOL_NAME) return false

  // 空规则或 * 通配符 = 允许所有命令 = 极度危险
  if (ruleContent === undefined || ruleContent === '' || ruleContent === '*') {
    return true
  }

  for (const pattern of DANGEROUS_BASH_PATTERNS) {
    if (content === `${pattern}:*`) return true  // "python:*" 匹配任意 python 命令
    if (content === `${pattern}*`) return true   // "python*" 匹配 python, python3 等
    if (content === `${pattern} *`) return true  // "python *" 匹配 python + 任意参数
  }
  return false
}
```

**新手解读**：假设用户配置了 `Bash(python:*)` 的权限，意思是"让 Claude 自动批准所有 python 开头的命令"。但这等于给了 AI 一个无限制运行 Python 脚本的权利——可以读写任意文件、发起网络请求。系统检测到这类规则后，在进入自动模式前会把它们临时移除（`stripDangerousPermissionsForAutoMode`），退出自动模式后再恢复（`restoreDangerousPermissions`）。

---

### 2.3 Git 逃逸攻击

**风险描述**：这是一个非常精妙的多阶段攻击。Claude Code 的沙盒内会执行某些命令，但有些 Git 操作发生在沙盒外（宿主机上）。攻击者可以：

1. 在沙盒内创建一个"裸 Git 仓库"的目录结构（含 `HEAD`、`objects/`、`refs/`）
2. 在这个假仓库中注入带有恶意钩子的 `core.fsmonitor` 配置
3. 当用户在宿主机（沙盒外）执行 `git log` 等命令时，触发恶意钩子

**源码的应对方案**：

```typescript
// src/utils/sandbox/sandbox-adapter.ts

function scrubBareGitRepoFiles(directory: string): void {
  // 命令执行完毕后，强制扫描并清空沙盒内被植入的 Git 裸库文件
  // 具体清理：HEAD、objects/、refs/ 等核心 Git 目录
}
```

这个函数在每次沙盒命令执行完毕后都会运行，从源头扫除多阶段 Git 逃逸的可能性。

---

### 2.4 MCP 服务器的不可信输入

**风险描述**：MCP（Model Context Protocol）允许第三方服务器向 Claude 提供工具能力。这意味着一个不受信任的 MCP 服务器可以：

- 返回包含恶意指令的"工具结果"
- 利用上面提到的 Prompt Injection 方式操控 Claude

源码在这一层的防御是多重的：
1. `recursivelySanitizeUnicode` 清洗所有 MCP 返回内容中的 Unicode 危险字符
2. 独立的权限认证系统（`src/services/mcp/auth.ts`）控制 MCP 工具的访问权限
3. 沙盒将 MCP 触发的文件写入操作限制在白名单路径内

---

## 第三节：防范性安全措施

本节梳理 Claude Code 为了保护用户机器所构建的多层防线。

### 3.1 双重权限闸：应用层 + 系统层

Claude Code 采用"双闸门"架构，即使一层被突破，另一层仍然有效：

```
AI 发出命令
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  第一道闸：Tool Permission（应用层逻辑拦截）          │
│  文件：src/utils/permissions/permissionSetup.ts      │
│  作用：判断 AI 想执行的操作是否已被用户显式允许       │
│  拦截方式：对话中弹出确认提示，用户可以选择拒绝       │
└─────────────────────────────────────────────────────┘
    │（通过后）
    ▼
┌─────────────────────────────────────────────────────┐
│  第二道闸：Sandbox（系统级隔离）                     │
│  文件：src/utils/sandbox/sandbox-adapter.ts          │
│  作用：即使 AI 的命令获得了权限，也只能在隔离环境执行 │
│  拦截方式：内核级 Namespace 隔离，无法突破文件和网络边界│
└─────────────────────────────────────────────────────┘
    │（最终执行）
    ▼
  受限执行环境
```

---

### 3.2 Sandbox 沙盒技术详解

**相关源码**：[`src/utils/sandbox/sandbox-adapter.ts`](../src/utils/sandbox/sandbox-adapter.ts)

沙盒是整个安全体系的底层基础设施。

**底层引擎**：

| 操作系统 | 使用技术 | 原理 |
|----------|----------|------|
| Linux / WSL2 | `bubblewrap (bwrap)` + `socat` | 内核 Namespace 隔离 |
| macOS | 原生沙盒框架 | macOS 系统调用沙盒 |

**新手解读 Namespace 隔离**：Linux 的 Namespace 是一种内核功能，让一个进程"看到"的文件系统、网络、进程表等是完全独立的视图。沙盒内的程序就算疯狂写入 `/etc/passwd`，宿主机上的真实文件也完全不受影响——因为沙盒进程根本"看不到"真正的 `/etc/passwd`。

**白名单驱动的细粒度控制**：沙盒不是把 AI 关在黑屋子里什么都不让做，而是精确控制"哪些路径可以读写，哪些域名可以访问"。

```typescript
// sandbox-adapter.ts 中的核心转换逻辑 (伪代码示意)
function convertToSandboxRuntimeConfig(permissions) {
  return {
    filesystem: {
      allowWrite: [...用户显式允许写入的路径],
      denyWrite:  [...系统核心路径，如 ~/.claude/settings.json],
      allowRead:  [...用户显式允许读取的路径],
      denyRead:   [...敏感配置路径]
    },
    network: {
      allowedDomains:  [...从 WebFetchTool 规则中提取的允许域名],
      deniedDomains:   [...被拒绝的域名],
      allowManagedOnly: [...企业管控模式下只允许受管域名]
    }
  }
}
```

**内置保护白名单**：即使用户自己的配置出了问题，沙盒也会自动保护：
- `~/.claude/settings.json`（主配置不被篡改）
- 当前工作目录的 `.claude/` 设置文件
- `.claude/skills/` 技能目录

**热更新同步**：系统通过 `settingsChangeDetector` 监听宿主机配置文件变化，一旦用户在运行过程中修改权限配置，沙盒内存中的配置也会通过 `refreshConfig()` 实时同步—— AI 无法利用"配置已改但沙盒还用旧规则"的时间窗口逃逸。

---

### 3.3 权限模式分级体系

**相关源码**：
- [`src/utils/permissions/PermissionMode.ts`](../src/utils/permissions/PermissionMode.ts)
- [`src/utils/permissions/permissionSetup.ts`](../src/utils/permissions/permissionSetup.ts)

系统定义了多种权限模式，从最严格到最宽松：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `default` | 每次操作前弹出确认 | 日常使用，最安全 |
| `acceptEdits` | 自动批准文件编辑，命令仍需确认 | 轻度自动化 |
| `plan` | 只允许规划，不执行任何写操作 | 方案评审 |
| `auto` | 分类器自动判断是否安全，安全的自动执行 | 高效开发 |
| `bypassPermissions` | 跳过所有权限检查（危险！） | CI/CD、测试脚本 |

**`bypassPermissions` 的重要保护**：这是最危险的模式。源码中有两层防护：

```typescript
// src/utils/permissions/bypassPermissionsKillswitch.ts

// 保护一：Statsig 远程开关（组织级管控）
const growthBookDisableBypassPermissionsMode =
  checkStatsigFeatureGate_CACHED_MAY_BE_STALE('tengu_disable_bypass_permissions_mode')

// 保护二：本地设置禁用
const settingsDisableBypassPermissionsMode =
  settings.permissions?.disableBypassPermissionsMode === 'disable'
```

也就是说，企业可以通过远程策略（Statsig 开关）或本地配置，强制禁用 `bypassPermissions` 模式，即使用户在命令行传了 `--dangerously-skip-permissions` 参数也会被忽略并通知用户。

---

### 3.4 客户端密钥扫描（Secret Scanner）

**相关源码**：[`src/services/teamMemorySync/secretScanner.ts`](../src/services/teamMemorySync/secretScanner.ts)

为了防止用户意外把 API 密钥、访问令牌等敏感凭据上传到 Team Memory 服务，系统内置了一套完整的正则表达式密钥扫描器——在内容离开本地前，先做一遍扫描。

扫描的密钥类型涵盖主流平台，以下是部分规则节选：

```typescript
// src/services/teamMemorySync/secretScanner.ts

const SECRET_RULES: SecretRule[] = [
  // AWS 访问密钥（以 AKIA/ASIA 等前缀开头）
  { id: 'aws-access-token',
    source: '\\b((?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16})\\b' },

  // Anthropic 自家 API Key（编译期拼接，避免密文出现在代码里）
  { id: 'anthropic-api-key',
    source: `\\b(${ANT_KEY_PFX}03-[a-zA-Z0-9_\\-]{93}AA)(?:...)` },

  // GitHub Personal Access Token
  { id: 'github-pat', source: 'ghp_[0-9a-zA-Z]{36}' },

  // OpenAI API Key
  { id: 'openai-api-key',
    source: '\\b(sk-(?:proj|svcacct|admin)-...' },

  // Stripe、Shopify、Slack、npm、PyPI 等 30+ 种凭据模式
  // ...（完整列表见源码）

  // 私钥文件（PEM 格式）
  { id: 'private-key',
    source: '-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY...' },
]
```

**工程亮点**：
1. **扫描结果不返回命中文本**：函数 `scanForSecrets` 返回的是"哪条规则命中了"，而非密钥原文，防止扫描本身成为信息泄漏渠道
2. **Redact 而非拒绝**：`redactSecrets` 函数可以把密钥替换为 `[REDACTED]` 而不是直接报错丢弃，保持上下文可读性
3. **Anthropic 自家密钥的特殊处理**：`ANT_KEY_PFX` 通过字符串拼接 `['sk', 'ant', 'api'].join('-')` 在运行时构造，避免密钥前缀字面量出现在打包后的 bundle 文件中（防止自动扫描工具误报）

---

### 3.5 遥测数据的隐私隔离设计

**相关源码**：
- [`src/services/analytics/index.ts`](../src/services/analytics/index.ts)
- [`src/utils/privacyLevel.ts`](../src/utils/privacyLevel.ts)

**分级隐私控制**：

```typescript
// src/utils/privacyLevel.ts

type PrivacyLevel = 'default' | 'no-telemetry' | 'essential-traffic'

export function getPrivacyLevel(): PrivacyLevel {
  if (process.env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC) {
    return 'essential-traffic'  // 最严格：关闭一切非必要网络
  }
  if (process.env.DISABLE_TELEMETRY) {
    return 'no-telemetry'       // 关闭遥测，保留自动更新等
  }
  return 'default'              // 全功能开启
}
```

三种级别说明：

| 级别 | 关闭内容 |
|------|----------|
| `default` | 全功能开启 |
| `no-telemetry` | 关闭 Datadog、1P 事件日志、反馈调查 |
| `essential-traffic` | 在 no-telemetry 基础上，额外关闭自动更新、Grove、Release Notes、Model Capabilities 获取等 |

**PII 路由保护**：遥测数据在发送前，PII（个人身份信息）相关字段会被路由到有访问控制的专属 BigQuery 列，而不会出现在通用的 Datadog 日志流中：

```typescript
// src/services/analytics/index.ts

// _PROTO_* 前缀的字段是 PII 标记字段，只会出现在有权限的 1P 导出渠道
// 发送到 Datadog 前必须经过 stripProtoFields 脱敏
export function stripProtoFields<V>(
  metadata: Record<string, V>,
): Record<string, V> {
  // 删除所有 _PROTO_ 开头的字段，再发给 Datadog
}
```

**MCP 工具名脱敏**：MCP 工具的名称格式是 `mcp__<server>__<tool>`，其中 server 名可能暴露用户的私有 MCP 服务器配置（视为中等敏感 PII）。上报前会被替换为通用标签 `mcp_tool`：

```typescript
// src/services/analytics/metadata.ts

export function sanitizeToolNameForAnalytics(toolName: string) {
  if (toolName.startsWith('mcp__')) {
    return 'mcp_tool'  // 不暴露用户的 MCP 服务器名称
  }
  return toolName
}
```

---

### 3.6 路径安全验证

**相关源码**：
- [`src/utils/permissions/pathValidation.ts`](../src/utils/permissions/pathValidation.ts)
- [`src/utils/permissions/filesystem.ts`](../src/utils/permissions/filesystem.ts)

系统对所有文件路径操作进行了防御性校验，防止 **Path Traversal**（路径穿越）攻击——一种通过 `../../etc/passwd` 类似的路径绕过限制目录的攻击手法。

Team Memory 同步的路径保护在 `secretScanner.ts` 中有专门的 path traversal 防护，确保即使 MCP 或 AI 尝试操作类似 `../../../important_file` 的路径，也会被拦截。

---

## 本章小结

Claude Code 的安全架构可以用一个同心圆来理解：

```
                    ┌──────────────────────────────────┐
                    │     遥测隐私隔离 + 密钥扫描       │  ← 数据出境防线
                 ┌──┼──────────────────────────────────┼──┐
                 │  │       权限模式分级管控             │  │ ← 策略防线
              ┌──┼──┼──────────────────────────────────┼──┼──┐
              │  │  │   Tool Permission 应用层拦截       │  │  │ ← 应用防线
           ┌──┼──┼──┼──────────────────────────────────┼──┼──┼──┐
           │  │  │  │       Sandbox 系统级隔离           │  │  │  │ ← 底层防线
           │  │  │  │  Unicode 清洗 / 路径校验           │  │  │  │
           └──┼──┼──┼──────────────────────────────────┼──┼──┼──┘
              └──┼──┼──────────────────────────────────┼──┼──┘
                 └──┼──────────────────────────────────┼──┘
                    └──────────────────────────────────┘
                                   │
                              宿主机（受保护）
```

**总体评价**：
- Claude Code **绝非**零风险产品——进入模型的上下文是最大的信息泄漏界面，这是此类产品的结构性特征，无法通过关闭遥测来规避
- 但工程团队在安全防护方面投入了相当多的精力：双重权限闸、沙盒隔离、密钥扫描、Unicode 清洗、危险模式拦截等机制都有扎实的源码实现
- 对用户来说，**最有效的安全措施**是：了解哪些内容会进入模型上下文，并主动控制输入的边界
