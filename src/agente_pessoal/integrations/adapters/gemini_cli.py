"""Detecção e contratos seguros para a CLI oficial Google Gemini.

Este adaptador não inicia processos, lê credenciais da CLI, nem envia prompts.
"""

from enum import StrEnum
from shutil import which
from typing import Callable

from agente_pessoal.integrations.connections import (
    ConnectionStatus,
    ConnectionVerificationResult,
    ConnectionVerificationStatus,
    ProviderConnection,
)
from agente_pessoal.integrations.providers import (
    AuthenticationMethod,
    ProviderAvailability,
    ProviderCapability,
    ProviderDefinition,
    ProviderIntegrationType,
    ProviderRegistry,
)
from agente_pessoal.security import (
    AuthorizationContext,
    Permission,
    PermissionPolicy,
)

GEMINI_PROVIDER_ID = "google-gemini-cli"


class GeminiCliAvailability(StrEnum):
    INSTALLED = "installed"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


def register_gemini_provider(registry: ProviderRegistry) -> ProviderDefinition:
    """Registra o provedor oficialmente documentado, sem autenticação implícita."""
    return registry.register(
        ProviderDefinition(
            id=GEMINI_PROVIDER_ID,
            name="Google Gemini CLI",
            description="Gemini CLI oficial com login Google ou outros métodos suportados.",
            integration_type=ProviderIntegrationType.OFFICIAL_CLI_SDK,
            authentication_methods=(
                AuthenticationMethod.BROWSER_LOGIN,
                AuthenticationMethod.API_KEY,
                AuthenticationMethod.OFFICIAL_CLI_SDK,
            ),
            capabilities=(
                ProviderCapability.TEXT_GENERATION,
                ProviderCapability.CODE_GENERATION,
                ProviderCapability.TOOL_CALLING,
            ),
            availability=ProviderAvailability.UNKNOWN,
        )
    )


class GeminiCliAdapter:
    """Detecta a CLI pelo PATH, sem executar ou retornar o caminho do binário."""

    def __init__(self, executable_locator: Callable[[str], str | None] | None = None) -> None:
        self._executable_locator = executable_locator or which

    def availability(self) -> GeminiCliAvailability:
        try:
            executable = self._executable_locator("gemini")
        except Exception:
            return GeminiCliAvailability.UNKNOWN
        if isinstance(executable, str) and executable.strip():
            return GeminiCliAvailability.INSTALLED
        return GeminiCliAvailability.NOT_INSTALLED

    @staticmethod
    def login_guidance() -> str:
        """Instrução para o usuário concluir autenticação fora do aplicativo."""
        return (
            "Instale a Gemini CLI oficial e inicie `gemini` no terminal. "
            "No primeiro uso, escolha Sign in with Google e conclua o fluxo "
            "no navegador aberto pela própria CLI. Não forneça sua senha ao Agente Pessoal."
        )


class GeminiConnectionVerifier:
    """Verificador conservador: instalação é observável; login não é verificado."""

    def __init__(
        self,
        cli: GeminiCliAdapter,
        authorization: AuthorizationContext | None = None,
    ) -> None:
        self._cli = cli
        self._authorization = authorization

    def verify(
        self,
        connection: ProviderConnection,
        provider: ProviderDefinition,
    ) -> ConnectionVerificationResult:
        PermissionPolicy.require(Permission.WEB_ACCESS, self._authorization)
        if provider.id != GEMINI_PROVIDER_ID or connection.provider_id != GEMINI_PROVIDER_ID:
            return ConnectionVerificationResult(
                status=ConnectionStatus.ERROR,
                availability=ProviderAvailability.UNKNOWN,
                verification_status=ConnectionVerificationStatus.FAILED,
            )

        availability = {
            GeminiCliAvailability.INSTALLED: ProviderAvailability.AVAILABLE,
            GeminiCliAvailability.NOT_INSTALLED: ProviderAvailability.UNAVAILABLE,
            GeminiCliAvailability.UNKNOWN: ProviderAvailability.UNKNOWN,
        }[self._cli.availability()]
        return ConnectionVerificationResult(
            status=ConnectionStatus.CONNECTION_REQUIRED,
            availability=availability,
            capabilities=(),
            verification_status=ConnectionVerificationStatus.UNVERIFIED,
        )
