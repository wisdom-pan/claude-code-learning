# 第七章：Sandbox 技术实现细节与运行机制

[返回总目录](../README.md)

## 1. 本章导读

这一章不再停留在“Claude Code 有个 sandbox 开关”这一层，而是直接回答四个实现问题：

1. 一个 Bash 命令到底什么时候会进入沙箱
2. 配置文件里的 `permissions` / `sandbox` 规则是怎么被翻译成底层隔离配置的
3. sandbox 和应用层 permission system 是什么关系，谁先判断，谁兜底
4. 代码里有哪些明确的沙箱逃逸防护，而不是抽象意义上的“更安全”

本章主要依据这些实现：

- [`src/tools/BashTool/shouldUseSandbox.ts`](../src/tools/BashTool/shouldUseSandbox.ts)
- [`src/tools/BashTool/bashPermissions.ts`](../src/tools/BashTool/bashPermissions.ts)
- [`src/tools/BashTool/BashTool.tsx`](../src/tools/BashTool/BashTool.tsx)
- [`src/utils/Shell.ts`](../src/utils/Shell.ts)
- [`src/utils/sandbox/sandbox-adapter.ts`](../src/utils/sandbox/sandbox-adapter.ts)
- [`src/utils/permissions/pathValidation.ts`](../src/utils/permissions/pathValidation.ts)
- [`src/components/permissions/SandboxPermissionRequest.tsx`](../src/components/permissions/SandboxPermissionRequest.tsx)
- [`src/components/sandbox/SandboxDoctorSection.tsx`](../src/components/sandbox/SandboxDoctorSection.tsx)

先给结论：

这个项目里的 sandbox 不是一个“调用前包一层 bwrap”那么简单的功能，而是一个四层结构：

1. `shouldUseSandbox()` 决定某条命令是否应该进沙箱
2. `convertToSandboxRuntimeConfig()` 把 Claude Code 自己的 settings 语义翻译成 sandbox runtime 能理解的文件系统和网络限制
3. `bashPermissions.ts` 把“沙箱自动放行”和“显式 deny / ask 规则”揉在一起，避免沙箱把权限系统绕过去
4. `Shell.ts` 和 `cleanupAfterCommand()` 负责把命令真正包进隔离环境，并在命令结束后做宿主机级清理

所以，sandbox 在这个项目里不是外围附属模块，而是 Bash 执行链路的一部分。

## 2. 总体架构：不是单点功能，而是一条执行链

先看整体流程：

```text
模型生成 BashTool 调用
  -> shouldUseSandbox()
     -> false: 走普通 Bash 权限路径
     -> true:
        -> bashPermissions.checkSandboxAutoAllow()
        -> Shell.ts
        -> SandboxManager.wrapWithSandbox()
        -> sandbox-runtime / bwrap / macOS runtime
        -> 命令执行
        -> cleanupAfterCommand()
        -> scrubBareGitRepoFiles()

settings.permissions / settings.sandbox
  -> convertToSandboxRuntimeConfig()
  -> 影响 wrapWithSandbox() 的 runtime config
  -> 同时影响 bashPermissions 和 pathValidation

网络越权访问
  -> SandboxPermissionRequest

依赖缺失 / 平台不支持
  -> SandboxDoctorSection
```

这张图说明了一个关键事实：

- sandbox 不是独立于 permissions 的第二套系统
- 它是“命令执行隔离”和“权限决策系统”共同作用的结果

如果只看 `sandbox-adapter.ts`，会误以为它只是配置转换器；但如果把 [`src/tools/BashTool/bashPermissions.ts`](../src/tools/BashTool/bashPermissions.ts) 和 [`src/utils/Shell.ts`](../src/utils/Shell.ts) 连起来看，就会发现它已经深入到了命令放行、执行、清理三个阶段。

## 3. 第一步：命令什么时候会进入沙箱

相关实现：

- [`src/tools/BashTool/shouldUseSandbox.ts`](../src/tools/BashTool/shouldUseSandbox.ts)
- [`src/tools/BashTool/BashTool.tsx`](../src/tools/BashTool/BashTool.tsx)
- [`src/utils/Shell.ts`](../src/utils/Shell.ts)

