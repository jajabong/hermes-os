# Hermes OS 第一性原理架构手册 (V2.1)

> **版本历史**: v1.0 → v2.0 → v2.1 (增加商业直觉与 ROI 度量层)
> **维护者**: Hermes OS Core Team
> **最后更新**: 2026-05-01

---

## 概述

Hermes OS 是一个基于 SQLite 分片、以飞书为唯一原生交互渠道的**多用户、多租户任务编排枢纽**。

**核心设计哲学**：
- 🎯 **专注而非全能**：拒绝通用平台化幻想，专注于”飞书原生交互”与”确定性流水线执行”
- ⚡ **线性扩展**：通过用户维度数据库分片实现从 1 到 100+ 用户的物理线性扩展
- 🛡️ **数据主权**：用户数据归属于私有目录，确保数据主权与隐私保护

---

## 1. 核心架构本质：数字装配线 (Digital Assembly Line)

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户 (飞书)                                │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Hermes OS 协调层                             │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │   │
│  │  │ UserRouter│ │ SessionMgr│ │TaskSched │ │GoalTrack │    │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              流水线执行层 (Pipeline Engine)              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │   │
│  │  │ Artifact │ │Guardian  │ │Notifier  │ │Governance│    │   │
│  │  │ Manager  │ │Controller│ │Manager   │ │ Layer    │    │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Agent 执行层 (ECC / OMC)                     │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**核心逻辑**：将所有复杂任务（写书、发布、代码修复）视为**原子生产任务**，通过流水线协议（Pipeline Protocol）驱动执行。

---

## 2. 高并发支撑：线性扩展的物理基础

### 2.1 并发架构

| 策略 | 实现方式 | 效果 |
|------|----------|------|
| **WAL 模式** | SQLite Write-Ahead Logging | 消除读写锁竞争 |
| **用户分片** | `~/.hermes/users/{user_id}/tasks.db` | 物理隔离，无锁冲突 |
| **异步事件** | asyncio 事件循环 | 高效并发调度 |

### 2.2 扩展路径

```
用户数:  1 ─────────────────────────────────────────────→ 100+
         │                                              │
         ↓                                              ↓
并发能力: 简单模式                                 完整分片模式
         │                                              │
         └── WAL 模式足够                            └── 需求分片
```

---

## 3. 记忆与智慧进化：双层治理模型 (Double-Layer Model)

### 3.1 三层上下文架构

```
┌────────────────────────────────────────────────────────────┐
│ L1: 用户记忆 (per-user)                                    │
│     目标：让 AI 认识这个用户                               │
│     技术：mem0 per-user namespace                         │
│     组件：memory_router.py                                 │
├────────────────────────────────────────────────────────────┤
│ L2: 共享知识库 (multi-user)                                │
│     目标：团队/组织的文档知识                               │
│     技术：GBrain / Qdrant + RAG                           │
│     组件：knowledge_router.py, brain_indexer.py            │
├────────────────────────────────────────────────────────────┤
│ L3: Hermes 压缩                                           │
│     目标：在有限 context 里塞最多有效信息                  │
│     技术：Context Compressor                               │
│     组件：context_injector.py                              │
└────────────────────────────────────────────────────────────┘
```

### 3.2 演化策略

- **失败变异**：任务失败触发知识搜索，自动发现替代方案
- **成功固化**：成功执行的任务模式通过 MV（Materialize & Validate）操作固化
- **Promotion Protocol**：个人沉淀经脱敏后转化为通用知识

---

## 4. 交互范式：从执行员到 JARVIS

### 4.1 认知去噪 (Entropy Reduction)

| 层级 | 输入 | 输出 |
|------|------|------|
| 原始日志 | 执行过程的完整 trace | ❌ 不直接呈现 |
| 结论萃取 | conclusion_extractor.py | ✅ 结论性陈述 |

**原则**：所有系统输出必须经过”结论萃取”，只交付**结论（Conclusion）** 而非原始日志（Raw Logs）。

