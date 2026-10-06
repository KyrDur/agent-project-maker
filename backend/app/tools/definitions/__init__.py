"""Built-in tool definitions — registered into the global registry on import."""

from app.tools.definitions.gmail_send import definition as gmail_send
from app.tools.definitions.google_calendar_event import definition as google_calendar_event
from app.tools.definitions.google_chat_message import definition as google_chat_message
from app.tools.definitions.google_search import (
    image_definition as google_search_image,
)
from app.tools.definitions.google_search import (
    news_definition as google_search_news,
)
from app.tools.definitions.google_search import (
    web_definition as google_search_web,
)
from app.tools.definitions.http_request import definition as http_request
from app.tools.definitions.tavily_search import definition as tavily_search
from app.tools.registry import registry

for _definition in (
    http_request,
    tavily_search,
    google_search_web,
    google_search_image,
    google_search_news,
    gmail_send,
    google_calendar_event,
    google_chat_message,
):
    registry.register(_definition)


__all__ = [
    "gmail_send",
    "google_calendar_event",
    "google_chat_message",
    "google_search_image",
    "google_search_news",
    "google_search_web",
    "http_request",
    "tavily_search",
]
