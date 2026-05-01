# Hermes OS 组织架构完整方案

> **第一性目标**：Hermes OS 是一个真正的 AI 原生组织架构，不是工具，不是平台，是一支永不停机的虚拟团队。

**文档状态**：已完成 Phase 1–2，正在推进 Phase 3
**最后更新**：2025-04-28

---

## 一、根本问题：什么是"真正的 AI 组织"

### 1.1 第一性定义

一个组织之所以是组织，而不是工具集合，必须满足以下**充要条件**：

| # | 条件 | 说明 | Hermes OS 当前 |
|---|------|------|---------------|
| 1 | **成员具有组织身份** | 成员知道自己属于哪个组织，有使命和价值观认知 | ❌ claude -p 不知道自己属于 Hermes OS |
| 2 | **成员之间有角色分工** | 不同成员有不同职责，有信息共享和协作接口 | ❌ 只有"意图解析"一个角色 |
| 3 | **组织具有跨时间连续性** | 记得做过什么、决策是什么、结果是什么 | ❌ 只有个人 session 记忆，无组织记忆 |
| 4 | **组织能主动行动** | 没人发消息时也在思考、监控、预防 | ❌ CRON_TICK 空转，无主动行为 |

### 1.2 成员身份问题：最根本的架构分歧

```
问题：claude -p 是 Hermes OS 的正式成员，还是外部承包商？
```

| 视角 | 结论 | 理由 |
|------|------|------|
| 传统软件视角 | 外部工具 | claude -p 是第三方进程，Hermes OS 通过 API 调用它 |
| 组织架构视角 | 正式成员 | 如果 Hermes OS 向 claude -p 注入了完整的组织身份、角色、团队上下文，它就是成员 |
| 法律/合规视角 | 承包商 | claude -p 不在 Hermes OS 进程内运行，不受直接控制 |

**本文档的结论（路径 C）**：prompt 注入后的 claude -p 是组织的正式成员，Hermes OS 对成员身份的构建质量直接决定组织智能的高低。

### 1.3 零工经济 vs 内部雇员类比

| 维度 | 滴滴模式 | Hermes OS 当前 | Hermes OS 目标 |
|------|----------|----------------|----------------|
| 平台与司机关系 | 平台赋予身份（"滴滴司机"） | 无身份赋予 | 完整组织身份注入 |
| 任务分配 | 平台统一调度 | 用户直接触发，无调度 | 智能调度 + 主动分配 |
| 司机之间协作 | 乘客看不到协作 | 无协作机制 | 跨任务上下文共享 |
| 平台知识积累 | 平台学司机经验 | 无积累 | 组织级技能库 |
| 身份连续性 | 司机记住平台规则 | 无记忆 | 永久组织记忆 |

---

## 二、当前架构分析（代码级诊断）

### 2.1 组件职责地图

```
hermes-agent gateway（外部）
  └── 接收飞书消息 → GatewayEvent
  └── 传入 Hermes OS

UserRouter（router.py）
  └── upsert_user()：用户注册
  └── route()：memory + knowledge 注入
  └── 返回 RoutedRequest → hermes-agent 直接响应

ChiefAgent（chief_agent.py）
  └── parse_intent()：LLM 解析意图（INTENT_PROMPT_TEMPLATE，只用一次）
  └── create_task_dag()：创建 Task 记录，metadata 有 intent_action + priority
  └── get_proactive_suggestions()：扫描失败/阻塞任务做建议 ← 从未被自动调用

TaskScheduler（task_scheduler.py）
  └── SQLite 持久化 Task DAG
  └── _process_pending_tasks()：调用 invoke() 执行任务

ClaudeCodeInvocator（claude_code_invocator.py）
  └── invoke()：封装 claude -p，支持 --append-system-prompt
  └── build_args()：构建命令行参数

SkillLoader（skill_loader.py）
  └── get_all_prompt_fragments()：生成 transient skills 注入片段
  └── 从未被集成到 invoke() 调用链

EventBus（event_loop.py）
  └── Pub/Sub 事件系统（CRON_TICK / USER_MESSAGE / TASK_COMPLETED 等）
  └── HermesOSEventLoop：定时发送 CRON_TICK
  └── 从未触发 ChiefAgent.get_proactive_suggestions()
```

