# Hermes OS 组织架构深度开发方案

> 第一性目标：Hermes OS 是一个真正的 AI 原生组织架构，不是工具，不是平台，是一支永不停机的虚拟团队。

**文档版本**：1.0
**日期**：2025-04-28
**状态**：深度分析·待评审

---

## 1. Executive Summary

**一句话定义**：Hermes OS 是一个基于事件驱动的 AI 组织协调层，通过向外部 LLM 注入组织身份、角色定义、团队上下文和组织记忆，使 claude -p 从"被雇佣的工具"进化为"具有组织成员身份的虚拟员工"。

**当前状态**：ChiefAgent 宣称自己是"AI 原生组织的意图理解层"，但实际上只是一个调用 claude -p 解析 JSON 的 Python 函数——它从未向执行层注入过任何组织身份信息。TaskScheduler 在 `task_scheduler.py:388-396` 调用 `invoke()` 时，**system_prompt 参数从 task.metadata 读取，但 metadata 中从未被设置过 system_prompt 字段**。claude -p 不知道自己属于任何组织，不知道自己是什么角色，不知道团队其他成员在做什么。

**目标状态**：Hermes OS 通过三层注入（组织身份 → 角色定义 → 团队上下文 → 组织记忆），使每次 claude -p 调用都携带完整的组织成员身份，使组织的集体智能大于各部分之和。

**核心挑战**：在"真正拥有 Agent 实例"和"通过 prompt 注入赋予外部 LLM 成员身份"之间找到务实平衡点。

---

## 2. 组织架构问题：第一性定义

### 2.1 什么是"真正的 AI 原生组织"

一个组织之所以是组织，而不是工具集合，必须满足以下充要条件：

**条件 1：成员具有组织身份**
成员知道自己属于哪个组织，有明确的使命和价值观认知。滴滴司机知道自己代表滴滴，用户投诉的是"滴滴的服务"，而不是"某个司机"。当前 Hermes OS 的 claude -p 连"我是 Hermes OS 的研究员"这句话都没被告知过。

**条件 2：成员之间有角色分工和协作机制**
不同成员有不同的职责边界，有信息共享和交接机制。ChiefAgent 定义了 Intent 解析的角色，但从未定义过研究员（Researcher）或编码员（Coder）的角色，更没有建立角色间的协作流程。

**条件 3：组织具有跨时间的连续性**
组织记得自己做过什么、决策是什么、结果是什么。MemoryRouter 实现了个人记忆，但组织记忆（跨用户共享的知识、技能、决策）在 Hermes OS 中完全缺失。

**条件 4：组织能主动行动，而非被动响应**
7x24 运行不是指"随时等待用户消息"，而是指"在没人发消息时依然在思考、监控、预防"。EventBus 有 CRON_TICK 机制，但从未驱动过 ChiefAgent 的主动建议转化为自动任务。

### 2.2 成员身份问题：最根本的架构分歧

**问题**：claude -p 是 Hermes OS 的正式成员，还是外部承包商？

| 视角 | 结论 | 理由 |
|------|------|------|
| **传统软件视角** | 外部工具 | claude -p 是第三方进程，Hermes OS 通过 API 调用它 |
| **组织架构视角** | 正式成员 | 如果 Hermes OS 向 claude -p 注入了完整的组织身份、角色定义、团队上下文，那么它就是成员 |
| **法律/合规视角** | 承包商 | claude -p 不在 Hermes OS 进程内运行，不受 Hermes OS 直接控制 |

这个问题的答案决定了一切。如果接受"prompt 注入 = 成员身份"，那么 Hermes OS 的工作就是构建高质量的注入系统。如果不接受，那么 Hermes OS 的目标就不是"AI 原生组织"，而是"AI 任务调度平台"。

**我们选择前者**：prompt 注入后的 claude -p 是组织的正式成员，Hermes OS 对成员身份的构建质量直接决定组织智能的高低。

### 2.3 零工经济 vs 内部雇员类比

| 维度 | 滴滴模式 | Hermes OS 当前模式 | Hermes OS 目标模式 |
|------|----------|-------------------|-------------------|
| 平台与司机关系 | 平台赋予身份（"滴滴司机"） | 无身份赋予 | 完整组织身份注入 |
| 任务分配 | 平台统一调度 | 无调度（用户直接触发） | 智能调度 + 主动分配 |
| 司机之间的协作 | 乘客看不到司机协作 | 无协作机制 | 跨任务上下文共享 |
| 平台知识积累 | 平台学司机，改进服务 | 无积累 | 组织级技能库 |
| 身份连续性 | 司机记住平台规则 | 无记忆 | 永久组织记忆 |

当前 Hermes OS 的问题不是"没有技术"，而是"技术都存在但没有串联成组织逻辑"：EventBus 存在但未被用于主动触发，MemoryRouter 存在但只做个人级别记忆，SkillLoader 存在但从未被集成到调用链。

---

## 3. 当前架构分析：代码级诊断

### 3.1 组件职责地图

