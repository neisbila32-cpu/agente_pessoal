"""Implementações de persistência."""

from agente_pessoal.persistence.sqlite import SQLiteStore
from agente_pessoal.persistence.records import (
    DesktopAgentBindingRecord,
    DesktopAgentRecord,
    DesktopPreferenceRecord,
    DesktopSettingsSnapshot,
)

__all__ = [
    "DesktopAgentBindingRecord",
    "DesktopAgentRecord",
    "DesktopPreferenceRecord",
    "DesktopSettingsSnapshot",
    "SQLiteStore",
]