### 2.2 关键断点：system_prompt 从未注入

**task_scheduler.py:388-396**（修改前）：
```python
result = await invoke(
    prompt=task.description,
    system_prompt=task.metadata.get("system_prompt"),  # ← 永远是 None
    ...
)
```

**chief_agent.py:311-316**（修改前）：
```python
metadata={"intent_action": action, "priority": priority.value}  # ← 没有 system_prompt
```

**结论**：claude -p 被调用时，接收到的只有 `task.description`，没有任何关于"我是谁"、"我在团队中的角色"、"我的同事在做什么"的信息。

### 2.3 完整事件流：当前 vs 目标

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
  → ChiefAgent.parse_intent() 或 get_proactive_suggestions()
  → create_task_dag() 创建任务
  → TaskScheduler._process_pending_tasks()
  → invoke() 时注入完整上下文：
      ├── Organization Identity Prompt（Hermes OS 的使命）
      ├── Role Definition（当前角色：Researcher/Coder/Reviewer）
      ├── Team Context（同任务链的其他 subtask 状态）
      └── Organization Memory（相关历史决策和技能）
  → claude -p 以组织成员身份执行
  → 结果写回 TaskScheduler
  → EventBus 触发后续任务或通知
```

---

## 三、技术路径选择：路径 C（混合型）

### 3.1 三条路径对比

| 路径 | 本质 | 优点 | 缺点 |
|------|------|------|------|
| **A：纯 prompt 注入** | Hermes OS = 高质量 prompt 工程系统 | 快速实现，复用 claude -p 能力 | 组织边界模糊，外部依赖强 |
| **B：内部 Agent 实例** | 自建 Python Agent 类（规划+记忆+工具调用） | 真正拥有成员，清晰边界 | 工作量大，重复造轮子 |
| **C：混合型 ★** | 内部协调层 + 外部专家顾问 | 务实平衡，可演进 | 需要维护两套路径 |

### 3.2 混合型架构图

```
┌─────────────────────────────────────────────────────────┐
│  Hermes OS（内部协调层）7x24 运行                         │
│                                                         │
│  EventBus ──→ 事件驱动核心                               │
│    ├── CRON_TICK（每60s）→ proactive_engine             │
│    ├── TASK_COMPLETED  → 触发后续任务                     │
│    ├── TASK_FAILED    → 触发自动修复                     │
│    └── USER_MESSAGE   → 被动响应                         │
│                                                         │
│  Organization Memory ──→ 跨任务知识积累                  │
│    ├── 技能库：有效技能记录                              │
│    ├── 决策日志：重大决策及理由                          │
│    └── 错误知识库：已知错误及解决方案                    │
│                                                         │
│  ChiefAgent ──→ 意图解析 + 主动建议                      │
│    ├── parse_intent()                                   │
│    ├── create_task_dag()                                │
│    └── get_proactive_suggestions()                      │
│                                                         │
│  TaskScheduler ──→ 任务调度 + 执行引擎                   │
│    └── _process_pending_tasks() → invoke() + 上下文注入  │
│                                                         │
│  Direct Action Layer（直接执行层）                       │
│    └── 文件/命令/API操作 → SkillLoader 集成             │
└─────────────────────────────────────────────────────────┘
                        │
                        │ 需要深度推理时
                        ▼
┌─────────────────────────────────────────────────────────┐
│  claude -p（外部专家，以 Hermes OS 成员身份运行）          │
│                                                         │
│  Organization Identity：Hermes OS 成员                   │
│  Role：Researcher / Coder / Reviewer / Executor         │
│  Team Context：当前任务链状态 + 前序结论                 │
│  Org Memory：相关历史经验和错误知识                      │
│  Transient Skills：从 SkillLoader 加载                   │
└─────────────────────────────────────────────────────────┘
```

---

## 四、已实施内容（Phase 1–2）

### 4.1 新增文件

**`org_context.py`**（新建，279+97行）

```python
# Role enum：10个角色
class Role(str, Enum):
    EXECUTOR = "executor"          # fix_bug / deploy / test / query
    PLANNER = "planner"            # code
    REVIEWER = "reviewer"          # review
    RESEARCHER = "researcher"       # research
    ARCHITECT = "architect"
    SECURITY_REVIEWER = "security_reviewer"
    BUILD_ERROR_RESOLVER = "build_error_resolver"
    REFACTOR_CLEANER = "refactor_cleaner"
    DOC_UPDATER = "doc_updater"

