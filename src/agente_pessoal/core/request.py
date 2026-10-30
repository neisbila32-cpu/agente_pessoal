"""Representação validada de uma solicitação recebida do usuário."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class UserRequest:
    text: str
    id: str = field(default_factory=lambda: str(uuid4()))
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("A solicitação não pode estar vazia.")
