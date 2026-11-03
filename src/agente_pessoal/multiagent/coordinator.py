"""Coordenação sequencial de solicitações para agentes registrados."""

from agente_pessoal.multiagent.executors import AgentExecutorRegistry
from agente_pessoal.multiagent.models import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
)
from agente_pessoal.multiagent.registry import AgentRegistry
from agente_pessoal.security import AuthorizationContext, Permission, PermissionPolicy


class AgentDisabledError(PermissionError):
    """O agente existe, mas está desabilitado."""


class MaestroCoordinator:
    """Valida agente e autorização antes de despachar a um executor injetado."""

    def __init__(
        self,
        agent_registry: AgentRegistry,
        executor_registry: AgentExecutorRegistry,
    ) -> None:
        self._agents = agent_registry
        self._executors = executor_registry

    def execute(
        self,
        request: AgentExecutionRequest,
        authorization: AuthorizationContext | None = None,
    ) -> AgentExecutionResult:
        """Despacha uma solicitação e converte falhas do executor em erro genérico."""
        if not isinstance(request, AgentExecutionRequest):
            raise TypeError("request deve ser um AgentExecutionRequest.")

        agent = self._agents.get(request.agent_id)
        if not agent.enabled:
            raise AgentDisabledError("O agente está desabilitado.")

        PermissionPolicy.require(Permission.AGENT_EXECUTE, authorization)
        executor = self._executors.get(agent.adapter_id)

        try:
            result = executor.execute(request)
        except Exception:
            return self._failed_result(request)

        if (
            not isinstance(result, AgentExecutionResult)
            or result.request_id != request.id
            or result.agent_id != request.agent_id
        ):
            return self._failed_result(request)
        if result.status is AgentExecutionStatus.FAILED:
            return self._failed_result(request)

        # Copia o resultado para descartar campos de erro acidentais na resposta.
        return AgentExecutionResult(
            request_id=request.id,
            agent_id=request.agent_id,
            status=AgentExecutionStatus.COMPLETED,
            output=result.output,
        )

    @staticmethod
    def _failed_result(request: AgentExecutionRequest) -> AgentExecutionResult:
        return AgentExecutionResult(
            request_id=request.id,
            agent_id=request.agent_id,
            status=AgentExecutionStatus.FAILED,
            error="A execução do agente falhou.",
        )
