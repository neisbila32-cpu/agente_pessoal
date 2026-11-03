"""Registro em memória de definições de agentes."""

from dataclasses import replace

from agente_pessoal.multiagent.models import AgentDefinition


class AgentRegistryError(Exception):
    """Erro base do catálogo de agentes."""


class DuplicateAgentError(AgentRegistryError):
    """O identificador já está registrado."""


class AgentNotFoundError(AgentRegistryError, KeyError):
    """O identificador não existe no registro."""


class AgentRegistry:
    """Armazena definições sem carregar adaptadores nem conceder permissões."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}

    def register(self, agent: AgentDefinition) -> AgentDefinition:
        if not isinstance(agent, AgentDefinition):
            raise TypeError("agent deve ser um AgentDefinition.")
        if agent.id in self._agents:
            raise DuplicateAgentError(f"Agente já registrado: {agent.id}")
        self._agents[agent.id] = agent
        return agent

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise AgentNotFoundError(agent_id) from None

    def list_agents(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._agents.values())

    def enable(self, agent_id: str) -> AgentDefinition:
        return self._set_enabled(agent_id, True)

    def disable(self, agent_id: str) -> AgentDefinition:
        return self._set_enabled(agent_id, False)

    def _set_enabled(self, agent_id: str, enabled: bool) -> AgentDefinition:
        current = self.get(agent_id)
        updated = replace(current, enabled=enabled)
        self._agents[agent_id] = updated
        return updated