这里最核心的判断函数就是 `shouldUseSandbox()`。

### 3.1 原始实现

**真实源码**（摘自 [`src/tools/BashTool/shouldUseSandbox.ts`](../src/tools/BashTool/shouldUseSandbox.ts)）：

```ts
export function shouldUseSandbox(input: Partial<SandboxInput>): boolean {
  if (!SandboxManager.isSandboxingEnabled()) {
    return false
  }

  if (
    input.dangerouslyDisableSandbox &&
    SandboxManager.areUnsandboxedCommandsAllowed()
  ) {
    return false
  }

  if (!input.command) {
    return false
  }

  if (containsExcludedCommand(input.command)) {
    return false
  }

  return true
}
```

这段实现非常重要，因为它把“是否启用 sandbox”从单纯的全局配置，变成了“全局开关 + 单次工具调用参数 + excludedCommands”三者共同决定的结果。

### 3.2 可以改写成下面的伪代码

```text
if sandbox 本身不可用:
  不进沙箱

if 当前调用显式要求禁用沙箱
  且策略允许执行 unsandboxed command:
  不进沙箱

if 当前没有 command:
  不进沙箱

if command 命中 excludedCommands:
  不进沙箱

否则:
  进沙箱
```

### 3.3 `excludedCommands` 是“便利特性”，不是安全边界

这点在源码里写得非常直白：

```ts
// NOTE: excludedCommands is a user-facing convenience feature, not a security boundary.
// It is not a security bug to be able to bypass excludedCommands — the sandbox permission
// system (which prompts users) is the actual security control.
```

这意味着：

- `excludedCommands` 的设计目标不是安全收口
- 它只是告诉系统“这类命令不要自动进沙箱”
- 真正的安全边界仍然是 permission system 和 sandbox runtime 本身

这也是一个很工程化的设计：用户可以对 `bazel`、`docker`、某些本地测试命令做兼容性豁免，但不能把它当成可信安全规则语言。

### 3.4 决策结果如何进入执行链

[`src/tools/BashTool/BashTool.tsx`](../src/tools/BashTool/BashTool.tsx) 最终把这个布尔值传给 shell 执行层：

```ts
const shellCommand = await exec(command, abortController.signal, 'bash', {
  timeout: timeoutMs,
  preventCwdChanges,
  shouldUseSandbox: shouldUseSandbox(input),
  shouldAutoBackground
})
```

到了 [`src/utils/Shell.ts`](../src/utils/Shell.ts) 才真正包一层 runtime：

```ts
if (shouldUseSandbox) {
  commandString = await SandboxManager.wrapWithSandbox(
    commandString,
    sandboxBinShell,
    undefined,
    abortSignal,
  )
}
```

也就是说：

- `BashTool` 只负责判断
- `Shell.ts` 负责真正把命令变成“沙箱内命令”

这是很明确的分层。

## 4. 第二步：Claude Code 的 settings 是怎么翻译成沙箱配置的

相关实现：

- [`src/utils/sandbox/sandbox-adapter.ts`](../src/utils/sandbox/sandbox-adapter.ts)

这部分的核心函数是 `convertToSandboxRuntimeConfig()`。它不是简单转字段，而是在做一层“语义翻译”。

### 4.1 这个函数做的不是 merge，而是语义重解释

先看源码入口：

```ts
export function convertToSandboxRuntimeConfig(
  settings: SettingsJson,
): SandboxRuntimeConfig {
  const permissions = settings.permissions || {}

  const allowedDomains: string[] = []
  const deniedDomains: string[] = []

  const allowWrite: string[] = ['.', getClaudeTempDir()]
  const denyWrite: string[] = []
  const denyRead: string[] = []
  const allowRead: string[] = []
```

这里已经能看出两件事：

1. `permissions` 和 `sandbox.*` 两套配置都会被纳入 runtime config
2. 运行时有一批内置初始规则，并不是完全以用户配置为准

例如：

