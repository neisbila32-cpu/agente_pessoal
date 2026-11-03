from dataclasses import fields
import unittest

from agente_pessoal.integrations import (
    AgentConnectionBindingRegistry,
    AuthenticationMethod,
    ConnectionNotFoundError,
    ConnectionRegistry,
    ConnectionService,
    ConnectionStatus,
    ConnectionVerificationResult,
    ConnectionVerificationStatus,
    ConnectionVerifierNotFoundError,
    ConnectionVerifierRegistry,
    DuplicateBindingError,
    DuplicateProviderError,
    ProviderAvailability,
    ProviderCapability,
    ProviderConnection,
    ProviderDefinition,
    ProviderIntegrationType,
    ProviderNotFoundError,
    ProviderRegistry,
)
from agente_pessoal.multiagent import (
    AgentDefinition,
    AgentExecutionRequest,
    AgentExecutor,
    AgentNotFoundError,
    AgentRegistry,
    MaestroCoordinator,
    MultiAgentWorkflow,
)
from agente_pessoal.security import Permission, PermissionDenied, PermissionPolicy


def make_provider(
    provider_id="provider-a",
    *,
    methods=(AuthenticationMethod.API_KEY,),
    integration_type=ProviderIntegrationType.REMOTE_API,
    capabilities=(ProviderCapability.TEXT_GENERATION,),
):
    return ProviderDefinition(
        id=provider_id,
        name=f"Provider {provider_id}",
        description="Provedor simulado para testes",
        integration_type=integration_type,
        authentication_methods=methods,
        capabilities=capabilities,
        availability=ProviderAvailability.AVAILABLE,
    )


class SimulatedConnectionVerifier:
    def __init__(self, result=None, error=None):
        self.result = result or ConnectionVerificationResult(
            status=ConnectionStatus.CONNECTED,
            availability=ProviderAvailability.AVAILABLE,
            capabilities=(ProviderCapability.TEXT_GENERATION,),
        )
        self.error = error
        self.calls = []

    def verify(self, connection, provider):
        self.calls.append((connection, provider))
        if self.error:
            raise self.error
        return self.result


class ProviderRegistryTests(unittest.TestCase):
    def test_register_query_and_list_providers(self):
        registry = ProviderRegistry()
        first = make_provider()
        second = make_provider("provider-b")

        registry.register(first)
        registry.register(second)

        self.assertIs(registry.get(first.id), first)
        self.assertEqual(registry.list_providers(), (first, second))

    def test_duplicate_provider_id_is_rejected(self):
        registry = ProviderRegistry()
        registry.register(make_provider())

        with self.assertRaises(DuplicateProviderError):
            registry.register(make_provider())

    def test_authentication_methods_are_typed_and_local_mode_has_no_remote_auth(self):
        with self.assertRaises(ValueError):
            make_provider(methods=("oauth",))
        with self.assertRaises(ValueError):
            make_provider(methods=(AuthenticationMethod.LOCAL_NO_AUTH,))
        local = make_provider(
            "local",
            methods=(AuthenticationMethod.LOCAL_NO_AUTH,),
            integration_type=ProviderIntegrationType.LOCAL_MODEL,
        )
        self.assertEqual(local.authentication_methods, (AuthenticationMethod.LOCAL_NO_AUTH,))

    def test_browser_login_is_only_an_explicitly_supported_option(self):
        browser_provider = make_provider(methods=(AuthenticationMethod.BROWSER_LOGIN,))
        registry = ProviderRegistry()
        registry.register(browser_provider)
        connections = ConnectionRegistry(registry)

        with self.assertRaises(ValueError):
            connections.register(
                ProviderConnection(
                    provider_id=browser_provider.id,
                    authentication_method=AuthenticationMethod.API_KEY,
                )
            )


