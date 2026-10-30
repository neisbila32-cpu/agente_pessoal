import unittest
from collections.abc import Mapping

from agente_pessoal.core import (
    PlannedStep,
    StepStatus,
    TaskOrchestrator,
    TaskPlan,
    TaskStatus,
    UserRequest,
)
from agente_pessoal.core.executor import ToolExecutor
from agente_pessoal.core.task_manager import TaskManager
from agente_pessoal.security import AuthorizationContext, Permission


class FakePlanner:
    def __init__(self, plan=None, error=None):
        self._plan = plan
        self._error = error
        self.requests = []

    def plan(self, request):
        self.requests.append(request)
        if self._error:
            raise self._error
        return self._plan


class FakeTool:
    required_permission = Permission.FILE_READ

    def __init__(self, name, transform=lambda arguments: dict(arguments), error=None):
        self.name = name
        self.transform = transform
        self.error = error
        self.calls = []

    def describe(self):
        return f"Ferramenta de teste {self.name}"

    def execute(self, arguments: Mapping[str, object]) -> object:
        self.calls.append(arguments)
        if self.error:
            raise self.error
        return self.transform(arguments)


def make_plan(*steps):
    return TaskPlan(steps=tuple(steps))


class OrchestrationTests(unittest.TestCase):
    def test_request_runs_multiple_steps_and_records_results(self):
        first = FakeTool("first", lambda args: args["value"] + 1)
        second = FakeTool("second", lambda args: args["value"] * 2)
        planner = FakePlanner(
            make_plan(
                PlannedStep("Somar um", "first", {"value": 4}),
                PlannedStep("Dobrar", "second", {"value": 5}),
            )
        )
        manager = TaskManager(planner, ToolExecutor([first, second]))
        agent = TaskOrchestrator(manager)

        task = agent.handle(
            "Realizar duas etapas",
            AuthorizationContext.from_permissions([Permission.FILE_READ]),
        )

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.description, "Realizar duas etapas")
        self.assertEqual(task.request_id, planner.requests[0].id)
        self.assertEqual([result.value for result in task.results], [5, 10])
        self.assertTrue(all(step.status is StepStatus.COMPLETED for step in task.steps))
        self.assertIs(manager.get(task.id), task)
        self.assertEqual(manager.list_tasks(), (task,))
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(len(second.calls), 1)

    def test_permission_is_checked_before_tool_call(self):
        tool = FakeTool("read")
        manager = TaskManager(
            FakePlanner(make_plan(PlannedStep("Ler", "read"))),
            ToolExecutor([tool]),
        )

        task = manager.submit(UserRequest("Ler"))

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("PermissionDenied", task.error)
        self.assertEqual(tool.calls, [])
        self.assertEqual(task.steps[0].status, StepStatus.FAILED)

    def test_tool_error_stops_execution_and_skips_remaining_steps(self):
        broken = FakeTool("broken", error=RuntimeError("falha controlada"))
        later = FakeTool("later")
        manager = TaskManager(
            FakePlanner(
                make_plan(
                    PlannedStep("Falhar", "broken"),
                    PlannedStep("Não executar", "later"),
                )
            ),
            ToolExecutor([broken, later]),
        )

        task = manager.submit(
            UserRequest("Executar"),
            AuthorizationContext.from_permissions([Permission.FILE_READ]),
        )

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("falha controlada", task.error)
        self.assertEqual(task.steps[0].status, StepStatus.FAILED)
        self.assertEqual(task.steps[1].status, StepStatus.SKIPPED)
        self.assertEqual(later.calls, [])

    def test_planning_error_is_recorded_as_failed_task(self):
        manager = TaskManager(
            FakePlanner(error=RuntimeError("planejamento indisponível")),
            ToolExecutor([]),
        )

        task = manager.submit(UserRequest("Planejar"))

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("planejamento indisponível", task.error)
        self.assertEqual(task.steps, [])

    def test_empty_request_is_rejected_before_planning(self):
        planner = FakePlanner(make_plan())
        manager = TaskManager(planner, ToolExecutor([]))

        with self.assertRaises(ValueError):
            TaskOrchestrator(manager).handle("   ")

        self.assertEqual(planner.requests, [])


if __name__ == "__main__":
    unittest.main()