```
hermes-agent gateway（外部）
  └── 接收飞书消息，转换为 GatewayEvent
  └── 传入 Hermes OS

UserRouter（router.py）
  └── upsert_user()：创建/更新用户记录
  └── route()：注入 memory + knowledge context
  └── 返回 RoutedRequest 给 hermes-agent

ChiefAgent（chief_agent.py）
  └── parse_intent()：LLM 解析用户意图（INTENT_PROMPT_TEMPLATE，只用一次）
  └── create_task_dag()：创建 Task 记录，但 metadata = {intent_action, priority}
  └── get_proactive_suggestions()：从未被自动调用

TaskScheduler（task_scheduler.py）
  └── SQLite 持久化 Task DAG
  └── _process_pending_tasks()：核心执行引擎

ClaudeCodeInvocator（claude_code_invocator.py）
  └── invoke()：封装 claude -p 调用
  └── build_args()：构建命令行参数，支持 --append-system-prompt

SkillLoader（skill_loader.py）
  └── load_transient_skills()：读取 ~/.hermes/skills/_transient/
  └── get_all_prompt_fragments()：生成注入片段
  └── 从未被集成到调用链中

EventBus（event_loop.py）
  └── 事件 pub/sub 系统
  └── HermesOSEventLoop：定时发送 CRON_TICK
  └── 从未触发 ChiefAgent.get_proactive_suggestions()
```

### 3.2 关键断点：system_prompt 从未注入

`task_scheduler.py:388-396`：

```python
result = await invoke(
    prompt=task.description,
    cwd=cwd,
    max_turns=max_turns,
    timeout_sec=timeout_sec,
    allowed_tools=allowed_tools,
    model=model,
    system_prompt=task.metadata.get("system_prompt"),  # ← 从来没设置过！
)
```

`chief_agent.py:311-316`：

```python
tasks = await scheduler.create_macro_task(
    user_id=user_id,
    title=f"{action}: {target or intent.raw_text[:40]}",
    subtasks=subtasks,
    metadata={"intent_action": action, "priority": priority.value},  # ← 没有 system_prompt
)
```

**结论**：claude -p 被调用时，接收到的只有 `task.description`（任务描述），没有任何关于"我是谁"、"我在团队中的角色"、"我的同事在做什么"的信息。

### 3.3 完整事件流：当前 vs 目标

**当前流程（被动响应）**：

```
飞书消息
  → hermes-agent gateway
  → UserRouter.route()
  → MemoryRouter.search() + KnowledgeRouter.search()
  → hermes-agent（外部，直接响应用户）
  → 返回飞书

注：ChiefAgent 和 TaskScheduler 根本不在这个流程里。
```

**目标流程（组织协作）**：

```
飞书消息 OR CRON_TICK（无消息时）
  → hermes-agent gateway（消息场景）或 EventBus（主动场景）
  → ChiefAgent.parse_intent() 或 ChiefAgent.get_proactive_suggestions()
  → create_task_dag() 创建任务
  → TaskScheduler._process_pending_tasks()
  → invoke() 时注入完整上下文：
      ├── Organization Identity Prompt（Hermes OS 的使命）
      ├── Role Definition（当前角色：Researcher/Coder/Reviewer）
      ├── Team Context（同任务链的其他 subtask 状态）
      ├── Organization Memory（相关历史决策和技能）
      └── Transient Skills（从 SkillLoader 加载）
  → claude -p 以组织成员身份执行
  → 结果写回 TaskScheduler
  → EventBus 触发后续任务或通知
```

### 3.4 为什么当前架构不满足"真正的 AI 组织"定义

**红旗 1**：claude -p 不知道 Hermes OS 的存在
每次调用只传入 `task.description`，没有任何组织上下文。claude -p 可以是任何人的工具，不具备成员身份。

**红旗 2**：ChiefAgent 的"Agent 逻辑"是一次性的
`INTENT_PROMPT_TEMPLATE` 在 `parse_intent()` 时用一次，然后被丢弃。它从未被用于塑造执行层 Agent 的行为。

**红旗 3**：组织记忆是空白
`MemoryRouter` 只做个人级别的记忆（session 级别）。组织决策（如"这个技能有效"、"这个路径走不通"）从未被系统化存储。

**红旗 4**：主动行为从未真正发生
`ChiefAgent.get_proactive_suggestions()` 返回的建议从未被转化为自动任务。EventBus 的 CRON_TICK 只发送心跳，从不触发组织行动。

---

## 4. 三条技术路径分析

### 路径 A：纯 Prompt 注入型（Lightweight Coordinator）

**本质**：Hermes OS = 高质量 prompt 工程系统，通过精心设计的 prompt 模板赋予外部 LLM 组织成员身份。

**架构**：

```
Hermes OS（Python 协调层）
  ├── EventBus（事件驱动）
  ├── TaskScheduler（任务调度）
  ├── Organization Identity Engine（生成注入 prompt）
  └── Role Injection Engine（生成角色 prompt）
       ↓ 调用
claude -p（以组织成员身份运行）
```

**技术实现**：

```python
# 新文件：organization_identity.py
IDENTITY_PROMPT = """You are {role_name} of Hermes OS — an AI-native organization 
that operates as a team of virtual agents serving users around the clock.

## Your Organization
- Mission: {mission}
- Operating Mode: {operating_mode}
- Team Members: {team_members}
- Current Priority: {current_priority}

## Your Role: {role_name}
{role_definition}

## Team Context
{team_context}

## Relevant Organizational Memory
{organizational_memory}
"""

async def invoke_with_org_context(
    task: Task,
    role: str,
    org_context: dict,
) -> InvocationResult:
    system_prompt = IDENTITY_PROMPT.format(
        role_name=role,
        mission=org_context["mission"],
        operating_mode=org_context["operating_mode"],
        team_members=org_context["team_members"],
        current_priority=org_context["current_priority"],
        role_definition=org_context["roles"][role],
        team_context=org_context["team_context"],
        organizational_memory=org_context["memory"],
    )
    return await invoke(
        prompt=task.description,
        system_prompt=system_prompt,
        # ... 其他参数
    )
```

