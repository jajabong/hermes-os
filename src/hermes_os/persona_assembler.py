"""PersonaAssembler — dynamic System Prompt assembly from user preferences.

Phase 1: 千人千面管家
核心职责：将 L2 PREFERENCES (brain/PREFERENCES.md) 转化为动态 System Prompt，
让不同用户（陆总 brief vs 周局 high-detail）得到完全不同的响应风格。

Architecture:
    MemoryHub (L2 preferences) + IdentityMemory (L1 identity)
        ↓
    PersonaAssembler.assemble()
        ↓
    PersonaBlock (system_prefix + style params)
        ↓
    block.render() → XML string to prepend as System Prompt
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hermes_os.memory_hub import MemoryHub

logger = logging.getLogger(__name__)

# Default preference values
DEFAULT_PREFERENCES = {
    "communication_style": "neutral",
    "detail_level": "medium",
    "language": "auto",
    "tone": "neutral",
    "format": "markdown",
    "max_length": 2000,
    "timezone": "Asia/Shanghai",
    "active_hours": [9, 10, 11, 14, 15, 16, 17, 20, 21],
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PersonaBlock:
    """A fully assembled persona / System Prompt block.

    Attributes:
        system_prefix: The XML system prompt to prepend to messages.
        communication_style: How concise/verbose the response should be.
        detail_level: How much detail to include.
        tone: The emotional tone (neutral, technical, casual, direct).
        format: Output format preference (markdown, plain, card).
    """

    system_prefix: str = ""
    communication_style: str = "neutral"
    detail_level: str = "medium"
    tone: str = "neutral"
    format: str = "markdown"
    max_length: int = 2000
    language: str = "auto"

    def render(self) -> str:
        """Render as an XML <assistant_persona> block for injection into prompts."""
        return (
            f"<assistant_persona>\n"
            f"<owner>{self._owner_name()}</owner>\n"
            f"<system_instructions>\n{self.system_prefix}\n</system_instructions>\n"
            f"<communication>{self._render_communication()}</communication>\n"
            f"<detail_level>{self.detail_level}</detail_level>\n"
            f"<tone>{self.tone}</tone>\n"
            f"<format>{self.format}</format>\n"
            f"<max_length>{self.max_length}</max_length>\n"
            f"</assistant_persona>"
        )

    def _owner_name(self) -> str:
        """Extract owner name from system_prefix if present."""
        if not self.system_prefix:
            return "User"
        # Try to find Chinese name in the prefix
        import re

        match = re.search(r"[一-鿿]{2,4}(?:总|局|董|经理|老板)", self.system_prefix)
        if match:
            return match.group(0)
        match = re.search(r"(?:你是|你是的)\s*(.+)", self.system_prefix)
        if match:
            return match.group(1).strip().split("\n")[0]
        return "User"

    def _render_communication(self) -> str:
        """Render communication style label based on style + language."""
        is_en = self.language == "en"
        is_zh = self.language == "zh"

        if self.communication_style == "brief":
            return "简洁" if is_zh else ("Concise" if is_en else "Brief")
        elif self.communication_style == "casual":
            return "随意" if is_zh else ("Casual" if is_en else "Casual")
        elif self.communication_style == "formal":
            return "正式" if is_zh else ("Formal" if is_en else "Formal")
        return "中性" if is_zh else ("Neutral" if is_en else "Neutral")


# ---------------------------------------------------------------------------
# PersonaAssembler
# ---------------------------------------------------------------------------


class PersonaAssembler:
    """Assembles a dynamic persona System Prompt from user preferences.

    Two sources of data:
    1. MemoryHub (if provided) — uses get_preferences() + get_identity()
    2. Direct file access (if no MemoryHub) — reads brain/PREFERENCES.md and brain/USER.md

    Example:
        # Direct file access (no mem0 required)
        assembler = PersonaAssembler(user_id="lu_zong", base_path=Path("~/.hermes/users"))
        block = await assembler.assemble()

        # With MemoryHub
        assembler = PersonaAssembler(user_id="lu_zong", memory_hub=hub)
        block = await assembler.assemble()
    """

    def __init__(
        self,
        user_id: str,
        base_path: Path | None = None,
        memory_hub: MemoryHub | None = None,
    ) -> None:
        self.user_id = user_id
        self.base_path = base_path or (Path.home() / ".hermes" / "users")
        self._memory_hub = memory_hub

    def _brain_path(self) -> Path:
        return self.base_path / self.user_id / "brain"

    def _preferences_path(self) -> Path:
        return self._brain_path() / "PREFERENCES.md"

    def _user_md_path(self) -> Path:
        return self._brain_path() / "USER.md"

    async def _load_preferences_from_file(self) -> dict[str, Any]:
        """Load preferences from brain/PREFERENCES.md, falling back to defaults."""
        path = self._preferences_path()
        if not path.exists():
            return dict(DEFAULT_PREFERENCES)
        try:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                return dict(DEFAULT_PREFERENCES)
            data = json.loads(content)
            return {**DEFAULT_PREFERENCES, **data}
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULT_PREFERENCES)

    async def _load_identity_from_file(self) -> dict[str, Any]:
        """Load identity from brain/USER.md."""
        path = self._user_md_path()
        if not path.exists():
            return {}
        try:
            content = path.read_text(encoding="utf-8")
            result: dict[str, Any] = {}
            for line in content.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "：" in line:
                    key_value = line.split("：", 1)
                    if len(key_value) == 2:
                        result[key_value[0].strip()] = key_value[1].strip()
                elif "=" in line:
                    key_value = line.split("=", 1)
                    result[key_value[0].strip()] = key_value[1].strip()
            return result
        except OSError:
            return {}

    async def assemble(self) -> PersonaBlock:
        """Assemble a PersonaBlock from user preferences and identity.

        Returns:
            PersonaBlock with system_prefix and style parameters.
        """
        # Load from MemoryHub if available, otherwise from files
        if self._memory_hub is not None:
            preferences = await self._memory_hub.get_preferences()
            identity = await self._memory_hub.get_identity()
        else:
            preferences = await self._load_preferences_from_file()
            identity = await self._load_identity_from_file()

        # Build system_prefix based on identity (owner name + role)
        owner_name = identity.get("name", "用户")
        system_prefix = self._build_system_prefix(owner_name, preferences)

        return PersonaBlock(
            system_prefix=system_prefix,
            communication_style=preferences.get("communication_style", "neutral"),
            detail_level=preferences.get("detail_level", "medium"),
            tone=preferences.get("tone", "neutral"),
            format=preferences.get("format", "markdown"),
            max_length=preferences.get("max_length", 2000),
            language=preferences.get("language", "auto"),
        )

    def _build_system_prefix(self, owner_name: str, preferences: dict[str, Any]) -> str:
        """Build the owner-specific system prefix."""
        is_en = preferences.get("language") == "en"
        is_zh = preferences.get("language", "auto") == "zh"

        # Base identity
        if is_en:
            lines = [f"You are {owner_name}'s personal assistant."]
        else:
            lines = [f"你是{owner_name}的私人助理。"]

        # Style-specific directives
        comm = preferences.get("communication_style", "neutral")
        detail = preferences.get("detail_level", "medium")
        tone = preferences.get("tone", "neutral")

        if comm == "brief" and tone == "direct":
            if is_en:
                lines.append("Communication style: extremely concise. Lead with conclusions.")
                lines.append(
                    "Never: detailed background, multiple options, 'here are three options'."
                )
                lines.append(
                    "Must: lead with conclusion, no more than 3 sentences, cite data when available."
                )
            else:
                lines.append("沟通风格：极度简洁，直奔结论，反对对账式回答。")
                lines.append("禁止：详细背景描述、并列多选项、「以下是三个方案」。")
                lines.append("必须：结论先行，不超过3句话，有数据给数据。")

        elif detail == "high" or tone == "conservative":
            if is_en:
                lines.append("Communication style: rigorous, cite evidence, assess risks.")
                lines.append("Must: cite sources, flag uncertainties, list assumptions.")
                lines.append("Never: definitive conclusions without confidence level.")
            else:
                lines.append("沟通风格：严谨详细，引用依据，给出风险评估。")
                lines.append("必须：说明依据来源，标注不确定项，列出前提条件。")
                lines.append("禁止：过于果断的结论（必须说明置信度）。")

        elif comm == "casual":
            if is_en:
                lines.append("Communication style: relaxed, conversational, friendly.")
                lines.append("Allowed: colloquial expressions, appropriate emoji.")
            else:
                lines.append("沟通风格：轻松随意，像和朋友聊天。")
                lines.append("可以：使用口语化表达，适当的 emoji。")

        elif comm == "formal":
            if is_en:
                lines.append("Communication style: formal, professional, written style.")
                lines.append("Avoid: colloquialisms, internet slang.")
            else:
                lines.append("沟通风格：正式专业，使用书面语。")
                lines.append("避免：口语化表达、网络用语。")

        return "\n".join(lines)
