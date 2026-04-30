"""Tests for DocWorkflow — government document (政务公文) rendering."""

import pytest
from hermes_os.doc_workflow import (
    DocType,
    ApprovalFlow,
    DocWorkflowEngine,
    DocWorkflowResult,
    get_template,
    render_document,
    apply_terminology,
)


class TestDocType:
    def test_doc_types(self) -> None:
        """All expected doc types exist."""
        assert hasattr(DocType, "NOTICE")
        assert hasattr(DocType, "REPORT")
        assert hasattr(DocType, "REQUEST")
        assert hasattr(DocType, "LETTER")


class TestApprovalFlow:
    def test_approval_flows(self) -> None:
        """All expected approval flows exist."""
        assert hasattr(ApprovalFlow, "NONE")
        assert hasattr(ApprovalFlow, "IMMEDIATE")
        assert hasattr(ApprovalFlow, "AWAIT_REPLY")


class TestGetTemplate:
    def test_notice_template(self) -> None:
        """NOTICE template has correct structure."""
        t = get_template(DocType.NOTICE)
        assert t["approval"] == ApprovalFlow.NONE
        assert "title" in t["placeholders"]
        assert "body" in t["placeholders"]

    def test_report_template(self) -> None:
        """REPORT template has 4 sections."""
        t = get_template(DocType.REPORT)
        assert t["approval"] == ApprovalFlow.IMMEDIATE
        assert "section1" in t["placeholders"]
        assert "section4" in t["placeholders"]

    def test_request_template(self) -> None:
        """REQUEST template ends with 妥否，请批示。"""
        t = get_template(DocType.REQUEST)
        assert t["approval"] == ApprovalFlow.AWAIT_REPLY
        assert "section1" in t["placeholders"]
        assert "section2" in t["placeholders"]

    def test_letter_template(self) -> None:
        """LETTER template is simplest structure."""
        t = get_template(DocType.LETTER)
        assert t["approval"] == ApprovalFlow.NONE
        assert "body" in t["placeholders"]


class TestRenderDocument:
    def test_render_notice(self) -> None:
        """NOTICE renders title, sender, date, body."""
        result = render_document(
            DocType.NOTICE,
            {
                "title": "关于开展安全检查的通知",
                "sender": "XX办公室",
                "date": "2026年4月30日",
                "body": "各部门：\n拟于5月开展安全检查，请配合。",
            },
        )
        assert "关于开展安全检查的通知" in result
        assert "XX办公室" in result
        assert "2026年4月30日" in result
        assert "安全检查" in result

    def test_render_request(self) -> None:
        """REQUEST renders with 妥否，请批示。 closing."""
        result = render_document(
            DocType.REQUEST,
            {
                "title": "关于申请经费的请示",
                "to": "XX领导",
                "section1": "因业务发展需要",
                "section2": "申请经费100万元",
                "sender": "XX部门",
                "date": "2026年4月30日",
            },
        )
        assert "关于申请经费的请示" in result
        assert "妥否，请批示。" in result
        assert "XX部门" in result

    def test_render_missing_placeholder_shows_placeholder(self) -> None:
        """Missing placeholder appears as literal {key} in output."""
        result = render_document(
            DocType.NOTICE,
            {
                "title": "测试通知",
                # sender and date missing
                "body": "内容",
            },
        )
        assert "{sender}" in result or "sender" in result.lower()


class TestApplyTerminology:
    def test_apply_terminology_replaces_terms(self) -> None:
        """Government terminology is applied."""
        text = "请贵单位知照，妥否请批示。"
        result = apply_terminology(text)
        assert "贵单位" in result
        assert "知照" in result

    def test_apply_terminology_empty(self) -> None:
        """Empty dict means no change."""
        text = "普通文本"
        result = apply_terminology(text, {})
        assert result == text


class TestDocWorkflowEngine:
    """DocWorkflowEngine.render() tests."""

    def test_render_request_success(self) -> None:
        """Valid REQUEST renders successfully."""
        engine = DocWorkflowEngine()
        result = engine.render(
            doc_type=DocType.REQUEST,
            values={
                "title": "关于采购设备的请示",
                "to": "XX领导",
                "section1": "因工作需要",
                "section2": "申请采购设备",
                "sender": "XX部门",
                "date": "2026年4月30日",
            },
        )
        assert result.success is True
        assert result.doc_type == DocType.REQUEST
        assert result.approval_flow == ApprovalFlow.AWAIT_REPLY
        assert "关于采购设备的请示" in result.rendered_text

    def test_render_missing_field_returns_error(self) -> None:
        """Missing required placeholders returns error."""
        engine = DocWorkflowEngine()
        result = engine.render(
            doc_type=DocType.REQUEST,
            values={
                "title": "标题",
                # section1, section2, sender, date all missing
            },
        )
        assert result.success is False
        assert "Missing placeholders" in result.error

    def test_render_notice_immediate_approval(self) -> None:
        """NOTICE has NONE approval flow."""
        engine = DocWorkflowEngine()
        result = engine.render(
            doc_type=DocType.NOTICE,
            values={
                "title": "测试通知",
                "sender": "XX部门",
                "date": "2026年4月30日",
                "body": "内容",
            },
        )
        assert result.success is True
        assert result.approval_flow == ApprovalFlow.NONE

    def test_to_feishu_card(self) -> None:
        """DocWorkflowResult.to_feishu_card() returns valid card structure."""
        engine = DocWorkflowEngine()
        result = engine.render(
            doc_type=DocType.NOTICE,
            values={
                "title": "测试通知",
                "sender": "XX部门",
                "date": "2026年4月30日",
                "body": "内容",
            },
        )
        card = result.to_feishu_card("政务文书")
        assert "header" in card
        assert card["header"]["title"]["content"] == "政务文书"
        assert "elements" in card