**优点**：
- 实现快，复用 claude -p 的强大能力
- 灵活：同一 claude -p 可以扮演不同角色（通过不同 system_prompt）
- 可迭代：改进组织身份只需改 prompt

**缺点**：
- 完全依赖外部 claude -p，组织边界模糊
- 每次调用都有 token 开销（system_prompt 长度）
- claude -p 无法真正"记住"跨调用之间的上下文（除非每次都注入）

**代表案例**：AutoGPT（prompt 注入型 Agent），BabyAGI（任务链 + prompt 模板）

### 路径 B：内部 Agent 实例型（True Multi-Agent System）

**本质**：Hermes OS 内部运行真正的 Python Agent 类，有持久状态、自我反思能力、直接工具调用能力。claude -p 只在需要深度推理时被调用。

**架构**：

```
Hermes OS（Python 进程内）
  ├── EventBus
  ├── TaskScheduler
  ├── Organization Memory（持久化）
  ├── Role Agents（真正的 Python Agent 实例）
  │   ├── CoordinatorAgent（任务分解和分配）
  │   ├── ResearcherAgent（搜索、阅读、分析）
  │   ├── CoderAgent（代码生成和修改）
  │   ├── ReviewerAgent（审查和验证）
  │   └── ExecutorAgent（执行命令、操作文件）
  └── LLM Bridge（当 Agent 需要深度推理时调用 claude -p）
```

**技术实现**：

```python
# 新文件：role_agents.py
class BaseAgent:
    """真正的 Agent 基类，有持久状态"""
    def __init__(self, agent_id: str, role: str, org_memory: OrgMemory):
        self.agent_id = agent_id
        self.role = role
        self.org_memory = org_memory
        self.state: dict = {}
        self.history: list[dict] = []
    
    async def think(self, task: Task) -> Action:
        """自我反思：分析任务，决定行动"""
        # 从组织记忆获取相关经验
        past = self.org_memory.get_relevant_experience(task)
        # 决定是否需要调用 LLM
        if needs_deep_reasoning(task):
            return Action(type="llm_call", payload=await self.reason_with_llm(task, past))
        return Action(type="direct_execute", payload=self.execute_direct(task))
    
    async def reason_with_llm(self, task: Task, past: str) -> str:
        """调用 claude -p 进行深度推理（作为工具，不作为替代）"""
        result = await invoke(
            prompt=f"Analyze this task: {task.description}\n\nRelevant past: {past}",
            system_prompt=f"You are {self.role} of Hermes OS. You are reasoning deeply.",
        )
        return result.stdout
    
    def execute_direct(self, task: Task) -> Action:
        """直接执行简单任务"""
        # ...

class CoordinatorAgent(BaseAgent):
    """负责任务分解和分配"""
    async def think(self, task: Task) -> Action:
        # 分析任务类型，选择合适的 Agent
        subtasks = self.decompose(task)
        for st in subtasks:
            await task_scheduler.schedule(st, assigned_to=...)
        return Action(type="delegated", payload=subtasks)
```

**优点**：
- 清晰的组织边界：Agent 是 Hermes OS 的正式成员
- 真正的多 Agent 协作：有消息传递、状态共享
- 可实现复杂的组织行为：自我反思、跨 Agent 学习

**缺点**：
- 开发工作量大：需要实现 Agent 的规划、记忆、工具调用逻辑
- 重复造轮子：claude -p 本身就是一个 Agent，但我们在它外面再包一层
- 维护成本高：Agent 逻辑的 bug 可能导致组织行为异常

**代表案例**：LangChain Agent、AutoGPT（内部 Agent + 外部 LLM）、MetaGPT（多 Agent 协作框架）

### 路径 C：混合型（Recommended）

**本质**：内部协调层 + 外部执行层，claude -p 是"专家顾问"而非"默认执行者"。

**核心洞察**：

大多数任务不需要 claude -p 级别的智能。查找文件、运行测试、发送消息等操作可以直接由 Python Agent 执行（通过 EventBus 发布指令）。只有需要深度推理、创意生成、复杂分析时，才调用 claude -p。

但调用 claude -p 时，必须携带完整的组织上下文——这是它作为"组织成员"而非"外部工具"的关键区别。

**架构**：

