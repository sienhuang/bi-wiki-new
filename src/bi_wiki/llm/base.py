"""Business-facing model contract; providers return text, not ontology objects."""

from collections.abc import Sequence
from typing import Literal, Protocol, TypedDict


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelProvider(Protocol):
    @property
    def ready(self) -> bool: ...

    @property
    def model(self) -> str: ...

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_object: bool = False,
    ) -> str: ...
