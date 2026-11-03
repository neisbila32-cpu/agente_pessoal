"""Catálogo, autorização e coordenação multiagente com executores injetados."""

from agente_pessoal.multiagent.models import (
    AgentDefinition,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
)
from agente_pessoal.multiagent.coordinator import AgentDisabledError, MaestroCoordinator
from agente_pessoal.multiagent.executors import (
    AgentExecutorRegistry,
    DuplicateExecutorError,
    ExecutorNotFoundError,
    ExecutorRegistryError,
)
from agente_pessoal.multiagent.ports import AgentExecutor
from agente_pessoal.multiagent.registry import (
    AgentNotFoundError,
    AgentRegistry,
    AgentRegistryError,
    DuplicateAgentError,
)
from agente_pessoal.multiagent.workflow import (
    AgentTask,
    AgentTaskResult,
    AgentTaskStatus,
    MultiAgentPlan,
    MultiAgentResult,
    MultiAgentStatus,
    MultiAgentWorkflow,
    TaskDependency,
)

__all__ = [
    "AgentDefinition",
    "AgentDisabledError",
    "AgentExecutionRequest",
    "AgentExecutionResult",
    "AgentExecutionStatus",
    "AgentExecutor",
    "AgentExecutorRegistry",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentRegistryError",
    "AgentTask",
    "AgentTaskResult",
    "AgentTaskStatus",
    "DuplicateAgentError",
    "DuplicateExecutorError",
    "ExecutorNotFoundError",
    "ExecutorRegistryError",
    "MaestroCoordinator",
    "MultiAgentPlan",
    "MultiAgentResult",
    "MultiAgentStatus",
    "MultiAgentWorkflow",
    "TaskDependency",
]
