"""Configurações simples, sem dependência de bibliotecas externas."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Agente Pessoal"
    log_level: str = "INFO"
    database_path: str = "~/.agente_pessoal/agente_pessoal.sqlite3"
    ai_model: str | None = None
    ai_credential_env_var: str | None = None
    ai_timeout_seconds: float = 30.0
    ai_max_attempts: int = 2
    ai_max_request_chars: int = 10_000
    ai_max_response_chars: int = 65_536

    @classmethod
    def from_environment(cls) -> "Settings":
        """Carrega configurações não sensíveis do ambiente."""
        level = os.getenv("AGENTE_PESSOAL_LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            level = "INFO"
        database_path = os.getenv(
            "AGENTE_PESSOAL_DB_PATH", "~/.agente_pessoal/agente_pessoal.sqlite3"
        )
        model = os.getenv("AGENTE_PESSOAL_AI_MODEL") or None
        credential_env_var = os.getenv("AGENTE_PESSOAL_AI_CREDENTIAL_ENV") or None
        timeout_seconds = cls._bounded_float(
            os.getenv("AGENTE_PESSOAL_AI_TIMEOUT_SECONDS"), 30.0, 0.1, 120.0
        )
        max_attempts = cls._bounded_int(os.getenv("AGENTE_PESSOAL_AI_MAX_ATTEMPTS"), 2, 1, 3)
        max_request_chars = cls._bounded_int(
            os.getenv("AGENTE_PESSOAL_AI_MAX_REQUEST_CHARS"), 10_000, 1, 100_000
        )
        max_response_chars = cls._bounded_int(
            os.getenv("AGENTE_PESSOAL_AI_MAX_RESPONSE_CHARS"), 65_536, 1_024, 200_000
        )
        return cls(
            log_level=level,
            database_path=database_path,
            ai_model=model,
            ai_credential_env_var=credential_env_var,
            ai_timeout_seconds=timeout_seconds,
            ai_max_attempts=max_attempts,
            ai_max_request_chars=max_request_chars,
            ai_max_response_chars=max_response_chars,
        )

    @staticmethod
    def _bounded_int(raw: str | None, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(raw) if raw is not None else default
        except ValueError:
            return default
        return value if minimum <= value <= maximum else default

    @staticmethod
    def _bounded_float(raw: str | None, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(raw) if raw is not None else default
        except ValueError:
            return default
        return value if minimum <= value <= maximum else default
