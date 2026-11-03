"""Registro explícito de executores injetados pela aplicação."""

from agente_pessoal.multiagent.ports import AgentExecutor


class ExecutorRegistryError(Exception):
    """Erro base do registro de executores."""


class DuplicateExecutorError(ExecutorRegistryError):
    """O identificador do adaptador já está associado a um executor."""


class ExecutorNotFoundError(ExecutorRegistryError, LookupError):
    """Não há executor injetado para o identificador do adaptador."""


class AgentExecutorRegistry:
    """Associa IDs de adaptador a implementações fornecidas explicitamente."""

    def __init__(self) -> None:
        self._executors: dict[str, AgentExecutor] = {}

    def register(self, adapter_id: str, executor: AgentExecutor) -> AgentExecutor:
        if not isinstance(adapter_id, str) or not adapter_id.strip():
            raise ValueError("adapter_id deve ser um texto não vazio.")
        if not callable(getattr(executor, "execute", None)):
            raise TypeError("executor deve implementar execute(request).")
        if adapter_id in self._executors:
            raise DuplicateExecutorError(f"Executor já registrado: {adapter_id}")
        self._executors[adapter_id] = executor
        return executor

    def get(self, adapter_id: str) -> AgentExecutor:
        try:
            return self._executors[adapter_id]
        except KeyError:
            raise ExecutorNotFoundError(adapter_id) from None
