"""Relatórios locais e controlados sobre integrações de provedores."""

from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata
from importlib.util import find_spec
import re
from typing import Callable

from agente_pessoal.integrations.adapters.codex import (
    CODEX_PROVIDER_ID,
    CodexAccountState,
    CodexAuthService,
    register_codex_provider,
)
from agente_pessoal.integrations.adapters.gemini_cli import (
    GEMINI_PROVIDER_ID,
    GeminiCliAdapter,
    GeminiCliAvailability,
    register_gemini_provider,
)
from agente_pessoal.integrations.providers import ProviderDefinition, ProviderRegistry
from agente_pessoal.security import (
    AuthorizationContext,
    Permission,
    PermissionDenied,
)


class DependencyStatus(StrEnum):
    INSTALLED = "installed"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class AuthenticationStatus(StrEnum):
    AUTHENTICATED = "authenticated"
    NOT_AUTHENTICATED = "not_authenticated"
    NOT_VERIFIED = "not_verified"
    NOT_CHECKED = "not_checked"
    PERMISSION_REQUIRED = "permission_required"
    ERROR = "error"


class OperationalStatus(StrEnum):
    READY = "ready"
    NOT_READY = "not_ready"
    NOT_IMPLEMENTED = "not_implemented"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DependencyDiagnostic:
    name: str
    status: DependencyStatus
    version: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionRequirement:
    permission: str
    reason: str
    required_for_current_check: bool


@dataclass(frozen=True, slots=True)
class ProviderDiagnostic:
    provider_id: str
    name: str
    registered: bool
    dependencies: tuple[DependencyDiagnostic, ...]
    authentication_methods: tuple[str, ...]
    authentication_status: AuthenticationStatus
    operational_status: OperationalStatus
    permissions: tuple[PermissionRequirement, ...]
    unavailable_features: tuple[str, ...]
    recommended_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntegrationDiagnosticReport:
    providers: tuple[ProviderDiagnostic, ...]


