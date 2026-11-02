"""Interpretação validada de uma solicitação em linguagem natural."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestInterpretation:
    objective: str
    intent: str
    required_information: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    requires_clarification: bool = False