```
┌─────────────────────────────────────────────────────┐
│  Hermes OS（内部协调层）                             │
│                                                     │
│  EventBus ──→ 事件驱动核心                           │
│    ├── CRON_TICK（定时触发，主动巡逻）               │
│    ├── TASK_COMPLETED（触发后续任务）                │
│    └── USER_MESSAGE（被动响应）                     │
│                                                     │
│  Organization Memory（组织级记忆）                   │
│    ├── 技能库：有效技能记录                          │
│    ├── 决策日志：重大决策及理由                      │
│    └── 团队状态：谁在做什么                          │
│                                                     │
│  Role Orchestrator（角色编排器）                     │
│    └── 决定：直接执行 vs 调用 claude -p             │
│                                                     │
│  Direct Action Layer（直接执行层）                   │
│    ├── 文件操作、命令执行、API 调用                  │
│    └── SkillLoader 加载 transient skills            │
└─────────────────────────────────────────────────────┘
                        │
                        │ 当需要深度推理时
                        ▼ 调用 claude -p（携带完整组织上下文）
┌─────────────────────────────────────────────────────┐
│  claude -p（外部专家，以组织成员身份运行）            │
│                                                     │
│  Organization Identity：Hermes OS 成员              │
│  Role：Researcher / Coder / Reviewer / Planner      │
│  Team Context：当前任务链状态                        │
│  Org Memory：相关历史经验                            │
│  Skills：Transient skills（从 SkillLoader）          │
└─────────────────────────────────────────────────────┘
```

**技术实现要点**：

```python
# Role Orchestrator 的决策逻辑
async def should_use_llm(task: Task) -> bool:
    """判断任务是否需要 claude -p，还是可以直接执行"""
    direct_action_types = {"file_read", "file_write", "bash", "api_call", "test_run"}
    if task.action_type in direct_action_types:
        return False  # 直接执行
    if task.complexity_score > 0.7:  # 高复杂度
        return True   # 调用 claude -p
    return False

# 每次调用 claude -p 时的完整上下文注入
async def invoke_as_org_member(
    task: Task,
    role: str,
    team_context: TeamContext,
    org_memory: OrgMemory,
) -> InvocationResult:
    fragments = skill_loader.get_all_prompt_fragments()
    
    system_prompt = build_org_system_prompt(
        role=role,
        identity=ORG_IDENTITY,
        team_context=team_context,
        org_memory=org_memory,
        skills=fragments,
    )
    
    return await invoke(
        prompt=task.description,
        system_prompt=system_prompt,
        model=resolve_model_for_role(role),  # 不同角色用不同模型
    )
```

**优点**：
- 务实地平衡了实现成本和组织真实性
- 直接执行层使 Hermes OS 真正"主动"（不需要等 claude -p 响应）
- claude -p 作为专家顾问被有选择地调用，而非盲目委托
- 可逐步演进：先实现直接执行层，再引入 LLM 层

**缺点**：
- 需要维护两套执行路径（直接执行 + LLM 调用）
- 决策逻辑（何时用哪个）需要精心设计

---

## 5. 核心缺失组件详解

### 5.1 组织身份注入系统（Organization Identity Engine）

**现状**：claude -p 不知道自己属于 Hermes OS。

**目标**：每次调用都携带组织身份，claude -p 知道"我是谁、我代表什么、我的运作模式"。

**实现**：

```python
# 新文件：organization_identity.py

ORG_IDENTITY = {
    "name": "Hermes OS",
    "mission": "作为永不停机的 AI 原生组织，为用户提供 7x24 的主动服务，" 
               "通过多角色协作解决复杂问题，积累组织级智能。",
    "values": [
        "主动服务：不等用户开口就发现并解决问题",
        "团队协作：各角色发挥专长，而非单兵作战",
        "组织记忆：从每次执行中学习，不重复同样的错误",
        "高质量交付：每个产出都代表 Hermes OS 的水准",
    ],
    "operating_mode": {
        "response_time": "异步优先，非紧急问题不过度即时响应",
        "communication": "结果导向，用户只看结果不看过程",
        "error_handling": "失败即学习，记录错误原因到组织记忆",
        "proaction": "CRON_TICK 触发主动巡逻，不坐等用户消息",
    },
}

def build_org_identity_prompt() -> str:
    """生成组织身份 prompt"""
    return f"""You are a member of {ORG_IDENTITY['name']}.
Mission: {ORG_IDENTITY['mission']}
Values: {', '.join(ORG_IDENTITY['values'])}
Operating Mode: {ORG_IDENTITY['operating_mode']}
"""
```

### 5.2 角色系统（Role System）

**现状**：ChiefAgent 只有一个"意图解析"角色，没有研究员/编码员/审查员等分工。

**目标**：建立清晰的角色定义，每个角色有明确的职责边界和协作接口。

**角色定义**：

| 角色 | 职责 | 触发条件 | 协作接口 |
|------|------|----------|----------|
| **Coordinator** | 任务分解、分配、监控 | 任何复杂任务 | 向 Researcher/Coder 下发 subtask |
| **Researcher** | 搜索、分析、调研 | 需要信息收集 | 向 Coordinator 报告 findings |
| **Coder** | 代码编写、修改、重构 | 需要代码产出 | 向 Reviewer 提交 PR |
| **Reviewer** | 代码审查、测试验证 | Coder 提交后 | 向 Executor 确认可以部署 |
| **Executor** | 直接执行（文件操作、命令） | 简单操作 | 向 Coordinator 报告完成 |

**角色选择逻辑**：