# 组织身份
ORG_IDENTITY = {
    "name": "Hermes OS",
    "type": "AI-native virtual organization",
    "mission": "Provide 7x24 autonomous task execution with zero manual intervention",
    "values": ["Full autonomy", "Quality-first", "Transparent reasoning", ...],
    "operating_principles": [...]
}

# Intent → Role 映射
INTENT_TO_ROLE = {
    "fix_bug": Role.EXECUTOR,
    "deploy": Role.EXECUTOR,
    "code": Role.PLANNER,
    "research": Role.RESEARCHER,
    "review": Role.REVIEWER,
    ...
}

# 核心函数
build_org_context(role)            # 组装完整 org context
build_team_context(task, scheduler) # 异步查询同 macro 链的 subtask 状态
get_role_for_intent(action)        # Intent → Role 自动选择
```

### 4.2 修改文件

**`chief_agent.py`**（2处）

```python
# 导入（line 23-29）
from hermes_os.org_context import (
    ORG_IDENTITY, ROLE_DEFINITIONS, Role,
    build_org_context, get_role_for_intent,
)

# create_task_dag() metadata 扩展（line 318-333）
role = get_role_for_intent(action)
org_ctx = build_org_context(role)
metadata={
    "intent_action": action,
    "priority": priority.value,
    "role": role.value,                    # ← 新增
    "system_prompt": org_ctx.system_prompt, # ← 新增
    "org_identity": ORG_IDENTITY,          # ← 新增
    "role_definition": ROLE_DEFINITIONS[role], # ← 新增
}
```

**`task_scheduler.py`**（3处）

```python
# 1. 导入（line 27）
from hermes_os.org_context import build_team_context

# 2. _process_pending_tasks() 执行前注入团队上下文（line 383-391）
base_system_prompt = task.metadata.get("system_prompt") or ""
team_context = await build_team_context(task, self)
system_prompt = (base_system_prompt + "\n" + team_context).strip()
invoke(prompt=task.description, system_prompt=system_prompt, ...)

# 3. get_macro_progress() 返回值增强（line 567-593）
"tasks[]" 新增 result / error 字段
"tasks[]" 按 subtask_index 排序（而非 created_at DESC）
```

### 4.3 验证结果

```
=== Full system_prompt for 'Fix bug' (task B) ===
=== HERMES OS ORGANIZATION CONTEXT ===
Organization: Hermes OS
Type: AI-native virtual organization
Mission: Provide 7x24 autonomous task execution with zero manual intervention

Core Values:
  - Full autonomy — act without asking confirmation
  - Quality-first — every deliverable meets production standards
  ...

You are an Executor Agent within Hermes OS — ...

=== TEAM CONTEXT ===
Project: Investigate bug in auth.py (step 2/3)

  ✓ [completed] Investigate bug in auth.py
      └─ Investigation complete: root cause is null pointer in auth.py line 42
  ○ [pending] Fix bug in auth.py → IN PROGRESS
  ○ [pending] Test fix for auth.py
========================================
Total: 1513 chars（含 org identity + role + team context）
```

---

## 五、待实施内容（Phase 3–6）

### Phase 3：主动触发机制（最关键）

**目标**：Hermes OS 在没有用户消息时也在工作。

**当前问题**：
```
EventBus CRON_TICK 每60秒发送心跳
  → 没有任何 handler 响应
  → Hermes OS 实际上处于"待机"状态
```

**解决方案**：

```python
# proactive_engine.py（新文件）
from hermes_os.event_loop import on_cron_tick