- `allowWrite` 默认就包含 `.` 和 Claude temp dir
- settings 文件路径会被强制塞进 `denyWrite`

### 4.2 路径语义分成两套，不能混着理解

这部分是当前文档里最容易被忽略，但实际最重要的实现细节之一。

源码里专门写了两个不同的解析函数：

```ts
export function resolvePathPatternForSandbox(
  pattern: string,
  source: SettingSource,
): string

export function resolveSandboxFilesystemPath(
  pattern: string,
  source: SettingSource,
): string
```

它们分别处理两类路径：

1. permission rule 里的路径
2. `sandbox.filesystem.*` 里的路径

两者的语义不一样。

**真实源码注释**（摘自 [`src/utils/sandbox/sandbox-adapter.ts`](../src/utils/sandbox/sandbox-adapter.ts)）：

```ts
 * Claude Code uses special path prefixes in permission rules:
 * - `//path` → absolute from filesystem root
 * - `/path` → relative to settings file directory
```

而对于 `sandbox.filesystem.*`：

```ts
 * Unlike permission rules (Edit/Read), these settings use standard path semantics:
 * - `/path` → absolute path
 * - `~/path` → expanded to home directory
 * - `./path` or `path` → relative to settings file directory
```

这说明：

- `permissions.allow = ["Edit(/foo)"]` 里的 `/foo` 是相对 settings 根目录
- `sandbox.filesystem.allowWrite = ["/foo"]` 里的 `/foo` 才是真正绝对路径

如果不把这点讲清楚，就很容易把整个 sandbox 行为理解错。

### 4.3 文件系统规则的真实构造过程

可以把 `convertToSandboxRuntimeConfig()` 的文件系统部分改写成下面这段伪代码：

```text
初始化:
  allowWrite = ['.', ClaudeTempDir]
  denyWrite = []
  denyRead = []
  allowRead = []

内置保护:
  永远拒绝写 settings.json / settings.local.json / managed settings drop-in
  永远拒绝写 .claude/skills
  针对 cwd / originalCwd 都做保护

兼容 Git worktree:
  如果当前是 worktree，把 main repo path 加入 allowWrite

兼容 add-dir:
  把 additionalDirectories 和 session add-dir 注入 allowWrite

遍历所有 setting source:
  从 permissions.allow/deny 提取 Edit / Read 规则
  从 sandbox.filesystem.allowWrite/denyWrite/allowRead/denyRead 提取规则
  按 source 解析路径语义

生成 runtime config:
  filesystem = { allowWrite, denyWrite, allowRead, denyRead }
