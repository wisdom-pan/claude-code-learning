# Claude Code — Source Code Analysis (`src/`)

This document provides a comprehensive architectural overview of the `src/` directory in the Claude Code codebase.

## Overview

| Metric | Value |
|---|---|
| **Total Files** | 1,884 |
| **Total Lines** | ~512,664 |
| **Subdirectories** | 35 |
| **Top-level Files** | 18 |

Claude Code is a multi-layered application combining a CLI entry point, an Agent Loop core, a React-based TUI, a tool/plugin ecosystem, and extensive service integrations (MCP, API, analytics, memory).

---

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                         TUI Layer                               │
│  ink/ ── components/ ── hooks/ ── screens/ ── keybindings/     │
│  moreright/ ── outputStyles/ ── vim/ ── voice/                  │
├─────────────────────────────────────────────────────────────────┤
│                      Command & Entry Layer                      │
│  main.tsx ── commands/ ── entrypoints/ ── cli/ ── replLauncher  │
│  dialogLaunchers.tsx ── interactiveHelpers.tsx                  │
├─────────────────────────────────────────────────────────────────┤
│                        Core Agent Layer                         │
│  query.ts ── QueryEngine.ts ── coordinator/ ── query/           │
├─────────────────────────────────────────────────────────────────┤
│                       Tool & Permission Layer                   │
│  Tool.ts ── tools.ts ── tools/ ── schemas/                      │
├─────────────────────────────────────────────────────────────────┤
│                   Context & State Layer                         │
│  context.ts ── history.ts ── state/ ── bootstrap/               │
│  context/ ── constants/ ── types/                               │
├─────────────────────────────────────────────────────────────────┤
│                   Memory & Knowledge Layer                      │
│  memdir/ ── skills/ ── services/SessionMemory/                  │
│  services/MagicDocs/ ── services/PromptSuggestion/              │
├─────────────────────────────────────────────────────────────────┤
│                   Bridge & Remote Layer                         │
│  bridge/ ── remote/ ── server/ ── upstreamproxy/                │
├─────────────────────────────────────────────────────────────────┤
│                       Service Layer                             │
│  services/ (API, MCP, analytics, LSP, voice, settings, …)      │
├─────────────────────────────────────────────────────────────────┤
│                  Infrastructure & Utilities                     │
│  utils/ ── migrations/ ── plugins/ ── native-ts/                │
│  setup.ts ── cost-tracker.ts ── Task.ts ── tasks/               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Module Directory

### 1. Entry Layer

| File | Lines | Description |
|---|---|---|
| `main.tsx` | 4,683 | CLI entry point — bootstraps the application, parses arguments, initializes state, and launches the TUI or SDK mode |
| `replLauncher.tsx` | 22 | REPL (Read-Eval-Print Loop) launcher entry |
| `setup.ts` | 477 | Application setup and initialization utilities |
| `ink.ts` | 85 | Ink TUI framework configuration |

| Directory | Files | Lines | Description |
|---|---|---|---|
| `cli/` | 19 | 12,353 | CLI transport layers, argument parsing, stdin/stdout handlers, and terminal setup |
| `entrypoints/` | 8 | 4,051 | Entry point definitions — different modes (CLI, SDK, remote, etc.) |
| `commands/` | 189 | 26,428 | Slash command implementations (100+ commands: `/help`, `/cost`, `/compact`, etc.) |

---

### 2. Core Agent Layer

| File | Lines | Description |
|---|---|---|
| `query.ts` | 1,729 | **Agent Loop core** — orchestrates the main conversation loop: sends prompts, processes responses, handles tool calls, manages context window |
| `QueryEngine.ts` | 1,295 | **SDK wrapper** — higher-level API around the agent loop, provides programmatic access to Claude Code |

| Directory | Files | Lines | Description |
|---|---|---|---|
| `query/` | 4 | 652 | Query configuration — system prompts, model selection, parameter defaults |
| `coordinator/` | 1 | 369 | Coordinator mode — manages multi-step orchestration and sub-agent delegation |

---

### 3. Context & State Layer

