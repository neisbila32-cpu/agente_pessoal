"""Configuração básica de logging para console."""

import logging

from agente_pessoal.config import Settings


def configure_logging(settings: Settings | None = None) -> None:
    """Configura logging sem instalar handlers duplicados."""
    selected = settings or Settings.from_environment()
    logging.basicConfig(
        level=getattr(logging, selected.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
