# Hermes OS

**AI-Native Operating System — Intent routing, multi-agent orchestration, and unified access to AI capabilities.**

> "用户只需要和 Hermes OS 说话，剩下的由 OS 完成。"

## Vision

Hermes OS is an AI-native operating system that transforms how humans interact with AI capabilities. Instead of choosing which AI tool to use, users simply express their intent — Hermes OS handles the rest.

```
用户："帮我修这个 bug，然后部署到服务器"

Hermes OS 自动：
  1. 理解意图（修 bug + 部署）
  2. 分发给正确的 Agent
  3. 协调执行流程
  4. 汇总结果
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Hermes OS 协调层                         │
│  ├── Intent Understanding（意图理解）                        │
│  ├── Agent Discovery（Agent 发现）                          │
│  ├── Task Routing（任务路由）                               │
│  └── Cross-Agent Memory（跨 Agent 共享记忆）                │
└─────────────────────────────────────────────────────────────┘
         │              │              │              │
    ┌────┴────┐   ┌────┴────┐   ┌────┴────┐   ┌────┴────┐
    │ Oct-OS  │   │Claude   │   │ Gemini  │   │ OpenBee │
    │         │   │ Code    │   │ CLI     │   │         │
    │ 自主探索 │   │ 代码专家 │   │ 大上下文 │   │ 并行执行 │
    │ 24/7    │   │ REPL    │   │ 分析    │   │ DAG     │
    └─────────┘   └─────────┘   └─────────┘   └─────────┘
```

## Design Principles

### 1. OS as Coordinator, Not Performer

Hermes OS is the **stage**, not the **actor**:
- It coordinates, routes, and orchestrates — it doesn't try to do everything itself
- Specialized Agents (Oct-OS, Claude Code, etc.) are the performers
- Clear separation of concerns: OS handles coordination, Agents handle execution

### 2. Agent-to-Agent, Not Master-Slave

```
错误模型：
  Hermes OS（主） → 调度 → Oct-OS（从）

正确模型：
  Hermes OS（协调层）
       ↕ 协议调用
  Oct-OS ↔ Claude Code ↔ Gemini CLI
       （对等的 Agent 网络）
```

### 3. Skills as Capabilities

Agents declare capabilities through a **Skills protocol**:
- Simple MD files define what each Agent can do
- Hermes OS discovers and routes based on available Skills
- Hot-swappable: add/remove Agents without changing core OS

### 4. Learning Through Use

Hermes OS gets smarter over time:
- Remembers user preferences (which Agent for which task)
- Learns coordination patterns (which Agents work well together)
- Improves routing decisions based on success history

## Status

**Early Stage** — This is the initial commit. The architecture is being designed.

## Contributing

This project welcomes contributions. Please see [ARCHITECTURE.md](./ARCHITECTURE.md) for the current design thinking.

## License

MIT

---

Built with the belief that AI should be accessible to everyone, not just those who know which tool to use.
