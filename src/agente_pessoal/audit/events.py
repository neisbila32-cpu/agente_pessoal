"""Eventos de auditoria com campos limitados para evitar dados sensíveis."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol


class AuditEventType(StrEnum):
    TASK_CREATED = "task.created"
    TASK_STATUS_CHANGED = "task.status_changed"
    TASK_FAILED = "task.failed"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    TOOL_ATTEMPTED = "tool.attempted"
    PERMISSION_CHECKED = "permission.checked"
    PERMISSION_GRANTED = "permission.granted"
    PERMISSION_REVOKED = "permission.revoked"
    AUTHORIZATION_DENIED = "authorization.denied"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_type: AuditEventType
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    task_id: str | None = None
    step_id: str | None = None
    tool_name: str | None = None
    permission: str | None = None
    outcome: str | None = None
    error_type: str | None = None


class AuditSink(Protocol):
    def append_audit_event(self, event: AuditEvent) -> None: ...


class AuditLogger:
    """Grava eventos estruturados; não aceita argumentos, resultados ou mensagens."""

    def __init__(self, sink: AuditSink) -> None:
        self._sink = sink

    def record(
        self,
        event_type: AuditEventType,
        *,
        task_id: str | None = None,
        step_id: str | None = None,
        tool_name: str | None = None,
        permission: str | None = None,
        outcome: str | None = None,
        error_type: str | None = None,
    ) -> None:
        self._sink.append_audit_event(
            AuditEvent(
                event_type=event_type,
                task_id=task_id,
                step_id=step_id,
                tool_name=tool_name,
                permission=permission,
                outcome=outcome,
                error_type=error_type,
            )
        )
