"""Contratos de persistência de permissões."""

from typing import Protocol

from agente_pessoal.security.permissions import Permission, PermissionGrant


class PermissionRepository(Protocol):
    def grant_permission(self, grant: PermissionGrant) -> None: ...

    def revoke_permission(
        self, permission: Permission, revoked_by: str, revoked_at: str
    ) -> bool: ...

    def get_permission(self, permission: Permission) -> PermissionGrant | None: ...

    def list_permissions(self, include_revoked: bool = False) -> tuple[PermissionGrant, ...]: ...


class ApprovalProvider(Protocol):
    """Porta para uma futura solicitação explícita de aprovação ao usuário."""

    def request_approval(self, permission: Permission, reason: str) -> bool: ...
