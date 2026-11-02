import json
import os
import unittest
from unittest.mock import patch

from agente_pessoal.ai import AIPlanner, ModelRequest, ModelResponse
from agente_pessoal.ai.errors import (
    ModelCommunicationError,
    ModelConfigurationError,
    ModelResponseError,
    ModelUnavailableError,
    PlanValidationError,
)
from agente_pessoal.config import Settings
from agente_pessoal.core import (
    RequestInterpretation,
    TaskOrchestrator,
    TaskStatus,
    UserRequest,
)
from agente_pessoal.core.executor import ToolExecutor
from agente_pessoal.core.task_manager import TaskManager
from agente_pessoal.persistence import SQLiteStore
from agente_pessoal.security import AuthorizationContext, Permission
from agente_pessoal.tools import ToolDescription


def response_payload(*, tool_name="controlled", steps=None, clarification=False):
    if steps is None:
        steps = [
            {
                "description": "Executar ação controlada",
                "tool_name": tool_name,
                "arguments": {"value": "ok"},
            }
        ]
    return json.dumps(
        {
            "interpretation": {
                "objective": "Concluir a solicitação",
                "intent": "ação controlada",
                "required_information": ["destino"],
                "limitations": ["somente ferramenta disponível"],
                "ambiguities": ["qual destino?"] if clarification else [],
                "requires_clarification": clarification,
            },
            "steps": steps,
        }
    )


class ControlledProvider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request):
        self.requests.append(request)
        next_response = self.responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return ModelResponse(next_response)


class ControlledTool:
    name = "controlled"
    required_permission = Permission.FILE_READ

    def __init__(self):
        self.calls = []

    def describe(self):
        return "Ação inofensiva controlada usada somente nos testes."

    def execute(self, arguments):
        self.calls.append(arguments)
        return {"done": True}


class AIPlannerTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            ai_model="model-test",
            ai_credential_env_var="AGENTE_TEST_KEY",
            ai_max_attempts=2,
        )
        self.catalog = [ToolDescription("controlled", "Ação de teste")]

    def test_interprets_request_and_returns_structured_plan(self):
        provider = ControlledProvider(response_payload())
        planner = AIPlanner(provider, self.settings, self.catalog)

        plan = planner.plan(UserRequest("Faça a ação controlada"))

        self.assertEqual(plan.interpretation.objective, "Concluir a solicitação")
        self.assertEqual(plan.interpretation.intent, "ação controlada")
        self.assertEqual(plan.interpretation.required_information, ("destino",))
        self.assertEqual(plan.steps[0].tool_name, "controlled")
        self.assertEqual(plan.steps[0].arguments, {"value": "ok"})
        request = provider.requests[0]
        self.assertEqual(request.model, "model-test")
        self.assertEqual(request.credential_env_var, "AGENTE_TEST_KEY")
        self.assertNotIn("credential", request.prompt.lower())
        with patch.dict(os.environ, {"AGENTE_TEST_KEY": "test-secret-value"}, clear=True):
            self.assertEqual(request.credential_from_environment(), "test-secret-value")
        self.assertNotIn("test-secret-value", repr(request))

    def test_model_must_request_clarification_without_executable_steps(self):
        provider = ControlledProvider(response_payload(steps=[], clarification=True))
        planner = AIPlanner(provider, self.settings, self.catalog)

        plan = planner.plan(UserRequest("Faça aquilo"))

        self.assertTrue(plan.interpretation.requires_clarification)
        self.assertEqual(plan.steps, ())

    def test_invalid_or_untrusted_plan_shapes_are_rejected(self):
        extra_permission = json.loads(response_payload())
        extra_permission["steps"][0]["permission"] = "command.execute"
        invalid_unknown_tool = response_payload(tool_name="not-registered")
        invalid_clarification = response_payload(clarification=True)
        provider = ControlledProvider(
            json.dumps(extra_permission), invalid_unknown_tool, invalid_clarification
        )
        planner = AIPlanner(provider, self.settings, self.catalog)

        with self.assertRaises(ModelResponseError):
            planner.plan(UserRequest("um"))
        with self.assertRaises(PlanValidationError):
            planner.plan(UserRequest("dois"))
        with self.assertRaises(PlanValidationError):
            planner.plan(UserRequest("três"))

    def test_malformed_and_empty_responses_are_rejected(self):
        planner = AIPlanner(
            ControlledProvider("```json\n{}\n```", "   "), self.settings, self.catalog
        )
        with self.assertRaises(ModelResponseError):
            planner.plan(UserRequest("um"))
        with self.assertRaises(ModelResponseError):
            planner.plan(UserRequest("dois"))

    def test_communication_failures_retry_with_a_bounded_attempt_count(self):
        provider = ControlledProvider(
            ModelCommunicationError("private token must not be logged"),
            response_payload(),
        )
        planner = AIPlanner(provider, self.settings, self.catalog)
        with self.assertLogs("agente_pessoal.ai.planner", level="WARNING") as captured:
            plan = planner.plan(UserRequest("pedido"))
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(len(plan.steps), 1)
        self.assertNotIn("private token", " ".join(captured.output))

    def test_repeated_provider_outage_is_sanitized_and_stops_at_limit(self):
        provider = ControlledProvider(
            ModelCommunicationError("secret-value"),
            ModelCommunicationError("secret-value"),
            ModelCommunicationError("should not be requested"),
        )
        planner = AIPlanner(provider, self.settings, self.catalog)
        with self.assertRaises(ModelUnavailableError) as raised:
            planner.plan(UserRequest("pedido"))
        self.assertEqual(len(provider.requests), 2)
        self.assertNotIn("secret-value", str(raised.exception))

    def test_model_configuration_is_required_and_request_size_is_bounded(self):
        with self.assertRaises(ModelConfigurationError):
            AIPlanner(ControlledProvider(response_payload()), Settings(), self.catalog)
        provider = ControlledProvider(response_payload())
        planner = AIPlanner(
            provider,
            Settings(ai_model="model-test", ai_max_request_chars=3),
            self.catalog,
        )
        with self.assertRaises(PlanValidationError):
            planner.plan(UserRequest("pedido longo"))
        self.assertEqual(provider.requests, [])

    def test_planner_connects_to_orchestrator_without_bypassing_permissions(self):
        provider = ControlledProvider(response_payload())
        tool = ControlledTool()
        executor = ToolExecutor([tool])
        planner = AIPlanner(provider, self.settings, executor.tool_catalog)
        manager = TaskManager(planner, executor)
        agent = TaskOrchestrator(manager)

        task = agent.handle("Ação em linguagem natural")

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(tool.calls, [])
        self.assertIn("PermissionDenied", task.error)

    def test_validated_plan_executes_only_after_existing_permission_check(self):
        provider = ControlledProvider(response_payload())
        tool = ControlledTool()
        executor = ToolExecutor([tool])
        planner = AIPlanner(provider, self.settings, executor.tool_catalog)
        agent = TaskOrchestrator(TaskManager(planner, executor))

        task = agent.handle(
            "Ação em linguagem natural",
            AuthorizationContext.from_permissions([Permission.FILE_READ]),
        )

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(len(tool.calls), 1)
        self.assertEqual(task.results[0].value, {"done": True})

    def test_clarification_plan_waits_without_running_tools(self):
        provider = ControlledProvider(response_payload(steps=[], clarification=True))
        tool = ControlledTool()
        executor = ToolExecutor([tool])
        planner = AIPlanner(provider, self.settings, executor.tool_catalog)
        store = SQLiteStore(":memory:")
        manager = TaskManager(planner, executor, repository=store)
        agent = TaskOrchestrator(manager)

        task = agent.handle("Faça aquilo")
        recovered = manager.get(task.id)

        self.assertEqual(task.status, TaskStatus.AWAITING_INPUT)
        self.assertIsNone(task.completed_at)
        self.assertEqual(tool.calls, [])
        self.assertTrue(task.interpretation.requires_clarification)
        self.assertEqual(recovered.interpretation.ambiguities, ("qual destino?",))
        store.close()


if __name__ == "__main__":
    unittest.main()
