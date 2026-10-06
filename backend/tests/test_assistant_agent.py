"""Tests for app.agent_runtime.assistant.assistant_agent — build + prompt loading."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _load_system_prompt — file exists
# ---------------------------------------------------------------------------


def test_load_system_prompt_from_file(tmp_path):
    """_load_system_prompt reads file and returns content."""
    import app.agent_runtime.assistant.assistant_agent as mod

    # Clear the lru_cache before testing
    mod._load_system_prompt.cache_clear()

    prompt_file = tmp_path / "test_prompt.md"
    prompt_file.write_text("You are a test assistant.", encoding="utf-8")

    with patch.object(mod, "_PROMPT_PATH", prompt_file):
        result = mod._load_system_prompt()

    assert result == "You are a test assistant."
    mod._load_system_prompt.cache_clear()


# ---------------------------------------------------------------------------
# _load_system_prompt — file not found → fallback
# ---------------------------------------------------------------------------


def test_load_system_prompt_fallback(tmp_path):
    """When prompt file doesn't exist, returns fallback string."""
    import app.agent_runtime.assistant.assistant_agent as mod

    mod._load_system_prompt.cache_clear()

    nonexistent = tmp_path / "nonexistent.md"

    with patch.object(mod, "_PROMPT_PATH", nonexistent):
        result = mod._load_system_prompt()

    assert "Agent Project Maker Assistant" in result
    assert "VERIFY" in result
    mod._load_system_prompt.cache_clear()


# ---------------------------------------------------------------------------
# build_assistant_agent — integrates model, tools, prompt, checkpointer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_assistant_agent():
    """build_assistant_agent wires model/tools/prompt/checkpointer into build_agent."""
    import app.agent_runtime.assistant.assistant_agent as mod

    mod._load_system_prompt.cache_clear()


@pytest.mark.asyncio
async def test_build_assistant_agent_requires_approval_for_write_tools_only():
    """Assistant DB-mutating tools must go through Deep Agents HITL approval."""
    import uuid
    from unittest.mock import AsyncMock

    import app.agent_runtime.assistant.assistant_agent as mod

    read_tool = MagicMock()
    read_tool.name = "get_agent_config"
    write_tool = MagicMock()
    write_tool.name = "add_subagent_to_agent"
    clarify_tool = MagicMock()
    clarify_tool.name = "ask_clarifying_question"
    captured: dict = {}

    from app.services.system_credential_resolver import ResolvedSystemModel

    resolved = ResolvedSystemModel(
        provider="openai",
        model_name="gpt-4o",
        api_key="sk-test",
        base_url=None,
    )

    def fake_build_agent(**kwargs):
        captured.update(kwargs)
        return object()

    with (
        patch.object(mod, "_load_system_prompt", return_value="Test prompt"),
        patch.object(mod, "resolve_system_model", AsyncMock(return_value=resolved)),
        patch.object(mod, "create_chat_model", return_value=MagicMock()),
        patch.object(mod, "build_read_tools", return_value=[read_tool]),
        patch.object(mod, "build_write_tools", return_value=[write_tool]),
        patch.object(mod, "build_clarify_tools", return_value=[clarify_tool]),
        patch.object(mod, "get_checkpointer", return_value=MagicMock()),
        patch.object(mod, "build_agent", fake_build_agent),
    ):
        await mod.build_assistant_agent(
            AsyncMock(),
            uuid.uuid4(),
            uuid.uuid4(),
            "thread-1",
        )

    assert captured["interrupt_on"] == {
        "add_subagent_to_agent": {"allowed_decisions": ["approve", "edit", "reject"]}
    }
    assert "get_agent_config" not in captured["interrupt_on"]
    assert "ask_clarifying_question" not in captured["interrupt_on"]
    from app.agent_runtime.runtime_policy import ASSISTANT_RUNTIME_POLICY

    assert captured["runtime_policy"] is ASSISTANT_RUNTIME_POLICY

    mock_model = MagicMock()
    mock_read_tools = [MagicMock()]
    mock_write_tools = [MagicMock()]
    mock_clarify_tools = [MagicMock()]
    mock_checkpointer = MagicMock()
    mock_compiled_graph = MagicMock()

    from app.services.system_credential_resolver import ResolvedSystemModel

    resolved = ResolvedSystemModel(
        provider="anthropic",
        model_name="claude-sonnet-4-6",
        api_key="sk-test",
        base_url=None,
    )
    with (
        patch.object(mod, "_load_system_prompt", return_value="Test prompt"),
        patch.object(mod, "resolve_system_model", AsyncMock(return_value=resolved)),
        patch.object(mod, "create_chat_model", return_value=mock_model),
        patch.object(mod, "build_read_tools", return_value=mock_read_tools),
        patch.object(mod, "build_write_tools", return_value=mock_write_tools),
        patch.object(mod, "build_clarify_tools", return_value=mock_clarify_tools),
        patch.object(mod, "get_checkpointer", return_value=mock_checkpointer),
        patch.object(mod, "build_agent", return_value=mock_compiled_graph) as mock_build,
    ):
        db = AsyncMock()
        agent_id = uuid.uuid4()
        user_id = uuid.uuid4()
        thread_id = f"assistant_{agent_id}"

        result = await mod.build_assistant_agent(db, agent_id, user_id, thread_id)

    assert result is mock_compiled_graph
    mock_build.assert_called_once()
    call_kwargs = mock_build.call_args
    assert call_kwargs.kwargs["model"] is mock_model
    assert call_kwargs.kwargs["system_prompt"].startswith("Test prompt")
    assert call_kwargs.kwargs["checkpointer"] is mock_checkpointer
    assert len(call_kwargs.kwargs["tools"]) == 3

    mod._load_system_prompt.cache_clear()


# ---------------------------------------------------------------------------
# Personal credentials must never fall back to operator keys.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_api_key_without_owner_ignores_environment(monkeypatch):
    from unittest.mock import AsyncMock

    from app.services import system_credential_resolver as resolver
    from app.services.llm_user_context import llm_user_id

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-operator-test")
    db = AsyncMock()
    token = llm_user_id.set(None)
    try:
        assert await resolver.resolve_system_api_key(db, "anthropic") is None
        db.execute.assert_not_awaited()
    finally:
        llm_user_id.reset(token)


@pytest.mark.asyncio
async def test_resolve_api_key_queries_personal_owner():
    import uuid
    from unittest.mock import AsyncMock

    from app.services import system_credential_resolver as resolver

    owner = uuid.uuid4()
    credential = MagicMock(data_encrypted="personal-blob")
    db = AsyncMock()
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = credential
    with patch.object(
        resolver.credential_service,
        "decrypt_with_external",
        AsyncMock(return_value={"api_key": "sk-personal-test"}),
    ):
        assert await resolver.resolve_system_api_key(db, "anthropic", owner) == "sk-personal-test"
    query = db.execute.call_args.args[0].compile()
    assert owner in query.params.values()
    assert "is_system IS false" in str(query)
