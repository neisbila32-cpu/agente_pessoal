"""Contrato de execução para ferramentas registradas no orquestrador."""

from collections.abc import Mapping
from typing import Protocol

from agente_pessoal.security import Permission


class Tool(Protocol):
    """Interface que ferramentas concretas deverão implementar."""

    @property
    def name(self) -> str:
        """Identificador estável da ferramenta."""
        ...

    def describe(self) -> str:
        """Descrição legível da capacidade oferecida."""
        ...

    @property
    def required_permission(self) -> Permission:
        """Permissão que o executor deve validar antes da chamada."""
        ...

    def execute(self, arguments: Mapping[str, object]) -> object:
        """Executa uma operação limitada e tipada pelos argumentos recebidos."""
        ...