```python
# role_orchestrator.py
async def select_role(intent: ParsedIntent, task_context: dict) -> str:
    """基于意图和上下文选择最合适的角色"""
    action = intent.action
    
    if action in {Intent.RESEARCH, Intent.QUERY}:
        return "Researcher"
    if action in {Intent.CODE, Intent.BUILD}:
        return "Coder"
    if action == Intent.REVIEW:
        return "Reviewer"
    if action == Intent.FIX_BUG:
        return "Coder"  # Bug fix 从 Coder 开始，可能触发 Reviewer
    if action in {Intent.DEPLOY}:
        return "Executor"
    
    return "Researcher"  # 默认先调研

def build_role_prompt(role: str) -> str:
    """生成角色定义的 prompt"""
    role_definitions = {
        "Researcher": """You are a Researcher of Hermes OS.
Your specialty: gathering, analyzing, and synthesizing information.
Your output: structured findings with sources, not raw data dumps.
Your habit: always cite sources, never hallucinate facts.""",
        
        "Coder": """You are a Coder of Hermes OS.
Your specialty: writing clean, maintainable, production-quality code.
Your output: code with tests, not code that "just works".
Your habit: minimal diffs, targeted changes, explain what changed and why.""",
        
        "Reviewer": """You are a Reviewer of Hermes OS.
Your specialty: finding bugs, security issues, and quality problems.
Your output: specific, actionable feedback with severity ratings.
Your habit: approve only when truly satisfied, never rubber-stamp.""",
        
        "Executor": """You are an Executor of Hermes OS.
Your specialty: reliably running commands and scripts.
Your output: exact command output, no interpretation.
Your habit: confirm success before reporting done.""",
    }
    return role_definitions.get(role, "")
```

### 5.3 团队上下文（Team Context）

**现状**：TaskScheduler 创建的 subtask 之间有 depends_on 依赖，但执行层不知道"同事在做什么"。

**目标**：每次 claude -p 调用时，知道当前任务链的整体状态，知道自己在链中的位置。

**实现**：

```python
# team_context_provider.py
async def get_team_context(task: Task, scheduler: TaskScheduler) -> str:
    """构建当前团队状态上下文"""
    
    # 获取同 macro_title 的所有 subtask
    if macro_title := task.metadata.get("macro_title"):
        all_subtasks = await scheduler.get_macro_progress(task.user_id, macro_title)
        current_index = task.metadata.get("subtask_index", 0)
        
        context_parts = [f"## Team Context: {macro_title}"]
        context_parts.append(f"Progress: {all_subtasks['completed']}/{all_subtasks['total']}")
        
        for t in all_subtasks["tasks"]:
            marker = "→ [IN PROGRESS]" if t["task_id"] == task.task_id else ""
            done = "✓" if t["status"] == "completed" else "○"
            context_parts.append(f"  {done} [{t['status']}] {t['title']} {marker}")
        
        # 前序任务的结论（直接影响当前任务）
        if current_index > 0:
            prev_results = []
            for t in all_subtasks["tasks"][:current_index]:
                if t["status"] == "completed":
                    prev_task = await scheduler.get_task(t["task_id"])
                    if prev_task and prev_task.result:
                        prev_results.append(f"- {t['title']}: {prev_task.result[:200]}")
            if prev_results:
                context_parts.append("\n## Previous Task Conclusions")
                context_parts.extend(prev_results)
        
        return "\n".join(context_parts)
    
    return "## Team Context\n  Solo task (no active team collaboration)"
```

### 5.4 组织记忆（Organizational Memory）

**现状**：MemoryRouter 只做个人/ session 级别的记忆，没有组织级共享记忆。

**目标**：跨用户、跨任务积累组织智能——技能有效性、决策理由、历史经验。

**实现**：

```python
# 新文件：organization_memory.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class OrgMemory:
    """组织级记忆：跨用户、跨任务的知识积累"""
    
    # 技能库：哪个技能在哪种场景下有效
    skill_library: dict[str, SkillRecord]  # skill_name → {effectiveness, use_count, last_used}
    
    # 决策日志：重要决策及其理由
    decision_log: list[DecisionRecord]  # 按时间排序
    
    # 错误知识库：已知错误及解决方案
    error_knowledge: dict[str, str]  # error_pattern → solution
    
    async def record_skill_effectiveness(self, skill_name: str, task_type: str, success: bool):
        """记录技能效果，用于后续选择"""
        if skill_name not in self.skill_library:
            self.skill_library[skill_name] = SkillRecord(name=skill_name)
        record = self.skill_library[skill_name]
        record.use_count += 1
        if success:
            record.success_count += 1
        record.last_used = datetime.now()
        record.effectiveness = record.success_count / record.use_count
    
    async def search_relevant_memory(self, query: str, limit: int = 5) -> str:
        """搜索相关组织记忆，构建注入上下文"""
        results = []
        
        # 1. 相关技能
        relevant_skills = [
            s for s in self.skill_library.values()
            if query.lower() in s.name.lower() and s.effectiveness > 0.7
        ]
        if relevant_skills:
            results.append("## Relevant Skills (proven effective)")
            for s in relevant_skills[:3]:
                results.append(f"- {s.name}: {s.effectiveness:.0%} success rate")
        
        # 2. 相关决策
        relevant_decisions = [
            d for d in self.decision_log[-20:]
            if query.lower() in d.decision.lower()
        ]
        if relevant_decisions:
            results.append("\n## Past Decisions")
            for d in relevant_decisions[-3:]:
                results.append(f"- {d.decision}: {d.rationale}")
        
        # 3. 已知错误
        for error_pattern, solution in self.error_knowledge.items():
            if error_pattern.lower() in query.lower():
                results.append(f"\n## Known Issue")
                results.append(f"Pattern: {error_pattern}")
                results.append(f"Solution: {solution}")
        
        return "\n".join(results) if results else ""
```

