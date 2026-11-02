"""Falhas tipadas da fronteira com provedores de modelos."""


class ModelProviderError(Exception):
    """Erro normalizado por um adaptador de provedor, sem exigir fornecedor."""


class ModelCommunicationError(ModelProviderError):
    """Falha temporária de comunicação que pode ser repetida com limite."""


class ModelTimeoutError(ModelCommunicationError):
    """A chamada excedeu o timeout configurado."""


class ModelUnavailableError(ModelCommunicationError):
    """O provedor está indisponível ou recusou a comunicação temporariamente."""


class MissingCredentialError(ModelProviderError):
    """A variável de ambiente de credencial configurada não está disponível."""


class ModelConfigurationError(ValueError):
    """A configuração do modelo está ausente ou inválida."""


class ModelResponseError(ValueError):
    """A resposta do modelo está vazia, inválida ou fora do formato esperado."""


class PlanValidationError(ModelResponseError):
    """O plano proposto pelo modelo viola o contrato ou a lista de ferramentas."""