class ConnectionRegistryTests(unittest.TestCase):
    def setUp(self):
        self.providers = ProviderRegistry()
        self.provider = make_provider()
        self.providers.register(self.provider)
        self.connections = ConnectionRegistry(self.providers)

    def test_connection_registration_is_not_a_verified_connection(self):
        connection = ProviderConnection(
            provider_id=self.provider.id,
            authentication_method=AuthenticationMethod.API_KEY,
            account_id="opaque-account-01",
        )

        self.connections.register(connection)

        stored = self.connections.get(connection.id)
        self.assertEqual(stored.status, ConnectionStatus.CONNECTION_REQUIRED)
        self.assertEqual(stored.verification_status, ConnectionVerificationStatus.UNVERIFIED)

    def test_registration_cannot_claim_that_a_connection_was_verified(self):
        with self.assertRaises(ValueError):
            self.connections.register(
                ProviderConnection(
                    provider_id=self.provider.id,
                    authentication_method=AuthenticationMethod.API_KEY,
                    status=ConnectionStatus.CONNECTED,
                    verification_status=ConnectionVerificationStatus.VERIFIED,
                )
            )

    def test_missing_provider_unsupported_method_and_missing_connection_are_rejected(self):
        with self.assertRaises(ProviderNotFoundError):
            self.connections.register(
                ProviderConnection("unknown", AuthenticationMethod.API_KEY)
            )
        with self.assertRaises(ValueError):
            self.connections.register(
                ProviderConnection(self.provider.id, AuthenticationMethod.BROWSER_LOGIN)
            )
        with self.assertRaises(ConnectionNotFoundError):
            self.connections.get("missing")

    def test_capabilities_must_be_offered_by_provider(self):
        with self.assertRaises(ValueError):
            self.connections.register(
                ProviderConnection(
                    self.provider.id,
                    AuthenticationMethod.API_KEY,
                    capabilities=(ProviderCapability.IMAGE_INPUT,),
                )
            )

    def test_injected_simulated_verifier_updates_status_without_credentials(self):
        connection = ProviderConnection(
            self.provider.id,
            AuthenticationMethod.API_KEY,
            account_id="opaque-account-01",
        )
        self.connections.register(connection)
        verifier = SimulatedConnectionVerifier()
        verifiers = ConnectionVerifierRegistry()
        verifiers.register(self.provider.id, verifier)

        updated = ConnectionService(self.connections, verifiers).verify(connection.id)

        self.assertEqual(updated.status, ConnectionStatus.CONNECTED)
        self.assertEqual(updated.verification_status, ConnectionVerificationStatus.VERIFIED)
        self.assertEqual(updated.capabilities, (ProviderCapability.TEXT_GENERATION,))
        self.assertEqual(verifier.calls[0][1].id, self.provider.id)

    def test_verifier_failure_does_not_expose_exception_details(self):
        connection = ProviderConnection(self.provider.id, AuthenticationMethod.API_KEY)
        self.connections.register(connection)
        verifiers = ConnectionVerifierRegistry()
        verifiers.register(
            self.provider.id,
            SimulatedConnectionVerifier(error=RuntimeError("secret-token-value")),
        )

        updated = ConnectionService(self.connections, verifiers).verify(connection.id)

        self.assertEqual(updated.status, ConnectionStatus.ERROR)
        self.assertEqual(updated.verification_status, ConnectionVerificationStatus.FAILED)
        self.assertNotIn("secret-token-value", repr(updated))

    def test_missing_verifier_does_not_claim_connection_is_verified(self):
        connection = ProviderConnection(self.provider.id, AuthenticationMethod.API_KEY)
        self.connections.register(connection)

        with self.assertRaises(ConnectionVerifierNotFoundError):
            ConnectionService(self.connections, ConnectionVerifierRegistry()).verify(connection.id)
        self.assertEqual(
            self.connections.get(connection.id).verification_status,
            ConnectionVerificationStatus.UNVERIFIED,
        )

    def test_provider_verification_isolation(self):
        second_provider = make_provider(
            "provider-b",
            methods=(AuthenticationMethod.OFFICIAL_CLI_SDK,),
            integration_type=ProviderIntegrationType.OFFICIAL_CLI_SDK,
            capabilities=(ProviderCapability.CODE_GENERATION,),
        )
        self.providers.register(second_provider)
        first_connection = ProviderConnection(self.provider.id, AuthenticationMethod.API_KEY)
        second_connection = ProviderConnection(
            second_provider.id, AuthenticationMethod.OFFICIAL_CLI_SDK
        )
        self.connections.register(first_connection)
        self.connections.register(second_connection)
        verifiers = ConnectionVerifierRegistry()
        verifiers.register(self.provider.id, SimulatedConnectionVerifier())
        second_verifier = SimulatedConnectionVerifier(
            ConnectionVerificationResult(
                status=ConnectionStatus.NOT_CONNECTED,
                availability=ProviderAvailability.UNAVAILABLE,
                capabilities=(),
            )
        )
        verifiers.register(second_provider.id, second_verifier)

        service = ConnectionService(self.connections, verifiers)
        first_result = service.verify(first_connection.id)
        second_result = service.verify(second_connection.id)

        self.assertEqual(first_result.status, ConnectionStatus.CONNECTED)
        self.assertEqual(second_result.status, ConnectionStatus.NOT_CONNECTED)
        self.assertEqual(first_result.capabilities, (ProviderCapability.TEXT_GENERATION,))
        self.assertEqual(second_result.capabilities, ())

    def test_models_do_not_define_credential_fields(self):
        forbidden_names = {"credential", "password", "token", "secret", "api_key"}
        field_names = {item.name for item in fields(ProviderConnection)}
        self.assertTrue(field_names.isdisjoint(forbidden_names))


class AgentConnectionBindingTests(unittest.TestCase):
    def setUp(self):
        self.providers = ProviderRegistry()
        self.providers.register(make_provider())
        self.connections = ConnectionRegistry(self.providers)
        self.connection = ProviderConnection("provider-a", AuthenticationMethod.API_KEY)
        self.connections.register(self.connection)
        self.agents = AgentRegistry()
        self.agents.register(
            AgentDefinition(
                id="agent-a",
                name="Agent A",
                description="Agente de teste",
                capabilities=("text",),
                adapter_id="simulated-agent",
            )
        )
        self.bindings = AgentConnectionBindingRegistry(self.agents, self.connections)

    def test_associate_agent_with_connection_without_granting_permissions(self):
        binding = self.bindings.register("agent-a", self.connection.id)

        self.assertEqual(self.bindings.get(binding.id), binding)
        self.assertEqual(self.bindings.list_bindings("agent-a"), (binding,))
        with self.assertRaises(PermissionDenied):
            PermissionPolicy.require(Permission.AGENT_EXECUTE)

    def test_missing_agent_or_connection_and_duplicate_binding_are_rejected(self):
        with self.assertRaises(AgentNotFoundError):
            self.bindings.register("missing-agent", self.connection.id)
        with self.assertRaises(ConnectionNotFoundError):
            self.bindings.register("agent-a", "missing-connection")
        self.bindings.register("agent-a", self.connection.id)
        with self.assertRaises(DuplicateBindingError):
            self.bindings.register("agent-a", self.connection.id)

    def test_existing_multiagent_contracts_remain_importable(self):
        self.assertTrue(callable(MaestroCoordinator))
        self.assertTrue(callable(MultiAgentWorkflow))
        self.assertTrue(callable(AgentExecutionRequest))
        self.assertTrue(callable(AgentExecutor))


if __name__ == "__main__":
    unittest.main()
