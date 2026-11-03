"""Adaptadores de provedores carregados por composição explícita."""

from agente_pessoal.integrations.adapters.codex import (
    CODEX_PROVIDER_ID,
    CodexAccountState,
    CodexAuthError,
    CodexAuthService,
    CodexConnectionVerifier,
    CodexLoginMethod,
    CodexLoginResult,
    CodexLoginState,
    CodexProviderUnavailableError,
    register_codex_provider,
)

__all__ = [
    "CODEX_PROVIDER_ID",
    "CodexAccountState",
    "CodexAuthError",
    "CodexAuthService",
    "CodexConnectionVerifier",
    "CodexLoginMethod",
    "CodexLoginResult",
    "CodexLoginState",
    "CodexProviderUnavailableError",
    "register_codex_provider",
]
