import unittest

from agente_pessoal.integrations.adapters.codex import CodexAuthService
from agente_pessoal.integrations.adapters.gemini_cli import GeminiCliAdapter
from agente_pessoal.multiagent import (
    AgentDefinition,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentExecutorRegistry,
    AgentRegistry,
    MaestroCoordinator,
)
from agente_pessoal.security import AuthorizationContext, Permission, PermissionDenied


class SimulatedExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        return AgentExecutionResult(
            request_id=request.id,
            agent_id=request.agent_id,
            status=AgentExecutionStatus.COMPLETED,
            output="fake response",
        )


class SupervisedExecutionAssessmentTests(unittest.TestCase):
    def test_provider_adapters_do_not_expose_real_task_execution(self):
        for adapter in (CodexAuthService, GeminiCliAdapter):
            with self.subTest(adapter=adapter.__name__):
                self.assertFalse(hasattr(adapter, "execute"))
                self.assertFalse(hasattr(adapter, "run_prompt"))

    def test_provider_adapters_are_not_registered_as_maestro_executors(self):
        registry = AgentExecutorRegistry()
        for adapter_id in ("openai-codex", "google-gemini-cli"):
            with self.subTest(adapter_id=adapter_id):
                with self.assertRaises(LookupError):
                    registry.get(adapter_id)

    def test_real_provider_path_stays_denied_without_agent_execute(self):
        agents = AgentRegistry()
        agents.register(
            AgentDefinition(
                id="codex-agent",
                name="Codex",
                description="Assessment only",
                capabilities=("text",),
                adapter_id="simulated-test-only",
            )
        )
        executors = AgentExecutorRegistry()
        simulated = SimulatedExecutor()
        executors.register("simulated-test-only", simulated)
        coordinator = MaestroCoordinator(agents, executors)
        request = AgentExecutionRequest(agent_id="codex-agent", input="hello")

        for authorization in (None, AuthorizationContext.from_permissions((Permission.WEB_ACCESS,))):
            with self.subTest(authorization=authorization):
                with self.assertRaises(PermissionDenied):
                    coordinator.execute(request, authorization)
        self.assertEqual(simulated.calls, [])


if __name__ == "__main__":
    unittest.main()
