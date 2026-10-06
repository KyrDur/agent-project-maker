"""Built-in credential definitions — registered into the global registry on import."""

from app.credentials.definitions.anthropic import definition as anthropic
from app.credentials.definitions.azure_openai import definition as azure_openai
from app.credentials.definitions.deepseek import definition as deepseek
from app.credentials.definitions.google_genai import definition as google_genai
from app.credentials.definitions.google_search import definition as google_search
from app.credentials.definitions.google_workspace_oauth2 import (
    definition as google_workspace_oauth2,
)
from app.credentials.definitions.http_api_key import definition as http_api_key
from app.credentials.definitions.http_basic import definition as http_basic
from app.credentials.definitions.http_bearer import definition as http_bearer
from app.credentials.definitions.mcp_oauth2 import definition as mcp_oauth2
from app.credentials.definitions.mcp_secret import definition as mcp_secret
from app.credentials.definitions.moonshot import definition as moonshot
from app.credentials.definitions.openai import definition as openai
from app.credentials.definitions.openai_compatible import (
    definition as openai_compatible,
)
from app.credentials.definitions.openrouter import definition as openrouter
from app.credentials.definitions.zhipu_glm import definition as zhipu_glm
from app.credentials.registry import registry

for _definition in (
    google_search,
    google_workspace_oauth2,
    deepseek,
    moonshot,
    openai,
    zhipu_glm,
    anthropic,
    google_genai,
    azure_openai,
    openrouter,
    openai_compatible,
    http_bearer,
    http_api_key,
    http_basic,
    mcp_secret,
    mcp_oauth2,
):
    registry.register(_definition)


__all__ = [
    "anthropic",
    "azure_openai",
    "deepseek",
    "google_genai",
    "google_search",
    "google_workspace_oauth2",
    "http_api_key",
    "http_basic",
    "http_bearer",
    "mcp_secret",
    "mcp_oauth2",
    "moonshot",
    "openai",
    "openai_compatible",
    "openrouter",
    "zhipu_glm",
]