class IntegrationDiagnostics:
    """Monta relatório sem prompts, execução de processos ou leitura de tokens."""

    CODEX_SDK_SUPPORTED_PREFIX = (0, 163)

    def __init__(
        self,
        providers: ProviderRegistry,
        codex_auth: CodexAuthService,
        gemini_cli: GeminiCliAdapter,
        *,
        codex_version_lookup: Callable[[], str | None] | None = None,
        codex_runtime_version_lookup: Callable[[], str | None] | None = None,
        codex_runtime_probe: Callable[[], bool | None] | None = None,
    ) -> None:
        self._providers = providers
        self._codex_auth = codex_auth
        self._gemini_cli = gemini_cli
        self._codex_version_lookup = codex_version_lookup or self._default_codex_version
        self._codex_runtime_version_lookup = (
            codex_runtime_version_lookup or self._default_codex_runtime_version
        )
        self._codex_runtime_probe = codex_runtime_probe or self._default_codex_runtime_probe

    def diagnose(
        self,
        *,
        check_codex_account: bool = False,
        authorization: AuthorizationContext | None = None,
    ) -> IntegrationDiagnosticReport:
        """Retorna estado estrutural; só consulta conta Codex se solicitado."""
        known = ProviderRegistry()
        register_codex_provider(known)
        register_gemini_provider(known)
        registered = {provider.id: provider for provider in self._providers.list_providers()}
        definitions = {provider.id: provider for provider in known.list_providers()}
        definitions.update(
            (provider_id, provider)
            for provider_id, provider in registered.items()
            if provider_id not in definitions
        )

        codex_report = self._diagnose_codex(
            definitions[CODEX_PROVIDER_ID],
            registered=CODEX_PROVIDER_ID in registered,
            check_account=check_codex_account,
            authorization=authorization,
        )
        gemini_report = self._diagnose_gemini(
            definitions[GEMINI_PROVIDER_ID],
            registered=GEMINI_PROVIDER_ID in registered,
        )
        other_reports = tuple(
            self._diagnose_other(provider)
            for provider_id, provider in registered.items()
            if provider_id not in {CODEX_PROVIDER_ID, GEMINI_PROVIDER_ID}
        )
        return IntegrationDiagnosticReport(
            providers=(codex_report, gemini_report, *other_reports)
        )

    def _diagnose_codex(
        self,
        provider: ProviderDefinition,
        *,
        registered: bool,
        check_account: bool,
        authorization: AuthorizationContext | None,
    ) -> ProviderDiagnostic:
        version, version_probe_failed = self._lookup_codex_version()
        if version_probe_failed:
            sdk_status = DependencyStatus.UNKNOWN
        elif version is None:
            sdk_status = DependencyStatus.MISSING
        elif self._is_supported_codex_version(version):
            sdk_status = DependencyStatus.INSTALLED
        else:
            sdk_status = DependencyStatus.INCOMPATIBLE

        runtime_version, runtime_version_probe_failed = self._lookup_codex_runtime_version()
        runtime_available = self._probe_codex_runtime()
        if runtime_version_probe_failed or runtime_available is None:
            runtime_status = DependencyStatus.UNKNOWN
        elif not runtime_available or runtime_version is None:
            runtime_status = DependencyStatus.MISSING
        elif sdk_status is DependencyStatus.INSTALLED and runtime_version != version:
            runtime_status = DependencyStatus.INCOMPATIBLE
        else:
            runtime_status = DependencyStatus.INSTALLED
        dependencies = (
            DependencyDiagnostic("openai-codex", sdk_status, version),
            DependencyDiagnostic("openai-codex-cli-bin", runtime_status, runtime_version),
        )

        auth_status = AuthenticationStatus.NOT_CHECKED
        permission = PermissionRequirement(
            Permission.WEB_ACCESS.value,
            "Consulta explícita da conta Codex pelo SDK oficial.",
            check_account,
        )
        if check_account:
            if not registered:
                auth_status = AuthenticationStatus.NOT_CHECKED
            elif authorization is None or Permission.WEB_ACCESS not in authorization.granted:
                auth_status = AuthenticationStatus.PERMISSION_REQUIRED
            elif sdk_status is not DependencyStatus.INSTALLED or runtime_status is not DependencyStatus.INSTALLED:
                auth_status = AuthenticationStatus.NOT_CHECKED
            else:
                try:
                    if not self._codex_auth.is_available():
                        auth_status = AuthenticationStatus.NOT_CHECKED
                    else:
                        state = self._codex_auth.check_account(authorization).state
                        auth_status = {
                            CodexAccountState.AUTHENTICATED: AuthenticationStatus.AUTHENTICATED,
                            CodexAccountState.NOT_AUTHENTICATED: AuthenticationStatus.NOT_AUTHENTICATED,
                            CodexAccountState.ERROR: AuthenticationStatus.ERROR,
                        }[state]
                except PermissionDenied:
                    auth_status = AuthenticationStatus.PERMISSION_REQUIRED
                except Exception:
                    auth_status = AuthenticationStatus.ERROR

        actions: list[str] = []
        if not registered:
            actions.append("Registre explicitamente o provedor Codex na composição da aplicação.")
        if sdk_status is DependencyStatus.MISSING:
            actions.append("Instale as dependências do projeto com `py -m pip install -e .`.")
        elif sdk_status is DependencyStatus.INCOMPATIBLE:
            actions.append("Instale uma versão openai-codex compatível com a faixa declarada pelo projeto.")
        if runtime_status is DependencyStatus.MISSING:
            actions.append("Reinstale as dependências do projeto para obter o runtime Codex pareado.")
        elif runtime_status is DependencyStatus.INCOMPATIBLE:
            actions.append("Reinstale o runtime Codex na mesma versão estável do SDK openai-codex.")
        if check_account and auth_status is AuthenticationStatus.PERMISSION_REQUIRED:
            actions.append("Conceda web.access explicitamente na aplicação e repita a consulta opcional.")
        elif check_account and auth_status is AuthenticationStatus.NOT_AUTHENTICATED:
            actions.append("Inicie o login oficial Codex pelo navegador ou código de dispositivo.")
        elif not check_account and registered and sdk_status is DependencyStatus.INSTALLED:
            actions.append(
                "Use --verify-codex-account --allow-web-access para uma consulta Codex "
                "única e explicitamente autorizada."
            )
        if not actions:
            actions.append("A verificação de conta foi concluída; execução de tarefas continua indisponível.")

        methods = self._methods_for(provider)
        return ProviderDiagnostic(
            provider_id=provider.id,
            name=provider.name,
            registered=registered,
            dependencies=dependencies,
            authentication_methods=methods,
            authentication_status=auth_status,
            operational_status=OperationalStatus.NOT_IMPLEMENTED,
            permissions=(
                permission,
                PermissionRequirement(
                    Permission.AGENT_EXECUTE.value,
                    "Execução futura de agentes; não implementada nesta etapa.",
                    False,
                ),
            ),
            unavailable_features=(
                "Executor de tarefas Codex controlado pelo Maestro.",
                "Execução textual segura não habilitada nesta fundação.",
            ),
            recommended_actions=tuple(actions),
        )

    def _diagnose_gemini(
        self,
        provider: ProviderDefinition,
        *,
        registered: bool,
    ) -> ProviderDiagnostic:
        availability = self._gemini_cli.availability()
        dependency_status = {
            GeminiCliAvailability.INSTALLED: DependencyStatus.INSTALLED,
            GeminiCliAvailability.NOT_INSTALLED: DependencyStatus.MISSING,
            GeminiCliAvailability.UNKNOWN: DependencyStatus.UNKNOWN,
        }[availability]
        actions = []
        if not registered:
            actions.append("Registre explicitamente o provedor Gemini na composição da aplicação.")
        if availability is GeminiCliAvailability.NOT_INSTALLED:
            actions.append("Instale a CLI oficial pelo guia de instalação do Gemini CLI.")
        actions.append("Para autenticar, inicie `gemini` e conclua o login Google na própria CLI.")
        actions.append("A conexão permanece não verificada; o diagnóstico não lê credenciais nem executa prompts.")
        return ProviderDiagnostic(
            provider_id=provider.id,
            name=provider.name,
            registered=registered,
            dependencies=(DependencyDiagnostic("gemini-cli", dependency_status),),
            authentication_methods=self._methods_for(provider),
            authentication_status=AuthenticationStatus.NOT_VERIFIED,
            operational_status=OperationalStatus.NOT_IMPLEMENTED,
            permissions=(
                PermissionRequirement(
                    Permission.WEB_ACCESS.value,
                    "Chamadas externas futuras pelo provedor.",
                    False,
                ),
                PermissionRequirement(
                    Permission.AGENT_EXECUTE.value,
                    "Execução futura de agentes; não implementada nesta etapa.",
                    False,
                ),
            ),
            unavailable_features=(
                "Consulta confiável do estado da sessão Google.",
                "Executor Gemini integrado ao Maestro.",
            ),
            recommended_actions=tuple(actions),
        )

    @staticmethod
    def _diagnose_other(provider: ProviderDefinition) -> ProviderDiagnostic:
        return ProviderDiagnostic(
            provider_id=provider.id,
            name=provider.name,
            registered=True,
            dependencies=(),
            authentication_methods=tuple(item.value for item in provider.authentication_methods),
            authentication_status=AuthenticationStatus.NOT_VERIFIED,
            operational_status=OperationalStatus.UNKNOWN,
            permissions=(),
            unavailable_features=("Diagnóstico específico ainda não implementado.",),
            recommended_actions=("Consulte a documentação deste provedor.",),
        )

    @staticmethod
    def _methods_for(provider: ProviderDefinition) -> tuple[str, ...]:
        return tuple(item.value for item in provider.authentication_methods)

    def _lookup_codex_version(self) -> tuple[str | None, bool]:
        try:
            return self._codex_version_lookup(), False
        except Exception:
            return None, True

    def _probe_codex_runtime(self) -> bool | None:
        try:
            result = self._codex_runtime_probe()
            return result if isinstance(result, bool) else None
        except Exception:
            return None

    def _lookup_codex_runtime_version(self) -> tuple[str | None, bool]:
        try:
            return self._codex_runtime_version_lookup(), False
        except Exception:
            return None, True

    @staticmethod
    def _default_codex_version() -> str | None:
        try:
            return metadata.version("openai-codex")
        except metadata.PackageNotFoundError:
            return None

    @staticmethod
    def _default_codex_runtime_version() -> str | None:
        try:
            return metadata.version("openai-codex-cli-bin")
        except metadata.PackageNotFoundError:
            return None

    @staticmethod
    def _default_codex_runtime_probe() -> bool | None:
        try:
            return find_spec("codex_cli_bin") is not None
        except (ImportError, ValueError):
            return None

    @classmethod
    def _is_supported_codex_version(cls, version: str) -> bool:
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
        return bool(match and tuple(map(int, match.groups()[:2])) == cls.CODEX_SDK_SUPPORTED_PREFIX)
