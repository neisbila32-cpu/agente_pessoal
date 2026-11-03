"""Portas agnósticas para futuros provedores e executores de agentes."""

from typing import Protocol

from agente_pessoal.multiagent.models import AgentExecutionRequest, AgentExecutionResult


class AgentExecutor(Protocol):
    """Contrato para futura execução de agentes, separado de provedores de modelos."""

    def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Executa uma solicitação de agente (nenhuma implementação é fornecida aqui)."""
        ...
