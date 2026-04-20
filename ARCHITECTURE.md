# Hermes OS Architecture

## 核心定义

**Hermes OS = hermes-agent。** 基于 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)，专注服务 100 用户。

## 第一性原理

### 什么是 AI-Native Operating System？

传统 OS：
- 管理资源（CPU、内存、磁盘、网络）
- 提供接口（CLI、GUI）
- 人类发起操作

AI-Native OS：
- 管理 **AI 能力**（LLM、Agent、Skills）
- 提供 **意图理解**（自然语言）
- AI **编排**操作

### 我们解决的核心问题

**当前状态（混乱）：**
```
用户 → 需要想：用哪个工具？
  - Claude Code？手动操作？
  - 它们怎么配合？
  - 结果怎么汇总？
```

**目标状态（Hermes OS）：**
```
用户 → "帮我修这个 bug，然后部署到服务器"
           ↓
    Hermes OS 理解意图
           ↓
    自动分发 + 协调 + 汇总
           ↓
    用户得到结果
```

## 架构层次

```
┌─────────────────────────────────────────────────────────────┐
│                    用户交互层                                 │
│         Natural Language → Intent → Action                  │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                 Hermes OS 协调层（hermes-agent）              │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │ Intent      │  │ Agent      │  │ Task            │  │
│  │ Understanding│ │ Discovery  │  │ Orchestration   │  │
│  └─────────────┘  └─────────────┘  └──────────────────┘  │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │ Cross-Agent │  │ Result      │  │ Learning &      │  │
│  │ Memory      │  │ Aggregation │  │ Adaptation      │  │
│  └─────────────┘  └─────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            ↓ Skill 调用
┌─────────────────────────────────────────────────────────────┐
│                    Agent 层                                  │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐     │
│  │ Claude  │  │ Gemini  │  │ OpenMind│  │ OpenBee │     │
│  │ Code    │  │ CLI     │  │         │  │         │     │
│  │ 代码专家 │  │ 大上下文 │  │ 价值发现 │  │ 并行执行 │     │
│  │ REPL    │  │ 分析    │  │ 研究分析 │  │ DAG     │     │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘     │
│         （按需扩展，暂不实现）                              │
└─────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. Intent Understanding Layer

**职责**：将自然语言解析为结构化意图

**输入**："帮我修这个 bug，然后部署到服务器"

**输出**：
```json
{
  "intents": [
    {"action": "fix_bug", "target": "utils.py", "priority": "high"},
    {"action": "deploy", "target": "production", "depends_on": "fix_bug"}
  ]
}
```

### 2. Agent Discovery Protocol

**职责**：知道每个 Agent 能做什么

**机制**：Skills 声明
```
Agent 启动时声明自己的 Skills：
  skills/
    ├── PROTOCOL.md      # 我是谁，能做什么
    ├── code-fix/         # 修 bug
    ├── autonomous/       # 自主探索
    └── long-running/     # 长时间任务
```

**Hermes OS 维护**：Agent 注册表 + Skills 索引

### 3. Task Orchestration

**职责**：将任务路由到正确的 Agent，处理依赖关系

**关键概念**：
- **Task Graph**：带依赖关系的任务 DAG
- **Agent Pool**：可用 Agent 及其当前状态
- **Routing**：将任务匹配到最合适的 Agent

### 4. Cross-Agent Memory

**职责**：Agent 之间的共享上下文

**设计**：
- 每个 Agent 有私有记忆
- Hermes OS 维护共享记忆空间
- Agent 可以读写共享上下文

### 5. Result Aggregation

**职责**：合并多个 Agent 的结果

**挑战**：不同输出格式、部分失败、冲突

## 实现路线图

### Phase 1: MVP（当前）
- [x] 基本仓库结构（CLAUDE.md）
- [ ] hermes-agent 配置与部署
- [ ] 基础 CLI 接口
- [ ] 多通道接入（Telegram, Feishu 等）

### Phase 2: 集成
- [ ] Claude Code Skill 集成
- [ ] Agent 注册协议
- [ ] 结果聚合

### Phase 3: 智能化
- [ ] 意图理解深化
- [ ] 从历史学习
- [ ] 智能路由

### Phase 4: 生态（暂不实现）
- [ ] OpenMind 集成（价值发现）
- [ ] OpenBee 集成（并行执行）
- [ ] Oct-OS 集成（自主探索）
- [ ] 插件系统
- [ ] 社区 Skills

## 参考项目

| Project | Stars | What It Does | Relevance |
|---------|-------|-------------|-----------|
| NousResearch/hermes-agent | 99k+ | Self-improving agent with skills | ⭐ 核心参考 |
| anthropics/claude-code | - | Claude Code CLI | 内置 Skill |
| oct-os / openbee / openmind | - | Agent 生态组件 | Phase 4 扩展 |
