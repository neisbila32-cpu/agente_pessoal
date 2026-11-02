"""Adaptador NVIDIA NIM usando o SDK oficial OpenAI em modo compatível."""

import os
from collections.abc import Callable
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    OpenAIError,
)

from agente_pessoal.ai.errors import (
    MissingCredentialError,
    ModelCommunicationError,
    ModelProviderError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from agente_pessoal.ai.provider import ModelProvider, ModelRequest, ModelResponse
from agente_pessoal.config.settings import NVIDIA_CREDENTIAL_ENV_VAR

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NvidiaNimProvider(ModelProvider):
    """Chama chat completions da NVIDIA sem expor a chave ou acoplar o núcleo."""

    def __init__(
        self,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._client_factory = client_factory or OpenAI

    def generate(self, request: ModelRequest) -> ModelResponse:
        if request.credential_env_var not in (None, NVIDIA_CREDENTIAL_ENV_VAR):
            raise ModelProviderError(
                "O adaptador NVIDIA aceita somente a variável NVIDIA_API_KEY."
            )
        api_key = os.getenv(NVIDIA_CREDENTIAL_ENV_VAR)
        if not api_key:
            raise MissingCredentialError("Configure a variável de ambiente NVIDIA_API_KEY.")

        client = None
        try:
            client = self._client_factory(
                base_url=NVIDIA_BASE_URL,
                api_key=api_key,
                timeout=request.timeout_seconds,
                # O AIPlanner é o único responsável por repetir chamadas.
                max_retries=0,
            )
            completion = client.chat.completions.create(
                model=request.model,
                messages=[{"role": "user", "content": request.prompt}],
                temperature=0.2,
                max_tokens=4096,
                stream=False,
            )
        except APITimeoutError:
            raise ModelTimeoutError("A chamada à NVIDIA excedeu o timeout.") from None
        except APIConnectionError:
            raise ModelUnavailableError("Não foi possível conectar à NVIDIA NIM.") from None
        except APIStatusError as exc:
            status = exc.status_code
            if status in {408, 409, 429} or status >= 500:
                raise ModelUnavailableError(
                    f"A NVIDIA NIM está indisponível (HTTP {status})."
                ) from None
            raise ModelProviderError(
                f"A NVIDIA NIM rejeitou a solicitação (HTTP {status})."
            ) from None
        except OpenAIError as exc:
            # Não propaga a mensagem do SDK, que pode carregar dados de transporte.
            raise ModelProviderError(
                f"Falha no SDK OpenAI ({type(exc).__name__})."
            ) from None
        except Exception as exc:
            raise ModelProviderError(
                f"Falha no adaptador NVIDIA ({type(exc).__name__})."
            ) from None
        finally:
            if client is not None:
                close = getattr(client, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass

        choices = getattr(completion, "choices", None)
        if not choices:
            raise ModelResponseError("A NVIDIA NIM retornou uma resposta sem escolhas.")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError("A NVIDIA NIM retornou conteúdo vazio ou inválido.")
        if len(content) > request.max_output_chars:
            raise ModelResponseError("A resposta excede o limite configurado.")
        return ModelResponse(content=content)
