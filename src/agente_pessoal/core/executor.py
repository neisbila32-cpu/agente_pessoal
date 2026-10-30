"""Execução de etapas por ferramentas registradas e autorizadas."""

import logging
from collections.abc import Iterable

from agente_pessoal.core.task import TaskStep
from agente_pessoal.security import AuthorizationContext, PermissionPolicy
from agente_pessoal.tools.base import Tool

logger = logging.getLogger(__name__)


class ToolNotFoundError(LookupError):
    """O plano referencia uma ferramenta que não foi registrada."""


class ToolExecutor:
    """Resolve ferramentas pelo nome e exige permissão antes de executá-las."""

    def __init__(self, tools: Iterable[Tool]) -> None:
        registry: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in registry:
                raise ValueError(f"Nome de ferramenta duplicado: {tool.name}")
            registry[tool.name] = tool
        self._tools = registry

    def execute(
        self,
        step: TaskStep,
        authorization: AuthorizationContext | None = None,
    ) -> object:
        tool = self._tools.get(step.tool_name)
        if tool is None:
            raise ToolNotFoundError(f"Ferramenta não registrada: {step.tool_name}")

        # A verificação ocorre imediatamente antes da chamada à ferramenta.
        PermissionPolicy.require(tool.required_permission, authorization)
        logger.info("Executando ferramenta %s na etapa %s", tool.name, step.id)
        return tool.execute(step.arguments)
