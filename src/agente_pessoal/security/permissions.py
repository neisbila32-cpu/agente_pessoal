"""Política explícita de permissões; não executa ações."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable


class Permission(StrEnum):
    FILE_READ = "file.read"
    FILE_WRITE = "file.write"
    COMMAND_EXECUTE = "command.execute"
    APP_CONTROL = "app.control"
    WEB_ACCESS = "web.access"
    SCHEDULE_MANAGE = "schedule.manage"


class PermissionDenied(PermissionError):
    """Lançada quando o contexto não concede a permissão solicitada."""


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    permission: Permission
    granted: bool
    granted_at: datetime | None = None
    granted_by: str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None

    @classmethod
    def create(cls, permission: Permission, granted_by: str) -> "PermissionGrant":
        return cls(
            permission=permission,
            granted=True,
            granted_at=datetime.now(timezone.utc),
            granted_by=granted_by,
        )


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """Conjunto de permissões concedidas para uma operação."""

    granted: frozenset[Permission] = field(default_factory=frozenset)

    @classmethod
    def from_permissions(cls, permissions: Iterable[Permission]) -> "AuthorizationContext":
        return cls(granted=frozenset(permissions))


class PermissionPolicy:
    """Exige uma concessão explícita; ausência de contexto sempre nega."""

    @staticmethod
    def require(
        permission: Permission,
        context: AuthorizationContext | None = None,
    ) -> None:
        if context is None or permission not in context.granted:
            raise PermissionDenied(f"Permissão necessária: {permission.value}")
