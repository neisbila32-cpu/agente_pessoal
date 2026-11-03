"""Modelos e contratos em memória para conexões de provedores."""

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from agente_pessoal.integrations.providers import (
    AuthenticationMethod,
    ProviderAvailability,
    ProviderCapability,
    ProviderDefinition,
    ProviderRegistry,
)


def _required_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} deve ser um texto não vazio.")


class ConnectionStatus(StrEnum):
    NOT_CONNECTED = "not_connected"
    CONNECTION_REQUIRED = "connection_required"
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"


class ConnectionVerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProviderConnection:
    """Estado de conexão sem credenciais; ``account_id`` é referência opaca."""

    provider_id: str
    authentication_method: AuthenticationMethod
    id: str = field(default_factory=lambda: str(uuid4()))
    status: ConnectionStatus = ConnectionStatus.CONNECTION_REQUIRED
    account_id: str | None = None
    capabilities: tuple[ProviderCapability, ...] = ()
    availability: ProviderAvailability = ProviderAvailability.UNKNOWN
    verification_status: ConnectionVerificationStatus = (
        ConnectionVerificationStatus.UNVERIFIED
    )

    def __post_init__(self) -> None:
        for name in ("id", "provider_id"):
            _required_text(getattr(self, name), name)
        if not isinstance(self.authentication_method, AuthenticationMethod):
            raise ValueError("authentication_method inválido.")
        if not isinstance(self.status, ConnectionStatus):
            raise ValueError("status inválido.")
        if self.account_id is not None:
            _required_text(self.account_id, "account_id")
            if len(self.account_id) > 128 or any(ord(char) < 32 for char in self.account_id):
                raise ValueError("account_id deve ser uma referência opaca curta.")
        capabilities = tuple(self.capabilities)
        if any(not isinstance(item, ProviderCapability) for item in capabilities):
            raise ValueError("capabilities deve conter capacidades tipadas.")
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("capabilities contém itens duplicados.")
        if not isinstance(self.availability, ProviderAvailability):
            raise ValueError("availability inválida.")
        if not isinstance(self.verification_status, ConnectionVerificationStatus):
            raise ValueError("verification_status inválido.")
        object.__setattr__(self, "capabilities", capabilities)


class DuplicateConnectionError(Exception):
    """O identificador da conexão já está registrado."""


class ConnectionNotFoundError(LookupError):
    """O identificador da conexão não existe."""


class ConnectionRegistry:
    """Armazena conexões sem credenciais e valida sua associação ao provedor."""

    def __init__(self, providers: ProviderRegistry) -> None:
        self._providers = providers
        self._connections: dict[str, ProviderConnection] = {}

    def register(self, connection: ProviderConnection) -> ProviderConnection:
        if not isinstance(connection, ProviderConnection):
            raise TypeError("connection deve ser um ProviderConnection.")
        if connection.verification_status is not ConnectionVerificationStatus.UNVERIFIED:
            raise ValueError("Uma conexão registrada deve iniciar sem verificação.")
        provider = self._providers.get(connection.provider_id)
        self._validate_provider_compatibility(connection, provider)
        if connection.id in self._connections:
            raise DuplicateConnectionError(f"Conexão já registrada: {connection.id}")
        self._connections[connection.id] = connection
        return connection

    def get(self, connection_id: str) -> ProviderConnection:
        try:
            return self._connections[connection_id]
        except KeyError:
            raise ConnectionNotFoundError(connection_id) from None

    def list_connections(self) -> tuple[ProviderConnection, ...]:
        return tuple(self._connections.values())

    def provider_for(self, connection: ProviderConnection) -> ProviderDefinition:
        return self._providers.get(connection.provider_id)

    def _apply_verification(
        self,
        connection_id: str,
        *,
        status: ConnectionStatus,
        availability: ProviderAvailability,
        capabilities: tuple[ProviderCapability, ...],
        verification_status: ConnectionVerificationStatus,
    ) -> ProviderConnection:
        current = self.get(connection_id)
        updated = replace(
            current,
            status=status,
            availability=availability,
            capabilities=capabilities,
            verification_status=verification_status,
        )
        self._validate_provider_compatibility(updated, self.provider_for(updated))
        self._connections[connection_id] = updated
        return updated

    @staticmethod
    def _validate_provider_compatibility(
        connection: ProviderConnection,
        provider: ProviderDefinition,
    ) -> None:
        if connection.authentication_method not in provider.authentication_methods:
            raise ValueError("O método de autenticação não é suportado pelo provedor.")
        if not set(connection.capabilities).issubset(provider.capabilities):
            raise ValueError("A conexão declara capacidades não oferecidas pelo provedor.")


