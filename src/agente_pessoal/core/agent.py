"""Entrada do agente e contrato de orquestração."""

from typing import Protocol

from agente_pessoal.core.request import UserRequest
from agente_pessoal.core.task_manager import TaskManager
from agente_pessoal.core.task import Task
from agente_pessoal.security import AuthorizationContext


class Agent(Protocol):
    """Interface pública para receber solicitações."""

    def handle(
        self,
        request: str,
        authorization: AuthorizationContext | None = None,
    ) -> Task:
        """Recebe uma solicitação, inicia seu ciclo e retorna o registro."""
        ...


class TaskOrchestrator:
    """Implementação do agente que delega o ciclo de vida ao gerenciador."""

    def __init__(self, task_manager: TaskManager) -> None:
        self._task_manager = task_manager

    def handle(
        self,
        request: str,
        authorization: AuthorizationContext | None = None,
    ) -> Task:
        return self._task_manager.submit(UserRequest(text=request), authorization)
