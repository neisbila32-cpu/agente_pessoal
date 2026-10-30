"""Interface de provedor de modelo; nenhum provedor é incluído."""

from typing import Protocol


class ModelProvider(Protocol):
    """Contrato mínimo para uma implementação de modelo selecionada no futuro."""

    def generate(self, prompt: str) -> str:
        """Gera uma resposta para um prompt."""
        ...
