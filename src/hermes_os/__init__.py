"""Hermes OS — Multi-user platform layer on top of hermes-agent."""

from .approval_tracker import (
    ApprovalRecord,
    ApprovalStatus,
    ApprovalTracker,
)
from .artifact_manager import (
    ArtifactManager,
    ArtifactMeta,
    ArtifactStage,
    ArtifactStatus,
    ArtifactWorkspace,
)
from .brain_indexer import BrainIndex, BrainIndexer
from .brain_updater import BrainUpdater
from .claude_code_invocator import (
    InvocationError,
    InvocationResult,
    health_check,
    invoke,
    invoke_bash,
    invoke_stream,
)
from .content_generator import ContentGeneratorAgent, ContentType, GenerationResult
from .conversation_state import ConversationState, ConversationStateManager
from .doc_workflow import (
    ApprovalFlow,
    DocType,
    DocWorkflowEngine,
    DocWorkflowResult,
)
from .emotion_engine import EmotionEngine
from .emotion_types import EmotionState, ToneConfig
from .gemini_cli import (
    GeminiResult,
)
from .gemini_cli import (
    health_check as gemini_health_check,
)
from .gemini_cli import (
    invoke as gemini_invoke,
)
from .gemini_cli import (
    invoke_stream as gemini_invoke_stream,
)
from .goal_tracker import (
    EvolutionEntry,
    GoalPattern,
    GoalPhase,
    GoalState,
    GoalTracker,
)
from .guardian_controller import (
    CheckpointData,
    ErrorAttribution,
    ErrorType,
    EscalationDecision,
    GuardianConfig,
    GuardianController,
    HandleResult,
)
from .hermes_tool_registry import HermesToolRegistry, get_tool_registry
from .jarvis_interface import JarvisInterface
from .labor_registry import (
    LaborInterface,
    LaborRegistry,
    LaborResult,
    get_labor_registry,
    initialize_default_labors,
)
from .memory_hub import (
    ContextMemory,
    IdentityMemory,
    KnowledgeMemory,
    MemoryHub,
    PreferencesMemory,
    RecentContextMemory,
)
from .notification_manager import (
    NotificationEvent,
    NotificationManager,
    SendThresholds,
)
from .output_adapter import (
    OutputAdapter,
    OutputStyle,
)
from .personality_tuner import PersonalityTuner, TonePreference
from .proactive_engine import ProactiveEngine
from .research_workflow import (
    IntelligenceResult,
    IntelligenceSource,
    ResearchWorkflowEngine,
    RiskFlag,
)
from .skill_discovery import CapabilityGap, DiscoveredSkill, SkillDiscovery
from .task_scheduler import Task, TaskPriority, TaskScheduler, TaskStatus
from .unified_router import (
    INTENT_AGENT_MAP,
    RouteResult,
    UnifiedRouter,
)
from .user_file_manager import UserFileManager
from .vertical_agent import (
    AgentRegistry,
    AgentRequest,
    AgentResult,
    VerticalAgent,
    get_agent_registry,
)
from .workflow_engine import (
    IntentToWorkflowMapper,
    Workflow,
    WorkflowEngine,
    WorkflowResult,
    WorkflowStep,
)

__version__ = "0.3.0"

__all__ = [
    # TaskScheduler
    "TaskScheduler",
    "TaskStatus",
    "TaskPriority",
    "Task",
    # SkillDiscovery
    "SkillDiscovery",
    "DiscoveredSkill",
    "CapabilityGap",
    # Claude Code Invoker
    "InvocationResult",
    "InvocationError",
    "invoke",
    "invoke_stream",
    "invoke_bash",
    "health_check",
    # Jarvis
    "JarvisInterface",
    "ConversationStateManager",
    "ConversationState",
    "UserFileManager",
    # Workflow
    "WorkflowEngine",
    "WorkflowStep",
    "Workflow",
    "WorkflowResult",
    "IntentToWorkflowMapper",
    # Brain
    "BrainIndexer",
    "BrainIndex",
    "BrainUpdater",
    # Emotion
    "EmotionEngine",
    "EmotionState",
    "ToneConfig",
    "PersonalityTuner",
    "TonePreference",
    # Tool Registry
    "HermesToolRegistry",
    "get_tool_registry",
    # Government Documents
    "DocType",
    "ApprovalFlow",
    "DocWorkflowEngine",
    "DocWorkflowResult",
    # Content Generation
    "ContentGeneratorAgent",
    "ContentType",
    "GenerationResult",
    # Research Workflow
    "ResearchWorkflowEngine",
    "IntelligenceSource",
    "IntelligenceResult",
    "RiskFlag",
    # Gemini CLI
    "GeminiResult",
    "gemini_invoke",
    "gemini_invoke_stream",
    "gemini_health_check",
    # Goal Tracker
    "GoalTracker",
    "GoalPhase",
    "GoalPattern",
    "GoalState",
    "EvolutionEntry",
    # Proactive Engine
    "ProactiveEngine",
    # Guardian Controller
    "GuardianController",
    "GuardianConfig",
    "CheckpointData",
    "HandleResult",
    "ErrorAttribution",
    "ErrorType",
    "EscalationDecision",
    # Approval Tracker
    "ApprovalTracker",
    "ApprovalStatus",
    "ApprovalRecord",
    # Notification Manager
    "NotificationManager",
    "NotificationEvent",
    "SendThresholds",
    # Labor Registry
    "LaborRegistry",
    "LaborResult",
    "LaborInterface",
    "get_labor_registry",
    "initialize_default_labors",
    # Artifact Manager
    "ArtifactManager",
    "ArtifactMeta",
    "ArtifactWorkspace",
    "ArtifactStage",
    "ArtifactStatus",
    # Vertical Agent
    "AgentRequest",
    "AgentResult",
    "VerticalAgent",
    "AgentRegistry",
    "get_agent_registry",
    # Memory Hub
    "MemoryHub",
    "ContextMemory",
    "IdentityMemory",
    "PreferencesMemory",
    "RecentContextMemory",
    "KnowledgeMemory",
    # Unified Router
    "UnifiedRouter",
    "RouteResult",
    "INTENT_AGENT_MAP",
    # Output Adapter
    "OutputStyle",
    "OutputAdapter",
]