@on_cron_tick(tick_interval=60.0)  # 每分钟巡逻
async def proactive_patrol(event: Event, scheduler: TaskScheduler, chief: ChiefAgent):
    tick = event.payload["tick_count"]

    # 每5分钟做深度主动检查（避免过载）
    if tick % 5 != 0:
        return

    for user in await get_active_users():
        # 1. 失败任务 → 自动创建修复任务
        failed = await scheduler.get_tasks_for_user(user.user_id, status=TaskStatus.FAILED)
        for task in failed[:1]:
            suggestion = await chief.analyze_failure_and_suggest_fix(task)
            if suggestion:
                await scheduler.schedule_task(
                    user_id=user.user_id,
                    title=f"Auto-fix: {task.title}",
                    description=suggestion.description,
                    metadata={**task.metadata, "auto_created": True, "role": "executor"}
                )

        # 2. 阻塞任务 → 尝试解决依赖
        blocked = await scheduler.get_tasks_for_user(user.user_id, status=TaskStatus.BLOCKED)
        for task in blocked[:1]:
            if await can_auto_resolve(task, scheduler):
                await resolve_and_unblock(task, scheduler)

        # 3. 主动建议 → 飞书通知用户
        suggestions = await chief.get_proactive_suggestions(user.user_id, scheduler)
        for text in suggestions[:2]:
            await notify_user(user, text)
```

**集成到 EventBus**：
```python
# 在 HermesOSEventLoop 启动时注册
loop = HermesOSEventLoop(tick_interval=60.0)
loop.register_handler(EventType.CRON_TICK, proactive_patrol)
await loop.start()
```

**验收标准**：
- [ ] 创建一个会失败的任务，等待5分钟，检查是否自动创建了修复任务
- [ ] 检查是否收到飞书主动通知

---

### Phase 4：组织记忆系统

**目标**：跨任务积累知识，不重复同样的错误。

**三层记忆架构**：

```
个人记忆（MemoryRouter）← session 级别，用户偏好
  ↓ 覆盖：用户个人习惯、对话历史

团队记忆（OrgMemory.team_scope）← 团队内共享
  ↓ 覆盖：团队内有效技能、团队内决策

组织记忆（OrgMemory.global_scope）← 全组织共享
  覆盖：使命、价值观、通用技能、错误知识库
```

**实现**：

```python
# organization_memory.py（新文件）
@dataclass
class OrgMemory:
    skill_library: dict[str, SkillRecord]   # skill_name → effectiveness
    decision_log: list[DecisionRecord]       # 决策及理由
    error_knowledge: dict[str, str]          # error_pattern → solution

    async def record_task_result(self, task: Task, success: bool):
        """任务完成后记录到组织记忆"""
        ...

    async def search_relevant_memory(self, query: str) -> str:
        """搜索相关组织记忆，构建注入上下文"""
        # 返回格式：
        # ## Relevant Skills
        # - skill_name: 85% success rate
        # ## Known Issues
        # Pattern: XXX → Solution: YYY
```

**与 invoke() 集成**：
```python
# task_scheduler.py _process_pending_tasks()
org_memory = await get_org_memory()
relevant_memory = await org_memory.search_relevant_memory(task.description)
system_prompt = base_sp + "\n" + team_ctx + "\n" + relevant_memory
```

**验收标准**：
- [ ] 任务A失败，记录到 error_knowledge
- [ ] 任务B（类似场景）创建时，claude -p 能读到"Known Issue"并避开错误方案

---

### Phase 5：混合执行层

**目标**：简单任务直接执行，不调用 claude -p。

**决策逻辑**：

```python
async def should_use_llm(task: Task) -> bool:
    """判断任务是否需要 claude -p"""
    direct_types = {"file_read", "file_write", "bash", "api_call", "test_run"}
    if task.action_type in direct_types:
        return False  # 直接执行
    if task.complexity_score > 0.7:
        return True   # 调用 claude -p
    return False
```

**直接执行层**：
```python
class DirectExecutor:
    """直接执行简单任务，不需要 LLM"""
    async def execute(self, task: Task) -> str:
        action = task.metadata.get("intent_action")
        if action == "bash":
            return await asyncio.create_subprocess_exec(...)
        if action == "file_read":
            return Path(task.description).read_text()
        ...