```

### 4.4 原始函数片段：从 permission rules 中提取文件系统规则

```ts
for (const source of SETTING_SOURCES) {
  const sourceSettings = getSettingsForSource(source)

  if (sourceSettings?.permissions) {
    for (const ruleString of sourceSettings.permissions.allow || []) {
      const rule = permissionRuleValueFromString(ruleString)
      if (rule.toolName === FILE_EDIT_TOOL_NAME && rule.ruleContent) {
        allowWrite.push(
          resolvePathPatternForSandbox(rule.ruleContent, source),
        )
      }
    }

    for (const ruleString of sourceSettings.permissions.deny || []) {
      const rule = permissionRuleValueFromString(ruleString)
      if (rule.toolName === FILE_EDIT_TOOL_NAME && rule.ruleContent) {
        denyWrite.push(resolvePathPatternForSandbox(rule.ruleContent, source))
      }
      if (rule.toolName === FILE_READ_TOOL_NAME && rule.ruleContent) {
        denyRead.push(resolvePathPatternForSandbox(rule.ruleContent, source))
      }
    }
  }
}
```

这里的关键点不是“循环提取规则”，而是：

- 它不是只读 merged settings，而是按 `SETTING_SOURCES` 逐源处理
- 这是因为路径解析依赖 source，不同来源的 `/foo` 需要映射到不同 settings 根目录

也就是说，source 在这里不是 metadata，而是路径语义的一部分。

### 4.5 网络规则不是独立配置，而是从 `WebFetch` 权限规则反推出来的

源码里对网络域名的提取逻辑也很直接：

```ts
for (const ruleString of permissions.allow || []) {
  const rule = permissionRuleValueFromString(ruleString)
  if (
    rule.toolName === WEB_FETCH_TOOL_NAME &&
    rule.ruleContent?.startsWith('domain:')
  ) {
    allowedDomains.push(rule.ruleContent.substring('domain:'.length))
  }
}
```

这说明 Claude Code 并没有把“网络权限”和“WebFetch 权限”完全拆开，而是把：

- `WebFetch(domain:example.com)` 这种应用层规则
- 转换成 sandbox runtime 能识别的网络 allowlist

这样做的结果是：上层工具权限和底层网络隔离保持一致，而不是各玩各的。

### 4.6 `allowManagedDomainsOnly` 是一个更强的策略钳制

相关实现：

- [`src/utils/sandbox/sandbox-adapter.ts`](../src/utils/sandbox/sandbox-adapter.ts)
- [`src/components/permissions/SandboxPermissionRequest.tsx`](../src/components/permissions/SandboxPermissionRequest.tsx)

源码里专门提供了：

```ts
export function shouldAllowManagedSandboxDomainsOnly(): boolean {
  return (
    getSettingsForSource('policySettings')?.sandbox?.network
      ?.allowManagedDomainsOnly === true
  )
}
```

它的含义不是“默认优先使用托管域名”，而是：

- 一旦 policy 开启这个选项
- sandbox 的网络放行只能来自 managed / policy source
- 运行时的 ask callback 也会被包装，直接拒绝临时放行

初始化时的实现非常明确：

```ts
const wrappedCallback: SandboxAskCallback | undefined = sandboxAskCallback
  ? async (hostPattern: NetworkHostPattern) => {
      if (shouldAllowManagedSandboxDomainsOnly()) {
        return false
      }
      return sandboxAskCallback(hostPattern)
    }
  : undefined
```

这实际上把“用户交互层的临时允许”也封死了。

## 5. 第三步：代码里有哪些内建逃逸防护

相关实现：

- [`src/utils/sandbox/sandbox-adapter.ts`](../src/utils/sandbox/sandbox-adapter.ts)
- [`src/utils/Shell.ts`](../src/utils/Shell.ts)

如果只把 sandbox 理解成“限制读写目录”，会低估这段实现的安全强度。这里有多处明显是针对真实攻击路径加的补丁。

### 5.1 settings 文件和 `.claude/skills` 被强制加入 denyWrite

源码里这段非常关键：

```ts
const settingsPaths = SETTING_SOURCES.map(source =>
  getSettingsFilePathForSource(source),
).filter((p): p is string => p !== undefined)
denyWrite.push(...settingsPaths)
denyWrite.push(getManagedSettingsDropInDir())

