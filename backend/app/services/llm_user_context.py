"""Authenticated owner propagated to nested model calls and spawned request tasks.

No owner means no model access. Background jobs should pass an explicit owner.
"""

from contextvars import ContextVar
from uuid import UUID

llm_user_id: ContextVar[UUID | None] = ContextVar("llm_user_id", default=None)


class LlmUserContextMiddleware:
    """Reset owner at every request boundary, including error and streaming paths."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = llm_user_id.set(None)
        try:
            await self.app(scope, receive, send)
        finally:
            llm_user_id.reset(token)
