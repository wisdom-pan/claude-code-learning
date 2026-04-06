# 第五章：Skills 技能机制实现细节与运行方式

[返回总目录](../README.md)

---

## 1. 导读与结论

Claude Code 通过 **Skills（技能）机制** 实现平台化扩展，核心是把 Markdown 文件 + YAML 元数据 + 可选的 Bash 脚本三者结合，低门槛地为 AI 注入领域能力。

主要源文件：
- [`src/skills/loadSkillsDir.ts`](../src/skills/loadSkillsDir.ts) — 技能发现、解析、实例化
- [`src/skills/bundledSkills.ts`](../src/skills/bundledSkills.ts) — 内建打包技能
- [`src/utils/promptShellExecution.ts`](../src/utils/promptShellExecution.ts) — prompt 内嵌 Shell 执行

---

## 2. Skills 的三种来源

| 类型 | 来源 | 关键 `loadedFrom` 值 |
|------|------|----------------------|
| **File-based（文件系统技能）** | 本地 `.claude/skills/` 目录及其变体 | `'skills'` / `'commands_DEPRECATED'` |
| **Bundled（内建打包技能）** | 源码内硬编码，由构建流程打包 | `'bundled'` |
| **MCP Skills（协议映射技能）** | 来自 MCP Server 的工具能力 | `'mcp'` |

---

## 3. 技能发现：`getSkillDirCommands()`

**真实源码**（[`src/skills/loadSkillsDir.ts:638`](../src/skills/loadSkillsDir.ts)）：

```typescript
export const getSkillDirCommands = memoize(
  async (cwd: string): Promise<Command[]> => {
    const userSkillsDir    = join(getClaudeConfigHomeDir(), 'skills')  // ~/.claude/skills
    const managedSkillsDir = join(getManagedFilePath(), '.claude', 'skills')  // 策略管理目录
    const projectSkillsDirs = getProjectDirsUpToHome('skills', cwd)   // 项目目录向上爬取

    // --bare 模式：跳过自动发现，只加载 --add-dir 显式指定的路径
    if (isBareMode()) {
      return additionalDirs.flatMap(dir =>
        loadSkillsFromSkillsDir(join(dir, '.claude', 'skills'), 'projectSettings')
      )
    }

    // 正常模式：并行加载所有来源
    const [managedSkills, userSkills, projectSkillsNested, additionalSkillsNested, legacyCommands] =
      await Promise.all([
        loadSkillsFromSkillsDir(managedSkillsDir, 'policySettings'),    // 策略级技能
        loadSkillsFromSkillsDir(userSkillsDir,    'userSettings'),      // 用户级技能
        Promise.all(projectSkillsDirs.map(dir =>
          loadSkillsFromSkillsDir(dir, 'projectSettings'))),            // 项目级技能（多目录）
        Promise.all(additionalDirs.map(dir =>
          loadSkillsFromSkillsDir(join(dir, '.claude', 'skills'), 'projectSettings'))), // --add-dir
        loadSkillsFromCommandsDir(cwd),                                 // 旧版 /commands/ 目录
      ])

    // 合并 + 去重（inode 级别，防止软链重复）
    return deduplicateByRealpath([
      ...managedSkills, ...userSkills,
      ...projectSkillsNested.flat(),
      ...additionalSkillsNested.flat(),
      ...legacyCommands,
    ])
  }
)
```

**关键设计点**：
- `memoize` 包裹 — 同一 `cwd` 只发现一次，结果缓存
- `Promise.all` 并行 — 所有来源同时读
- 去重通过 `fs.realpath` 取 inode 级真实路径，防止软链接导致重复加载

---

## 4. 技能解析：Frontmatter 字段

每个 `SKILL.md` 文件的 YAML 前置数据通过 [`parseSkillFrontmatterFields()`](../src/skills/loadSkillsDir.ts) 解析：

```typescript
// src/skills/loadSkillsDir.ts:185
export function parseSkillFrontmatterFields(frontmatter: FrontmatterData): {
  name?:              string
  description?:       string | string[]
  when_to_use?:       string
  allowed_tools?:     string[]
  model?:             string
  effort?:            EffortValue     // 任务估时: 'low' | 'medium' | 'high'
  user_invocable?:    boolean         // false = 仅供模型内部调用，不出现在 REPL 命令列表
  paths?:             string[]        // 条件技能触发路径（文件改变时自动激活）
  version?:           string
  context?:           'inline' | 'fork'
  agent?:             string          // 绑定到指定 agent 类型
  shell?:             'bash' | 'powershell'
} { ... }
```

**`paths` 字段是核心魔法**：声明了 `paths` 的技能是**条件技能（Conditional Skill）**——当用户操作或修改了匹配该 glob pattern 的文件时，技能自动激活并注入上下文。这是一种精准触发的 Hook 订阅模式。

---

## 5. 技能实例化：`createSkillCommand()`

**真实源码**（[`src/skills/loadSkillsDir.ts:270`](../src/skills/loadSkillsDir.ts)，精简节选）：

