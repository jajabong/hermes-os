"""Government Document Workflow — templates for 政务公文 (government official documents).

Types supported:
- 通知 (Notice): 标题+主送+正文+落款，流程简单（起草→签发）
- 报告 (Report): 基本情况+主要工作+存在问题+下一步，流程是上行报告
- 请示 (Request): 请示缘由+请示事项+结语（妥否，请批示），需上级批复
- 函 (Letter): 平行文，语气中立，格式最简

Each type has:
- structure_template: 占位符填充后的正文模板
- terminology: 政务规范用语替换表
- approval_flow: 审批流程类型 (none/immediate/await_reply)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DocType(str, Enum):
    NOTICE = "notice"       # 通知
    REPORT = "report"       # 报告
    REQUEST = "request"    # 请示
    LETTER = "letter"      # 函


class ApprovalFlow(str, Enum):
    NONE = "none"              # 直接发出，无需审批
    IMMEDIATE = "immediate"    # 立即提交上级
    AWAIT_REPLY = "await_reply"  # 需等待批复（妥否，请批示）


# ---------------------------------------------------------------------------
# Terminology dictionary (政务规范用语)
# ---------------------------------------------------------------------------

_TERMINOLOGY: dict[str, str] = {
    "贵单位": "贵单位",
    "兹": "兹",
    "妥否": "妥否",
    "函复": "函复",
    "知照": "知照",
    "报送": "报送",
    "呈报": "呈报",
    "拟办": "拟办",
    "审批": "审批",
    "签发": "签发",
    "印发": "印发",
    "主送": "主送",
    "抄送": "抄送",
}


# ---------------------------------------------------------------------------
# Document templates
# ---------------------------------------------------------------------------

_TEMPLATES: dict[DocType, dict[str, Any]] = {
    DocType.NOTICE: {
        "approval": ApprovalFlow.NONE,
        "structure": [
            "{title}",
            "",
            "{sender}",
            "{date}",
            "",
            "---",
            "",
            "{body}",
        ],
        "placeholders": ["title", "sender", "date", "body"],
    },
    DocType.REPORT: {
        "approval": ApprovalFlow.IMMEDIATE,
        "structure": [
            "{title}",
            "",
            "{to}",
            "",
            "一、基本情况",
            "{section1}",
            "",
            "二、主要工作",
            "{section2}",
            "",
            "三、存在问题",
            "{section3}",
            "",
            "四、下一步工作计划",
            "{section4}",
            "",
            "{sender}",
            "{date}",
        ],
        "placeholders": ["title", "to", "section1", "section2", "section3", "section4", "sender", "date"],
    },
    DocType.REQUEST: {
        "approval": ApprovalFlow.AWAIT_REPLY,
        "structure": [
            "{title}",
            "",
            "{to}",
            "",
            "一、请示缘由",
            "{section1}",
            "",
            "二、请示事项",
            "{section2}",
            "",
            "妥否，请批示。",
            "",
            "{sender}",
            "{date}",
        ],
        "placeholders": ["title", "to", "section1", "section2", "sender", "date"],
    },
    DocType.LETTER: {
        "approval": ApprovalFlow.NONE,
        "structure": [
            "{title}",
            "",
            "{to}",
            "",
            "{body}",
            "",
            "{sender}",
            "{date}",
        ],
        "placeholders": ["title", "to", "body", "sender", "date"],
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_template(doc_type: DocType) -> dict[str, Any]:
    """Return template config for a given document type."""
    return _TEMPLATES.get(doc_type, _TEMPLATES[DocType.NOTICE])


def render_document(doc_type: DocType, values: dict[str, str]) -> str:
    """
    Render a government document from a doc_type and key-value placeholders.

    Args:
        doc_type: NOTICE / REPORT / REQUEST / LETTER
        values: Dict mapping placeholder names to values

    Returns:
        Rendered document text
    """
    template = get_template(doc_type)
    lines = list(template["structure"])

    # Fill placeholders
    for i, line in enumerate(lines):
        for key, val in values.items():
            placeholder = f"{{{key}}}"
            if placeholder in line:
                lines[i] = line.replace(placeholder, val)

    return "\n".join(lines)


def apply_terminology(text: str, terminology: dict[str, str] | None = None) -> str:
    """Apply government document terminology to text."""
    if terminology is None:
        terminology = _TERMINOLOGY
    for standard_term, replacement in terminology.items():
        text = re.sub(standard_term, replacement, text)
    return text


@dataclass
class DocWorkflowResult:
    """Result of rendering a government document workflow."""
    doc_type: DocType
    rendered_text: str
    approval_flow: ApprovalFlow
    success: bool
    error: str | None = None

    def to_feishu_card(self, title: str) -> dict[str, Any]:
        """Format as a Feishu card for sending."""
        content = self.rendered_text[:500] + ("..." if len(self.rendered_text) > 500 else "")
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**类型**: {self.doc_type.value}\n**审批流程**: {self.approval_flow.value}"}},
            ],
        }


class DocWorkflowEngine:
    """
    Renders government official documents (政务公文) from structured input.

    Usage:
        engine = DocWorkflowEngine()
        result = engine.render(
            doc_type=DocType.REQUEST,
            values={
                "title": "关于申请XXX经费的请示",
                "to": "XX领导",
                "section1": "因业务发展需要...",
                "section2": "申请经费XXX万元...",
                "sender": "XX部门",
                "date": "2026年4月30日",
            },
        )
    """

    def render(self, doc_type: DocType, values: dict[str, str]) -> DocWorkflowResult:
        """
        Render a government document.

        Validates required placeholders are present and applies terminology.
        """
        template = get_template(doc_type)
        required = template["placeholders"]
        missing = [k for k in required if k not in values or not values[k]]
        if missing:
            return DocWorkflowResult(
                doc_type=doc_type,
                rendered_text="",
                approval_flow=template["approval"],
                success=False,
                error=f"Missing placeholders: {missing}",
            )

        raw = render_document(doc_type, values)
        # Apply terminology for government style
        text = apply_terminology(raw)
        return DocWorkflowResult(
            doc_type=doc_type,
            rendered_text=text,
            approval_flow=template["approval"],
            success=True,
        )
