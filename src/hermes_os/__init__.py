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
]
