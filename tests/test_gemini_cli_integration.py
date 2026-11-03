from dataclasses import fields
import unittest

from agente_pessoal.integrations import (
    AgentConnectionBindingRegistry,
    AuthenticationMethod,
    ConnectionRegistry,
    ConnectionService,
    ConnectionStatus,
    ConnectionVerificationStatus,
    ConnectionVerifierRegistry,
    ProviderAvailability,
    ProviderConnection,
    ProviderRegistry,
)
from agente_pessoal.integrations.adapters import (
    CODEX_PROVIDER_ID,
    GEMINI_PROVIDER_ID,
    CodexAuthService,
    CodexConnectionVerifier,
    GeminiCliAdapter,
    GeminiCliAvailability,
    GeminiConnectionVerifier,
    register_codex_provider,
    register_gemini_provider,
)
from agente_pessoal.multiagent import AgentDefinition, AgentRegistry, MaestroCoordinator, MultiAgentWorkflow
from agente_pessoal.security import AuthorizationContext, Permission, PermissionDenied


AUTH = AuthorizationContext.from_permissions((Permission.WEB_ACCESS,))


class FakeCodexClient:
    def account(self):
        return type("AccountResponse", (), {"account": object()})()


class GeminiCliIntegrationTests(unittest.TestCase):
    def test_provider_registration_lists_documented_authentication_options(self):
        registry = ProviderRegistry()
        provider = register_gemini_provider(registry)

        self.assertEqual(provider.id, GEMINI_PROVIDER_ID)
        self.assertEqual(registry.list_providers(), (provider,))
        self.assertEqual(
            set(provider.authentication_methods),
            {
                AuthenticationMethod.BROWSER_LOGIN,
                AuthenticationMethod.API_KEY,
                AuthenticationMethod.OFFICIAL_CLI_SDK,
            },
        )
        self.assertEqual(provider.availability, ProviderAvailability.UNKNOWN)

    def test_cli_installation_detection_is_injected_and_sanitized(self):
        installed = GeminiCliAdapter(lambda name: r"C:\trusted\gemini.cmd")
        absent = GeminiCliAdapter(lambda name: None)

        self.assertEqual(installed.availability(), GeminiCliAvailability.INSTALLED)
        self.assertEqual(absent.availability(), GeminiCliAvailability.NOT_INSTALLED)

        def broken_locator(_name):
            raise RuntimeError("private/path/with-secret")

        self.assertEqual(
            GeminiCliAdapter(broken_locator).availability(), GeminiCliAvailability.UNKNOWN
        )

    def test_login_guidance_uses_the_official_cli_without_collecting_passwords(self):
        guidance = GeminiCliAdapter.login_guidance()

        self.assertIn("gemini", guidance)
        self.assertIn("Sign in with Google", guidance)
        self.assertIn("Não forneça sua senha", guidance)

    def test_installed_cli_does_not_mark_connection_authenticated_or_verified(self):
        providers = ProviderRegistry()
        provider = register_gemini_provider(providers)
        connections = ConnectionRegistry(providers)
        connection = ProviderConnection(provider.id, AuthenticationMethod.BROWSER_LOGIN)
        connections.register(connection)
        verifiers = ConnectionVerifierRegistry()
        verifiers.register(
            provider.id,
            GeminiConnectionVerifier(GeminiCliAdapter(lambda _: r"C:\bin\gemini.cmd"), AUTH),
        )

        result = ConnectionService(connections, verifiers).verify(connection.id)

        self.assertEqual(result.status, ConnectionStatus.CONNECTION_REQUIRED)
        self.assertEqual(result.availability, ProviderAvailability.AVAILABLE)
        self.assertEqual(result.verification_status, ConnectionVerificationStatus.UNVERIFIED)
        self.assertEqual(result.capabilities, ())

    def test_absent_or_uncheckable_cli_keeps_account_state_unknown(self):
        providers = ProviderRegistry()
        provider = register_gemini_provider(providers)
        connections = ConnectionRegistry(providers)
        verifiers = ConnectionVerifierRegistry()
        absent = ProviderConnection(provider.id, AuthenticationMethod.BROWSER_LOGIN)
        unknown = ProviderConnection(
            provider.id,
            AuthenticationMethod.OFFICIAL_CLI_SDK,
            id="gemini-unknown",
        )
        connections.register(absent)
        connections.register(unknown)
        verifiers.register(
            provider.id,
            GeminiConnectionVerifier(GeminiCliAdapter(lambda _: None), AUTH),
        )
        service = ConnectionService(connections, verifiers)

        absent_state = service.verify(absent.id)
        unknown_state = service.verify(unknown.id)

        self.assertEqual(absent_state.status, ConnectionStatus.CONNECTION_REQUIRED)
        self.assertEqual(absent_state.availability, ProviderAvailability.UNAVAILABLE)
        self.assertEqual(absent_state.verification_status, ConnectionVerificationStatus.UNVERIFIED)
        self.assertEqual(unknown_state.verification_status, ConnectionVerificationStatus.UNVERIFIED)

    def test_web_permission_is_required_before_verification(self):
        providers = ProviderRegistry()
        provider = register_gemini_provider(providers)
        connection = ProviderConnection(provider.id, AuthenticationMethod.BROWSER_LOGIN)
        calls = []
        verifier = GeminiConnectionVerifier(
            GeminiCliAdapter(lambda name: calls.append(name) or r"C:\bin\gemini.cmd")
        )

        with self.assertRaises(PermissionDenied):
            verifier.verify(connection, provider)
        self.assertEqual(calls, [])

    def test_verification_denial_is_sanitized(self):
        providers = ProviderRegistry()
        gemini = register_gemini_provider(providers)
        connections = ConnectionRegistry(providers)
        connection = ProviderConnection(gemini.id, AuthenticationMethod.BROWSER_LOGIN)
        connections.register(connection)
        verifiers = ConnectionVerifierRegistry()
        verifiers.register(
            gemini.id,
            GeminiConnectionVerifier(GeminiCliAdapter(lambda _: None)),
        )

        result = ConnectionService(connections, verifiers).verify(connection.id)

        self.assertEqual(result.status, ConnectionStatus.ERROR)
        self.assertEqual(result.verification_status, ConnectionVerificationStatus.FAILED)
        self.assertNotIn("PermissionDenied", repr(result))

    def test_codex_and_gemini_connections_are_independent(self):
        providers = ProviderRegistry()
        codex = register_codex_provider(providers)
        gemini = register_gemini_provider(providers)
        connections = ConnectionRegistry(providers)
        codex_connection = ProviderConnection(
            codex.id,
            AuthenticationMethod.BROWSER_LOGIN,
            id="codex-account",
        )
        gemini_connection = ProviderConnection(
            gemini.id,
            AuthenticationMethod.BROWSER_LOGIN,
            id="gemini-account",
        )
        connections.register(codex_connection)
        connections.register(gemini_connection)
        verifiers = ConnectionVerifierRegistry()
        codex_auth = CodexAuthService(
            FakeCodexClient,
            availability_probe=lambda: True,
        )
        verifiers.register(codex.id, CodexConnectionVerifier(codex_auth, AUTH))
        verifiers.register(
            gemini.id,
            GeminiConnectionVerifier(GeminiCliAdapter(lambda _: r"C:\bin\gemini.cmd"), AUTH),
        )

        service = ConnectionService(connections, verifiers)
        codex_result = service.verify(codex_connection.id)
        gemini_result = service.verify(gemini_connection.id)

        self.assertEqual(codex_result.status, ConnectionStatus.CONNECTED)
        self.assertEqual(codex_result.verification_status, ConnectionVerificationStatus.VERIFIED)
        self.assertEqual(gemini_result.status, ConnectionStatus.CONNECTION_REQUIRED)
        self.assertEqual(gemini_result.verification_status, ConnectionVerificationStatus.UNVERIFIED)
        self.assertNotEqual(codex_result.id, gemini_result.id)

    def test_agent_binding_and_multiagent_contracts_remain_unchanged(self):
        providers = ProviderRegistry()
        provider = register_gemini_provider(providers)
        connections = ConnectionRegistry(providers)
        connection = ProviderConnection(provider.id, AuthenticationMethod.BROWSER_LOGIN)
        connections.register(connection)
        agents = AgentRegistry()
        agents.register(
            AgentDefinition(
                id="gemini-agent",
                name="Gemini agent",
                description="Bound by ID only",
                capabilities=("text",),
                adapter_id="simulated",
            )
        )
        binding = AgentConnectionBindingRegistry(agents, connections).register(
            "gemini-agent", connection.id
        )

        self.assertEqual(binding.connection_id, connection.id)
        self.assertTrue(callable(MaestroCoordinator))
        self.assertTrue(callable(MultiAgentWorkflow))

    def test_connection_model_has_no_credential_fields_and_adapter_never_runs_cli(self):
        forbidden = {"credential", "password", "token", "secret", "api_key"}
        self.assertTrue({field.name for field in fields(ProviderConnection)}.isdisjoint(forbidden))
        self.assertFalse(hasattr(GeminiCliAdapter, "execute"))
        self.assertFalse(hasattr(GeminiCliAdapter, "run_prompt"))


if __name__ == "__main__":
    unittest.main()
