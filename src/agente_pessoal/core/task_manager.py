"""Recebimento, planejamento e acompanhamento de tarefas."""

import logging
from datetime import datetime, timezone

from agente_pessoal.audit.events import AuditEventType, AuditLogger
from agente_pessoal.core.executor import ToolExecutor
from agente_pessoal.core.planning import Planner
from agente_pessoal.core.ports import TaskRepository
from agente_pessoal.core.request import UserRequest
from agente_pessoal.core.task import (
    StepResult,
    StepStatus,
    Task,
    TaskStatus,
    TaskStep,
)
from agente_pessoal.security import AuthorizationContext

logger = logging.getLogger(__name__)


class TaskManager:
    """Gerencia o ciclo de vida com repositório opcional e auditoria estruturada."""

    def __init__(
        self,
        planner: Planner,
        executor: ToolExecutor,
        repository: TaskRepository | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._repository = repository
        self._audit = audit
        self._tasks: dict[str, Task] = {}

    def submit(
        self,
        request: UserRequest,
        authorization: AuthorizationContext | None = None,
    ) -> Task:
        task = Task(request=request.text, request_id=request.id)
        self._tasks[task.id] = task
        if self._repository:
            self._repository.create_task(request, task)
        self._record(AuditEventType.TASK_CREATED, task_id=task.id)
        logger.info("Tarefa %s recebida", task.id)

        try:
            plan = self._planner.plan(request)
            if plan.interpretation and plan.interpretation.requires_clarification:
                if plan.steps or not plan.interpretation.ambiguities:
                    raise ValueError("O plano para esclarecimento deve conter ambiguidades e zero etapas.")
            elif not plan.steps:
                raise ValueError("O plano não contém etapas.")
        except Exception as exc:
            task.error = f"{type(exc).__name__}: {exc}"
            logger.error("Planejamento da tarefa %s falhou (%s)", task.id, type(exc).__name__)
            self._change_status(task, TaskStatus.FAILED)
            self._record(
                AuditEventType.TASK_FAILED,
                task_id=task.id,
                error_type=type(exc).__name__,
            )
            return self._finish(task)

        task.interpretation = plan.interpretation
        if plan.interpretation and plan.interpretation.requires_clarification:
            self._persist(task)
            self._change_status(task, TaskStatus.AWAITING_INPUT)
            return self._finish(task)

        task.steps = [
            TaskStep(
                id=step.id,
                description=step.description,
                tool_name=step.tool_name,
                arguments=step.arguments,
            )
            for step in plan.steps
        ]
        self._persist(task)
        self._change_status(task, TaskStatus.RUNNING)
        logger.info("Tarefa %s planejada com %d etapa(s)", task.id, len(task.steps))

        for index, step in enumerate(task.steps):
            step.status = StepStatus.RUNNING
            step.started_at = datetime.now(timezone.utc)
            self._persist(task)
            self._record(
                AuditEventType.STEP_STARTED,
                task_id=task.id,
                step_id=step.id,
                tool_name=step.tool_name,
            )
            logger.info("Iniciando etapa %s da tarefa %s", step.id, task.id)
            try:
                value = self._executor.execute(step, authorization, task_id=task.id)
            except Exception as exc:
                step.status = StepStatus.FAILED
                step.error = f"{type(exc).__name__}: {exc}"
                step.completed_at = datetime.now(timezone.utc)
                task.error = step.error
                self._skip_remaining(task.steps[index + 1 :])
                self._persist(task)
                self._change_status(task, TaskStatus.FAILED)
                self._record(
                    AuditEventType.STEP_FAILED,
                    task_id=task.id,
                    step_id=step.id,
                    tool_name=step.tool_name,
                    error_type=type(exc).__name__,
                )
                self._record(
                    AuditEventType.TASK_FAILED,
                    task_id=task.id,
                    error_type=type(exc).__name__,
                )
                logger.error("Etapa %s falhou (%s)", step.id, type(exc).__name__)
                break

            step.status = StepStatus.COMPLETED
            step.result = value
            step.completed_at = datetime.now(timezone.utc)
            task.results.append(
                StepResult(step_id=step.id, tool_name=step.tool_name, value=value)
            )
            self._persist(task)
            self._record(
                AuditEventType.STEP_COMPLETED,
                task_id=task.id,
                step_id=step.id,
                tool_name=step.tool_name,
                outcome="completed",
            )
            logger.info("Etapa %s concluída", step.id)
        else:
            self._change_status(task, TaskStatus.COMPLETED)

        return self._finish(task)

    def get(self, task_id: str) -> Task | None:
        """Busca primeiro no repositório persistente para permitir recuperação."""
        if self._repository:
            task = self._repository.get_task(task_id)
            if task is not None:
                self._tasks[task_id] = task
            return task
        return self._tasks.get(task_id)

    def list_tasks(self) -> tuple[Task, ...]:
        if self._repository:
            tasks = self._repository.list_tasks()
            self._tasks.update((task.id, task) for task in tasks)
            return tasks
        return tuple(self._tasks.values())

    def _change_status(self, task: Task, status: TaskStatus) -> None:
        previous = task.status
        if previous is status:
            self._persist(task)
            return
        task.status = status
        self._persist(task)
        self._record(
            AuditEventType.TASK_STATUS_CHANGED,
            task_id=task.id,
            outcome=f"{previous.value}->{status.value}",
        )

    def _finish(self, task: Task) -> Task:
        task.completed_at = (
            None
            if task.status is TaskStatus.AWAITING_INPUT
            else datetime.now(timezone.utc)
        )
        self._persist(task)
        logger.info("Tarefa %s finalizada com status %s", task.id, task.status.value)
        return task

    def _persist(self, task: Task) -> None:
        if self._repository:
            self._repository.save_task(task)

    def _record(self, event_type: AuditEventType, **fields: str | None) -> None:
        if self._audit:
            self._audit.record(event_type, **fields)

    @staticmethod
    def _skip_remaining(steps: list[TaskStep]) -> None:
        for step in steps:
            step.status = StepStatus.SKIPPED