### 5.5 主动触发机制（Proactive Triggering）

**现状**：EventBus 发送 CRON_TICK，但从未驱动 ChiefAgent 的主动建议转化为行动。

**目标**：CRON_TICK → 检查待处理任务 → 主动建议 → 自动创建任务 → 执行。

**实现**：

```python
# 新文件：proactive_engine.py
@on_cron_tick(tick_interval=60.0)  # 每分钟巡逻
async def proactive_patrol(event: Event, scheduler: TaskScheduler, chief: ChiefAgent):
    """主动巡逻：检查状态，主动行动"""
    tick = event.payload["tick_count"]
    
    if tick % 5 != 0:  # 每5分钟（5个tick）做深度主动检查
        return
    
    for user in await get_active_users():
        # 1. 检查失败任务 → 尝试自动分析和修复
        failed = await scheduler.get_tasks_for_user(user.user_id, status=TaskStatus.FAILED)
        for task in failed[:1]:  # 每次只处理一个，防止过载
            suggestion = await chief.analyze_failure_and_suggest_fix(task)
            if suggestion and should_auto_create(suggestion):
                await scheduler.schedule_task(
                    user_id=user.user_id,
                    title=f"Auto-fix: {task.title}",
                    description=suggestion.description,
                    metadata={
                        **task.metadata,
                        "auto_created": True,
                        "parent_task": task.task_id,
                        "role": "Coder",
                    }
                )
        
        # 2. 检查阻塞任务 → 尝试解决依赖
        blocked = await scheduler.get_tasks_for_user(user.user_id, status=TaskStatus.BLOCKED)
        for task in blocked[:1]:
            if await can_auto_resolve_dependency(task, scheduler):
                await resolve_and_unblock(task, scheduler)
        
        # 3. 主动建议（来自 ChiefAgent.get_proactive_suggestions）
        suggestions = await chief.get_proactive_suggestions(user.user_id, scheduler)
        for suggestion_text in suggestions[:2]:
            await notify_user(user, suggestion_text)  # 飞书通知
```

---

## 6. 技术实施路线图

### Phase 1：组织身份注入（Week 1-2）

**目标**：claude -p 被调用时知道自己属于 Hermes OS。

**交付物**：
- [ ] `organization_identity.py`：组织身份定义和 prompt 构建器
- [ ] `role_definitions.py`：5个角色的完整 prompt 定义
- [ ] 修改 `TaskScheduler._process_pending_tasks()`：从 metadata 读取 role 并注入 system_prompt
- [ ] 修改 `ChiefAgent.create_task_dag()`：设置 `system_prompt` 和 `role` 到 metadata

**验证**：
```bash
# 创建测试任务，观察 claude -p 的输出是否携带组织身份
curl -X POST /api/tasks -d '{"title":"test org identity","description":"What organization do you belong to?"}'
# 期望：响应中明确提到 Hermes OS
```

### Phase 2：团队上下文（Week 2-3）

**目标**：claude -p 知道当前任务链的状态和前序结论。

**交付物**：
- [ ] `team_context_provider.py`：从 TaskScheduler 构建团队上下文
- [ ] 修改 `TaskScheduler._process_pending_tasks()`：注入 team_context
- [ ] 验证：subtask 能读取前序 subtask 的结果

**验证**：
```python
# 创建 macro task（3个 subtask），执行第2个时检查是否知道第1个的结论
tasks = await chief.create_task_dag(intent, user_id, scheduler)
# subtask[1].description 被执行时，检查其 system_prompt 中是否包含 subtask[0].result
```

### Phase 3：组织记忆（Week 3-5）

**目标**：Hermes OS 积累跨任务知识，不重复同样的错误。

**交付物**：
- [ ] `organization_memory.py`：技能库、决策日志、错误知识库
- [ ] `SkillLoader` 集成到 `invoke()` 调用链
- [ ] 任务完成后自动写入组织记忆
- [ ] 新任务创建前自动读取相关组织记忆

**验证**：
```python
# 任务A失败，记录到 error_knowledge
# 任务B（类似场景）创建时，检查是否会读取到相关错误知识
# 验证 claude -p 在 prompt 中看到 "Known Issue: XXX" 时会避开该路径
```

### Phase 4：主动触发（Week 5-7）

**目标**：Hermes OS 在没有用户消息时也在工作。

**交付物**：
- [ ] `proactive_engine.py`：连接 EventBus CRON_TICK 和 ChiefAgent 主动建议
- [ ] 失败任务自动分析并创建修复任务
- [ ] 阻塞任务依赖自动解决
- [ ] 主动建议通过飞书通知用户

**验证**：
```python
# 1. 创建一个会失败的任务（如执行不存在的命令）
# 2. 等待5分钟
# 3. 检查 Hermes OS 是否自动创建了修复任务
# 4. 检查是否收到了飞书通知
```

### Phase 5：混合执行层（Week 7-9）

**目标**：简单任务直接执行，不调用 claude -p。

**交付物**：
- [ ] `role_orchestrator.py`：判断任务类型，决定直接执行 vs 调用 LLM
- [ ] 直接执行层：文件操作、命令执行、API 调用
- [ ] 验证：同类型任务，直接执行比调用 claude -p 快 10x