| File | Lines | Description |
|---|---|---|
| `context.ts` | 189 | System and user context definitions — environment, project config, user preferences |
| `history.ts` | 464 | Message history management — conversation turn tracking, compact/summarize logic |
| `Task.ts` | 125 | Task model definition |
| `tasks.ts` | 39 | Task management entry point |
| `cost-tracker.ts` | 323 | Cost tracking — token usage, API cost calculation, budget monitoring |
| `costHook.ts` | 22 | Cost tracking React hook |
| `projectOnboardingState.ts` | 83 | Project onboarding state management |

| Directory | Files | Lines | Description |
|---|---|---|---|
| `state/` | 6 | 1,190 | AppState management — global application state, reducers, selectors |
| `bootstrap/` | 1 | 1,758 | Global state bootstrap — initialization, configuration loading, environment detection |
| `context/` | 9 | 1,004 | React context providers — theme, auth, session, settings contexts |
| `constants/` | 21 | 2,648 | Application constants — model IDs, default configs, feature flags |
| `types/` | 11 | 3,446 | TypeScript type definitions — shared interfaces, enums, utility types |

---

### 4. Tool & Permission Layer

| File | Lines | Description |
|---|---|---|
| `Tool.ts` | 792 | **Tool interface** — base tool class, permission system, tool result types, input schemas |
| `tools.ts` | 389 | **Tool registry** — tool discovery, registration, and lifecycle management |

| Directory | Files | Lines | Description |
|---|---|---|---|
| `tools/` | 184 | 50,828 | **Tool implementations** — 43+ tools including Bash, Read, Write, Edit, Grep, Glob, Notebook, WebFetch, and more |
| `schemas/` | 1 | 222 | JSON schema definitions for tool inputs and outputs |

---

### 5. Memory & Knowledge Layer

| Directory | Files | Lines | Description |
|---|---|---|---|
| `memdir/` | 8 | 1,736 | Memory directory management — project memory files, CLAUDE.md loading, cross-project memory |
| `skills/` | 20 | 4,066 | Bundled skills — specialized domain instructions loaded on demand |
| `services/SessionMemory/` | 3 | — | Session-scoped memory — short-term context persistence |
| `services/MagicDocs/` | 2 | — | Magic Docs — automatic documentation generation |
| `services/PromptSuggestion/` | 2 | — | Prompt suggestion — context-aware prompt recommendations |

---

### 6. TUI Layer

| Directory | Files | Lines | Description |
|---|---|---|---|
| `ink/` | 96 | 19,842 | **TUI rendering engine** — custom fork of Ink (React for CLI), handles terminal rendering, layout, input |
| `components/` | 389 | 81,546 | **React UI components** — the full component library: messages, tool output, status bars, dialogs, etc. |
| `hooks/` | 104 | 19,204 | **React hooks** — custom hooks for state, effects, keyboard handling, animations |
| `screens/` | 3 | 5,977 | Screen-level components — full-page layouts (main screen, settings, onboarding) |
| `keybindings/` | 14 | 3,159 | Keyboard shortcut system — keymap definitions, chord handling, vim mode support |
| `moreright/` | 1 | 25 | UI utilities — right-panel helpers |
| `outputStyles/` | 1 | 98 | Output style definitions — formatting, colors, themes for terminal output |
| `vim/` | 5 | 1,513 | Vim mode — vim keybindings and command mode emulation |
| `voice/` | 1 | 54 | Voice feature entry point |

---

### 7. Bridge & Remote Layer

| Directory | Files | Lines | Description |
|---|---|---|---|
| `bridge/` | 31 | 12,613 | **Remote communication** — WebSocket transport, SSE streaming, message serialization, connection management |
| `remote/` | 4 | 1,127 | Remote session management — SDK message adapter, remote permission bridge, session WebSocket |
| `server/` | 3 | 358 | Server utilities — HTTP server setup, health checks |
| `upstreamproxy/` | 2 | 740 | Upstream proxy — request forwarding, proxy configuration |

---

### 8. Service Layer

| Directory | Files | Lines | Description |
|---|---|---|---|
| `services/` (root) | 130 | 53,680 | **Service layer** — comprehensive service integrations |

Key service submodules:

