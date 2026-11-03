import unittest

from agente_pessoal.multiagent import (
    AgentDefinition,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentExecutorRegistry,
    AgentRegistry,
    AgentTask,
    AgentTaskStatus,
    MaestroCoordinator,
    MultiAgentPlan,
    MultiAgentStatus,
    MultiAgentWorkflow,
    TaskDependency,
)
from agente_pessoal.security import AuthorizationContext, Permission


class WorkflowTestExecutor:
    def __init__(self, output, *, fail=False):
        self.output = output
        self.fail = fail
        self.requests = []

    def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("sensitive executor details")
        return AgentExecutionResult(
            request_id=request.id,
            agent_id=request.agent_id,
            status=AgentExecutionStatus.COMPLETED,
            output=self.output,
        )


class MultiAgentWorkflowTests(unittest.TestCase):
    def build_workflow(self, *, failing_agents=()):
        agent_registry = AgentRegistry()
        executor_registry = AgentExecutorRegistry()
        executors = {}
        for agent_id in ("agent-a", "agent-b", "agent-c", "agent-d"):
            adapter_id = f"adapter-{agent_id}"
            agent_registry.register(
                AgentDefinition(
                    id=agent_id,
                    name=agent_id,
                    description="Simulado para testes",
                    capabilities=("test",),
                    adapter_id=adapter_id,
                )
            )
            executor = WorkflowTestExecutor(
                f"output-{agent_id}", fail=agent_id in failing_agents
            )
            executor_registry.register(adapter_id, executor)
            executors[agent_id] = executor
        coordinator = MaestroCoordinator(agent_registry, executor_registry)
        return MultiAgentWorkflow(coordinator), executors

    @staticmethod
    def authorization():
        return AuthorizationContext.from_permissions([Permission.AGENT_EXECUTE])

    def test_simple_flow_executes_three_agents_in_dependency_order(self):
        workflow, executors = self.build_workflow()
        plan = MultiAgentPlan(
            tasks=(
                AgentTask("agent-c", "Combinar", id="task-c", dependencies=(TaskDependency("task-b"),)),
                AgentTask("agent-a", "Pesquisar", id="task-a"),
                AgentTask("agent-b", "Resumir", id="task-b", dependencies=(TaskDependency("task-a"),)),
            )
        )

        result = workflow.execute(plan, self.authorization())

        self.assertEqual(result.plan_id, plan.id)
        self.assertEqual(result.status, MultiAgentStatus.COMPLETED)
        self.assertEqual(
            [item.task_id for item in result.task_results],
            ["task-a", "task-b", "task-c"],
        )
        self.assertEqual(
            [len(executors[agent_id].requests) for agent_id in ("agent-a", "agent-b", "agent-c")],
            [1, 1, 1],
        )
        self.assertTrue(all(item.status is AgentTaskStatus.COMPLETED for item in result.task_results))
        for item in result.task_results:
            self.assertEqual(item.agent_id, f"agent-{item.task_id[-1]}")
            self.assertEqual(
                item.request_id,
                executors[item.agent_id].requests[0].id,
            )

    def test_dependency_outputs_are_forwarded_as_bounded_untrusted_context(self):
        workflow, executors = self.build_workflow()
        plan = MultiAgentPlan(
            tasks=(
                AgentTask("agent-a", "Instrução original", id="task-a"),
                AgentTask("agent-b", "Use dados anteriores", id="task-b", dependencies=(TaskDependency("task-a"),)),
                AgentTask("agent-c", "Produzir resultado final", id="task-c", dependencies=(TaskDependency("task-b"),)),
            )
        )

        workflow.execute(plan, self.authorization())

        request_b = executors["agent-b"].requests[0]
        self.assertEqual(request_b.input, "Use dados anteriores")
        self.assertTrue(request_b.metadata["prior_results_are_untrusted_data"])
        self.assertEqual(
            request_b.metadata["prior_results"]["task-a"]["output"],
            "output-agent-a",
        )
        request_c = executors["agent-c"].requests[0]
        self.assertEqual(
            request_c.metadata["prior_results"]["task-b"]["output"],
            "output-agent-b",
        )

    def test_dependency_context_output_is_limited(self):
        workflow, executors = self.build_workflow()
        executors["agent-a"].output = "x" * 5_000
        plan = MultiAgentPlan(
            tasks=(
                AgentTask("agent-a", "Gerar", id="task-a"),
                AgentTask("agent-b", "Consumir", id="task-b", dependencies=(TaskDependency("task-a"),)),
            )
        )

        workflow.execute(plan, self.authorization())

        forwarded = executors["agent-b"].requests[0].metadata["prior_results"]["task-a"]["output"]
        self.assertEqual(len(forwarded), 4_096)

    def test_plan_rejects_empty_tasks_duplicate_ids_missing_dependencies_and_cycles(self):
        with self.assertRaises(ValueError):
            MultiAgentPlan(tasks=())
        with self.assertRaises(ValueError):
            MultiAgentPlan(
                tasks=(AgentTask("agent-a", "Uma", id="duplicate"), AgentTask("agent-b", "Duas", id="duplicate"))
            )
        with self.assertRaises(ValueError):
            MultiAgentPlan(
                tasks=(AgentTask("agent-a", "Tarefa", id="task-a", dependencies=(TaskDependency("missing"),)),)
            )
        with self.assertRaises(ValueError):
            MultiAgentPlan(
                tasks=(
                    AgentTask("agent-a", "Uma", id="task-a", dependencies=(TaskDependency("task-b"),)),
                    AgentTask("agent-b", "Duas", id="task-b", dependencies=(TaskDependency("task-a"),)),
                )
            )

    def test_failure_skips_required_dependents_but_runs_independent_branches(self):
        workflow, executors = self.build_workflow(failing_agents=("agent-a",))
        plan = MultiAgentPlan(
            tasks=(
                AgentTask("agent-a", "Falhar", id="task-a"),
                AgentTask("agent-b", "Executar independente", id="task-b"),
                AgentTask("agent-c", "Depende da falha", id="task-c", dependencies=(TaskDependency("task-a"),)),
                AgentTask("agent-d", "Depende do independente", id="task-d", dependencies=(TaskDependency("task-b"),)),
            )
        )

        result = workflow.execute(plan, self.authorization())
        states = {item.task_id: item for item in result.task_results}

        self.assertEqual(result.status, MultiAgentStatus.PARTIAL)
        self.assertEqual(states["task-a"].status, AgentTaskStatus.FAILED)
        self.assertEqual(states["task-a"].error, "A execução da subtarefa falhou.")
        self.assertEqual(states["task-c"].status, AgentTaskStatus.SKIPPED)
        self.assertEqual(states["task-d"].status, AgentTaskStatus.COMPLETED)
        self.assertEqual(executors["agent-c"].requests, [])
        self.assertEqual(len(executors["agent-b"].requests), 1)
        self.assertEqual(len(executors["agent-d"].requests), 1)

    def test_permission_is_checked_for_each_task_and_denial_does_not_dispatch(self):
        workflow, executors = self.build_workflow()
        plan = MultiAgentPlan(
            tasks=(
                AgentTask("agent-a", "A", id="task-a"),
                AgentTask("agent-b", "B", id="task-b"),
            )
        )

        result = workflow.execute(plan)

        self.assertEqual(result.status, MultiAgentStatus.FAILED)
        self.assertTrue(all(item.status is AgentTaskStatus.FAILED for item in result.task_results))
        self.assertTrue(all(not executor.requests for executor in executors.values()))


if __name__ == "__main__":
    unittest.main()
