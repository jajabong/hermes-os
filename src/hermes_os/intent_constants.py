"""Intent → Agent mapping constants.

Single source of truth for all intent-to-agent routing decisions.
6 functional agents (按功能分工, 不是按领域):
  - ResearchAgent: 搜索/研究/分析
  - CodeAgent: 代码生成/debug/测试
  - BrowserAgent: 浏览器自动化(填表/抓取)
  - ContentAgent: 写作/文案/排版
  - DataAgent: 数据处理/可视化
  - IntelligenceAgent: 实时数据(嵌入ResearchAgent)
"""

# Intent → Functional Agent name mapping
INTENT_AGENT_MAP: dict[str, str] = {
    # Core functional agents
    "code": "CodeAgent",
    "fix_bug": "CodeAgent",
    "test": "CodeAgent",       # 测试 → CodeAgent
    "review": "CodeAgent",     # 审查 → CodeAgent
    "research": "ResearchAgent",
    "investment": "ResearchAgent",  # 投资分析 → Research(研究) + Data(数据)
    "legal": "ResearchAgent",       # 法律研究 → ResearchAgent
    "education": "ContentAgent",    # 教育内容 → ContentAgent
    "deploy": "CodeAgent",          # 部署 → CodeAgent
    "write_book": "ContentAgent",  # 写书 → ContentAgent
    "content": "ContentAgent",
    "browser": "BrowserAgent",
    "data": "DataAgent",
    # Default fallback: ChiefAgent does dispatch
    "unknown": "ChiefAgent",
}