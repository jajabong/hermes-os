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
│  │ Claude  │  │ Search  │  │ Research│  │ Worker  │     │
│  │ Code    │  │ Specialist│  │ Analyst │  │ Engine  │     │
│  │ 代码专家 │  │ 搜索专家  │  │ 研究分析 │  │ 并行执行 │     │
│  │ REPL    │  │           │  │         │  │         │     │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘     │
│         （通过 Skills 协议按需动态扩展）                     │
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

### 3. Task Orchestration (task_scheduler.py)

**职责**：将任务路由到正确的 Agent，处理依赖关系，支持长时间窗口

**关键概念**：
- **Task Graph**：带依赖关系的任务 DAG
- **TaskScheduler**：持久化任务、7×24 唤醒机制、DAG 调度
- **SQLite 持久化**：任务状态 survives 重启

**Task 状态机**：`pending → running → completed/failed`
- `blocked`：等待依赖项
- 自动 unblock 依赖满足时

### 4. Cross-Agent Memory

**职责**：Agent 之间的共享上下文

**设计**：
- 每个 Agent 有私有记忆
- Hermes OS 维护共享记忆空间
- Agent 可以读写共享上下文

### 5. Skill Discovery (skill_discovery.py)

**职责**：动态从 GitHub 获取缺失能力，主动学习

**发现环路**：
```
检测能力缺口 → GitHub 搜索 → 评估质量 → 存储为 transient skill
     ↓
使用 → 追踪有效性 → 决定固化或丢弃
```

**Transient Skills**：存储在 `~/.hermes/skills/_transient/`
**Solidified Skills**：移动到 `~/.hermes/skills/<name>/`

### 6. Result Aggregation

**职责**：合并多个 Agent 的结果

**挑战**：不同输出格式、部分失败、冲突

### 7. Claude Code Invoker (claude_code_invocator.py)

**职责**：Hermes OS 调用 Claude Code 的标准化接口

**设计决策**：
- `--bare` 模式：跳过 CLAUDE.md 自动发现（避免递归超时）
- `--add-dir` 显式添加目录：保留工具访问能力
- `--no-session-persistence`：每次调用独立 session
- SIGTERM 超时保护：避免永不终止的任务

**关键发现（2026-04-28）**：
- `--bare` + Read 工具组合读大文件会超时
- 解决：用 Bash 命令（`head`, `wc`, `grep`）代替 Read 工具

**API**：
```python
from hermes_os import invoke, invoke_stream, invoke_bash, health_check

# 单次任务（分析/规划）
result = await invoke(prompt="分析 PR 安全性", cwd=project_path, max_turns=20)

# 流式任务（代码生成）
async for line in invoke_stream(prompt="生成测试", cwd=project_path):
    print(line)

# 纯命令执行
result = await invoke_bash("wc -l src/main.py")
```

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