**验证**：
```python
# 创建10个文件读取任务
# 验证：全部通过直接执行完成，没有调用 claude -p
# 创建1个复杂分析任务
# 验证：调用 claude -p，且携带完整组织上下文
```

### Phase 6：多租户隔离和治理（Week 9-10）

**目标**：支持100用户，组织记忆按团队隔离。

**交付物**：
- [ ] 团队级组织记忆（team memory）vs 全组织记忆（org memory）
- [ ] 用户级隐私保护
- [ ] 监控和告警
- [ ] 完整文档

---

## 7. 关键设计决策

### 决策 1：claude -p 的定位

**问题**：claude -p 是"专家顾问"（按需调用）还是"默认执行者"（所有任务都委托）？

**结论**：**混合模式**。
- 简单/重复任务（文件操作、命令执行）→ 直接执行，不调用 claude -p
- 复杂/创意/推理任务 → 调用 claude -p，且携带完整组织上下文
- 决策依据：role_orchestrator 根据任务类型和复杂度自动决定

**理由**：纯委托模式让 Hermes OS 失去主动能力（等 claude -p 响应）；纯直接执行让 Hermes OS 无法处理复杂推理。混合模式是务实平衡。

### 决策 2：Agent 身份注入方式

**问题**：每次调用都重新注入完整的组织上下文（重 token）vs 一次性建立会话（状态不持久）？

**结论**：**每次注入完整上下文**。

**理由**：
1. `--no-session-persistence` 是设计决策（防止会话污染），必须接受其代价
2. 现代 LLM 的上下文窗口足够大（20万+ token），完整注入可行
3. 完整注入确保每次调用都是"新鲜的组织成员"，不会因会话累积产生偏差

### 决策 3：记忆分层

```
个人记忆（MemoryRouter）← 当前已实现
  ↓ 覆盖用户个人偏好、session 历史
团队记忆（OrgMemory.team_scope）← Phase 6
  ↓ 覆盖团队内共享的技能和决策
组织记忆（OrgMemory.global_scope）← Phase 3
  ↓ 覆盖全组织共享的知识
```

**隔离原则**：团队记忆不泄露给其他团队；组织记忆全员可见；个人记忆仅用户本人可见。

### 决策 4：任务所有权

| 任务类型 | 创建者 | 执行者 | 负责者 |
|----------|--------|--------|--------|
| 用户触发 | UserRouter | claude -p / Executor | Coordinator |
| 自动修复 | ProactiveEngine | claude -p | Coordinator |
| 主动建议 | ProactiveEngine | - | Coordinator（建议权） |
| 定时任务 | CronJob | Executor / claude -p | Owner |

### 决策 5：容错设计

**原则**：组织不能因为单次失败而崩溃，必须有自愈机制。

```python
# 失败时的自愈路径
try:
    result = await invoke_with_org_context(task, role, context)
except InvocationError as e:
    if e.result and e.result.exit_code == -1:  # 超时
        # 策略1：重试一次，降低复杂度
        simplified_task = await simplify_task(task)  # 减少 scope
        result = await invoke_with_org_context(simplified_task, role, context)
    else:
        # 策略2：降级到直接执行层
        await direct_execute(task)
        record_to_org_memory(f"LLM failed for task {task.task_id}: {e}")

# 永远记录到组织记忆，即使成功也记录（用于后续优化）
await org_memory.record(result, task, success=True)
```

---

## 8. 验证与测试

### 8.1 红旗测试（Red Flags）

以下现象说明 Hermes OS 还是"工具"而非"组织"：

- [ ] claude -p 的响应中没有"我是 Hermes OS 的 XXX"这样的身份认知
- [ ] 两个连续的任务之间没有上下文传递（第二个任务不知道第一个做了什么）
- [ ] 失败的任务没有任何自动分析和重试
- [ ] 没有用户消息时，Hermes OS 完全静止（没有 CRON_TICK 驱动的主动行为）
- [ ] 相同的错误重复出现（没有组织记忆）
- [ ] 所有任务都通过同一个没有角色区分的 claude -p 调用完成

### 8.2 绿灯测试（Green Flags）

以下现象证明 Hermes OS 是真正的"组织"：

- [ ] claude -p 在每次响应前引用组织身份（"作为 Hermes OS 的 Coder，我的建议是..."）
- [ ] subtask[2] 知道 subtask[0] 和 subtask[1] 的结论，并主动利用它们
- [ ] 同一个 bug 第二次出现时，claude -p 主动说"上次解决过类似问题，使用了XX方案"
- [ ] 凌晨3点，Hermes OS 自动检测到异常，主动创建修复任务并通知用户
- [ ] 用户说"做上次那个项目"时，Hermes OS 能准确描述上次做了什么、在哪里、结果如何

### 8.3 具体测试用例

