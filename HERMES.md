# Hermes OS — 开发规范

> Hermes OS = hermes-agent + 自定义扩展。专注服务 100 用户。

## 核心定义

**Hermes OS** 基于 [hermes-agent](https://github.com/NousResearch/hermes-agent)，通过本地扩展实现差异化：

- **Skills**: `~/.hermes/hermes-agent/skills/local/`（源码）+ `~/.hermes/skills/`（运行时）
- **Plugins**: `~/.hermes/hermes-agent/plugins/local/`
- **Memory**: holographic（推荐）、mem0、hindsight 等
- **Gateway**: Telegram、Discord、Feishu/Lark、WhatsApp 等多通道

## 目录结构

```
hermes-agent/           # NousResearch 源码（git 管理，不直接修改）
├── skills/
│   ├── <built-in>/     # 内置 skills（不修改）
│   └── local/           # Hermes OS 自定义 skills 源码
│       └── hermes-os/   # Hermes OS 自身 skill
├── plugins/
│   ├── memory/         # Memory providers（holographic, mem0, etc.）
│   └── local/           # Hermes OS 自定义 plugins
└── ...


~/.hermes/              # 运行时配置（hermes-agent 的 HERMES_HOME）
├── config.yaml         # 主配置
├── .env                # API keys
├── skills/             # 运行时 skills（从 skills/local/ 复制）
└── memories/           # Memory 数据
```

## Skills 开发规范

### 目录布局

```
skills/local/<skill-name>/
├── SKILL.md            # Skill 主文件（含 frontmatter）
├── DESCRIPTION.md      # Category/description 文件
└── <辅助文件>           # 可选辅助文件
```

### SKILL.md 格式

```markdown
---
name: <skill-name>
description: 当用户想做 X 时加载此 skill。描述要精确，Hermes 据此做 intent matching。
version: 1.0.0
author: Hermes OS Team
license: MIT
metadata:
  hermes:
    tags: [tag1, tag2]
    related_skills: [other-skill]
---

# Title

Guide content...
```

### DESCRIPTION.md 格式

```markdown
---
description: 一句话描述此 skill 的用途（用于 skills hub 展示和分类）。
---
```

### 开发流程

1. 在 `~/.hermes/hermes-agent/skills/local/<name>/` 创建 skill 源码
2. 复制到 `~/.hermes/skills/<name>/` 使其生效
3. 验证：`hermes skills list | grep <name>`
4. 测试：启动 hermes 并触发 skill

### Skill 示例

**deploy.md:**

```markdown
---
name: deploy
description: 当用户想部署、发布或上线软件时加载。
---

# Deployment Workflow

1. 运行测试：`make test`
2. 构建镜像：`docker build -t <image> .`
3. 推送到 registry：`docker push <registry>/<image>`
4. 部署：`kubectl apply -f k8s/`
5. 健康检查：`curl https://<domain>/health`
```

## Plugin 开发规范

### 目录布局

```
plugins/local/<plugin-name>/
├── __init__.py         # Plugin 入口，注册 MemoryProvider
├── store.py            # 存储实现
├── retrieval.py        # 检索逻辑
└── config.py           # 可选配置 schema
```

### MemoryProvider 注册

```python
from agent.memory_provider import MemoryProvider

class MyProvider(MemoryProvider):
    async def store(self, key: str, value: Any) -> None: ...
    async def retrieve(self, key: str) -> Any: ...
    async def search(self, query: str, limit: int = 10) -> List[Any]: ...

registry.register(provider=MyProvider())
```

## Memory 配置

### config.yaml

```yaml
memory:
  memory_enabled: true
  provider: holographic  # holographic | mem0 | hindsight | honcho | ''
  memory_char_limit: 2200
  user_char_limit: 1375
  nudge_interval: 10
  flush_min_turns: 6
```

### Provider 选择

| Provider | 说明 | 适用场景 |
|----------|------|---------|
| `holographic` | FTS5 事实存储 + 信任评分 | MVP 推荐，结构化事实 |
| `mem0` | Mem0 托管服务 | 需要云端记忆同步 |
| `hindsight` | 对话摘要 | 简单摘要需求 |
| `honcho` | Honcho 集成 | 已有 Honcho 使用习惯 |
| `''` | 内置默认 | 最小依赖 |

## Gateway 配置

Hermes Agent 内置多通道 gateway，无需额外开发：

```bash
hermes gateway setup
```

支持的平台：Telegram、Discord、Slack、WhatsApp、Signal、Email、SMS、Matrix、Mattermost、Home Assistant、DingTalk、Feishu/Lark、WeCom、Weixin、BlueBubbles。

## OMC + ECC 开发工作流

### 8 阶段流程

```
需求 → 理解(读CLAUDE.md) → 规划(OMC) → TDD(ECC) → 专业Agent → 并行(team) → QA循环(ultraqa) → 安全审查 → 提交
```

### 铁律

1. **完全无人化**：不询问确认，直接执行
2. **TDD 先行**：先写测试，再写实现
3. **每批 < 6 任务**：防止上下文溢出
4. **5 轮 QA 循环**：失败超限停止并报告
5. **先理解再编码**：先读 CLAUDE.md
6. **用专业 Agent**：不自己硬扛
7. **聚焦 MVP**：暂不考虑 openbee/oct-os/openmind/lark-gateway

## 快速命令

```bash
# Skills
ls ~/.hermes/hermes-agent/skills/local/
hermes skills list | grep hermes-os

# Plugins
hermes plugins list

# Memory
hermes doctor | grep -A3 "Memory Provider"

# Gateway
hermes gateway status

# Config
hermes config edit
hermes config set memory.provider holographic
```

## 暂不开发

- openbee（异构并行）
- oct-os（自主探索）
- openmind（价值发现）
- lark-gateway（飞书已内置）
- 其他外部 Agent 调用（Phase 2+ 考虑）
