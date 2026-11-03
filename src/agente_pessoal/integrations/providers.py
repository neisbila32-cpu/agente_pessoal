"""Catálogo agnóstico de provedores de IA e seus contratos de autenticação."""

from dataclasses import dataclass, field
from enum import StrEnum


def _required_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} deve ser um texto não vazio.")


class ProviderIntegrationType(StrEnum):
    REMOTE_API = "remote_api"
    OFFICIAL_CLI_SDK = "official_cli_sdk"
    LOCAL_MODEL = "local_model"
    OTHER = "other"


class AuthenticationMethod(StrEnum):
    BROWSER_LOGIN = "browser_login"
    DEVICE_CODE_LOGIN = "device_code_login"
    OFFICIAL_CLI_SDK = "official_cli_sdk"
    API_KEY = "api_key"
    LOCAL_NO_AUTH = "local_no_auth"


class ProviderCapability(StrEnum):
    TEXT_GENERATION = "text_generation"
    CODE_GENERATION = "code_generation"
    IMAGE_INPUT = "image_input"
    TOOL_CALLING = "tool_calling"
    EMBEDDINGS = "embeddings"


class ProviderAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    """Descrição de um provedor; cadastrar não cria conta nem autentica."""

    id: str
    name: str
    description: str
    integration_type: ProviderIntegrationType
    authentication_methods: tuple[AuthenticationMethod, ...]
    capabilities: tuple[ProviderCapability, ...] = ()
    availability: ProviderAvailability = ProviderAvailability.UNKNOWN

    def __post_init__(self) -> None:
        for name in ("id", "name", "description"):
            _required_text(getattr(self, name), name)
        if not isinstance(self.integration_type, ProviderIntegrationType):
            raise ValueError("integration_type inválido.")
        methods = tuple(self.authentication_methods)
        capabilities = tuple(self.capabilities)
        if not methods or any(not isinstance(item, AuthenticationMethod) for item in methods):
            raise ValueError("authentication_methods deve conter métodos tipados.")
        if len(set(methods)) != len(methods):
            raise ValueError("authentication_methods contém itens duplicados.")
        if any(not isinstance(item, ProviderCapability) for item in capabilities):
            raise ValueError("capabilities deve conter capacidades tipadas.")
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("capabilities contém itens duplicados.")
        if not isinstance(self.availability, ProviderAvailability):
            raise ValueError("availability inválida.")

        local_methods = AuthenticationMethod.LOCAL_NO_AUTH in methods
        if self.integration_type is ProviderIntegrationType.LOCAL_MODEL:
            if methods != (AuthenticationMethod.LOCAL_NO_AUTH,):
                raise ValueError("Modelo local deve usar somente LOCAL_NO_AUTH.")
        elif local_methods:
            raise ValueError("LOCAL_NO_AUTH só é válido para modelo local.")

        object.__setattr__(self, "authentication_methods", methods)
        object.__setattr__(self, "capabilities", capabilities)


class ProviderRegistryError(Exception):
    """Erro base do catálogo de provedores."""


class DuplicateProviderError(ProviderRegistryError):
    """O identificador do provedor já está cadastrado."""


class ProviderNotFoundError(ProviderRegistryError, LookupError):
    """O identificador do provedor não existe."""


class ProviderRegistry:
    """Registro local em memória, sem integração ou autenticação real."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderDefinition] = {}

    def register(self, provider: ProviderDefinition) -> ProviderDefinition:
        if not isinstance(provider, ProviderDefinition):
            raise TypeError("provider deve ser um ProviderDefinition.")
        if provider.id in self._providers:
            raise DuplicateProviderError(f"Provedor já cadastrado: {provider.id}")
        self._providers[provider.id] = provider
        return provider

    def get(self, provider_id: str) -> ProviderDefinition:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise ProviderNotFoundError(provider_id) from None

    def list_providers(self) -> tuple[ProviderDefinition, ...]:
        return tuple(self._providers.values())