| Submodule | Description |
|---|---|
| `services/api/` | API client — session ingress, retry logic, usage tracking, error handling, Claude API integration |
| `services/mcp/` | MCP (Model Context Protocol) — server connections, OAuth, auth, config, transport layers, elicitation |
| `services/analytics/` | Analytics — DataDog, GrowthBook, first-party event logging, metrics |
| `services/lsp/` | LSP (Language Server Protocol) — client, server manager, diagnostic registry |
| `services/voice*` | Voice services — streaming STT, keyword detection, voice pipeline |
| `services/autoDream/` | Auto Dream — background consolidation, config |
| `services/tips/` | Tips system — tip registry, scheduler, history |
| `services/teamMemorySync/` | Team memory sync — secret scanning, watcher, type definitions |
| `services/settingsSync/` | Settings sync — cross-device settings synchronization |
| `services/plugins/` | Plugin installation manager |
| `services/toolUseSummary/` | Tool use summary generation |
| `services/notifier.ts` | Notification service |
| `services/preventSleep.ts` | Sleep prevention service |
| `services/diagnosticTracking.ts` | Diagnostic tracking |
| `services/claudeAiLimits.ts` | Claude AI rate limits handling |
| `services/internalLogging.ts` | Internal logging service |

---

### 9. Commands Layer

| Directory | Files | Lines | Description |
|---|---|---|---|
| `commands/` | 189 | 26,428 | **Slash command definitions** — 100+ commands organized by category |

Command categories include:
- **Session**: `/clear`, `/compact`, `/continue`, `/resume`
- **Configuration**: `/config`, `/theme`, `/model`
- **Tools**: `/tools`, `/mcp`
- **Information**: `/help`, `/cost`, `/stats`
- **File operations**: `/read`, `/edit`
- **And many more…**

---

### 10. State & Task Management

| Directory | Files | Lines | Description |
|---|---|---|---|
| `tasks/` | 12 | 3,286 | Task management — task creation, lifecycle, sub-task delegation, task state machine |
| `assistant/` | 1 | 87 | Session history — assistant-side conversation tracking |

---

### 11. Buddy & Companion

| Directory | Files | Lines | Description |
|---|---|---|---|
| `buddy/` | 6 | 1,298 | Companion/buddy features — AI assistant personality, conversational helpers |

---

### 12. Infrastructure & Utilities

| Directory | Files | Lines | Description |
|---|---|---|---|
| `utils/` | 564 | 180,472 | **Utility functions** — the largest module: string manipulation, file I/O, path handling, formatting, validation, async helpers, and hundreds of domain-specific utilities |
| `migrations/` | 11 | 603 | Data migrations — schema versioning, config migration scripts |
| `plugins/` | 2 | 182 | Plugin system — plugin loader, plugin interface |
| `native-ts/` | 4 | 4,081 | Native TypeScript bindings — platform-specific native code interfaces |

---

## Module Dependency Diagram

```
                    ┌──────────┐
                    │  main.tsx │
                    └─────┬────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        ┌──────────┐ ┌────────┐ ┌──────────┐
        │  cli/    │ │ ink/   │ │entrypoints│
        └─────┬────┘ └───┬────┘ └──────────┘
              │          │
              ▼          ▼
        ┌──────────────────────┐
        │    commands/         │
        │  dialogLaunchers     │
        │  interactiveHelpers  │
        └──────────┬───────────┘
                   │
          ┌────────┼────────┐
          ▼        ▼        ▼
    ┌─────────┐ ┌──────┐ ┌────────┐
    │ query.ts│ │Tool.ts│ │context │
    └────┬────┘ └──┬───┘ └───┬────┘
         │         │         │
         ▼         ▼         ▼
    ┌──────────────────────────────┐
    │       QueryEngine.ts         │
    │       coordinator/           │
    └──────────────┬───────────────┘
                   │
          ┌────────┼────────────────┐
          ▼        ▼                ▼
    ┌─────────┐ ┌──────┐    ┌──────────┐
    │ tools/  │ │history│    │ services/│
    └────┬────┘ └───┬───┘    └────┬─────┘
         │          │              │
         ▼          ▼              ▼
    ┌──────────────────────────────────┐
    │         state/                   │
    │         bootstrap/               │
    │         memdir/                  │
    │         skills/                  │
    └──────────────────────────────────┘
                   │
          ┌────────┼────────┐
          ▼        ▼        ▼
    ┌─────────┐ ┌──────┐ ┌────────┐
    │ bridge/ │ │remote│ │ utils/ │
    └─────────┘ └──────┘ └────────┘
```