@dataclass(frozen=True, slots=True)
class ConnectionVerificationResult:
    """Resposta estruturada do verificador; não transporta tokens ou mensagens."""

    status: ConnectionStatus
    availability: ProviderAvailability
    capabilities: tuple[ProviderCapability, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ConnectionStatus):
            raise ValueError("status inválido.")
        if not isinstance(self.availability, ProviderAvailability):
            raise ValueError("availability inválida.")
        capabilities = tuple(self.capabilities)
        if any(not isinstance(item, ProviderCapability) for item in capabilities):
            raise ValueError("capabilities deve conter capacidades tipadas.")
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("capabilities contém itens duplicados.")
        object.__setattr__(self, "capabilities", capabilities)


class ConnectionVerifier(Protocol):
    """Porta para verificar uma conexão; implementations reais ficam para depois."""

    def verify(
        self,
        connection: ProviderConnection,
        provider: ProviderDefinition,
    ) -> ConnectionVerificationResult:
        ...


class ConnectionVerifierNotFoundError(LookupError):
    """Não há verificador injetado para o provedor."""


class ConnectionVerifierRegistry:
    """Associa explicitamente provedores a verificadores injetados."""

    def __init__(self) -> None:
        self._verifiers: dict[str, ConnectionVerifier] = {}

    def register(self, provider_id: str, verifier: ConnectionVerifier) -> None:
        _required_text(provider_id, "provider_id")
        if not callable(getattr(verifier, "verify", None)):
            raise TypeError("verifier deve implementar verify(connection, provider).")
        if provider_id in self._verifiers:
            raise ValueError(f"Verificador já registrado para: {provider_id}")
        self._verifiers[provider_id] = verifier

    def get(self, provider_id: str) -> ConnectionVerifier:
        try:
            return self._verifiers[provider_id]
        except KeyError:
            raise ConnectionVerifierNotFoundError(provider_id) from None


class ConnectionService:
    """Mantém estados registrados e resultados de verificação separados."""

    def __init__(
        self,
        connections: ConnectionRegistry,
        verifiers: ConnectionVerifierRegistry,
    ) -> None:
        self._connections = connections
        self._verifiers = verifiers

    def verify(self, connection_id: str) -> ProviderConnection:
        connection = self._connections.get(connection_id)
        provider = self._connections.provider_for(connection)
        verifier = self._verifiers.get(provider.id)
        try:
            result = verifier.verify(connection, provider)
            if not isinstance(result, ConnectionVerificationResult):
                raise TypeError("Resultado do verificador inválido.")
            self._connections._validate_provider_compatibility(
                replace(
                    connection,
                    capabilities=result.capabilities,
                    authentication_method=connection.authentication_method,
                ),
                provider,
            )
        except Exception:
            return self._connections._apply_verification(
                connection.id,
                status=ConnectionStatus.ERROR,
                availability=ProviderAvailability.UNKNOWN,
                capabilities=connection.capabilities,
                verification_status=ConnectionVerificationStatus.FAILED,
            )

        verification_status = (
            ConnectionVerificationStatus.FAILED
            if result.status is ConnectionStatus.ERROR
            else ConnectionVerificationStatus.VERIFIED
        )
        return self._connections._apply_verification(
            connection.id,
            status=result.status,
            availability=result.availability,
            capabilities=result.capabilities,
            verification_status=verification_status,
        )
