# Hermes OS 协调者架构 — Agent 关系重新定义

## 第一性目标

**Hermes OS 是一支虚拟团队，不是工具集合。**

核心隐喻：
- **协调者（Orchestrator）** = Hermes，不执行具体任务，只决策和分配
- **执行者（Executor）** = Claude Code subagent，独立运行，有自主权
- **专业 Agent** = OMC/ECC 的领域专家，作为 subagent 被调度

---

## 架构原则

### 1. 决策与执行分离

```
用户请求
    ↓
Hermes（协调者）— 理解意图、分解任务、分配、执行监督、质量门控
    ↓ 分配
Claude Code subagent — 以专业角色运行，自主执行，有自己的工具集
    ↓ 结果
Hermes — 审核结果，决定是否重做或交付
```

**违反此原则的症状：**
- Hermes 自己读代码、自己写代码 → 是工具，不是协调者
- Hermes 读了一个 agent prompt 然后"以那个角色"执行 → 是角色扮演，不是 delegation

### 2. Agent 是独立进程，不是 context 注入

OMC/ECC 的 subagent 通过 `spawn_agent` 启动独立进程，拥有：
- 独立 context window
- 独立工具访问
- 独立决策权

**Hermes 的等效实现：**
- 通过 `claude -p` 启动独立进程（每次调用 = 一个 subagent）
- 注入完整的 role prompt + 任务描述
- subagent 有自主执行权，Hermes 不中途干预

### 3. 协调者不做事，只派活

协调者的职责：
- 理解用户意图
- 决定调用哪个/哪些专业 agent
- 构造完整的 agent 调用（prompt + context）
- 监督执行（看结果，不看过程）
- 质量门控（接受/打回/重组）
- 组合多 agent 结果交付用户

---

## Agent 目录（映射到 OMC/ECC）

| 任务类型 | Agent | 来源 | 执行模式 |
|---------|-------|------|---------|
| 系统架构/设计 | `architect` | OMC | claude -p + role prompt |
| 多文件实现/重构 | `executor` | OMC | claude -p + role prompt |
| 执行计划/任务排序 | `planner` | OMC | claude -p + role prompt |
| Bug 根因分析 | `debugger` | OMC | claude -p + role prompt |
| 方案质疑/挑战 | `critic` | OMC | claude -p + role prompt |
| TDD 开发流程 | `tdd-guide` | ECC | claude -p + role prompt |
| 全面代码审查 | `code-reviewer` | ECC | claude -p + role prompt |
| 安全漏洞扫描 | `security-reviewer` | ECC | claude -p + role prompt |
| 死代码清理 | `refactor-cleaner` | ECC | claude -p + role prompt |
| 构建错误修复 | `build-error-resolver` | ECC | claude -p + role prompt |

---

## 调用协议

### 核心原语：`orchestrate(agent, task, context)`

```python
# Hermes 调用一个 subagent 的标准方式
def orchestrate(agent: str, task: str, cwd: str, context: str = "") -> str:
    """
    1. 读取对应 agent prompt 文件
    2. 拼接完整 prompt: <agent_prompt>\n\n<Task>\n{task}\n</Task>\n<Context>\n{context}\n</Context>
    3. 调用 claude -p <prompt> --no-stream --max-turns N --add-dir <cwd>
    4. 返回 stdout 结果
    """
```

### 并行调用（独立任务）

当多个子任务互不依赖时，**必须并行调度**：

```python
# 场景：PR 审查需要安全 + 质量 + 性能 三个维度同时审查
async def orchestrate_parallel(tasks: list[dict]) -> list[str]:
    """
    tasks = [
        {"agent": "security-reviewer", "task": "...", "cwd": "..."},
        {"agent": "code-reviewer", "task": "...", "cwd": "..."},
        {"agent": "performance-reviewer", "task": "...", "cwd": "..."},
    ]
    并行调用 claude -p，结果汇总给 Hermes 协调者
    """
```

### 顺序编排（依赖任务）

```python
# 场景：先规划 → 再实现 → 再审查
result_plan = orchestrate("planner", task_plan_request)
result_impl = orchestrate("executor", task_impl_request + f"\n\nPlan:\n{result_plan}")
result_review = orchestrate("code-reviewer", review_request + f"\n\nChanges:\n{result_impl}")
```

---

## Agent Prompt 注入格式

每个 subagent 调用必须包含：

```
[读取的 agent prompt 完整内容]

<Task>
[具体任务描述，明确交付物]
</Task>

<Context>
[必要的上下文：文件路径、相关代码片段、约束条件]
</Context>

<Constraints>
- 必须输出 [具体格式]
- 完成后必须验证 [具体指标]
- 遇到问题时 [如何处理]
</Constraints>
```

---

## 质量门控协议

Hermes 审核 subagent 结果时：

| 状态 | 行动 |
|------|------|
| 交付物完整、符合要求 | 接受，组合结果 |
| 交付物部分符合 | 打回具体步骤，要求重做那部分 |
| 方向错误 | 重新分解任务，更换 agent 类型 |
| 多次打回失败 | 升级：换成 architect 做全局分析 |

---

## 路由决策树（协调者视角）

```
用户请求
    ↓
这是「思考」还是「执行」？
    ↓
思考类（分析/规划/理解）→ Hermes 原生工具 → 快速响应
    ↓
执行类 → 哪种专业？
    ├─ 架构设计 → architect
    ├─ 编码实现 → executor 或 tdd-guide
    ├─ 代码审查 → code-reviewer + security-reviewer（并行）
    ├─ Bug 调试 → debugger（先读证据）
    ├─ 构建错误 → build-error-resolver
    ├─ 死代码清理 → refactor-cleaner
    └─ 探索性研究 → 多个专家并行
    ↓
派发给对应的 Claude Code subagent
    ↓
质量门控 → 交付用户
```

---

## 当前实现方式

由于 `claude --acp` 不可用，Hermes 通过 `terminal()` 调用 `claude -p`：

```bash
claude -p "<full_prompt>" \
  --no-stream \
  --max-turns 50 \
  --add-dir /path/to/project \
  --output-format text
```

每次调用 = 一个独立 subagent 生命周期。

---

## 文件位置

- Agent prompts: `~/oh-my-claudecode/agents/*.md`
- ECC agent prompts: `~/everything-claude-code/agents/*.md`
- 调用封装: `~/.hermes/scripts/orchestrate.py`
- 本文档: `~/hermes-os/orchestrator-architecture.md`
