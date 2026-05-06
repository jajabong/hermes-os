"""ConclusionExtractor — JARVIS 三段式总结卡片.

将 CLI 原始输出转换为"认知极简"的三段式卡片：
- 结论 (Conclusion): 一句话概括结果
- 证据 (Evidence): 关键指标/数据
- 详情 (Details): 折叠的原始日志

目标：消除"日志焦虑"，让用户只关注结论。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConclusionLevel(Enum):
    """任务状态级别，对应不同图标和颜色。"""

    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"
    RUNNING = "running"
    INFO = "info"

    @property
    def icon(self) -> str:
        return {
            ConclusionLevel.SUCCESS: "✅",
            ConclusionLevel.FAILURE: "❌",
            ConclusionLevel.WARNING: "⚠️",
            ConclusionLevel.RUNNING: "🔄",
            ConclusionLevel.INFO: "ℹ️",
        }[self]

    @property
    def template(self) -> str:
        """Feishu card header template color."""
        return {
            ConclusionLevel.SUCCESS: "green",
            ConclusionLevel.FAILURE: "red",
            ConclusionLevel.WARNING: "orange",
            ConclusionLevel.RUNNING: "blue",
            ConclusionLevel.INFO: "blue",
        }[self]


@dataclass
class ConclusionCard:
    """
    三段式总结卡片。

    Attributes:
        level: 结论级别 (SUCCESS/FAILURE/WARNING/RUNNING)
        conclusion: 一句话结论（不超过50字）
        evidence: 关键证据列表 (最多5条)
        details: 原始日志详情（折叠内容）
        task_title: 任务名称
        task_id: 任务ID
        goal_context: 可选的目标语境（如 "完成供应商对比 (Phase 2/5)"）
    """

    level: ConclusionLevel
    conclusion: str
    evidence: list[str] = field(default_factory=list)
    details: str = ""
    task_title: str = ""
    task_id: str = ""
    goal_context: str = ""

    def to_markdown(self) -> str:
        """转换为 Markdown 格式（用于飞书卡片 body）。"""
        icon = self.level.icon
        parts = [f"{icon} **{self.conclusion}**"]

        if self.goal_context:
            parts.append(f"\n> 🎯 {self.goal_context}")

        if self.evidence:
            parts.append("\n**证据:**")
            for e in self.evidence[:5]:
                parts.append(f"- {e}")

        parts.append(
            f"\n<details>\n<summary>📋 详情（点击展开）</summary>\n\n```\n{self.details}\n```\n</details>"
        )

        return "\n".join(parts)

    def to_feishu_elements(self) -> list[dict[str, Any]]:
        """转换为 Feishu 卡片 elements 列表。"""
        elements = []

        # Conclusion section
        icon = self.level.icon
        conclusion_text = f"{icon} **{self.conclusion}**"
        if self.goal_context:
            conclusion_text += f"\n🎯 {self.goal_context}"

        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": conclusion_text,
                },
            }
        )

        # Evidence section
        if self.evidence:
            evidence_text = "**证据:**\n" + "\n".join(f"- {e}" for e in self.evidence[:5])
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": evidence_text,
                    },
                }
            )

        # Collapsible details (using note tag)
        if self.details:
            elements.append(
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "lark_md",
                            "content": f"**详情:**\n```\n{self.details[:1500]}\n```",
                        }
                    ],
                }
            )

        return elements

    def to_feishu_card(self, title: str | None = None) -> dict[str, Any]:
        """构建完整的 Feishu 卡片 JSON。"""
        card_title = title or f"{self.level.icon} {self.task_title}"
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": card_title},
                "template": self.level.template,
            },
            "elements": self.to_feishu_elements(),
        }


class ConclusionExtractor:
    """
    将原始 CLI 输出萃取为三段式结论卡片。

    设计原则：
    - 规则+启发式：不需要 LLM，轻量快速
    - 证据提取：数字/时间/成功率等关键指标
    - 状态检测：成功/失败/警告/运行中
    """

    # 失败关键词模式
    _FAILURE_PATTERNS = [
        r"\berror\b",
        r"\bfail(?:ed|ure)?\b",
        r"\bexception\b",
        r"\btraceback\b",
        r"\bcrash\b",
        r"\btimeout\b",
        r"\brefused\b",
        r"\bdenied\b",
    ]

    # 警告关键词模式（任务继续执行）
    _WARNING_PATTERNS = [
        r"\bwarning\b",
        r"\bwarn\b",
        r"\bhigh usage\b",
        r"\bdeprecated\b",
    ]

    # 时间模式
    _TIME_PATTERNS = [
        r"(\d+(?:\.\d+)?)\s*(?:s|sec|seconds|分钟|min)",
        r"completed?\s+in\s+(\d+)",
        r"duration[:\s]+(\d+(?:\.\d+)?)",
        r"耗时\s*(\d+)",
    ]

    # 计数模式
    _COUNT_PATTERNS = [
        r"(?:passed?|成功|完成)[:\s]*(\d+)",
        r"(?:failed?|失败)[:\s]*(\d+)",
        r"(?:errors?)[:\s]*(\d+)",
        r"processed\s+(\d+)",
        r"(\d+)\s+files?",
    ]

    def extract_summary(
        self,
        raw_output: str,
        task_title: str,
        task_id: str,
        status: str = "completed",
        goal_context: str | None = None,
    ) -> ConclusionCard:
        """
        从原始输出中萃取三段式结论。

        Args:
            raw_output: CLI 原始输出
            task_title: 任务名称
            task_id: 任务ID
            status: 任务状态 (completed/failed/running)
            goal_context: 可选的目标语境

        Returns:
            ConclusionCard with level, conclusion, evidence, details
        """
        output = raw_output.strip()

        # Detect level
        level = self._detect_level(output, status)

        # Extract conclusion
        conclusion = self._extract_conclusion(output, level, task_title)

        # Extract evidence
        evidence = self._extract_evidence(output)

        # Truncate details
        details = output[:2000] if len(output) > 2000 else output

        return ConclusionCard(
            level=level,
            conclusion=conclusion,
            evidence=evidence,
            details=details,
            task_title=task_title,
            task_id=task_id,
            goal_context=goal_context or "",
        )

    def _detect_level(self, output: str, status: str) -> ConclusionLevel:
        """检测结论级别。"""
        if status == "running":
            return ConclusionLevel.RUNNING

        if status == "failed":
            return ConclusionLevel.FAILURE

        output_lower = output.lower()

        # Check failure patterns
        for pattern in self._FAILURE_PATTERNS:
            if re.search(pattern, output_lower):
                return ConclusionLevel.FAILURE

        # Check warning patterns
        for pattern in self._WARNING_PATTERNS:
            if re.search(pattern, output_lower):
                return ConclusionLevel.WARNING

        return ConclusionLevel.SUCCESS

    def _extract_conclusion(self, output: str, level: ConclusionLevel, task_title: str) -> str:
        """萃取一句话结论。"""
        if level == ConclusionLevel.FAILURE:
            # Try to extract error type
            match = re.search(r"(error|exception|failed)[:\s]+(.+?)(?:\n|$)", output, re.IGNORECASE)
            if match:
                error_type = match.group(2).strip()[:40]
                return f"{task_title} 失败: {error_type}"
            return f"{task_title} 执行失败"

        if level == ConclusionLevel.WARNING:
            match = re.search(r"(warning|warn)[:\s]+(.+?)(?:\n|$)", output, re.IGNORECASE)
            if match:
                return f"{task_title} 警告: {match.group(2).strip()[:40]}"
            return f"{task_title} 存在警告"

        if level == ConclusionLevel.RUNNING:
            return f"{task_title} 进行中..."

        # Success: try to find completion message
        if "completed" in output.lower() or "done" in output.lower():
            match = re.search(r"(completed|done|success)[:\s]*(.+?)(?:\n|$)", output, re.IGNORECASE)
            if match:
                return f"{task_title} 完成: {match.group(2).strip()[:30]}"
            return f"{task_title} 已完成"

        # Default
        return f"{task_title} 完成"

    def _extract_evidence(self, output: str) -> list[str]:
        """从输出中提取关键证据/指标。"""
        evidence: list[str] = []

        # Extract time
        for pattern in self._TIME_PATTERNS:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                evidence.append(
                    f"耗时: {match.group(1)}{match.group(2) if len(match.groups()) > 1 else 's'}"
                )
                break

        # Extract counts (passed/failed)
        passed_match = re.search(r"(?:passed?|成功|完成)[:\s]*(\d+)", output, re.IGNORECASE)
        if passed_match:
            evidence.append(f"成功: {passed_match.group(1)}")

        failed_match = re.search(r"(?:failed?|失败)[:\s]*(\d+)", output, re.IGNORECASE)
        if failed_match:
            evidence.append(f"失败: {failed_match.group(1)}")

        # Extract success rate
        rate_match = re.search(
            r"(?:rate|成功率|准确率)[:\s]*(\d+(?:\.\d+)?%?)", output, re.IGNORECASE
        )
        if rate_match:
            evidence.append(f"成功率: {rate_match.group(1)}")

        # Extract deployed info
        if "deploy" in output.lower():
            deploy_match = re.search(
                r"deploy(?:ed|ing)?\s+(?:to\s+)?(.+?)(?:\n|$)", output, re.IGNORECASE
            )
            if deploy_match:
                evidence.append(f"部署目标: {deploy_match.group(1).strip()[:30]}")

        # Extract file count
        file_match = re.search(r"(\d+)\s+files?", output, re.IGNORECASE)
        if file_match:
            evidence.append(f"文件数: {file_match.group(1)}")

        # Extract version
        version_match = re.search(r"version[:\s]*v?(\d+(?:\.\d+)+)", output, re.IGNORECASE)
        if version_match:
            evidence.append(f"版本: v{version_match.group(1)}")

        return evidence[:5]  # Max 5 evidence items
