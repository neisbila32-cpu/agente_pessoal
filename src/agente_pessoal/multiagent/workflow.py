"""Modelos validados e execução sequencial de fluxos multiagente."""

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from agente_pessoal.multiagent.coordinator import MaestroCoordinator
from agente_pessoal.multiagent.models import (
    AgentExecutionRequest,
    AgentExecutionStatus,
)
from agente_pessoal.security import AuthorizationContext

MAX_WORKFLOW_TASKS = 100
MAX_TASK_DEPENDENCIES = 16
MAX_INSTRUCTION_CHARS = 10_000
MAX_DEPENDENCY_OUTPUT_CHARS = 4_096


def _required_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} deve ser um texto não vazio.")


@dataclass(frozen=True, slots=True)
class TaskDependency:
    """Referência a uma subtarefa que deve concluir antes da tarefa atual."""

    task_id: str

    def __post_init__(self) -> None:
        _required_text(self.task_id, "task_id")


@dataclass(frozen=True, slots=True)
class AgentTask:
    """Subtarefa atribuída a um agente e às dependências que precisa aguardar."""

    agent_id: str
    instruction: str
    id: str = field(default_factory=lambda: str(uuid4()))
    dependencies: tuple[TaskDependency, ...] = ()

    def __post_init__(self) -> None:
        _required_text(self.id, "id")
        _required_text(self.agent_id, "agent_id")
        _required_text(self.instruction, "instruction")
        if len(self.instruction) > MAX_INSTRUCTION_CHARS:
            raise ValueError("instruction excede o limite permitido.")
        try:
            dependencies = tuple(self.dependencies)
        except TypeError:
            raise ValueError("dependencies deve ser uma coleção de dependências.") from None
        if any(not isinstance(item, TaskDependency) for item in dependencies):
            raise ValueError("Cada dependência deve ser um TaskDependency.")
        dependency_ids = [item.task_id for item in dependencies]
        if len(dependency_ids) > MAX_TASK_DEPENDENCIES:
            raise ValueError("A subtarefa excede o limite de dependências.")
        if len(set(dependency_ids)) != len(dependency_ids):
            raise ValueError("A subtarefa contém dependências duplicadas.")
        object.__setattr__(self, "dependencies", dependencies)


@dataclass(frozen=True, slots=True)
class MultiAgentPlan:
    """Plano não vazio validado contra IDs repetidos, referências e ciclos."""

    tasks: tuple[AgentTask, ...]
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        _required_text(self.id, "id")
        try:
            tasks = tuple(self.tasks)
        except TypeError:
            raise ValueError("tasks deve ser uma coleção de subtarefas.") from None
        if not tasks:
            raise ValueError("O plano multiagente não pode estar vazio.")
        if len(tasks) > MAX_WORKFLOW_TASKS:
            raise ValueError("O plano excede o limite de subtarefas.")
        if any(not isinstance(task, AgentTask) for task in tasks):
            raise ValueError("Cada etapa deve ser um AgentTask.")

        task_ids = [task.id for task in tasks]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("O plano contém identificadores de subtarefa duplicados.")
        known_ids = set(task_ids)
        for task in tasks:
            missing = [
                dependency.task_id
                for dependency in task.dependencies
                if dependency.task_id not in known_ids
            ]
            if missing:
                raise ValueError("O plano referencia uma dependência inexistente.")

        object.__setattr__(self, "tasks", tasks)
        self.ordered_tasks()  # Rejeita ciclos no momento da validação do plano.

    def ordered_tasks(self) -> tuple[AgentTask, ...]:
        """Retorna ordem topológica estável ou rejeita dependências circulares."""
        remaining = list(self.tasks)
        completed: set[str] = set()
        ordered: list[AgentTask] = []
        while remaining:
            ready = [
                task
                for task in remaining
                if all(dep.task_id in completed for dep in task.dependencies)
            ]
            if not ready:
                raise ValueError("O plano contém dependências circulares.")
            for task in ready:
                ordered.append(task)
                completed.add(task.id)
                remaining.remove(task)
        return tuple(ordered)


class AgentTaskStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class MultiAgentStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AgentTaskResult:
    """Estado final e resultado seguro de uma subtarefa do fluxo."""

    task_id: str
    agent_id: str
    status: AgentTaskStatus
    request_id: str | None = None
    output: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.task_id, "task_id")
        _required_text(self.agent_id, "agent_id")
        if not isinstance(self.status, AgentTaskStatus):
            raise ValueError("status deve ser um AgentTaskStatus.")
        if self.request_id is not None:
            _required_text(self.request_id, "request_id")
        if self.output is not None and not isinstance(self.output, str):
            raise ValueError("output deve ser texto ou None.")
        if self.error is not None and not isinstance(self.error, str):
            raise ValueError("error deve ser texto ou None.")


