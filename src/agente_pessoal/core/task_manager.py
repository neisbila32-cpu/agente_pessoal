"""Recebimento, planejamento e acompanhamento de tarefas em memória."""

import logging
from datetime import datetime, timezone

from agente_pessoal.core.executor import ToolExecutor
from agente_pessoal.core.planning import Planner
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
    """Gerencia tarefas em memória; persiste cada etapa e captura falhas."""

    def __init__(self, planner: Planner, executor: ToolExecutor) -> None:
        self._planner = planner
        self._executor = executor
        self._tasks: dict[str, Task] = {}

    def submit(
        self,
        request: UserRequest,
        authorization: AuthorizationContext | None = None,
    ) -> Task:
        task = Task(request=request.text, request_id=request.id)
        self._tasks[task.id] = task
        logger.info("Tarefa %s recebida", task.id)

        try:
            plan = self._planner.plan(request)
            if not plan.steps:
                raise ValueError("O plano não contém etapas.")
            task.steps = [
                TaskStep(
                    id=step.id,
                    description=step.description,
                    tool_name=step.tool_name,
                    arguments=step.arguments,
                )
                for step in plan.steps
            ]
            task.status = TaskStatus.RUNNING
            logger.info("Tarefa %s planejada com %d etapa(s)", task.id, len(task.steps))

            for index, step in enumerate(task.steps):
                step.status = StepStatus.RUNNING
                step.started_at = datetime.now(timezone.utc)
                logger.info("Iniciando etapa %s da tarefa %s", step.id, task.id)
                try:
                    value = self._executor.execute(step, authorization)
                except Exception as exc:
                    step.status = StepStatus.FAILED
                    step.error = f"{type(exc).__name__}: {exc}"
                    step.completed_at = datetime.now(timezone.utc)
                    task.status = TaskStatus.FAILED
                    task.error = step.error
                    self._skip_remaining(task.steps[index + 1 :])
                    logger.error(
                        "Etapa %s falhou (%s)", step.id, type(exc).__name__
                    )
                    break

                step.status = StepStatus.COMPLETED
                step.result = value
                step.completed_at = datetime.now(timezone.utc)
                task.results.append(
                    StepResult(step_id=step.id, tool_name=step.tool_name, value=value)
                )
                logger.info("Etapa %s concluída", step.id)
            else:
                task.status = TaskStatus.COMPLETED
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = f"{type(exc).__name__}: {exc}"
            logger.error("Planejamento da tarefa %s falhou (%s)", task.id, type(exc).__name__)
        finally:
            task.completed_at = datetime.now(timezone.utc)
            logger.info("Tarefa %s finalizada com status %s", task.id, task.status.value)
        return task

    def get(self, task_id: str) -> Task | None:
        """Retorna uma tarefa pelo identificador, se estiver neste processo."""
        return self._tasks.get(task_id)

    def list_tasks(self) -> tuple[Task, ...]:
        """Retorna uma fotografia ordenada pela inserção das tarefas em memória."""
        return tuple(self._tasks.values())

    @staticmethod
    def _skip_remaining(steps: list[TaskStep]) -> None:
        for step in steps:
            step.status = StepStatus.SKIPPED
