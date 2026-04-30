"""Feishu Enhancer — wrapper that exposes Feishu functions from the skills directory.

This module acts as a bridge between hermes-os and the feishu_enhancer skill
installed at ~/.hermes/hermes-agent/skills/local/feishu_enhancer/.
"""

from __future__ import annotations

import logging
import os
import sys
import json
from typing import Any

logger = logging.getLogger(__name__)

def _setup_path():
    """Ensure hermes-agent and skills are in sys.path."""
    agent_path = os.path.expanduser("~/.hermes/hermes-agent/")
    skill_path = os.path.expanduser("~/.hermes/hermes-agent/skills/local/")
    if agent_path not in sys.path:
        sys.path.append(agent_path)
    if skill_path not in sys.path:
        sys.path.append(skill_path)

class FeishuEnhancer:
    """Wrapper class compatible with the old import path hermes_os.feishu_enhancer.
    
    Delegates to functions in the feishu_enhancer skill.
    """

    def __init__(self) -> None:
        _setup_path()

    async def send_message_to_user(self, user_id: str, message: str) -> None:
        """Send a Feishu message to a user."""
        try:
            from feishu_enhancer.feishu_client import send_text
            # It's likely sync, but we treat it as async compatible if needed
            send_text(open_id=user_id, text=message)
        except Exception as e:
            logger.warning("Feishu send_text failed: %s", e)

    async def send_action_card(self, user_id: str, title: str, content: str, actions: list[dict[str, str]]) -> None:
        """Send an interactive action card to Feishu."""
        try:
            from feishu_enhancer.feishu_client import send_card
            
            # Construct Feishu Card JSON
            # Reference: https://open.feishu.cn/document/common-capabilities/message-card/message-cards-content/card-structure/card-elements/button
            card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title
                    },
                    "template": "blue"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": content
                        }
                    },
                    {
                        "tag": "action",
                        "actions": []
                    }
                ]
            }
            
            for action in actions:
                # 贾维斯优化：使用符合 hermes-agent 规范的 value 格式
                # 包含 hermes_action 能够让 gateway 将其路由回 hook
                btn_value = {
                    "hermes_action": action["value"],
                    "task_id": action.get("task_id", "unknown")
                }
                btn = {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": action["text"]
                    },
                    "type": action.get("type", "default"),
                    "value": btn_value
                }
                card["elements"][1]["actions"].append(btn)
                
            send_card(open_id=user_id, card=card)
        except Exception as e:
            logger.warning("Feishu send_card failed: %s", e)
            # Fallback
            action_text = "\n".join([f"- {a['text']}: {a['value']}" for a in actions])
            await self.send_message_to_user(user_id, f"**{title}**\n{content}\n\n{action_text}")


def send_text(open_id: str, text: str) -> None:
    """Standalone send_text function."""
    _setup_path()
    try:
        from feishu_enhancer.feishu_client import send_text as _send
        _send(open_id=open_id, text=text)
    except Exception as e:
        logger.warning("Feishu standalone send_text failed: %s", e)