```

---

### Phase 6：多租户隔离与治理

**目标**：支持100用户，组织记忆按团队隔离。

**隔离架构**：

```
用户 → 团队（team）→ 组织（org）
  ↓
个人记忆（user_id 隔离）
  ↓
团队记忆（team_id 隔离）
  ↓
组织记忆（全局可见）
```

---

## 六、Intent → Role 映射表

| Intent | Role | 说明 |
|--------|------|------|
| `fix_bug` | EXECUTOR | 执行修复，精准导向 |
| `deploy` | EXECUTOR | 执行部署 |
| `code` | PLANNER | 先规划再实施 |
| `research` | RESEARCHER | 调研分析 |
| `review` | REVIEWER | 代码审查 |
| `test` | EXECUTOR | 执行测试 |
| `build` | BUILD_ERROR_RESOLVER | 专注构建错误 |
| `query` | EXECUTOR | 执行查询 |

---

## 七、Role 系统完整定义

| Role | 系统提示词关键词 | 职责 |
|------|----------------|------|
| **EXECUTOR** | "precision and quality" | 精准执行，不多不少，验证后再报完成 |
| **PLANNER** | "break down into <10 atomic steps" | 分解任务，识别风险和依赖 |
| **REVIEWER** | "BLOCKER/MAJOR/MINOR/SUGGESTION" | 找 bug、风格、最佳实践 |
| **RESEARCHER** | "multiple sources, cite facts" | 多源调研，结构化输出 |
| **ARCHITECT** | "scalability, reliability, security" | 系统设计，多方案对比 |
| **SECURITY_REVIEWER** | "CRITICAL/HIGH/MEDIUM/LOW" | 安全漏洞识别 |
| **BUILD_ERROR_RESOLVER** | "fix one at a time" | 逐个修复构建错误 |
| **REFACTOR_CLEANER** | "preserve behavior" | 清理死代码，不改功能 |
| **DOC_UPDATER** | "match actual behavior" | 文档与代码同步 |

---

## 八、技术实施路线图

```
Week 1-2   Phase 1: 组织身份 + 角色注入          ✓ 已完成
Week 2-3   Phase 2: 团队上下文传递               ✓ 已完成
Week 3-5   Phase 3: 主动触发机制                 ← 下一阶段
Week 5-7   Phase 4: 组织记忆系统
Week 7-9   Phase 5: 混合执行层
Week 9-10  Phase 6: 多租户隔离与治理
```

---

## 九、红旗测试（验证是否真正成为组织）

以下现象说明 Hermes OS 还是"工具"而非"组织"：

- [ ] claude -p 的响应中没有"我是 Hermes OS 的 XXX"这样的身份认知
- [ ] 两个连续任务之间没有上下文传递
- [ ] 失败的任务没有任何自动分析和重试
- [ ] 没有用户消息时，Hermes OS 完全静止
- [ ] 相同的错误重复出现（没有组织记忆）
- [ ] 所有任务都通过没有角色区分的调用完成

**绿灯测试**（真正成为组织的标志）：

- [ ] claude -p 每次响应前引用组织身份
- [ ] subtask[2] 知道 subtask[0] 和 subtask[1] 的结论
- [ ] 凌晨3点 Hermes OS 自动检测异常并创建修复任务
- [ ] 用户说"做上次那个项目"，Hermes OS 能准确描述上次的工作

---

## 十、核心设计决策记录

| # | 问题 | 结论 | 理由 |
|---|------|------|------|
| 1 | claude -p 的定位 | 混合模式（专家顾问+直接执行） | 纯委托失去主动能力，纯自建工作量大 |
| 2 | 身份注入方式 | 每次调用完整注入 | --no-session-persistence 强制要求；现代 LLM 上下文足够 |
| 3 | 记忆分层 | 个人→团队→组织三级隔离 | 多租户安全和知识复用的平衡 |
| 4 | 任务所有权 | Coordinator 创建，Executor/Coder 等执行 | 符合组织角色分工原则 |
| 5 | 容错设计 | 失败自动记录，错误知识库复用 | 组织必须从失败中学习 |

---

*本文档是整个讨论的系统性总结，随实施进度更新。*
*文档路径：/Users/dongshenglu/hermes-os/docs/*
