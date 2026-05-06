"""Intent → Agent mapping constants.

Single source of truth for all intent-to-agent routing decisions.
Imported by unified_router.py and delegation_protocol.py.
"""

# Intent → Agent name mapping
INTENT_AGENT_MAP: dict[str, str] = {
    # Vertical agents
    "code": "CodeAgent",
    "fix_bug": "CodeAgent",
    "research": "ResearchAgent",
    "investment": "InvestmentAgent",
    "legal": "LegalAgent",
    "content": "ContentAgent",
    "education": "EducationAgent",
    "deploy": "DeployAgent",
    "review": "ReviewAgent",
    "test": "TestAgent",
    "write_book": "BookPipelineAgent",
    # Default fallback
    "unknown": "ChiefAgent",
}