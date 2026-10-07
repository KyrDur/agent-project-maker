"""Service-injected review boundary; the graph does not resolve storage or services."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol

from app.schemas.builder import ToolRecommendation


class BuilderConsistency(Protocol):
    async def prepare_tools(
        self, owner: uuid.UUID, tools: list[ToolRecommendation]
    ) -> list[ToolRecommendation]: ...

    async def review(
        self,
        owner: uuid.UUID,
        requirements: dict[str, Any],
        prompt: str,
        tools: list[ToolRecommendation],
    ) -> dict[str, Any]: ...


_adapter: ContextVar[BuilderConsistency | None] = ContextVar("builder_consistency", default=None)


def consistency_adapter() -> BuilderConsistency:
    adapter = _adapter.get()
    if adapter is None:
        raise ValueError("builder_consistency_unavailable")
    return adapter


@contextmanager
def builder_consistency_scope(adapter: BuilderConsistency) -> Iterator[None]:
    token = _adapter.set(adapter)
    try:
        yield
    finally:
        _adapter.reset(token)
