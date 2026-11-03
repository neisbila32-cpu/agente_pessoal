from types import SimpleNamespace
import unittest

from agente_pessoal.desktop import DesktopApplicationServices, DesktopController, DesktopPage
from agente_pessoal.integrations import (
    AgentConnectionBindingRegistry,
    ConnectionRegistry,
    ProviderRegistry,
)
from agente_pessoal.integrations.adapters.codex import (
    CODEX_PROVIDER_ID,
    CodexAccountState,
    CodexAuthService,
    CodexLoginMethod,
    CodexLoginState,
    register_codex_provider,
)
from agente_pessoal.integrations.adapters.gemini_cli import (
    GeminiCliAdapter,
    register_gemini_provider,
)
from agente_pessoal.integrations.diagnostics import (
    AuthenticationStatus,
    IntegrationDiagnostics,
)
from agente_pessoal.multiagent import AgentRegistry, AgentTaskStatus, MultiAgentStatus
from agente_pessoal.security import PermissionDenied


class FakeLoginHandle:
    auth_url = "https://auth.openai.com/authorize"
    verification_url = "https://auth.openai.com/device"
    user_code = "ABCD-EFGH"

    def __init__(self, *, success=True):
        self.success = success
        self.cancelled = False

    def wait(self):
        return SimpleNamespace(success=self.success)

    def cancel(self):
        self.cancelled = True


class FakeCodexClient:
    def __init__(self, *, authenticated=True):
        self.authenticated = authenticated
        self.handle = FakeLoginHandle()
        self.closed = False

    def login_chatgpt(self):
        return self.handle

    def login_chatgpt_device_code(self):
        return self.handle

    def account(self):
        return SimpleNamespace(account=object() if self.authenticated else None)

    def close(self):
        self.closed = True


def make_controller(*, authenticated=True, include_demo_agents=True):
    providers = ProviderRegistry()
    register_codex_provider(providers)
    register_gemini_provider(providers)
    agents = AgentRegistry()
    connections = ConnectionRegistry(providers)
    bindings = AgentConnectionBindingRegistry(agents, connections)
    clients = []

    def client_factory():
        client = FakeCodexClient(authenticated=authenticated)
        clients.append(client)
        return client

    codex_auth = CodexAuthService(client_factory, availability_probe=lambda: True)
    gemini_cli = GeminiCliAdapter(lambda _name: None)
    diagnostics = IntegrationDiagnostics(
        providers,
        codex_auth,
        gemini_cli,
        codex_version_lookup=lambda: "0.163.0",
        codex_runtime_version_lookup=lambda: "0.163.0",
        codex_runtime_probe=lambda: True,
    )
    services = DesktopApplicationServices(
        provider_registry=providers,
        agent_registry=agents,
        connection_registry=connections,
        binding_registry=bindings,
        codex_auth=codex_auth,
        gemini_cli=gemini_cli,
        diagnostics=diagnostics,
        include_demo_agents=include_demo_agents,
    )
    return DesktopController(services), clients