### 4.2 主动治理 (Proactive Agency)

**里程碑交互协议（Milestone-Based Interaction）**：

```
任务执行时间线 ──────────────────────────────────────────────────→

  阶段 1      阶段 2      里程碑 A      阶段 3      里程碑 B      完成
    ↓          ↓            ↓            ↓            ↓          ↓
  [自动]    [自动]    ┌──────────┐    [自动]    ┌──────────┐    [完成]
                      │ 用户确认  │               │ 用户确认  │
                      └──────────┘               └──────────┘
                       ↑ 交互点                    ↑ 交互点
```

- ✅ 常规阶段：JARVIS 保持静默，自主执行
- ⚠️ 关键节点：请求用户确认后再继续

---

## 5. 全自动生产：数字装配线的泛化 (The Production Factory)

### 5.1 Artifact 协议

标准化工件目录结构：

```
/artifacts/{task_id}/
├── src/              # 源代码
├── render/           # 渲染产物
├── delivery/         # 交付物
├── meta.json         # 元数据（stage 状态、依赖关系）
└── logs/             # 执行日志
```

### 5.2 流水线编排流程

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  规格约束    │ →  │   生产制造   │ →  │  对抗式审计  │ →  │   交付封装   │
│  (Spec)     │    │  (Build)    │    │  (Review)   │    │ (Delivery)  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
      ↓                  ↓                  ↓                  ↓
 Pipeline.yaml     Labor Units       Guardian Pattern      Artifact Pack
```

**核心组件**：
- `pipeline_engine_v2.py`：流水线编排引擎
- `artifact_manager.py`：工件生命周期管理
- `pipeline_task_runner.py`：任务执行器

### 5B. 五大Pipeline母版 (Five Pipeline Bricks)

Hermes OS 将所有复杂任务归纳为 **5 个标准化 Pipeline 母版**，通过组合实现任意生产目标。

```
┌──────────────────────────────────────────────────────────────────────┐
│                    五大Pipeline母版 (Five Bricks)                      │
├──────────────────────────────────────────────────────────────────────┤
│  P1 │ Content Assembly  │ 内容组装流水线                               │
│     │  Write→Render→Deliver                                             │
│     │  输出：PDF/EPUB 交付物                                            │
├──────────────────────────────────────────────────────────────────────┤
│  P2 │ Intelligence     │  intelligence流水线                          │
│     │  ResearchLabor + DataLabor                                        │
│     │  DataFetch→Normalize→Reasoning→Visualize                          │
│     │  输出：结构化分析报告                                             │
├──────────────────────────────────────────────────────────────────────┤
│  P3 │ Delivery         │  交付流水线                                    │
│     │  Artifact生成→格式转换→分发                                        │
│     │  输出：Amazon/Feishu 等平台分发物                                  │
├──────────────────────────────────────────────────────────────────────┤
│  P4 │ Engineering      │  工程流水线                                   │
│     │  GitHubLabor                                                     │
│     │  Branch→Commit→PR→Merge                                          │
│     │  输出：合并到 main 的代码                                         │
├──────────────────────────────────────────────────────────────────────┤
│  P5 │ Governance       │  治理流水线（middleware）                      │
│     │  Pre/Post-Execute Hooks                                          │
│     │  权限检查→合规审计→记录                                           │
└──────────────────────────────────────────────────────────────────────┘
```

#### Pipeline Brick 详细定义

| Brick | 入口Labor | 核心阶段 | 关键工具 |
|-------|-----------|----------|----------|
| **P1** Content Assembly | ContentLabor | Write → Render → Deliver | ArtifactManager |
| **P2** Intelligence | DataLabor + ResearchLabor | DataFetch → Normalize → Reasoning → Visualize | GitHub/GitHub API |
| **P3** Delivery | DeliveryLabor | Generate → Convert → Distribute | PDF/EPUB引擎 |
| **PP4** Engineering | GitHubLabor | Branch → Commit → PR → Merge | `gh` CLI |
| **P5** Governance | 钩子（所有Pipeline共享） | pre_execute → post_execute | 策略引擎 |

#### Artifact Handover Protocol（工件交接协议）

Pipeline之间通过 `parent_artifact_id` 实现工件链式传递：

```
P3 (Intelligence)  ──parent_artifact_id──►  P1 (Content Assembly)  ──parent_artifact_id──►  P4 (Delivery)
```

每个工件的 `meta.json` 记录 `parent_artifact_id`，下游 Pipeline 自动继承上游产物。

#### Project Orchestrator（项目编排器）

多 Pipeline 协作通过 `project.yaml` 声明式驱动：

```yaml
name: "my-book-project"
steps:
  - pipeline: P3_Intelligence
    task_id: "topic-research"
    context:
      topic: "AI时代的组织变革"
  - pipeline: P1_Content_Assembly
    task_id: "write-book"
    depends_on: ["topic-research"]
    context:
      title: "AI时代的组织变革"
  - pipeline: P4_Delivery
    task_id: "publish-amazon"
    depends_on: ["write-book"]