```typescript
export function createSkillCommand({
  skillName, markdownContent, allowedTools,
  loadedFrom, baseDir, paths, shell, ...rest
}: SkillCommandOptions): Command {
  return {
    type: 'prompt',
    name: skillName,
    paths,   // 条件技能触发路径
    isHidden: !userInvocable,
    // ...

    // 核心执行逻辑：getPromptForCommand 在模型调用技能时触发
    async getPromptForCommand(args, toolUseContext) {
      let finalContent = markdownContent  // 原始 Markdown 内容

      // 1. 展开 CLI 参数占位符
      finalContent = substituteArguments(finalContent, args, true, argumentNames)

      // 2. 展开内置变量（skill 目录、session ID）
      if (baseDir) {
        const skillDir = baseDir.replace(/\\/g, '/')  // Windows 路径标准化
        finalContent = finalContent.replace(/\${CLAUDE_SKILL_DIR}/g, skillDir)
      }
      finalContent = finalContent.replace(/\${CLAUDE_SESSION_ID}/g, getSessionId())

      // 3. 执行 prompt 内嵌 Shell 命令（只对受信任来源执行，MCP 来源跳过）
      if (loadedFrom !== 'mcp') {
        finalContent = await executeShellCommandsInPrompt(
          finalContent, toolUseContext, `/${skillName}`, shell
        )
      }

      return [{ type: 'text', text: finalContent }]
    },
  }
}
```

---

## 6. 内嵌 Shell 执行：`executeShellCommandsInPrompt()`

这是 Skills 系统最精妙的功能：Markdown 内容里可以嵌入 Shell 命令，这些命令在技能被调用前先在宿主机执行，输出结果替换回 Markdown 正文。

**语法示例**（在 `.claude/skills/my-skill/SKILL.md` 里）：

```markdown
---
name: git-status-helper
description: 查看当前 Git 状态并提供建议
---

当前分支信息：
!`git log --oneline -5`

未提交的变更：
!`git status --short`

请根据以上信息帮我分析当前代码状态。
```

**真实源码**（[`src/utils/promptShellExecution.ts:69`](../src/utils/promptShellExecution.ts)）：

```typescript
export async function executeShellCommandsInPrompt(
  text: string,
  context: ToolUseContext,
  slashCommandName: string,
  shell?: FrontmatterShell,
): Promise<string> {
  let result = text

  // 选择执行工具：默认 BashTool，frontmatter 可指定 PowerShell
  const shellTool = shell === 'powershell' && isPowerShellToolEnabled()
    ? getPowerShellTool()
    : BashTool

  // 扫描两种语法：!`command`（内联）和 ```!\ncommand\n```（代码块）
  const blockMatches  = text.matchAll(BLOCK_PATTERN)
  const inlineMatches = text.includes('!`') ? text.matchAll(INLINE_PATTERN) : []

  await Promise.all(
    [...blockMatches, ...inlineMatches].map(async match => {
      const command = match[1]?.trim()
      if (!command) return

      // 1. 权限检查（走同一套 ToolPermission 流程）
      const permissionResult = await hasPermissionsToUseTool(
        shellTool, { command }, context,
        createAssistantMessage({ content: [] }), '',
      )
      if (permissionResult.behavior !== 'allow') {
        throw new MalformedCommandError(`Permission denied: ${permissionResult.message}`)
      }

      // 2. 执行 Shell 命令
      const { data } = await shellTool.call({ command }, context)

      // 3. 提取输出并替换原始 pattern
      const output = typeof toolResultBlock.content === 'string'
        ? toolResultBlock.content
        : formatBashOutput(data.stdout, data.stderr)

      // 注意：用函数形式替换，防止 $& 等特殊替换符号被 PowerShell 输出污染
      result = result.replace(match[0], () => output)
    })
  )

  return result
}
```

**安全切断**：`loadedFrom !== 'mcp'` 这个判断极为关键——来自 MCP Server 的技能不会执行内嵌 Shell，防止恶意远程服务器通过 MCP 注入 RCE（远程代码执行）攻击。同时，所有命令执行前都走 `hasPermissionsToUseTool`，遵从同一套权限体系。

---

## 7. 技能加载全流程总结

```text
用户目录/项目目录/.claude/skills/<skill-name>/SKILL.md
        │
        ▼
getSkillDirCommands(cwd)           ← 并行扫描所有技能目录，结果 memoize
        │
        ▼
loadSkillsFromSkillsDir(basePath)  ← 读取目录，筛选 SKILL.md 文件
        │
        ▼
parseFrontmatter(content)          ← 解析 YAML 元数据
parseSkillFrontmatterFields(fm)    ← 提取 name/paths/model/effort/... 字段
        │
        ▼
createSkillCommand(fields)         ← 实例化为 Command 对象，挂入命令系统
        │
        ▼  （用户调用 /<skill-name> 或模型自主选择）
getPromptForCommand(args, ctx)
  ├── substituteArguments()        ← 展开 CLI 参数
  ├── 展开 ${CLAUDE_SKILL_DIR}     ← 内置变量替换
  └── executeShellCommandsInPrompt() ← 执行嵌入 Shell（仅受信任来源）
        │
        ▼
返回给模型的最终 Prompt（含实时系统状态）
```

---

## 8. 设计总结

| 特性 | 实现方式 |
|------|----------|
| 低门槛扩展 | Markdown + YAML，无需编写 TypeScript |
| 实时系统上下文 | `!`command`` 内嵌 Shell，prompt 携带真实环境信息 |
| 条件精准触发 | `paths` 字段订阅文件变更 Hook，避免认知过载 |
| 安全隔离 | MCP 来源跳过 Shell 执行，所有命令走统一权限系统 |
| 可组合 | File-based / Bundled / MCP 三种来源统一为 `Command` 对象 |
