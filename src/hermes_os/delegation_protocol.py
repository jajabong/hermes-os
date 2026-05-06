"""DelegationProtocol — 委派协议 for Hermes OS.

Phase 1: 千人千面管家
P0: 当管家收到重度任务（代码/长文/报告）时，优雅委派 + 飞书进度推送

核心职责：
1. 判断是否需要委派（TaskComplexity 分类）
2. 创建 TaskScheduler 任务
3. 立即返回「收到，我来处理」让用户感知
4. 附加 Feishu notify_target 用于进度推送
5. 后台由 TaskScheduler + NotificationManager 处理进度推送

Architecture:
    UnifiedRouter.route()
        ↓
    DelegationProtocol.delegate(message, intent, user)
        ├── HEAVY → create_task() + return immediate_reply + notify_target
        ├── MEDIUM → create_task() (可选) + return immediate_reply
        └── LIGHT → NOT_DELEGATED + return direct response
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hermes_os.feishu_enhancer import FeishuEnhancer
    from hermes_os.jarvis_interface import JarvisInterface
    from hermes_os.task_scheduler import TaskScheduler


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskComplexity(str, Enum):
    """任务复杂度分类 — 决定是否委派。"""

    LIGHT = "light"  # 日常对话，直接响应
    MEDIUM = "medium"  # 中等复杂度，可委派
    HEAVY = "heavy"  # 重度任务，必须委派


class DelegationStatus(str, Enum):
    """委派状态。"""

    DELEGATED = "delegated"  # 已委派给 TaskScheduler
    NOT_DELEGATED = "not_delegated"  # 不需要委派，直接响应


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DelegationResult:
    """委派结果 — 包含立即回复内容和任务信息。"""

    task_id: str
    user_id: str
    status: DelegationStatus
    title: str
    immediate_reply: str  # 飞书立即展示给用户的文字
    agent_name: str = "ChiefAgent"
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Intent → Agent mapping
# ---------------------------------------------------------------------------

INTENT_TO_AGENT: dict[str, str] = {
    "code": "CodeAgent",
    "fix_bug": "CodeAgent",
    "investment": "InvestmentAgent",
    "legal": "LegalAgent",
    "content": "ContentAgent",
    "research": "ResearchAgent",
    "education": "EducationAgent",
    "deploy": "DeployAgent",
    "review": "ReviewAgent",
    "test": "TestAgent",
    "write_book": "BookPipelineAgent",
    "unknown": "ChiefAgent",
}


# ---------------------------------------------------------------------------
# DelegationTrigger — 任务复杂度判断
# ---------------------------------------------------------------------------


class DelegationTrigger:
    """根据消息内容判断任务复杂度。"""

    # 重度关键词：明确需要后台执行的任务
    # Tuple format: (prefix, suffix) — suffix=None means just check prefix
    HEAVY_PATTERNS = (
        # 代码/开发
        ("帮我写", None),
        ("帮我开发", None),
        ("帮我实现", None),
        ("帮我调试", None),
        # "写"开头的任何消息（长文/代码/方案等都是重度）
        ("写", None),
        ("开发", None),
        ("编程", None),
        ("debug", None),
        ("fix this bug", None),
        # 长文/内容
        ("写文章", None),
        ("写报告", None),
        ("写方案", None),
        ("写文档", None),
        ("写书", None),
        ("写总结", None),
        ("写分析", None),
        # 研究/分析
        ("分析报告", None),
        ("竞品分析", None),
        ("投资分析", None),
        ("风险评估", None),
        ("市场调研", None),
        ("调研", None),
        ("研究", None),
    )

    # 中度关键词：需要一定处理但不需要委派
    # 注意：所有带"帮我"开头的动作词请求默认是重度任务，
    # 只有这里明确列出的"写+短内容"模式才是 MEDIUM
    MEDIUM_KEYWORDS = (
        "查一下",
        "解释一下",
        "介绍一下",
        "有什么区别",
        "怎么看",
        "如何理解",
        "这个概念",
        "这个技术",
        "这个工具",
        # "写"开头的非重度消息（短内容请求）
        "写篇文章",
        "写份报告",
        "写个总结",
        "写点东西",
        # "分析"类但不构成重度短语
        "分析一下",
        "分析这个",
    )

    def classify(self, message: str) -> TaskComplexity:
        """判断消息对应的任务复杂度。优先检查 HEAVY，再检查 MEDIUM。"""
        # 先检查重度（更具体的模式优先）
        if self._is_heavy(message):
            return TaskComplexity.HEAVY
        # 再检查中度（较通用的模式）
        if self._is_medium(message):
            return TaskComplexity.MEDIUM
        return TaskComplexity.LIGHT

    def _is_heavy(self, message: str) -> bool:
        """检查是否重度任务。

        支持精确匹配和截断匹配（如"写文章"匹配"写一篇文章"）。
        """
        msg_lower = message.lower()

        # 优先检查明确的重度模式
        for pattern in self.HEAVY_PATTERNS:
            kw1, kw2 = pattern
            if kw1 in msg_lower:
                if kw2 is None or kw2 in msg_lower:
                    return True
            # 截断匹配：检查消息是否以动作词开头，后跟内容
            if self._starts_with_verb_and_content(msg_lower, kw1):
                return True

        # "帮我 + 动作词" → 重度（帮我分析、帮我研究、帮我调研等）
        if msg_lower.startswith("帮我"):
            after_prefix = msg_lower[2:]  # after "帮我"
            heavy_verbs = ("分析", "研究", "调研", "写", "开发", "实现", "审查", "评估")
            for verb in heavy_verbs:
                if after_prefix.startswith(verb):
                    return True

        return False

    def _starts_with_verb_and_content(self, msg: str, pattern: str) -> bool:
        """检查 msg 是否以 pattern 开头（允许中间有量词/助词分隔）。"""
        if len(pattern) < 2:
            return False
        # For Chinese verb patterns like "写文章", check if message starts with
        # the verb and contains the noun somewhere close after
        verb = pattern[0]  # e.g., "写"
        noun = pattern[1:]  # e.g., "文章"
        if msg.startswith(verb) and noun in msg[:8]:  # within first 8 chars
            return True
        return False

    def _is_medium(self, message: str) -> bool:
        """检查是否中度任务。"""
        msg_lower = message.lower()
        for kw in self.MEDIUM_KEYWORDS:
            if kw in msg_lower:
                return True
        return False


# ---------------------------------------------------------------------------
# DelegationProtocol — 委派协议核心
# ---------------------------------------------------------------------------


class DelegationProtocol:
    """管家委派协议。

    当管家收到重度任务时：
    1. 立即返回「收到，我来处理」
    2. 在 TaskScheduler 创建任务（带 Feishu notify_target）
    3. 在 TopicTracker 记录当前话题（用于「接着上次」检测）
    4. 后台由 TaskScheduler 执行 + 推送进度

    Example:
        protocol = DelegationProtocol()
        result = await protocol.delegate(
            user=user,
            message="帮我写一个 FastAPI 接口",
            intent="code",
        )
        if result.status == DelegationStatus.DELEGATED:
            # 立即展示 result.immediate_reply 给用户
            # 任务在后台运行，通过飞书推送进度
        else:
            # 直接回复 result.immediate_reply
    """

    def __init__(
        self,
        task_scheduler: TaskScheduler | None = None,
        feishu_enhancer: FeishuEnhancer | None = None,
        jarvis: JarvisInterface | None = None,
        topic_tracker_factory: Any | None = None,
    ) -> None:
        self._task_scheduler = task_scheduler
        self._feishu_enhancer = feishu_enhancer
        self._jarvis = jarvis
        self._topic_tracker_factory = topic_tracker_factory
        self._trigger = DelegationTrigger()

    @property
    def _scheduler(self) -> TaskScheduler:
        if self._task_scheduler is None:
            from hermes_os.task_scheduler import TaskScheduler

            self._task_scheduler = TaskScheduler()
        return self._task_scheduler

    @property
    def _feishu(self) -> FeishuEnhancer | None:
        return self._feishu_enhancer

    @property
    def _jarvis_iface(self) -> JarvisInterface | None:
        return self._jarvis

    def should_delegate(self, message: str) -> bool:
        """快速判断是否应该委派。"""
        return self._trigger.classify(message) != TaskComplexity.LIGHT

    async def delegate(
        self,
        user: Any,
        message: str,
        intent: str = "unknown",
    ) -> DelegationResult:
        """执行委派。

        Args:
            user: User 对象（必须有 user_id, platform, platform_user_id, name）
            message: 用户原始消息
            intent: 解析后的意图（如 "code", "investment"）

        Returns:
            DelegationResult — 包含 immediate_reply 和任务信息
        """
        complexity = self._trigger.classify(message)

        # LIGHT: 不需要委派，直接返回
        if complexity == TaskComplexity.LIGHT:
            return DelegationResult(
                task_id="",
                user_id=getattr(user, "user_id", ""),
                status=DelegationStatus.NOT_DELEGATED,
                title=message[:50],
                immediate_reply=self._build_light_reply(message),
                agent_name="ChiefAgent",
            )

        # HEAVY / MEDIUM: 委派给 TaskScheduler
        return await self._delegate_heavy(user, message, intent)

    async def _delegate_heavy(
        self,
        user: Any,
        message: str,
        intent: str,
    ) -> DelegationResult:
        """委派重度任务给 TaskScheduler。"""
        user_id = getattr(user, "user_id", "unknown")
        user_name = getattr(user, "name", "用户")
        platform = getattr(user, "platform", "unknown")
        platform_user_id = getattr(user, "platform_user_id", "")

        # 构建任务标题
        title = self._build_title(message, intent)

        # 构建即时回复（用户看到的第一句话）
        immediate_reply = self._build_immediate_reply(user_name, intent, message)

        # 确定 agent 名称
        agent_name = INTENT_TO_AGENT.get(intent, "ChiefAgent")

        # 构建 metadata（含 notify_target 用于飞书推送）
        metadata: dict[str, Any] = {
            "original_message": message,
            "intent": intent,
            "agent_name": agent_name,
            "delegated_via": "DelegationProtocol",
        }

        # 如果是飞书平台，附加 notify_target
        if platform == "feishu" and platform_user_id:
            metadata["notify_target"] = {
                "type": "feishu",
                "open_id": platform_user_id,
            }

        # 创建 TaskScheduler 任务
        task_id = ""
        try:
            task = await self._scheduler.create_task(
                user_id=user_id,
                title=title,
                description=message,
                metadata=metadata,
            )
            task_id = task.task_id

            # 记录话题到 TopicTracker（用于「接着上次」检测）
            if self._topic_tracker_factory and task_id:
                tracker = self._topic_tracker_factory(user_id=user_id)
                await tracker.record_topic(
                    topic=title,
                    task_id=task_id,
                    intent=intent,
                )
        except Exception:
            # TaskScheduler 失败不应该阻塞委派流程
            pass

        return DelegationResult(
            task_id=task_id,
            user_id=user_id,
            status=DelegationStatus.DELEGATED,
            title=title,
            immediate_reply=immediate_reply,
            agent_name=agent_name,
            metadata=metadata,
        )

    def _build_title(self, message: str, intent: str) -> str:
        """从消息构建任务标题。"""
        # 截断消息前 60 字符作为标题
        title = message[:60]
        if len(message) > 60:
            title += "..."

        # 根据 intent 添加前缀
        prefix_map = {
            "code": "💻 代码",
            "investment": "📊 投资分析",
            "legal": "⚖️ 法律审查",
            "content": "✍️ 内容创作",
            "research": "🔍 调研",
            "education": "📚 教育",
            "deploy": "🚀 部署",
            "review": "🔍 审查",
        }
        prefix = prefix_map.get(intent, "📋 任务")
        return f"{prefix}：{title}"

    def _build_immediate_reply(self, user_name: str, intent: str, message: str) -> str:
        """构建即时回复 — 用户立即看到的飞书消息。"""
        # 根据意图定制回复
        reply_templates = {
            "code": [
                "收到，我来帮您处理这个代码任务，预计需要 2-3 分钟搞定。",
                "好的，代码任务已安排，专业的代码 Agent 正在处理中。",
            ],
            "investment": [
                "收到，我来帮您分析这份投资报告，3-5 分钟出结果。",
                "好的，投资分析任务已委派，完成后向您汇报。",
            ],
            "legal": [
                "收到，律师 Agent 正在审查条款，5 分钟左右完成。",
                "好的，法律审查任务已安排，完成后向您汇报。",
            ],
            "content": [
                "收到，内容创作任务已安排，2-3 分钟完成。",
                "好的，文章/报告正在撰写中，完成后发送给您。",
            ],
            "research": [
                "收到，调研任务已安排，3-5 分钟出分析结果。",
                "好的，正在研究分析，完成后向您汇报。",
            ],
        }

        templates = reply_templates.get(
            intent,
            [
                "收到，我来帮您处理这个任务，预计需要几分钟。",
                "好的，任务已安排，处理完成后向您汇报。",
            ],
        )

        # 选择一个模板（简化：使用第一个）
        return templates[0]

    def _build_light_reply(self, message: str) -> str:
        """LIGHT 任务直接回复（日常对话）。"""
        # 这里只是占位，实际回复由 LLM 生成
        # 委派协议只负责判断，回复内容由 ChiefAgent/VerticalAgent 生成
        return ""
