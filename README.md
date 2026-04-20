# Hermes OS

> "用户只需要和 Hermes OS 说话，剩下的由 OS 完成。"

**Hermes OS = hermes-agent (NousResearch)。专注服务 100 用户，后续按需扩展 Agent 生态。**

## 核心定义

Hermes OS 基于 [hermes-agent](https://github.com/NousResearch/hermes-agent)，是一个自进化的 AI 原生操作系统：

- **意图理解**：自然语言 → 结构化意图
- **多通道接入**：Telegram, Discord, Feishu/Lark, WhatsApp, Signal, Email, SMS, DingTalk, WeCom, Weixin 等
- **技能系统**：热插拔 Skills，动态加载
- **记忆持久化**：跨会话记忆，持续学习用户偏好
- **自进化**：通过使用不断优化协调模式
- **Agent 编排**：内置 Claude Code Skill，按需调用外部 Agent

## 设计原则

### 1. OS 作为协调层，而非执行者

Hermes OS 是**舞台**，不是**演员**：
- 协调、路由、编排——不自己做执行
- 专业 Agent（Claude Code 等）是表演者
- 清晰关注分离：OS 负责协调，Agent 负责执行

### 2. Agent 协作网络，而非主从关系

```
Hermes OS（协调层）
     ↕ 协议调用
Claude Code ↔ 外部 Agent
     （对等的 Agent 网络）
```

### 3. Skills 作为能力声明

Agent 通过 **Skills 协议**声明能力：
- 简单的 MD 文件定义每个 Agent 能做什么
- Hermes OS 基于可用 Skills 发现和路由
- 热插拔：增删 Agent 不影响核心 OS

### 4. 通过使用自进化

Hermes OS 越用越聪明：
- 记忆用户偏好（哪个 Agent 适合哪个任务）
- 学习协调模式（哪些 Agent 配合得好）
- 基于成功历史改进路由决策

## 技术栈

- **核心**：hermes-agent (NousResearch)
- **开发工具**：OMC (oh-my-claudecode) + ECC (everything-claude-code)
- **Python**：>= 3.11

## 状态

**MVP 阶段** — 使用 OMC + ECC 驱动全自动开发，专注服务 100 用户。

## License

MIT
