"""Vínculos lógicos entre agentes cadastrados e conexões de IA."""

from dataclasses import dataclass, field
from uuid import uuid4

from agente_pessoal.integrations.connections import ConnectionRegistry
from agente_pessoal.multiagent.registry import AgentRegistry


@dataclass(frozen=True, slots=True)
class AgentConnectionBinding:
    """Associação de roteamento, sem alterar permissões ou executar o agente."""

    agent_id: str
    connection_id: str
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        for name in ("id", "agent_id", "connection_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} deve ser um texto não vazio.")


class DuplicateBindingError(Exception):
    """O agente já está associado à conexão informada."""


class BindingNotFoundError(LookupError):
    """O vínculo informado não existe."""


class AgentConnectionBindingRegistry:
    """Valida referências existentes e armazena vínculos sem conceder acesso."""

    def __init__(self, agents: AgentRegistry, connections: ConnectionRegistry) -> None:
        self._agents = agents
        self._connections = connections
        self._bindings: dict[str, AgentConnectionBinding] = {}

    def register(self, agent_id: str, connection_id: str) -> AgentConnectionBinding:
        self._agents.get(agent_id)
        self._connections.get(connection_id)
        if any(
            item.agent_id == agent_id and item.connection_id == connection_id
            for item in self._bindings.values()
        ):
            raise DuplicateBindingError("Agente já associado a essa conexão.")
        binding = AgentConnectionBinding(agent_id=agent_id, connection_id=connection_id)
        self._bindings[binding.id] = binding
        return binding

    def get(self, binding_id: str) -> AgentConnectionBinding:
        try:
            return self._bindings[binding_id]
        except KeyError:
            raise BindingNotFoundError(binding_id) from None

    def unregister(self, binding_id: str) -> AgentConnectionBinding:
        binding = self.get(binding_id)
        del self._bindings[binding_id]
        return binding

    def list_bindings(self, agent_id: str | None = None) -> tuple[AgentConnectionBinding, ...]:
        bindings = self._bindings.values()
        if agent_id is not None:
            self._agents.get(agent_id)
            bindings = (item for item in bindings if item.agent_id == agent_id)
        return tuple(bindings)

    def remove_for_agent(self, agent_id: str) -> tuple[AgentConnectionBinding, ...]:
        """Remove vínculos em memória para exclusão controlada do agente."""
        self._agents.get(agent_id)
        removed = tuple(item for item in self._bindings.values() if item.agent_id == agent_id)
        for binding in removed:
            del self._bindings[binding.id]
        return removed