denyWrite.push(resolve(originalCwd, '.claude', 'skills'))
if (cwd !== originalCwd) {
  denyWrite.push(resolve(cwd, '.claude', 'skills'))
}
```

这代表系统不是只保护“代码文件”，而是保护 Claude 自己的控制平面：

- settings 文件不能被 sandbox 内命令偷偷改掉
- `.claude/skills` 也不能被投毒

为什么 `.claude/skills` 值得单独保护？源码注释写得很清楚：

```ts
// Skills have the same privilege level
// (auto-discovered, auto-loaded, full Claude capabilities)
```

也就是说，一旦允许写 skills 目录，本质上就是允许命令去注入未来会被自动加载的高权限能力。

### 5.2 针对 Git bare repo 逃逸做了专门清理

这是整套 sandbox 里最有代表性的“现实攻击面防护”。

源码注释：

```ts
// SECURITY: Git's is_git_directory() treats cwd as a bare repo if it has
// HEAD + objects/ + refs/. An attacker planting these (plus a config with
// core.fsmonitor) escapes the sandbox when Claude's unsandboxed git runs.
```

这段注释几乎已经把攻击链写出来了：

1. 沙箱内命令在 cwd 植入伪造 bare repo 文件
2. 后续 Claude 在宿主机无沙箱执行某些 git 命令
3. Git 把当前目录当成 repo 处理
4. 恶意 `core.fsmonitor` 等配置被宿主机 git 消费
5. 从“沙箱内写文件”升级成“宿主机执行恶意逻辑”

对应实现分成两步：

第一步，在构建 config 时尽量把已存在的关键路径直接加到 `denyWrite`：

```ts
const bareGitRepoFiles = ['HEAD', 'objects', 'refs', 'hooks', 'config']
for (const dir of cwd === originalCwd ? [originalCwd] : [originalCwd, cwd]) {
  for (const gitFile of bareGitRepoFiles) {
    const p = resolve(dir, gitFile)
    try {
      statSync(p)
      denyWrite.push(p)
    } catch {
      bareGitRepoScrubPaths.push(p)
    }
  }
}
```

第二步，对“配置时不存在、执行后才被种出来”的路径，在命令结束后同步清理：

```ts
function scrubBareGitRepoFiles(): void {
  for (const p of bareGitRepoScrubPaths) {
    try {
      rmSync(p, { recursive: true })
    } catch {
      // ENOENT is the expected common case
    }
  }
}
```

而这个清理又被挂到了 `cleanupAfterCommand()`：

```ts
cleanupAfterCommand: (): void => {
  BaseSandboxManager.cleanupAfterCommand()
  scrubBareGitRepoFiles()
}
```

再由 [`src/utils/Shell.ts`](../src/utils/Shell.ts) 在命令结束时触发：

```ts
if (shouldUseSandbox) {
  SandboxManager.cleanupAfterCommand()
}
```

这说明 sandbox 的安全边界不是“进了隔离环境就结束”，而是：

- 执行前：构造限制
- 执行中：runtime 隔离
- 执行后：宿主机残留清理

这是完整攻击链视角下的防护，而不是单次调用视角。

## 6. 第四步：sandbox 和 permission system 是怎么耦合的

相关实现：

- [`src/tools/BashTool/bashPermissions.ts`](../src/tools/BashTool/bashPermissions.ts)
- [`src/utils/permissions/pathValidation.ts`](../src/utils/permissions/pathValidation.ts)

这一层是最容易被误解的：很多人会以为“既然进了沙箱，就不需要 permission prompt 了”。源码不是这么实现的。

### 6.1 `autoAllowBashIfSandboxed` 不是无脑放行

[`src/tools/BashTool/bashPermissions.ts`](../src/tools/BashTool/bashPermissions.ts) 的主逻辑里有这段：

```ts
if (
  SandboxManager.isSandboxingEnabled() &&
  SandboxManager.isAutoAllowBashIfSandboxedEnabled() &&
  shouldUseSandbox(input)
) {
  const sandboxAutoAllowResult = checkSandboxAutoAllow(
    input,
    appState.toolPermissionContext,
  )
  if (sandboxAutoAllowResult.behavior !== 'passthrough') {
    return sandboxAutoAllowResult
  }
}
```

注意这里的含义：

- 只有在“sandbox 已启用 + autoAllowBashIfSandboxed 已开启 + 当前命令确实会进沙箱”的三重条件下
- 才会进入自动放行分支

### 6.2 自动放行之前，仍然尊重显式 deny / ask

`checkSandboxAutoAllow()` 的实现写得非常清楚：

```ts
// Check for explicit deny/ask rules on the full command
const { matchingDenyRules, matchingAskRules } = matchingRulesForInput(...)

