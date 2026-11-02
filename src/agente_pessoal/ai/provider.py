"""Interface agnóstica para provedores; nenhum adaptador concreto é incluído."""

import os
from dataclasses import dataclass
from typing import Protocol

from agente_pessoal.ai.errors import MissingCredentialError


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """Pedido ao adaptador; contém o nome da variável, nunca o segredo."""

    prompt: str
    model: str
    credential_env_var: str | None
    timeout_seconds: float
    max_output_chars: int

    def credential_from_environment(self) -> str | None:
        """Obtém a credencial apenas quando o adaptador precisa dela."""
        if self.credential_env_var is None:
            return None
        credential = os.getenv(self.credential_env_var)
        if not credential:
            raise MissingCredentialError(
                f"A variável de credencial {self.credential_env_var} não está configurada."
            )
        return credential


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str


class ModelProvider(Protocol):
    """Adaptador concreto deverá normalizar transporte e respostas neste contrato."""

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Envia a solicitação e devolve conteúdo; não deve registrar credenciais."""
        ...
