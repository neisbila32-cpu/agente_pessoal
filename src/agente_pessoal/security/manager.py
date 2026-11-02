"""Gerencia concessões persistentes e autorizações deny by default."""

from datetime import datetime, timezone

from agente_pessoal.audit.events import AuditEventType, AuditLogger
from agente_pessoal.security.permissions import (
    Permission,
    PermissionDenied,
    PermissionGrant,
)
from agente_pessoal.security.ports import ApprovalProvider, PermissionRepository


class PermissionManager:
    def __init__(
        self,
        repository: PermissionRepository,
        audit: AuditLogger | None = None,
        approval_provider: ApprovalProvider | None = None,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._approval_provider = approval_provider

    def grant(self, permission: Permission, granted_by: str = "user") -> PermissionGrant:
        grant = PermissionGrant.create(permission, granted_by)
        self._repository.grant_permission(grant)
        if self._audit:
            self._audit.record(
                AuditEventType.PERMISSION_GRANTED,
                permission=permission.value,
                outcome="granted",
            )
        return grant

    def revoke(self, permission: Permission, revoked_by: str = "user") -> bool:
        changed = self._repository.revoke_permission(
            permission,
            revoked_by,
            datetime.now(timezone.utc).isoformat(),
        )
        if self._audit:
            self._audit.record(
                AuditEventType.PERMISSION_REVOKED,
                permission=permission.value,
                outcome="revoked" if changed else "not_granted",
            )
        return changed

    def list_permissions(self, include_revoked: bool = False) -> tuple[PermissionGrant, ...]:
        return self._repository.list_permissions(include_revoked)

    def require(
        self,
        permission: Permission,
        *,
        reason: str = "",
        task_id: str | None = None,
        step_id: str | None = None,
        tool_name: str | None = None,
    ) -> None:
        grant = self._repository.get_permission(permission)
        allowed = bool(grant and grant.granted)
        approval_error: Exception | None = None
        if not allowed and self._approval_provider is not None:
            try:
                if self._approval_provider.request_approval(permission, reason):
                    self.grant(permission, granted_by="approval_provider")
                    allowed = True
            except Exception as exc:
                approval_error = exc

        if self._audit:
            self._audit.record(
                AuditEventType.PERMISSION_CHECKED,
                task_id=task_id,
                step_id=step_id,
                tool_name=tool_name,
                permission=permission.value,
                outcome="allowed" if allowed else "denied",
                error_type=type(approval_error).__name__ if approval_error else None,
            )
            if not allowed:
                self._audit.record(
                    AuditEventType.AUTHORIZATION_DENIED,
                    task_id=task_id,
                    step_id=step_id,
                    tool_name=tool_name,
                    permission=permission.value,
                    outcome="denied",
                    error_type=type(approval_error).__name__ if approval_error else None,
                )
        if not allowed:
            message = "A aprovação não pôde ser confirmada." if approval_error else (
                f"Permissão necessária: {permission.value}"
            )
            raise PermissionDenied(message) from approval_error
