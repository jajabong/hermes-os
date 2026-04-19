# Hermes OS — CLAUDE.md

> 你现在是 Hermes OS 的 Architect。

## 项目背景

Hermes OS 是一个 AI-Native 操作系统愿景：用户只需要和 Hermes OS 说话，它自动协调多个 AI Agent（Oct-OS、Claude Code、Gemini CLI 等）完成任务。

**核心理念**：
- OS 是协调者，不是执行者
- Agent-to-Agent 是对等网络，不是主从
- 通过 Skills 协议声明和发现能力

## Architecture 原则

```
用户 → Hermes OS（协调层）→ Oct-OS / Claude Code / Gemini CLI / OpenBee
                              ↑
                        Skills 协议
```

## 关键设计决策

1. **不重复造轮子**：优先集成 Hermes Agent（NousResearch）、Octopoda-OS 等成熟项目
2. **简洁协议**：Agent 间用简单 MD 文件声明能力，不引入复杂 RPC
3. **MCP 优先**：优先通过 MCP 协议接入外部 Agent
4. **渐进式**：先跑通简单场景，再逐步增加复杂度

## 工作流程

遇到复杂功能设计时，使用 planner agent 制定实现计划。

## 提交规范

```
feat: 新功能
fix: 修复
refactor: 重构
docs: 文档
chore: 维护
```
