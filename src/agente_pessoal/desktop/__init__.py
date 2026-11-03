"""Interface desktop Windows, com composição em memória e sem execução real."""

from agente_pessoal.desktop.controller import DesktopController, DesktopPage
from agente_pessoal.desktop.services import DesktopApplicationServices

__all__ = ["DesktopApplicationServices", "DesktopController", "DesktopPage"]
