# Hermes OS — 多用户服务平台 SPEC

> Version: 0.3.0
> Base: hermes-agent v0.11.0
> Goal: 在 hermes-agent 之上构建多用户路由层，服务 100 用户

---

## 故事列表

### Phase 1: MVP（当前）

- [story-01] 用户身份识别：接收 gateway 消息，识别 user_id，复用 pairing system
- [story-02] Session 隔离：为每个用户创建独立 session，对话历史不串
- [story-03] 上下文注入：在消息发往 hermes-agent 前，注入 `<current_user>` 标签块
- [story-04] 记忆隔离：per-user 外部记忆，user_id 路由到独立记忆空间
- [story-05] 双用户集成测试：模拟两个用户同时发消息，验证上下文不串

### Phase 2: 知识库

- [story-06] 共享知识库：GBrain / Qdrant RAG，多用户可查
- [story-07] 知识库路由：用户查询时自动检索相关文档注入上下文

### Phase 3: 用户管理

- [story-08] 邀请码/审批流：用户注册需要管理员审批
- [story-09] 用户管理后台：Supabase 存储用户/团队/订阅
- [story-10] 订阅/计费：Free / Pro / Team 套餐

---

## 架构

### 完整层次

```
用户
  ↓
┌─────────────────────────────────────────────────────────┐
│                 Hermes OS 多用户层                         │
│                                                         │
│  用户管理层                                              │
│  ├── 认证（Supabase Auth）                              │
│  ├── 邀请码 / 审批流                                    │
│  └── 订阅 / 计费（Stripe）                              │
│                                                         │
│  上下文控制层（三层叠加）                                  │
│  ├── L1: 用户记忆（mem0 per-user）                      │
│  ├── L2: 共享知识库（GBrain / Qdrant）                   │
│  └── L3: Hermes 压缩（Context Compressor）               │
│                                                         │
│  路由层                                                  │
│  ├── UserRouter（身份识别）                             │
│  ├── SessionManager（会话隔离）                          │
│  ├── ContextInjector（上下文注入）                        │
│  └── KnowledgeRouter（知识库检索）                       │
└─────────────────────────────────────────────────────────┘
  ↓
hermes-agent（执行者，对用户不可见）
  ↓
模型层（用户不可见）
├── 本地推理（AMD AI MAX 395）
└── 云端 API（Claude / GPT，按需 fallback）
```

### 三层上下文（核心价值）

```
┌────────────────────────────────────────────────────────┐
│ L1: 用户记忆（per-user）                               │
│     目标：让 AI 认识这个用户                           │
│     技术：mem0 per-user namespace                      │
├────────────────────────────────────────────────────────┤
│ L2: 共享知识库（multi-user）                          │
│     目标：团队/组织的文档知识                           │
│     技术：GBrain / Qdrant + RAG                        │
├────────────────────────────────────────────────────────┤
│ L3: Hermes 压缩                                        │
│     目标：在有限 context 里塞最多有效信息               │
│     技术：Context Compressor（hermes-agent 内置）      │
└────────────────────────────────────────────────────────┘
```

### 上下文注入格式

```xml
<current_user>
id: {user_id}
name: {name}
role: {role}
team: {team}
</current_user>

<knowledge>
{retrieved_context_from_knowledge_base}
</knowledge>
```

---

## 用户视角

```
用户感知到的：
  → 一个私人助理
  → 多通道接入（微信/飞书/Telegram）
  → 无感知模型切换

用户不感知的：
  → 底层模型（本地/云端）
  → 多用户隔离逻辑
  → 知识库检索
```

---

## 数据模型

### User

```python
@dataclass
class User:
    user_id: str           # 唯一标识
    supabase_uid: str      # Supabase Auth UID（关联）
    name: str              # 显示名
    role: str              # user | admin
    team: str              # 团队名
    tier: str              # free | pro | team
    platform: str           # telegram | discord | feishu | wechat
    platform_user_id: str  # 平台原始 user id
    status: str            # pending | active | suspended
    created_at: datetime
```

### Session

```python
@dataclass
class Session:
    session_id: str
    user_id: str
    conversation_history: list[Message]
    created_at: datetime
    last_active: datetime
```

### KnowledgeBase

```python
@dataclass
class KnowledgeDoc:
    doc_id: str
    team: str              # 团队可见范围
    title: str
    content: str
    embedding: list[float]  # 向量
    updated_at: datetime
```

---

## 技术决策

| 决策 | 选项 | 选择 |
|------|------|------|
| 用户进来 | 复用 hermes-agent pairing + 邀请码审批 | MVP: pairing，全态: Supabase |
| 上下文隔离 | 单实例 + system prompt 注入 | ✓ |
| 记忆隔离 | mem0 per-user | ✓ |
| 知识库 | GBrain / Qdrant RAG | Phase 2 |
| 用户管理 | Supabase（用户+订阅+RLS） | Phase 3 |
| 计费 | Stripe + 按用户数套餐 | Phase 3 |
| Session 存储 | SQLite（MVP）/ PostgreSQL（全态） | ✓ |
| 并发模型 | asyncio | ✓ |

