"""Registros auxiliares retornados pelos repositórios."""

from dataclasses import dataclass
from datetime import datetime

from agente_pessoal.core.task import TaskStatus


@dataclass(frozen=True, slots=True)
class TaskStatusChange:
    status: TaskStatus
    changed_at: datetime
