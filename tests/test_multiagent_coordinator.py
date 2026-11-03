import unittest

from agente_pessoal.multiagent import (
    AgentDefinition,
    AgentDisabledError,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentExecutorRegistry,
    AgentNotFoundError,
    AgentRegistry,
    DuplicateExecutorError,
    ExecutorNotFoundError,
    MaestroCoordinator,
)
from agente_pessoal.security import AuthorizationContext, Permission, PermissionDenied


class SimulatedExecutor:
    def __init__(self, *, result=None, error=None):
        self.result = result
        self.error = error
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        if callable(self.result):
            return self.result(request)
        return self.result or AgentExecutionResult(
            request_id=request.id,
            agent_id=request.agent_id,
            status=AgentExecutionStatus.COMPLETED,
            output="resultado controlado",
        )


def make_agent(*, enabled=True, adapter_id="simulated"):
    return AgentDefinition(
        id="research",
        name="Pesquisa",
        description="Agente simulado",
        capabilities=("summarize",),
        adapter_id=adapter_id,
        enabled=enabled,
    )


def make_request():
    return AgentExecutionRequest(agent_id="research", input="Resuma o texto")


class MaestroCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.agents = AgentRegistry()
        self.agents.register(make_agent())
        self.executors = AgentExecutorRegistry()
        self.executor = SimulatedExecutor()
        self.executors.register("simulated", self.executor)
        self.maestro = MaestroCoordinator(self.agents, self.executors)
        self.authorization = AuthorizationContext.from_permissions([Permission.AGENT_EXECUTE])

    def test_authorized_enabled_agent_is_dispatched_and_result_is_correlated(self):
        request = make_request()

        result = self.maestro.execute(request, self.authorization)

        self.assertEqual(self.executor.requests, [request])
        self.assertEqual(result.request_id, request.id)
        self.assertEqual(result.agent_id, request.agent_id)
        self.assertEqual(result.status, AgentExecutionStatus.COMPLETED)
        self.assertEqual(result.output, "resultado controlado")

    def test_unknown_agent_is_rejected(self):
        request = AgentExecutionRequest(agent_id="missing", input="Executar")

        with self.assertRaises(AgentNotFoundError):
            self.maestro.execute(request, self.authorization)
        self.assertEqual(self.executor.requests, [])

    def test_disabled_agent_is_rejected(self):
        agents = AgentRegistry()
        agents.register(make_agent(enabled=False))
        maestro = MaestroCoordinator(agents, self.executors)

        with self.assertRaises(AgentDisabledError):
            maestro.execute(make_request(), self.authorization)
        self.assertEqual(self.executor.requests, [])

    def test_unregistered_adapter_is_rejected(self):
        agents = AgentRegistry()
        agents.register(make_agent(adapter_id="unconfigured"))
        maestro = MaestroCoordinator(agents, self.executors)

        with self.assertRaises(ExecutorNotFoundError):
            maestro.execute(make_request(), self.authorization)
        self.assertEqual(self.executor.requests, [])

    def test_execution_is_denied_by_default_before_executor_dispatch(self):
        for authorization in (None, AuthorizationContext()):
            with self.subTest(authorization=authorization):
                with self.assertRaises(PermissionDenied):
                    self.maestro.execute(make_request(), authorization)
        self.assertEqual(self.executor.requests, [])

    def test_executor_exception_is_converted_to_sanitized_failure_result(self):
        self.executor.error = RuntimeError("secret token and private response")
        request = make_request()

        result = self.maestro.execute(request, self.authorization)

        self.assertEqual(result.status, AgentExecutionStatus.FAILED)
        self.assertEqual(result.request_id, request.id)
        self.assertEqual(result.agent_id, request.agent_id)
        self.assertEqual(result.error, "A execução do agente falhou.")
        self.assertNotIn("secret", result.error)

    def test_executor_failure_result_is_sanitized_and_correlated(self):
        self.executor.result = lambda request: AgentExecutionResult(
            request_id=request.id,
            agent_id=request.agent_id,
            status=AgentExecutionStatus.FAILED,
            error="private credential",
        )
        request = make_request()

        result = self.maestro.execute(request, self.authorization)

        self.assertEqual(result.status, AgentExecutionStatus.FAILED)
        self.assertEqual(result.request_id, request.id)
        self.assertEqual(result.agent_id, request.agent_id)
        self.assertEqual(result.error, "A execução do agente falhou.")

    def test_mismatched_executor_result_is_not_returned(self):
        self.executor.result = AgentExecutionResult(
            request_id="different-request",
            agent_id="different-agent",
            status=AgentExecutionStatus.COMPLETED,
            output="wrong result",
        )
        request = make_request()

        result = self.maestro.execute(request, self.authorization)

        self.assertEqual(result.status, AgentExecutionStatus.FAILED)
        self.assertEqual(result.request_id, request.id)
        self.assertEqual(result.agent_id, request.agent_id)
        self.assertIsNone(result.output)

    def test_executor_registration_rejects_duplicate_adapter_ids(self):
        with self.assertRaises(DuplicateExecutorError):
            self.executors.register("simulated", SimulatedExecutor())


if __name__ == "__main__":
    unittest.main()