class DesktopInterfaceTests(unittest.TestCase):
    def test_navigation_covers_all_requested_pages(self):
        controller, _ = make_controller()
        self.assertEqual(controller.current_page, DesktopPage.HOME)
        self.assertEqual(
            set(controller.PAGES),
            {
                DesktopPage.HOME,
                DesktopPage.INTEGRATIONS,
                DesktopPage.AGENTS,
                DesktopPage.MAESTRO,
                DesktopPage.DIAGNOSTICS,
            },
        )
        self.assertEqual(controller.navigate("agents"), DesktopPage.AGENTS)
        with self.assertRaises(ValueError):
            controller.navigate("unknown")

    def test_tk_presentation_can_be_imported_without_opening_a_window(self):
        from agente_pessoal.desktop.app import DesktopWindow

        self.assertTrue(callable(DesktopWindow))

    def test_initial_provider_states_are_unverified_and_not_operational(self):
        controller, clients = make_controller()

        rows = {row.provider_id: row for row in controller.integration_statuses()}

        self.assertEqual(rows[CODEX_PROVIDER_ID].authentication, "Não verificada")
        self.assertEqual(rows["google-gemini-cli"].authentication, "Não verificada")
        self.assertEqual(rows[CODEX_PROVIDER_ID].installation, "Instalada")
        self.assertEqual(rows["google-gemini-cli"].installation, "Ausente")
        self.assertIn("execução real desativada", rows[CODEX_PROVIDER_ID].operation)
        self.assertEqual(clients, [])

    def test_remote_codex_operations_require_one_run_explicit_confirmation(self):
        controller, clients = make_controller()

        with self.assertRaises(PermissionError):
            controller.start_codex_login(CodexLoginMethod.BROWSER, confirmed=False)
        with self.assertRaises(PermissionError):
            controller.verify_codex_account(confirmed=False)
        self.assertEqual(clients, [])

        started = controller.start_codex_login(CodexLoginMethod.BROWSER, confirmed=True)
        self.assertEqual(started.state, CodexLoginState.PENDING)
        self.assertTrue(started.verification_url.startswith("https://"))
        self.assertEqual(started.user_code, None)
        self.assertEqual(len(clients), 1)

        finished = controller.finish_codex_login()
        self.assertEqual(finished.account_state, CodexAccountState.AUTHENTICATED)
        self.assertTrue(clients[-1].closed)
        row = next(row for row in controller.integration_statuses() if row.provider_id == CODEX_PROVIDER_ID)
        self.assertEqual(row.authentication, "Autenticada (verificada)")

    def test_device_code_flow_and_cancel_use_authorized_session(self):
        controller, clients = make_controller()
        started = controller.start_codex_login(CodexLoginMethod.DEVICE_CODE, confirmed=True)
        self.assertEqual(started.user_code, "ABCD-EFGH")
        self.assertTrue(started.verification_url.startswith("https://"))

        cancelled = controller.cancel_codex_login()

        self.assertEqual(cancelled.state, CodexLoginState.CANCELLED)
        self.assertTrue(clients[-1].handle.cancelled)
        self.assertTrue(clients[-1].closed)
        with self.assertRaises(ValueError):
            controller.finish_codex_login()

    def test_codex_not_authenticated_state_is_verified_without_exposing_identity(self):
        controller, _ = make_controller(authenticated=False)
        state = controller.verify_codex_account(confirmed=True)
        self.assertEqual(state, CodexAccountState.NOT_AUTHENTICATED)
        row = next(row for row in controller.integration_statuses() if row.provider_id == CODEX_PROVIDER_ID)
        self.assertEqual(row.authentication, "Não autenticada (verificada)")
        self.assertNotIn("@", row.guidance)

    def test_agent_registration_state_and_logical_provider_binding(self):
        controller, _ = make_controller(include_demo_agents=False)
        agent = controller.add_agent(
            agent_id="assistente-revisao",
            name="Revisão",
            description="Revisa textos fornecidos pelo usuário.",
            capabilities_text="texto, revisão",
            provider_id="google-gemini-cli",
        )
        self.assertTrue(agent.enabled)
        self.assertEqual(agent.capabilities, ("texto", "revisão"))
        binding = controller.services.bindings_for(agent.id)
        self.assertEqual(len(binding), 1)
        self.assertEqual(binding[0].connection_id, "desktop-google-gemini-cli")
        self.assertEqual(controller.services.list_connections()[1].status.value, "connection_required")
        with self.assertRaises(LookupError):
            controller.services.executors.get("provider:google-gemini-cli")

        disabled = controller.set_agent_enabled(agent.id, False)
        self.assertFalse(disabled.enabled)
        enabled = controller.set_agent_enabled(agent.id, True)
        self.assertTrue(enabled.enabled)
        with self.assertRaises(Exception):
            controller.bind_agent("missing-agent", "openai-codex")
        self.assertFalse(hasattr(controller.services, "permission_manager"))

    def test_demo_requires_confirmation_and_only_returns_simulated_results(self):
        controller, clients = make_controller()

        with self.assertRaises(PermissionError):
            controller.run_demo("tema", confirmed=False)

        result = controller.run_demo("tema", confirmed=True)

        self.assertEqual(result.status, MultiAgentStatus.COMPLETED)
        self.assertEqual(len(result.task_results), 3)
        self.assertTrue(all(item.status is AgentTaskStatus.COMPLETED for item in result.task_results))
        self.assertTrue(all(item.output.startswith("[SIMULAÇÃO") for item in result.task_results))
        self.assertIn("1 etapa(s) anterior(es)", result.task_results[1].output)
        self.assertEqual(clients, [])

    def test_ui_service_construction_starts_no_login_or_network(self):
        controller, clients = make_controller()
        self.assertEqual(clients, [])
        self.assertEqual(controller.services.list_connections()[0].verification_status.value, "unverified")
        self.assertEqual(controller.services.diagnostics.diagnose().providers[0].authentication_status, AuthenticationStatus.NOT_CHECKED)
        self.assertEqual(clients, [])


if __name__ == "__main__":
    unittest.main()