---

## File Count & Line Count Statistics

### Top-Level Files

| File | Lines |
|---|---|
| `main.tsx` | 4,683 |
| `commands.ts` | 754 |
| `query.ts` | 1,729 |
| `QueryEngine.ts` | 1,295 |
| `Tool.ts` | 792 |
| `tools.ts` | 389 |
| `history.ts` | 464 |
| `setup.ts` | 477 |
| `context.ts` | 189 |
| `cost-tracker.ts` | 323 |
| `interactiveHelpers.tsx` | 365 |
| `Task.ts` | 125 |
| `dialogLaunchers.tsx` | 132 |
| `ink.ts` | 85 |
| `projectOnboardingState.ts` | 83 |
| `tasks.ts` | 39 |
| `costHook.ts` | 22 |
| `replLauncher.tsx` | 22 |
| **Total** | **11,967** |

### Subdirectories (by line count)

| Directory | Files | Lines | % of Total |
|---|---|---|---|
| `utils/` | 564 | 180,472 | 35.2% |
| `components/` | 389 | 81,546 | 15.9% |
| `services/` | 130 | 53,680 | 10.5% |
| `tools/` | 184 | 50,828 | 9.9% |
| `commands/` | 189 | 26,428 | 5.2% |
| `hooks/` | 104 | 19,204 | 3.7% |
| `ink/` | 96 | 19,842 | 3.9% |
| `bridge/` | 31 | 12,613 | 2.5% |
| `cli/` | 19 | 12,353 | 2.4% |
| `bootstrap/` | 1 | 1,758 | 0.3% |
| `memdir/` | 8 | 1,736 | 0.3% |
| `vim/` | 5 | 1,513 | 0.3% |
| `buddy/` | 6 | 1,298 | 0.3% |
| `remote/` | 4 | 1,127 | 0.2% |
| `state/` | 6 | 1,190 | 0.2% |
| `context/` | 9 | 1,004 | 0.2% |
| `native-ts/` | 4 | 4,081 | 0.8% |
| `tasks/` | 12 | 3,286 | 0.6% |
| `keybindings/` | 14 | 3,159 | 0.6% |
| `screens/` | 3 | 5,977 | 1.2% |
| `entrypoints/` | 8 | 4,051 | 0.8% |
| `skills/` | 20 | 4,066 | 0.8% |
| `constants/` | 21 | 2,648 | 0.5% |
| `types/` | 11 | 3,446 | 0.7% |
| `upstreamproxy/` | 2 | 740 | 0.1% |
| `migrations/` | 11 | 603 | 0.1% |
| `coordinator/` | 1 | 369 | 0.1% |
| `server/` | 3 | 358 | 0.1% |
| `plugins/` | 2 | 182 | <0.1% |
| `schemas/` | 1 | 222 | <0.1% |
| `query/` | 4 | 652 | 0.1% |
| `outputStyles/` | 1 | 98 | <0.1% |
| `assistant/` | 1 | 87 | <0.1% |
| `voice/` | 1 | 54 | <0.1% |
| `moreright/` | 1 | 25 | <0.1% |
| **Total** | **1,884** | **512,664** | **100%** |

---

## Quick Reference: Key Entry Points

| Purpose | File |
|---|---|
| Start the CLI | `main.tsx` |
| Agent loop logic | `query.ts` |
| SDK integration | `QueryEngine.ts` |
| Tool interface | `Tool.ts` |
| Tool registry | `tools.ts` |
| Command definitions | `commands/` |
| TUI engine | `ink/` |
| State management | `state/`, `bootstrap/` |
| API client | `services/api/` |
| MCP integration | `services/mcp/` |
| Remote/bridge | `bridge/`, `remote/` |
| Utilities | `utils/` |