if (matchingDenyRules[0] !== undefined) {
  return { behavior: 'deny', ... }
}
```

而且它还专门处理 compound command：

```ts
const subcommands = splitCommand(command)
if (subcommands.length > 1) {
  for (const sub of subcommands) {
    const subResult = matchingRulesForInput(...)
    if (subResult.matchingDenyRules[0] !== undefined) {
      return { behavior: 'deny', ... }
    }
    firstAskRule ??= subResult.matchingAskRules[0]
  }
}
```

这里体现了一个很成熟的安全判断顺序：

1. 先检查完整命令是否命中显式 deny
2. 再检查 compound command 的每个 subcommand 是否命中 deny / ask
3. 只有当没有显式规则时，才返回：

```ts
return {
  behavior: 'allow',
  decisionReason: {
    type: 'other',
    reason: 'Auto-allowed with sandbox (autoAllowBashIfSandboxed enabled)',
  },
}
```

也就是说，sandbox 的自动放行只是“默认允许”，不是“覆盖已有拒绝规则”。

### 6.3 文件路径权限也会读取 sandbox allowlist

[`src/utils/permissions/pathValidation.ts`](../src/utils/permissions/pathValidation.ts) 里有一个关键函数：

```ts
export function isPathInSandboxWriteAllowlist(resolvedPath: string): boolean {
  if (!SandboxManager.isSandboxingEnabled()) {
    return false
  }
  const { allowOnly, denyWithinAllow } = SandboxManager.getFsWriteConfig()
  ...
}
```

接着，在 `isPathAllowed()` 里有一段专门把 sandbox write allowlist 作为额外自动允许条件：

```ts
if (
  operationType !== 'read' &&
  !isInWorkingDir &&
  isPathInSandboxWriteAllowlist(resolvedPath)
) {
  return {
    allowed: true,
    decisionReason: {
      type: 'other',
      reason: 'Path is in sandbox write allowlist',
    },
  }
}
```

这段实现很有意思，因为它说明：

- sandbox 配置不仅影响“Bash 是否被隔离”
- 还反向影响应用层的 path permission 判断

这样做的直接收益是：

- 用户已经在 sandbox 配置里明确允许 `/tmp/claude/`
- 那么 `echo foo > /tmp/claude/x.txt` 这类命令就不需要再额外弹 permission prompt

这是一种“底层隔离状态反馈到上层交互”的设计。

## 7. 第五步：初始化、依赖检测和热更新怎么做

相关实现：

- [`src/utils/sandbox/sandbox-adapter.ts`](../src/utils/sandbox/sandbox-adapter.ts)
- [`src/components/sandbox/SandboxDoctorSection.tsx`](../src/components/sandbox/SandboxDoctorSection.tsx)

### 7.1 sandbox 不是简单看 `sandbox.enabled`

源码里的 `isSandboxingEnabled()`：

```ts
function isSandboxingEnabled(): boolean {
  if (!isSupportedPlatform()) {
    return false
  }

  if (checkDependencies().errors.length > 0) {
    return false
  }

  if (!isPlatformInEnabledList()) {
    return false
  }

  return getSandboxEnabledSetting()
}
```

这意味着“settings 写了 `sandbox.enabled: true`”和“实际正在沙箱模式运行”不是同一个概念。中间还隔着：

- 当前平台是否支持
- runtime 依赖是否齐全
- 是否被 `enabledPlatforms` 限制掉

### 7.2 `failIfUnavailable` 体现的是严格安全模式

源码里有：

```ts
function isSandboxRequired(): boolean {
  const settings = getSettings_DEPRECATED()
  return (
    getSandboxEnabledSetting() &&
    (settings?.sandbox?.failIfUnavailable ?? false)
  )
}
```

这说明：

- 默认情况下，sandbox 不可用时可以退化
- 但如果用户显式要求 `failIfUnavailable`，那 sandbox 就从“增强安全”升级成“必须条件”

### 7.3 明确给出“为什么没有真正启用 sandbox”

这部分也做得很细。

源码里的 `getSandboxUnavailableReason()` 不只是返回 `true/false`，而是给出具体原因，比如：

- 平台不支持
- 是 WSL1 而不是 WSL2
- 缺少依赖
- 当前平台不在 `enabledPlatforms` 列表里

对应 UI 侧的 [`src/components/sandbox/SandboxDoctorSection.tsx`](../src/components/sandbox/SandboxDoctorSection.tsx) 会把依赖错误和 warning 展示出来：

```ts
const depCheck = SandboxManager.checkDependencies()
const hasErrors = depCheck.errors.length > 0
const hasWarnings = depCheck.warnings.length > 0
```

这不是“体验优化”这么简单，它是在避免一个很危险的情况：

- 用户以为自己开启了 sandbox
- 实际上依赖缺失，命令根本没进沙箱
- 但系统又不告诉他

源码注释直接把这叫做 security footgun，这个判断是准确的。

### 7.4 配置热更新不是重启式，而是 runtime 级 update

初始化阶段的关键代码：

```ts
settingsSubscriptionCleanup = settingsChangeDetector.subscribe(() => {
  const settings = getSettings_DEPRECATED()
  const newConfig = convertToSandboxRuntimeConfig(settings)
  BaseSandboxManager.updateConfig(newConfig)
})
```

以及显式刷新函数：

```ts
function refreshConfig(): void {
  if (!isSandboxingEnabled()) return
  const settings = getSettings_DEPRECATED()
  const newConfig = convertToSandboxRuntimeConfig(settings)
  BaseSandboxManager.updateConfig(newConfig)
}
```

这说明 sandbox config 不是一次性装配，而是 session 内可更新的。

换句话说，Claude Code 不是：

- 改完设置
- 必须退出 CLI
- 重启后才能生效

它允许配置实时收缩/放宽，并把变化同步到底层 runtime。

## 8. 第六步：网络越权时如何向用户抛出交互

相关实现：

- [`src/components/permissions/SandboxPermissionRequest.tsx`](../src/components/permissions/SandboxPermissionRequest.tsx)

sandbox 不只管文件系统，也管网络。对于超出 allowlist 的网络访问，UI 侧有单独的 permission dialog。

它的标题就很直白：

```ts
<PermissionDialog title="Network request outside of sandbox">
```

可选项包括：

- `Yes`
- `Yes, and don't ask again for <host>`
- `No, and tell Claude what to do differently`

