"""Fundação de catálogo e contratos multiagente, sem execução de agentes."""

from agente_pessoal.multiagent.models import (
    AgentDefinition,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
)
from agente_pessoal.multiagent.ports import AgentExecutor
from agente_pessoal.multiagent.registry import (
    AgentNotFoundError,
    AgentRegistry,
    AgentRegistryError,
    DuplicateAgentError,
)

__all__ = [
    "AgentDefinition",
    "AgentExecutionRequest",
    "AgentExecutionResult",
    "AgentExecutionStatus",
    "AgentExecutor",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentRegistryError",
    "DuplicateAgentError",
]
