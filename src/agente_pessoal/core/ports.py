"""Portas de saída usadas pelo núcleo sem acoplamento ao banco escolhido."""

from typing import Protocol

from agente_pessoal.core.request import UserRequest
from agente_pessoal.core.task import Task


class TaskRepository(Protocol):
    def create_task(self, request: UserRequest, task: Task) -> None: ...

    def save_task(self, task: Task) -> None: ...

    def get_task(self, task_id: str) -> Task | None: ...

    def list_tasks(self) -> tuple[Task, ...]: ...
