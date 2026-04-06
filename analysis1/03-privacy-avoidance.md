# 第三章：从用户角度看，如何规避或降低信息收集

[返回总目录](../README.md)

## 1. 本章导读

本章讨论的不是“理论上能否零采集”，而是“用户实际能做哪些事情来降低暴露面”。

结论先行：如果用户要最小化暴露，需要同时控制三件事：

1. 不让敏感内容进入模型上下文
2. 不让 transcript / memory 长期落盘
3. 不开启同步、遥测、分享和远程能力

## 2. 先分清三类风险

要规避信息收集，至少要区分：

1. `发给模型的内容`
2. `本地持久化的内容`
3. `上传到外部服务的内容`

很多人只盯着第 3 类，但对 coding agent 来说，第 1 类通常更敏感。

## 3. 最有效的技术规避动作

### 3.1 禁用遥测与非必要网络

相关实现：

- [`src/utils/privacyLevel.ts`](../src/utils/privacyLevel.ts)

可用手段：

- `DISABLE_TELEMETRY`
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`

效果区别：

- `DISABLE_TELEMETRY`：主要关闭 telemetry/analytics
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`：更严格，关闭非必要网络能力

如果目标是“尽量少出网”，后者更有效。

### 3.2 禁用 transcript 持久化

相关实现：

- [`src/main.tsx`](../src/main.tsx)
- [`src/utils/settings/types.ts`](../src/utils/settings/types.ts)
- [`src/bootstrap/state.ts`](../src/bootstrap/state.ts)

可用方式：

- CLI：`--no-session-persistence`
- 设置：`cleanupPeriodDays: 0`

收益：

- 不生成可恢复 transcript
- 降低会话被再次用于 memory、resume、share 的机会

### 3.3 关闭 Auto Memory

相关实现：

- [`src/memdir/paths.ts`](../src/memdir/paths.ts)

可用方式：

- `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
- `settings.autoMemoryEnabled = false`
- `--bare` / SIMPLE 模式

收益：

- 不再自动提取长期记忆
- 降低“用户画像长期累积”
- 减少后续 prompt 自动注入 memory

### 3.4 不启用 Team Memory

原因：

- team memory 会触发目录监听、pull、push、服务端同步

相关实现：

- [`src/services/teamMemorySync/index.ts`](../src/services/teamMemorySync/index.ts)
- [`src/services/teamMemorySync/watcher.ts`](../src/services/teamMemorySync/watcher.ts)

如果用户或团队不希望项目知识被持续同步，应关闭此能力。

### 3.5 不启用 Remote / Bridge / Transcript Share

这些功能都会扩大系统边界：

- `remote-control` / bridge：扩大会话控制面与远程数据面
- transcript share：直接上传会话内容

对于隐私敏感场景，应默认关闭。

## 4. 行为层面的规避建议

即便所有 telemetry 都关了，如果用户把敏感信息直接交给模型，风险依然存在。

建议：

- 不在 prompt 中直接粘贴密钥、token、私有证书
- 不把整个 `.env`、生产配置、客户数据文件送入上下文
- 不让 agent 扫描包含敏感资料的大目录
- 不把敏感知识写入 auto memory 或 team memory
- 不在开启 Grove 的状态下处理敏感项目

## 5. 团队与企业用户的治理建议

如果这是团队使用场景，单个开发者的手动习惯不足以保证收敛，应采用统一策略：

- 默认关闭 auto memory
- 默认关闭 team memory
- `cleanupPeriodDays` 设为 `0` 或很短
- 默认启用 `essential-traffic`
- 禁止 remote / bridge
- 用隔离仓库、脱敏镜像或临时 worktree 运行 agent

## 6. 一个现实判断

如果用户的真实目标是：

- 代码绝不离开本机
- 不进入模型
- 不形成长期记忆
- 不产生任何恢复痕迹

那这类产品天然不适合作为默认工作方式。

最接近这个目标的使用形态只能是：

- `--bare`
- no telemetry
- no persistence
- no auto memory
- no team memory
- no remote
- 严格控制输入上下文

也就是说，本项目可以“降低暴露面”，但并不是“零采集优先”架构。

## 7. 本章小结

对用户最实际的规避路线是：

1. 先关闭网络与遥测
2. 再关闭 transcript 与 memory
3. 最后控制自己的输入行为

如果只做第 1 步而忽略第 2、3 步，隐私收益会远低于预期。
