"""Modelos tipados para tarefas e etapas do orquestrador."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping
from uuid import uuid4


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class TaskStep:
    """Etapa planejada e seu estado de execução."""

    description: str
    tool_name: str
    arguments: Mapping[str, object] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    status: StepStatus = StepStatus.PENDING
    result: object | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StepResult:
    """Resultado imutável produzido por uma etapa concluída."""

    step_id: str
    tool_name: str
    value: object
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class Task:
    """Solicitação recebida e estado acumulado de seu ciclo de vida."""

    request: str
    id: str = field(default_factory=lambda: str(uuid4()))
    request_id: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    steps: list[TaskStep] = field(default_factory=list)
    results: list[StepResult] = field(default_factory=list)
    error: str | None = None
    completed_at: datetime | None = None

    @property
    def description(self) -> str:
        """Descrição da solicitação (alias legível para ``request``)."""
        return self.request
