"""Modelos imutáveis para catálogo e futuras solicitações multiagente."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping
from uuid import uuid4


def _required_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} deve ser um texto não vazio.")


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Metadados de um agente; ``adapter_id`` não instancia nem executa código."""

    id: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    adapter_id: str
    enabled: bool = True

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "description", "adapter_id"):
            _required_text(getattr(self, field_name), field_name)
        if isinstance(self.capabilities, (str, bytes)):
            raise ValueError("capabilities deve ser uma coleção de textos.")
        try:
            capabilities = tuple(self.capabilities)
        except TypeError:
            raise ValueError("capabilities deve ser uma coleção de textos.") from None
        if any(not isinstance(item, str) or not item.strip() for item in capabilities):
            raise ValueError("Cada capability deve ser um texto não vazio.")
        object.__setattr__(self, "capabilities", capabilities)
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled deve ser booleano.")


class AgentExecutionStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AgentExecutionRequest:
    """Pedido tipado para um executor futuro; não executa nem autoriza ações."""

    agent_id: str
    input: str
    id: str = field(default_factory=lambda: str(uuid4()))
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("id", "agent_id", "input"):
            _required_text(getattr(self, field_name), field_name)
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata deve ser um mapeamento.")


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    """Resultado tipado de um executor futuro, sem semântica de execução nesta etapa."""

    request_id: str
    agent_id: str
    status: AgentExecutionStatus
    output: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _required_text(self.request_id, "request_id")
        _required_text(self.agent_id, "agent_id")
        if not isinstance(self.status, AgentExecutionStatus):
            raise ValueError("status deve ser um AgentExecutionStatus.")
        if self.output is not None and not isinstance(self.output, str):
            raise ValueError("output deve ser texto ou None.")
        if self.error is not None and not isinstance(self.error, str):
            raise ValueError("error deve ser texto ou None.")
        if not isinstance(self.created_at, datetime):
            raise ValueError("created_at deve ser datetime.")