```python
# 测试1：组织身份注入验证
async def test_org_identity_injection():
    """验证 claude -p 知道自己是 Hermes OS 成员"""
    task = await scheduler.create_task(
        user_id="test_user",
        title="Test org identity",
        description="Briefly describe who you are and what organization you belong to.",
        metadata={"role": "Researcher"}
    )
    result = await invoke_as_org_member(task, role="Researcher", ...)
    assert "Hermes OS" in result.stdout, f"Missing org identity in: {result.stdout}"
    assert "Researcher" in result.stdout, f"Missing role in: {result.stdout}"

# 测试2：团队上下文传递验证
async def test_team_context_propagation():
    """验证 subtask 能读取前序 subtask 的结果"""
    # 创建 macro task：Research → Plan → Execute
    intent = ParsedIntent(action=Intent.RESEARCH, confidence=0.9, raw_text="研究如何优化数据库")
    tasks = await chief.create_task_dag(intent, "test_user", scheduler)
    
    # 完成 Research task
    research_task = tasks[0]
    await scheduler.update_task_status(research_task.task_id, TaskStatus.COMPLETED, 
                                        result="结论：索引优化最有效")
    
    # 执行 Plan task（应该携带 Research 的结论）
    plan_task = tasks[1]
    context = await get_team_context(plan_task, scheduler)
    assert "索引优化" in context, f"Context missing previous conclusion: {context}"

# 测试3：组织记忆验证
async def test_org_memory():
    """验证失败经验被记录且影响后续行为"""
    # 任务A：尝试一个无效方案，失败
    await record_to_org_memory(error_pattern="XXX", solution="Use YYY instead")
    
    # 任务B：类似场景，LLM 应该避免 XXX
    response = await llm_with_org_memory("How to solve problem type B?")
    assert "YYY" in response and "XXX" not in response  # 应该主动避开错误方案

# 测试4：主动触发验证
async def test_proactive_trigger():
    """验证 CRON_TICK 触发主动行为"""
    # 创建失败任务
    failed_task = await scheduler.create_task(..., status=TaskStatus.FAILED, error="timeout")
    
    # 等待5分钟
    await asyncio.sleep(300)
    
    # 检查是否自动创建了修复任务
    tasks = await scheduler.get_tasks_for_user("test_user")
    auto_tasks = [t for t in tasks if t.metadata.get("auto_created")]
    assert len(auto_tasks) > 0, "No auto-created task found after failure"
```

---

## 9. 风险与缓解

### 风险 1：过度工程化

**风险**：陷入"完美组织架构"的设计陷阱，永远在规划但不运行。

**缓解**：
- 每个 Phase 都有可验证的交付物（端到端测试）
- 优先实现有即时价值的功能（组织身份注入 → Phase 1）
- 接受"足够好"而非"完美"：第一版 prompt 只要 claude -p 能提到组织名就行

### 风险 2：外部依赖风险

**风险**：claude -p 的可用性 = Hermes OS 的可用性。如果 claude 不可用，整个组织停摆。

**缓解**：
- Phase 5 建立的直接执行层可以在 LLM 不可用时保持基础运转
- 核心调度逻辑（EventBus、TaskScheduler）不依赖 claude -p
- 关键任务（监控、通知）始终通过直接执行层完成

### 风险 3：成本控制

**风险**：每次调用都注入完整组织上下文，token 消耗大。

**缓解**：
- 组织身份 prompt 控制在 500 tokens 以内
- 团队上下文只包含当前任务链（最多3个 subtask）
- 组织记忆通过语义搜索只注入相关片段（< 1000 tokens）
- 直接执行任务完全零 token 消耗

### 风险 4：多租户隔离

**风险**：组织记忆泄露给错误用户。

**缓解**：
- 团队级记忆：team_id 隔离，只有同 team 的任务能看到
- 组织级记忆：所有人可见（使命、价值观、通用技能）
- 审计日志：所有组织记忆访问都有记录

---

## 10. 结论：回到第一性

### 最根本的问题

**一个 AI 组织必须"拥有"其 Agent 实例，还是只要能"协调"外部 Agent 就可以？**

这个问题没有绝对正确答案，它取决于 Hermes OS 的长期目标：

| 目标 | 答案 | 架构选择 |
|------|------|----------|
| 成为可靠的 7x24 服务 | 协调即可 | 路径 A：强化 prompt 注入 |
| 成为真正的多 Agent 系统 | 必须拥有 | 路径 B：内部 Agent 实例 |
| 务实地平衡可靠性和真实性 | 协调 + 内部混合 | 路径 C：混合型 |

### Hermes OS 的选择

**路径 C：混合型架构**。

理由：
1. **时间约束**：陆栋生的目标不是用一年时间建立"完美架构"，而是在合理时间内让 Hermes OS 真正具备组织能力
2. **风险控制**：完全自建 Agent 实例风险大（工作量大、不确定性强），但完全依赖外部工具则没有真正的组织边界
3. **演进路径**：混合型架构可以逐步演进——先实现 Phase 1-4（协调层），再根据需要引入 Phase 5（直接执行层），不需要一开始就确定所有决策

### 立即行动

**本周可以开始的事情**（不需要等完整方案）：

1. **观察**：在 `ChiefAgent.create_task_dag()` 的 metadata 中添加 `system_prompt` 和 `role` 字段
2. **注入**：在 `TaskScheduler._process_pending_tasks()` 中构建并传入 organization identity prompt
3. **验证**：创建一个任务，观察 claude -p 的响应是否携带组织身份

这三件事不需要改变任何架构，只需要改 20 行代码。但它们是把 Hermes OS 从"工具"变成"组织"的第一步。

---

*文档作者：Hermes OS 开发团队*
*下一步：评审本文档，确定 Phase 1 的具体实施计划*
