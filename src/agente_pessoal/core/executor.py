"""Execução de etapas por ferramentas registradas e autorizadas."""

import logging
from collections.abc import Iterable

from agente_pessoal.audit.events import AuditEventType, AuditLogger
from agente_pessoal.core.task import TaskStep
from agente_pessoal.security import AuthorizationContext, PermissionPolicy
from agente_pessoal.security.manager import PermissionManager
from agente_pessoal.security.permissions import PermissionDenied
from agente_pessoal.tools.base import Tool, ToolDescription

logger = logging.getLogger(__name__)


class ToolNotFoundError(LookupError):
    """O plano referencia uma ferramenta que não foi registrada."""


class ToolExecutor:
    """Resolve ferramentas pelo nome e exige permissão antes de executá-las."""

    def __init__(
        self,
        tools: Iterable[Tool],
        permission_manager: PermissionManager | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        registry: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in registry:
                raise ValueError(f"Nome de ferramenta duplicado: {tool.name}")
            registry[tool.name] = tool
        self._tools = registry
        self._permission_manager = permission_manager
        self._audit = audit

    @property
    def tool_catalog(self) -> tuple[ToolDescription, ...]:
        """Catálogo sem dados de permissão para orientar um planejador de IA."""
        return tuple(
            ToolDescription(name=tool.name, description=tool.describe())
            for tool in self._tools.values()
        )

    def execute(
        self,
        step: TaskStep,
        authorization: AuthorizationContext | None = None,
        *,
        task_id: str | None = None,
    ) -> object:
        tool = self._tools.get(step.tool_name)
        if tool is None:
            raise ToolNotFoundError(f"Ferramenta não registrada: {step.tool_name}")

        if self._audit:
            self._audit.record(
                AuditEventType.TOOL_ATTEMPTED,
                task_id=task_id,
                step_id=step.id,
                tool_name=tool.name,
            )

        # A verificação ocorre imediatamente antes da chamada à ferramenta.
        if self._permission_manager is not None:
            self._permission_manager.require(
                tool.required_permission,
                reason=step.description,
                task_id=task_id,
                step_id=step.id,
                tool_name=tool.name,
            )
        else:
            try:
                PermissionPolicy.require(tool.required_permission, authorization)
            except PermissionDenied:
                if self._audit:
                    self._audit.record(
                        AuditEventType.PERMISSION_CHECKED,
                        task_id=task_id,
                        step_id=step.id,
                        tool_name=tool.name,
                        permission=tool.required_permission.value,
                        outcome="denied",
                    )
                    self._audit.record(
                        AuditEventType.AUTHORIZATION_DENIED,
                        task_id=task_id,
                        step_id=step.id,
                        tool_name=tool.name,
                        permission=tool.required_permission.value,
                        outcome="denied",
                    )
                raise
            if self._audit:
                self._audit.record(
                    AuditEventType.PERMISSION_CHECKED,
                    task_id=task_id,
                    step_id=step.id,
                    tool_name=tool.name,
                    permission=tool.required_permission.value,
                    outcome="allowed",
                )
        logger.info("Executando ferramenta %s na etapa %s", tool.name, step.id)
        return tool.execute(step.arguments)