---

## 暂不实现（Phase 4+）

- 多租户 SLA 保障
- 开发者 API Keys（外部接入）
- 自定义 Agent 定制
- 插件市场
- 企业 SSO（SAML/OIDC）

---

## 核心组件

| 文件 | 职责 | 关键能力 |
|------|------|----------|
| `router.py` | 多用户路由层入口 | UserRegistry、SessionManager、上下文注入 |
| `task_scheduler.py` | 任务持久化 + DAG 调度 | 长时间窗口、7×24、任务依赖、macro task |
| `skill_discovery.py` | GitHub 技能发现 + 自学习 | 能力缺口检测、transient skills、有效性追踪 |
| `memory_router.py` | per-user 记忆（mem0） | 用户偏好学习 |
| `knowledge_router.py` | 共享知识库 RAG | 团队文档检索 |
| `context_injector.py` | 上下文注入 | 三层叠加（L1/L2/L3） |

### TaskScheduler 核心能力

```python
# 创建独立任务
task = await scheduler.create_task(user_id="...", title="清理技术债")

# 创建宏任务（自动管理依赖 DAG）
subtasks = await scheduler.create_macro_task(
    user_id="...",
    title="开发新产品",
    subtasks=[
        {"title": "调研", "description": "..."},
        {"title": "设计", "description": "..."},
        {"title": "开发", "description": "..."},
    ]
)
# subtasks[1] 自动 depends_on subtasks[0]

# 查询进度
progress = await scheduler.get_macro_progress(user_id, "开发新产品")

# 启动 7×24 监听
await scheduler.start_watcher(interval_seconds=30)
```

### SkillDiscovery 核心能力

```python
# 主动发现
skill = await discovery.discover_and_learn(
    query="claude-code-tdd-workflow",
    gap_type="missing_skill",
    context="用户请求用 TDD 开发"
)

# 追踪有效性
await discovery.record_usage("tdd-workflow", success=True)
decision = await discovery.make_solidify_decision("tdd-workflow")
# decision: "solidify" | "discard" | "keep_transient"
```

### 架构图

```
用户
  ↓
┌─────────────────────────────────────────────────────────┐
│              Hermes OS 多用户层（协调层）                    │
│                                                         │
│  router.UserRouter                                      │
│  ├── SessionManager（会话隔离）                          │
│  ├── MemoryRouter（per-user 记忆）                       │
│  ├── KnowledgeRouter（共享知识库）                        │
│  ├── ContextInjector（三层上下文注入）                     │
│  ├── TaskScheduler ← 【新增：任务持久化 + 7×24】           │
│  └── SkillDiscovery ← 【新增：GitHub 自主动学习】          │
└─────────────────────────────────────────────────────────┘
  ↓
hermes-agent（Chief 角色）
  ↓
┌─────────────────────────────────────────────────────────┐
│                 Agent 执行层（ECC / newtype-os）           │
│  ECC 28 agents  +  newtype-os 8 agents  +  外部 Agents    │
└─────────────────────────────────────────────────────────┘
  ↓
GitHub（Skills 宝库 → skill_discovery 自动获取）
```

### 三层上下文

```
┌────────────────────────────────────────────────────────┐
│ L1: 用户记忆（per-user）                               │
│     目标：让 AI 认识这个用户                           │
│     技术：mem0 per-user namespace                      │
├────────────────────────────────────────────────────────┤
│ L2: 共享知识库（multi-user）                          │
│     目标：团队/组织的文档知识                           │
│     技术：GBrain / Qdrant + RAG                        │
├────────────────────────────────────────────────────────┤
│ L3: Hermes 压缩                                        │
│     目标：在有限 context 里塞最多有效信息               │
│     技术：Context Compressor（hermes-agent 内置）      │
└────────────────────────────────────────────────────────┘
```

---

## 迭代计划

```
Phase 1（MVP）— ✅ 已完成
  pairing → UserRegistry → SessionManager → 上下文注入 → hermes-agent
  → 目标：100 用户能跑通

Phase 2（+ 知识库）
  + GBrain 接入 → 共享文档 RAG 检索
  → 目标：团队知识可被助理引用

Phase 3（+ 收费）
  + Supabase 用户管理 → 订阅制
  + Stripe 计费

Phase 4（+ 任务持久化）— ✅ 已实现
  + TaskScheduler → 长时间窗口任务
  + SkillDiscovery → 动态 GitHub 自学习
  + 7×24 唤醒机制
  → 目标：宏观任务可分片执行，永不停机

Phase 5（+ 自驱动）
  + Chief proactive 模式 → 主动建议
  + 主动任务发现 → 自动创建清理/优化任务
  → 目标：Hermes OS 有自己的意志
```
Phase 4（企业功能）：
  审批流 + API Keys + 多租户隔离
```

Phase 5（+ 自驱动）：
  + Chief proactive 模式 → 主动建议
  + 主动任务发现 → 自动创建清理/优化任务
  → 目标：Hermes OS 有自己的意志
```
