"""Registros auxiliares retornados pelos repositórios."""

from dataclasses import dataclass
from datetime import datetime
import re

from agente_pessoal.core.task import TaskStatus


@dataclass(frozen=True, slots=True)
class TaskStatusChange:
    status: TaskStatus
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class DesktopAgentRecord:
    """Somente campos de configuração não sensíveis de um agente pessoal."""

    id: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    enabled: bool

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "description"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} deve ser texto não vazio.")
        try:
            capabilities = tuple(self.capabilities)
        except TypeError:
            raise ValueError("capabilities deve ser uma coleção de textos.") from None
        if isinstance(self.capabilities, (str, bytes)) or any(
            not isinstance(item, str) or not item.strip() for item in capabilities
        ):
            raise ValueError("capabilities deve conter somente textos não vazios.")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled deve ser booleano.")
        object.__setattr__(self, "capabilities", capabilities)


@dataclass(frozen=True, slots=True)
class DesktopAgentBindingRecord:
    """Vínculo lógico; não contém estado de autenticação nem credenciais."""

    agent_id: str
    connection_id: str

    def __post_init__(self) -> None:
        for field_name in ("agent_id", "connection_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} deve ser texto não vazio.")


@dataclass(frozen=True, slots=True)
class DesktopPreferenceRecord:
    """Preferência local allowlist; atualmente apenas dimensões da janela."""

    key: str
    value: str

    def __post_init__(self) -> None:
        if self.key != "window_size":
            raise ValueError("Preferência desktop não permitida.")
        dimensions = r"(?:[4-9][0-9]{2}|[1-9][0-9]{3})"
        if not isinstance(self.value, str) or re.fullmatch(
            rf"{dimensions}x{dimensions}", self.value
        ) is None:
            raise ValueError("window_size deve conter dimensões válidas no formato LARGURAxALTURA.")


@dataclass(frozen=True, slots=True)
class DesktopSettingsSnapshot:
    agents: tuple[DesktopAgentRecord, ...]
    bindings: tuple[DesktopAgentBindingRecord, ...]
    issues: tuple[str, ...] = ()
    preferences: tuple[DesktopPreferenceRecord, ...] = ()