```

---

## 6. 鲁棒性与语义校准 (Robustness & Alignment)

### 6.1 断点续传机制

基于 `meta.json` 的 `stage` 状态，支持任意时刻中断并从最新阶段恢复。

### 6.2 守护者模式 (Guardian Pattern)

异常分类与处理策略：

| 异常类型 | 特征 | 自动处理 |
|----------|------|----------|
| **基础设施故障** | 网络/IO/超时 | 重试 (指数退避) |
| **模型幻觉** | 输出一致性低 | 修正提示词 |
| **逻辑冲突** | 依赖关系错误 | 人工接管 |

### 6.3 意图动态校准

**北极星指标注入**：
- 实时校验用户当前输入与活跃目标的语义对齐度
- 自动拦截语义漂移，防止任务蔓延

---

## 7. 商业直觉与 ROI 度量 (Commercial Intuition & ROI)

### 7.1 资产账本协议 (Asset Ledger)

每个 Artifact 的元数据中包含数字资产负债表字段：
- **Liabilities (负债)**：Token 消耗、API 成本、计算工时、人工干预次数。
- **Equity (权益)**：实收利润 (Realized Revenue)、估值、市场反响 (Market Traction)。
- **ROI (投资回报率)**：$(Equity - Liabilities) / Liabilities$。

### 7.2 自动成本核算

- **Labor 上报**：所有 Labor 执行单元在完成后必须上报 `token_usage`。
- **引擎核算**：`PipelineEngine` 自动将成本累加至 `meta.json`，并实时重算 ROI。

### 7.3 商业决策逻辑 (Autonomous ROI Decisions)

- **资源倾斜**：JARVIS 监控不同项目的 ROI。对于高回报项目，自动分配更高优先级的模型资源（如 Claude Opus）。
- **风险预警**：当成本增长速度超过预设阈值而收益停滞时，主动通过飞书推送“止损建议”。
- **组织大盘**：通过 `ArtifactManager` 汇总财务数据，为用户提供“自治帝国”的盈亏全景图。

---

## 8. 核心组件映射

| 组件 | 文件 | 核心职责 |
|------|------|----------|
| **协调层** | `chief_agent.py` | 意图理解、任务分解、结果审核 |
| **编排层** | `pipeline_engine_v2.py` | 流水线定义、任务调度 |
| **工件管理** | `artifact_manager.py` | 标准化目录、ROI 汇总 |
| **守护者** | `guardian_controller.py` | 异常检测、错误恢复 |
| **目标追踪** | `goal_tracker.py` | 北极星指标、进度监控 |
| **审批流** | `approval_tracker.py` | 里程碑确认、人工审批 |
| **通知管理** | `notification_manager.py` | 飞书消息、多通道推送 |
| **治理层** | `governance_layer.py` | 策略执行、合规检查 |

---

*文档版本：v2.1 | 增加了商业直觉与 ROI 度量层*
