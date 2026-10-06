"""Verify supported credential families after retiring regional integrations."""

from app.credentials import definitions  # noqa: F401
from app.credentials.registry import registry


def test_supported_credential_families_are_registered() -> None:
    assert {d.key for d in registry.all()} == {
        "anthropic",
        "azure_openai",
        "deepseek",
        "google_genai",
        "google_search",
        "google_workspace_oauth2",
        "http_api_key",
        "http_basic",
        "http_bearer",
        "mcp_oauth2",
        "mcp_secret",
        "moonshot",
        "openai",
        "openai_compatible",
        "openrouter",
        "zhipu_glm",
    }