但如果 `allowManagedDomainsOnly` 打开，这个“don't ask again”选项会被拿掉：

```ts
const managedDomainsOnly = shouldAllowManagedSandboxDomainsOnly()
...
!managedDomainsOnly ? [yes-dont-ask-again] : []
```

这再次验证了前面的判断：

- policy 不只是影响 runtime config
- 还会收缩 UI 上可供用户做出的选择

## 9. 一个更准确的理解：sandbox 在这个项目里扮演什么角色

到这里可以给出一个更准确的定义：

### 9.1 它不是 Docker 式“黑箱容器”

这个项目的 sandbox 更像“围绕 Bash 执行链构建的策略型隔离层”，特点是：

- 直接从 Claude Code 的 settings / permissions 生成 runtime config
- 允许和应用层 permission system 联动
- 有专门为 CLI 工作流补的后处理逻辑，比如 bare repo scrub
- 会把 sandbox 的 allowlist 反哺给 path validation

这和“拉个容器跑命令”完全不是一回事。

### 9.2 它也不是唯一安全边界

源码已经反复说明这一点：

- `excludedCommands` 不是 security boundary
- auto-allow 仍然要尊重显式 deny / ask
- path validation 和 permission rules 仍然保留

因此更准确的说法是：

- sandbox 负责 OS 级隔离
- permission system 负责应用层规则表达和用户确认
- 两者互相引用、互相补位

## 10. 本章小结

这一章最核心的结论有四条：

1. sandbox 的入口不在 `sandbox-adapter.ts`，而是在 `shouldUseSandbox()` 对每条 Bash 命令做路由决策
2. `convertToSandboxRuntimeConfig()` 的本质不是字段映射，而是把 Claude Code 自己的 permission 语义翻译成 runtime 的文件系统和网络限制
3. `bashPermissions.ts` 没有把“进沙箱”当成免审通行证，而是先尊重显式 deny / ask，再做 auto-allow
4. 这套实现显式考虑了真实逃逸路径，例如 settings 投毒、skills 注入、Git bare repo 残留逃逸，并在执行后做宿主机级清理

所以，Claude Code 的 sandbox 不是一个外围安全插件，而是和 Bash、permissions、settings、UI、清理逻辑深度耦合的执行安全基础设施。
