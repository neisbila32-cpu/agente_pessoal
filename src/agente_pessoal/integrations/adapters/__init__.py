"""Adaptadores de provedores carregados por composição explícita."""

from agente_pessoal.integrations.adapters.codex import (
    CODEX_PROVIDER_ID,
    CodexAccountCheck,
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
from agente_pessoal.integrations.adapters.gemini_cli import (
    GEMINI_PROVIDER_ID,
    GeminiCliAdapter,
    GeminiCliAvailability,
    GeminiConnectionVerifier,
    register_gemini_provider,
)

__all__ = [
    "CODEX_PROVIDER_ID",
    "CodexAccountCheck",
    "CodexAccountState",
    "CodexAuthError",
    "CodexAuthService",
    "CodexConnectionVerifier",
    "CodexLoginMethod",
    "CodexLoginResult",
    "CodexLoginState",
    "CodexProviderUnavailableError",
    "GEMINI_PROVIDER_ID",
    "GeminiCliAdapter",
    "GeminiCliAvailability",
    "GeminiConnectionVerifier",
    "register_codex_provider",
    "register_gemini_provider",
]
