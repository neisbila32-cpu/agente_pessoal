"""Tipos e interface de planejamento independentes de fornecedor de IA."""

from dataclasses import dataclass, field
from typing import Mapping, Protocol
from uuid import uuid4

from agente_pessoal.core.request import UserRequest


@dataclass(frozen=True, slots=True)
class PlannedStep:
    description: str
    tool_name: str
    arguments: Mapping[str, object] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True, slots=True)
class TaskPlan:
    steps: tuple[PlannedStep, ...]


class Planner(Protocol):
    """Contrato de planejador; pode ser implementado por regras ou IA futura."""

    def plan(self, request: UserRequest) -> TaskPlan:
        """Converte uma solicitação em etapas explícitas, sem executá-las."""
        ...
