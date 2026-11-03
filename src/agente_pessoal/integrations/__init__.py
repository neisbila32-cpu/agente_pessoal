"""Catálogo de provedores e modelos de conexões, sem autenticação real."""

from agente_pessoal.integrations.bindings import (
    AgentConnectionBinding,
    AgentConnectionBindingRegistry,
    BindingNotFoundError,
    DuplicateBindingError,
)
from agente_pessoal.integrations.connections import (
    ConnectionNotFoundError,
    ConnectionRegistry,
    ConnectionService,
    ConnectionStatus,
    ConnectionVerificationResult,
    ConnectionVerificationStatus,
    ConnectionVerifier,
    ConnectionVerifierNotFoundError,
    ConnectionVerifierRegistry,
    DuplicateConnectionError,
    ProviderConnection,
)
from agente_pessoal.integrations.providers import (
    AuthenticationMethod,
    DuplicateProviderError,
    ProviderAvailability,
    ProviderCapability,
    ProviderDefinition,
    ProviderIntegrationType,
    ProviderNotFoundError,
    ProviderRegistry,
    ProviderRegistryError,
)

__all__ = [
    "AgentConnectionBinding",
    "AgentConnectionBindingRegistry",
    "AuthenticationMethod",
    "BindingNotFoundError",
    "ConnectionNotFoundError",
    "ConnectionRegistry",
    "ConnectionService",
    "ConnectionStatus",
    "ConnectionVerificationResult",
    "ConnectionVerificationStatus",
    "ConnectionVerifier",
    "ConnectionVerifierNotFoundError",
    "ConnectionVerifierRegistry",
    "DuplicateBindingError",
    "DuplicateConnectionError",
    "DuplicateProviderError",
    "ProviderAvailability",
    "ProviderCapability",
    "ProviderConnection",
    "ProviderDefinition",
    "ProviderIntegrationType",
    "ProviderNotFoundError",
    "ProviderRegistry",
    "ProviderRegistryError",
]
