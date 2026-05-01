"""Hermes OS — Multi-user platform layer on top of hermes-agent."""

from hermes_os.task_scheduler import TaskScheduler, TaskStatus, TaskPriority, Task
from hermes_os.skill_discovery import SkillDiscovery, DiscoveredSkill, CapabilityGap
from hermes_os.claude_code_invocator import (
    InvocationResult,
    InvocationError,
    invoke,
    invoke_stream,
    invoke_bash,
    health_check,
)
from hermes_os.jarvis_interface import JarvisInterface
from hermes_os.conversation_state import ConversationStateManager, ConversationState
from hermes_os.user_file_manager import UserFileManager
from hermes_os.workflow_engine import (
    WorkflowEngine,
    WorkflowStep,
    Workflow,
    WorkflowResult,
    IntentToWorkflowMapper,
)
from hermes_os.brain_indexer import BrainIndexer, BrainIndex
from hermes_os.brain_updater import BrainUpdater
from hermes_os.emotion_engine import EmotionEngine
from hermes_os.emotion_types import EmotionState, ToneConfig
from hermes_os.personality_tuner import PersonalityTuner, TonePreference
from hermes_os.hermes_tool_registry import HermesToolRegistry, get_tool_registry
from hermes_os.doc_workflow import (
    DocType,
    ApprovalFlow,
    DocWorkflowEngine,
    DocWorkflowResult,
)
from hermes_os.content_generator import ContentGeneratorAgent, ContentType, GenerationResult
from hermes_os.research_workflow import (
    ResearchWorkflowEngine,
    IntelligenceSource,
    IntelligenceResult,
    RiskFlag,
)
from hermes_os.gemini_cli import (
    GeminiResult,
    invoke as gemini_invoke,
    invoke_stream as gemini_invoke_stream,
    health_check as gemini_health_check,
)
from hermes_os.goal_tracker import (
    GoalTracker,
    GoalPhase,
    GoalPattern,
    GoalState,
    EvolutionEntry,
)
from hermes_os.proactive_engine import ProactiveEngine
from hermes_os.guardian_controller import (
    GuardianController,
    GuardianConfig,
    CheckpointData,
    HandleResult,
    ErrorAttribution,
    ErrorType,
    EscalationDecision,
)
from hermes_os.approval_tracker import (
    ApprovalTracker,
    ApprovalStatus,
    ApprovalRecord,
)
from hermes_os.notification_manager import (
    NotificationManager,
    NotificationEvent,
    SendThresholds,
)
from hermes_os.labor_registry import (
    LaborRegistry,
    LaborResult,
    LaborInterface,
    get_labor_registry,
    initialize_default_labors,
)
from hermes_os.artifact_manager import (
    ArtifactManager,
    ArtifactMeta,
    ArtifactWorkspace,
    ArtifactStage,
    ArtifactStatus,
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
]
