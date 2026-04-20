# Hermes OS — OMC + ECC 全自动开发 Prompt

> Hermes OS = hermes-agent。专注服务 100 用户。

## 核心定义

**Hermes OS** 基于 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)，是它的自定义扩展：
- 自定义 skills（`~/.hermes/hermes-agent/skills/local/`）
- 自定义 plugins（`~/.hermes/hermes-agent/plugins/local/`）
- 自定义 memory 配置
- 自定义 gateway 配置（Feishu/Lark 等内置）

**技术栈**：Python >= 3.11，pip

**开发工具**：Claude Code + OMC + ECC

## 暂不考虑

以下全部暂不开发，等 MVP 跑通再加：
- openbee（异构并行）
- oct-os（自主探索）
- openmind（价值发现）
- lark-gateway（飞书集成，已是 hermes-agent 内置）
- 其他 Agent 调用（Claude Code / Gemini CLI 等）

## 工作流程（OMC + ECC 驱动）

### 阶段 1：理解需求
1. 读取 `CLAUDE.md`（本文件）
2. 读取 `ARCHITECTURE.md`（如有）
3. 确定修改范围（skills / plugins / memory / gateway）

### 阶段 2：规划（OMC）
```
Task(subagent_type="oh-my-claudecode:planner", model="opus", prompt="
为以下需求制定实现计划：

需求：[自然语言描述]

要求：
1. 识别修改类型（skill / plugin / memory / gateway）
2. 分解为 < 10 个原子任务
3. 标注依赖关系
4. 识别风险

输出格式：
## 计划
### 任务列表
### 依赖图
### 风险
")
```

### 阶段 3：TDD 先行（ECC）
```
Task(subagent_type="tdd-guide", model="sonnet", prompt="
对以下任务执行 TDD 流程：

任务：[任务描述]
目标文件：[文件路径]

流程：
1. 写测试（RED）
2. 运行测试，确认失败
3. 写最小实现（GREEN）
4. 重构（IMPROVE）
5. 验证测试 100% 通过
")
```

### 阶段 4：专业 Agent 执行（ECC）
```
根据任务类型选择 Agent：

架构/设计       → Task(subagent_type="architect", model="opus")
代码审查       → Task(subagent_type="code-reviewer", model="opus")
安全扫描       → Task(subagent_type="security-reviewer", model="sonnet")
构建错误       → Task(subagent_type="build-error-resolver", model="sonnet")
死代码清理     → Task(subagent_type="refactor-cleaner", model="sonnet")
文档更新       → Task(subagent_type="doc-updater", model="haiku")
```

### 阶段 5：多任务并行（OMC team）
```
独立任务并行执行：

/team N:executor "任务 1"
/team N:executor "任务 2"
/team N:executor "任务 3"

N = min(6, 任务数量)
```

### 阶段 6：QA 验证循环（OMC ultraqa）
```
/oh-my-claudecode:ultraqa --tests
/oh-my-claudecode:ultraqa --build
/oh-my-claudecode:ultraqa --lint

规则：
- 最多 5 轮循环
- 相同失败连续 3 次停止并报告
- 通过后输出验证报告
```

### 阶段 7：安全审查（ECC）
```
Task(subagent_type="security-reviewer", model="sonnet", prompt="
检查本次修改：
1. 无硬编码 secrets
2. 输入验证完整
3. 无注入风险
4. 权限检查正确

输出：安全报告 + 修复建议
")
```

### 阶段 8：提交
```
feat: 新功能
fix: 修复
refactor: 重构
docs: 文档
chore: 维护
```

## 铁律

1. **完全无人化**：不询问确认，直接执行
2. **TDD 先行**：先写测试，再写实现
3. **每批 < 6 任务**：防止上下文溢出
4. **5 轮 QA 循环**：失败超限停止并报告
5. **先理解再编码**：先读 CLAUDE.md
6. **用专业 Agent**：不自己硬扛
7. **聚焦 MVP**：暂不考虑 openbee / oct-os / openmind 等

## 启动方式

用户只需说：
```
帮我实现 [需求]
```

系统自动执行完整流程，输出：
```
✅ [功能名] 已完成
📁 修改文件：[列表]
🧪 测试：全部通过
🔒 安全：无问题
📦 已提交：feat: ...
```
