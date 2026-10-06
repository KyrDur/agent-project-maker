"""Request-scoped authenticated owner for nested model calls."""

from contextvars import ContextVar
from uuid import UUID

llm_user_id: ContextVar[UUID | None] = ContextVar("llm_user_id", default=None)