@dataclass(frozen=True, slots=True)
class MultiAgentResult:
    """Resultado consolidado, ordenado pela execução topológica do plano."""

    workflow_id: str
    plan_id: str
    task_results: tuple[AgentTaskResult, ...]
    status: MultiAgentStatus

    def __post_init__(self) -> None:
        _required_text(self.workflow_id, "workflow_id")
        _required_text(self.plan_id, "plan_id")
        results = tuple(self.task_results)
        if not results or any(not isinstance(item, AgentTaskResult) for item in results):
            raise ValueError("O resultado deve conter resultados tipados de subtarefas.")
        task_ids = [item.task_id for item in results]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("O resultado contém subtarefas duplicadas.")
        if not isinstance(self.status, MultiAgentStatus):
            raise ValueError("status deve ser um MultiAgentStatus.")
        object.__setattr__(self, "task_results", results)


class MultiAgentWorkflow:
    """Executa planos validados sequencialmente pelo Maestro existente."""

    def __init__(self, coordinator: MaestroCoordinator) -> None:
        self._coordinator = coordinator

    def execute(
        self,
        plan: MultiAgentPlan,
        authorization: AuthorizationContext | None = None,
    ) -> MultiAgentResult:
        """Executa cada subtarefa uma vez e consolida estados e resultados."""
        if not isinstance(plan, MultiAgentPlan):
            raise TypeError("plan deve ser um MultiAgentPlan validado.")

        workflow_id = str(uuid4())
        completed: dict[str, AgentTaskResult] = {}
        ordered_results: list[AgentTaskResult] = []

        for task in plan.ordered_tasks():
            dependencies = [completed[item.task_id] for item in task.dependencies]
            if any(item.status is not AgentTaskStatus.COMPLETED for item in dependencies):
                task_result = AgentTaskResult(
                    task_id=task.id,
                    agent_id=task.agent_id,
                    status=AgentTaskStatus.SKIPPED,
                    error="Dependência obrigatória não concluída.",
                )
                completed[task.id] = task_result
                ordered_results.append(task_result)
                continue

            request = AgentExecutionRequest(
                agent_id=task.agent_id,
                input=task.instruction,
                metadata=self._build_context(workflow_id, task, dependencies),
            )
            try:
                result = self._coordinator.execute(request, authorization)
            except Exception:
                task_result = AgentTaskResult(
                    task_id=task.id,
                    agent_id=task.agent_id,
                    status=AgentTaskStatus.FAILED,
                    request_id=request.id,
                    error="A execução da subtarefa falhou.",
                )
            else:
                if (
                    result.request_id != request.id
                    or result.agent_id != task.agent_id
                    or result.status is AgentExecutionStatus.FAILED
                ):
                    task_result = AgentTaskResult(
                        task_id=task.id,
                        agent_id=task.agent_id,
                        status=AgentTaskStatus.FAILED,
                        request_id=request.id,
                        error="A execução da subtarefa falhou.",
                    )
                else:
                    task_result = AgentTaskResult(
                        task_id=task.id,
                        agent_id=task.agent_id,
                        status=AgentTaskStatus.COMPLETED,
                        request_id=result.request_id,
                        output=result.output,
                    )
            completed[task.id] = task_result
            ordered_results.append(task_result)

        statuses = {item.status for item in ordered_results}
        if statuses == {AgentTaskStatus.COMPLETED}:
            overall_status = MultiAgentStatus.COMPLETED
        elif AgentTaskStatus.COMPLETED in statuses:
            overall_status = MultiAgentStatus.PARTIAL
        else:
            overall_status = MultiAgentStatus.FAILED

        return MultiAgentResult(
            workflow_id=workflow_id,
            plan_id=plan.id,
            task_results=tuple(ordered_results),
            status=overall_status,
        )

    @staticmethod
    def _build_context(
        workflow_id: str,
        task: AgentTask,
        dependencies: list[AgentTaskResult],
    ) -> dict[str, object]:
        prior_results: dict[str, object] = {}
        for result in dependencies:
            output = result.output or ""
            prior_results[result.task_id] = {
                "task_id": result.task_id,
                "agent_id": result.agent_id,
                "request_id": result.request_id,
                "status": result.status.value,
                "output": output[:MAX_DEPENDENCY_OUTPUT_CHARS],
            }
        return {
            "workflow_id": workflow_id,
            "subtask_id": task.id,
            "prior_results_are_untrusted_data": True,
            "prior_results": prior_results,
        }
