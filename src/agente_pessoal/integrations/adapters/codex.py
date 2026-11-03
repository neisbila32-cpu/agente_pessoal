"""Integração explícita com login e consulta de conta do SDK oficial Codex.

O módulo não carrega o SDK nem inicia runtime durante importação. Operações
remotas exigem ``web.access`` e clientes/handles permanecem apenas em memória.
"""

from dataclasses import dataclass
from enum import StrEnum
from importlib.util import find_spec
from typing import Callable
from uuid import uuid4

from agente_pessoal.integrations.connections import (
    ConnectionStatus,
    ConnectionVerificationResult,
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

CODEX_PROVIDER_ID = "openai-codex"


class CodexLoginMethod(StrEnum):
    BROWSER = "browser"
    DEVICE_CODE = "device_code"


class CodexLoginState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class CodexAccountState(StrEnum):
    AUTHENTICATED = "authenticated"
    NOT_AUTHENTICATED = "not_authenticated"
    ERROR = "error"


class CodexAuthError(RuntimeError):
    """Erro público seguro da integração de autenticação Codex."""


class CodexProviderUnavailableError(CodexAuthError):
    """SDK oficial ou runtime Codex não está disponível."""


@dataclass(frozen=True, slots=True)
class CodexLoginResult:
    """Informações não secretas necessárias para concluir um login explícito."""

    session_id: str
    state: CodexLoginState
    verification_url: str | None = None
    user_code: str | None = None


@dataclass(frozen=True, slots=True)
class CodexAccountCheck:
    """Estado sanitizado da conta; não inclui identidade, tokens nem erros brutos."""

    state: CodexAccountState


@dataclass(slots=True)
class _PendingLogin:
    client: object
    handle: object


def register_codex_provider(registry: ProviderRegistry) -> ProviderDefinition:
    """Registra o provedor sem autenticar, importar SDK ou criar conexões."""
    return registry.register(
        ProviderDefinition(
            id=CODEX_PROVIDER_ID,
            name="OpenAI Codex",
            description="Codex autenticado por conta ChatGPT via SDK oficial.",
            integration_type=ProviderIntegrationType.OFFICIAL_CLI_SDK,
            authentication_methods=(
                AuthenticationMethod.BROWSER_LOGIN,
                AuthenticationMethod.DEVICE_CODE_LOGIN,
            ),
            capabilities=(
                ProviderCapability.TEXT_GENERATION,
                ProviderCapability.CODE_GENERATION,
            ),
            availability=ProviderAvailability.UNKNOWN,
        )
    )


class CodexAuthService:
    """Operações oficiais de login/conta com dependências lazy e injetáveis."""

    def __init__(
        self,
        client_factory: Callable[[], object] | None = None,
        *,
        availability_probe: Callable[[], bool] | None = None,
    ) -> None:
        self._client_factory = client_factory or self._default_client_factory
        self._availability_probe = availability_probe or self._default_availability_probe
        self._pending: dict[str, _PendingLogin] = {}

    def is_available(self) -> bool:
        """Verifica disponibilidade de SDK/runtime sem instanciar o runtime."""
        try:
            return bool(self._availability_probe())
        except Exception:
            return False

    def start_login(
        self,
        method: CodexLoginMethod,
        authorization: AuthorizationContext | None = None,
    ) -> CodexLoginResult:
        PermissionPolicy.require(Permission.WEB_ACCESS, authorization)
        if not isinstance(method, CodexLoginMethod):
            raise ValueError("Método de login inválido.")
        client = self._new_client()
        try:
            if method is CodexLoginMethod.BROWSER:
                handle = client.login_chatgpt()
                url = getattr(handle, "auth_url", None)
                code = None
            else:
                handle = client.login_chatgpt_device_code()
                url = getattr(handle, "verification_url", None)
                code = getattr(handle, "user_code", None)
            if not isinstance(url, str) or not url.startswith("https://"):
                raise CodexAuthError("O SDK não retornou um endereço de autenticação válido.")
            session_id = str(uuid4())
            self._pending[session_id] = _PendingLogin(client=client, handle=handle)
            return CodexLoginResult(
                session_id=session_id,
                state=CodexLoginState.PENDING,
                verification_url=url,
                user_code=code if isinstance(code, str) else None,
            )
        except CodexAuthError:
            self._close(client)
            raise
        except Exception:
            self._close(client)
            raise CodexAuthError("Não foi possível iniciar o login Codex.") from None

    def finish_login(
        self,
        session_id: str,
        authorization: AuthorizationContext | None = None,
    ) -> CodexLoginResult:
        PermissionPolicy.require(Permission.WEB_ACCESS, authorization)
        pending = self._get_pending(session_id)
        try:
            notification = pending.handle.wait()
            success = bool(getattr(notification, "success", False))
            state = CodexLoginState.COMPLETED if success else CodexLoginState.FAILED
        except Exception:
            state = CodexLoginState.FAILED
        finally:
            self._pending.pop(session_id, None)
            self._close(pending.client)
        return CodexLoginResult(session_id=session_id, state=state)

    def cancel_login(
        self,
        session_id: str,
        authorization: AuthorizationContext | None = None,
    ) -> CodexLoginResult:
        PermissionPolicy.require(Permission.WEB_ACCESS, authorization)
        pending = self._get_pending(session_id)
        try:
            pending.handle.cancel()
        except Exception:
            pass
        finally:
            self._pending.pop(session_id, None)
            self._close(pending.client)
        return CodexLoginResult(session_id=session_id, state=CodexLoginState.CANCELLED)

    def check_account(
        self,
        authorization: AuthorizationContext | None = None,
    ) -> CodexAccountCheck:
        PermissionPolicy.require(Permission.WEB_ACCESS, authorization)
        client = self._new_client()
        try:
            response = client.account()
            return CodexAccountCheck(
                CodexAccountState.AUTHENTICATED
                if getattr(response, "account", None) is not None
                else CodexAccountState.NOT_AUTHENTICATED
            )
        except Exception:
            return CodexAccountCheck(CodexAccountState.ERROR)
        finally:
            self._close(client)

    def _new_client(self) -> object:
        if not self.is_available():
            raise CodexProviderUnavailableError("SDK/runtime Codex indisponível.")
        try:
            return self._client_factory()
        except CodexAuthError:
            raise
        except Exception:
            raise CodexProviderUnavailableError("SDK/runtime Codex indisponível.") from None

    def _get_pending(self, session_id: str) -> _PendingLogin:
        if not isinstance(session_id, str) or session_id not in self._pending:
            raise CodexAuthError("Sessão de login inexistente ou encerrada.")
        return self._pending[session_id]

    @staticmethod
    def _close(client: object) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    @staticmethod
    def _default_availability_probe() -> bool:
        try:
            return find_spec("openai_codex") is not None and find_spec("codex_cli_bin") is not None
        except (ImportError, ValueError):
            return False

    @staticmethod
    def _default_client_factory() -> object:
        try:
            from openai_codex import Codex
        except Exception:
            raise CodexProviderUnavailableError("SDK/runtime Codex indisponível.") from None
        return Codex()


class CodexConnectionVerifier:
    """Implementa a porta M4.1 usando confirmação positiva do SDK."""

    def __init__(
        self,
        auth_service: CodexAuthService,
        authorization: AuthorizationContext | None = None,
    ) -> None:
        self._auth = auth_service
        self._authorization = authorization

    def verify(
        self,
        connection: ProviderConnection,
        provider: ProviderDefinition,
    ) -> ConnectionVerificationResult:
        if provider.id != CODEX_PROVIDER_ID or connection.provider_id != CODEX_PROVIDER_ID:
            return ConnectionVerificationResult(
                ConnectionStatus.ERROR,
                ProviderAvailability.UNKNOWN,
            )
        try:
            state = self._auth.check_account(self._authorization).state
        except Exception:
            return ConnectionVerificationResult(ConnectionStatus.ERROR, ProviderAvailability.UNKNOWN)
        if state is CodexAccountState.AUTHENTICATED:
            return ConnectionVerificationResult(
                ConnectionStatus.CONNECTED,
                ProviderAvailability.AVAILABLE,
                provider.capabilities,
            )
        if state is CodexAccountState.NOT_AUTHENTICATED:
            return ConnectionVerificationResult(
                ConnectionStatus.CONNECTION_REQUIRED,
                ProviderAvailability.AVAILABLE,
            )
        return ConnectionVerificationResult(ConnectionStatus.ERROR, ProviderAvailability.UNKNOWN)
