"""Configurações simples, sem dependência de bibliotecas externas."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Agente Pessoal"
    log_level: str = "INFO"

    @classmethod
    def from_environment(cls) -> "Settings":
        """Carrega configurações não sensíveis do ambiente."""
        level = os.getenv("AGENTE_PESSOAL_LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            level = "INFO"
        return cls(log_level=level)
