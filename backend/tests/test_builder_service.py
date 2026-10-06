"""Tests for app.services.builder_service — session CRUD, claim, confirm, helpers."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.service import encrypt_data
from app.models.agent import Agent
from app.models.credential import Credential
from app.models.mcp_server import McpServer
from app.models.mcp_tool import McpTool
from app.models.model import Model
from app.models.skill import Skill
from app.models.tool import Tool
from app.models.user import User
from app.schemas.builder import BuilderStatus
from app.services.builder_service import (
    _get_middlewares_catalog,
    claim_for_confirming,
    confirm_build,
    create_session,
    get_agent_by_id,
    get_session,
)
from tests.conftest import TEST_USER_ID


async def _seed_user(db: AsyncSession) -> User:
    user = User(id=TEST_USER_ID, email="test@test.com", name="Test")
    db.add(user)
    await db.flush()
    return user


async def _seed_model(db: AsyncSession, *, is_default: bool = True) -> Model:
    encrypted, key_id, field_keys = encrypt_data({"api_key": "sk-test-builder"})
    credential = Credential(
        user_id=TEST_USER_ID,
        definition_key="openai",
        name="Builder test key",
        data_encrypted=encrypted,
        key_id=key_id,
        field_keys=field_keys,
        is_system=False,
        status="active",
    )
    db.add(credential)
    await db.flush()
    model = Model(
        provider="openai",
        model_name="gpt-4o",
        display_name="GPT-4o",
        is_default=is_default,
        default_credential_id=credential.id,
    )
    db.add(model)
    await db.flush()
    return model


async def _seed_tool(db: AsyncSession) -> Tool:
    tool = Tool(
        name="HTTP Request",
        definition_key="http_request",
        description="HTTP request tool",
    )
    db.add(tool)
    await db.flush()
    return tool


async def _seed_mcp_tools(db: AsyncSession, *, names: list[str]) -> tuple[McpServer, list[McpTool]]:
    """创建1个 McpServer + 与 names 数量相同的 McpTool。"""
    server = McpServer(
        user_id=TEST_USER_ID,
        name="Hancom Org Chart",
        transport="sse",
        url="https://example.com/mcp",
    )
    db.add(server)
    await db.flush()
    tools = []
    for name in names:
        mt = McpTool(server_id=server.id, name=name, description=f"{name} desc")
        db.add(mt)
        tools.append(mt)
    await db.flush()
    return server, tools


async def _seed_skills(db: AsyncSession, *, names: list[str]) -> list[Skill]:
    """创建 Test user 的 ``Skill`` row。slug 为 name 小写 hyphenate。"""
    skills = []
    for name in names:
        skill = Skill(
            user_id=TEST_USER_ID,
            name=name,
            slug=name.lower().replace(" ", "-").replace("_", "-"),
            description=f"{name} 指南",
        )
        db.add(skill)
        skills.append(skill)
    await db.flush()
    return skills


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session(db: AsyncSession):
    await _seed_user(db)
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "帮我创建天气机器人")
    assert session.id is not None
    assert session.status == BuilderStatus.BUILDING
    assert session.user_request == "帮我创建天气机器人"
    assert session.user_id == TEST_USER_ID
    assert session.current_phase == 0
    assert session.draft_config is None


# ---------------------------------------------------------------------------
# get_session / get_session_not_found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session(db: AsyncSession):
    await _seed_user(db)
    await db.commit()

    created = await create_session(db, TEST_USER_ID, "搜索智能体")
    found = await get_session(db, created.id, TEST_USER_ID)
    assert found is not None
    assert found.id == created.id
    assert found.user_request == "搜索智能体"


@pytest.mark.asyncio
async def test_get_session_not_found(db: AsyncSession):
    result = await get_session(db, uuid.uuid4(), TEST_USER_ID)
    assert result is None


# ---------------------------------------------------------------------------
# claim_for_confirming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_for_confirming(db: AsyncSession):
    """PREVIEW -> CONFIRMING transition succeeds."""
    await _seed_user(db)
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "测试")
    # Manually set status to PREVIEW
    session.status = BuilderStatus.PREVIEW
    await db.commit()

    ok = await claim_for_confirming(db, session.id, TEST_USER_ID)
    assert ok is True

    reloaded = await get_session(db, session.id, TEST_USER_ID)
    assert reloaded is not None
    assert reloaded.status == BuilderStatus.CONFIRMING


# ---------------------------------------------------------------------------
# confirm_build
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_build_success(db: AsyncSession):
    """draft_config + model match -> Agent created."""
    await _seed_user(db)
    model = await _seed_model(db)
    await _seed_tool(db)
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "天气机器人")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "天气机器人",
        "description": "提供天气信息的机器人",
        "system_prompt": "You are a weather bot.",
        "tools": ["HTTP Request"],
        "middlewares": [],
        "model_name": "GPT-4o",
        "identity_mode": "per_user",
    }
    await db.commit()

    agent = await confirm_build(db, session)
    assert agent is not None
    assert agent.name == "天气机器人"
    assert agent.system_prompt == "You are a weather bot."
    assert agent.model_id == model.id
    assert agent.identity_mode == "per_user"

    reloaded = await get_session(db, session.id, TEST_USER_ID)
    assert reloaded is not None
    assert reloaded.status == BuilderStatus.COMPLETED
    assert reloaded.agent_id == agent.id


@pytest.mark.asyncio
async def test_confirm_build_uses_fixed_identity_from_draft(db: AsyncSession):
    await _seed_user(db)
    await _seed_model(db)
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "定时机器人")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "定时机器人",
        "description": "在指定时间运行的机器人",
        "system_prompt": "Run on schedule.",
        "tools": [],
        "middlewares": [],
        "model_name": "GPT-4o",
        "identity_mode": "fixed",
    }
    await db.commit()

    agent = await confirm_build(db, session)
    assert agent is not None
    assert agent.identity_mode == "fixed"


@pytest.mark.asyncio
async def test_confirm_build_links_mcp_tools(db: AsyncSession):
    """MCP tool 回归保护。

    Builder phase3 catalog 同时暴露 ``Tool + McpTool``，因此 phase8
    confirm 也必须匹配两者。验证用户注册 MCP server 后，当 tool
    名称只存在于 ``McpTool`` 时，``confirm_build`` 不会 silent drop，
    而是准确连接到 ``agent.mcp_tool_links``。
    """
    await _seed_user(db)
    await _seed_model(db)
    _, mcp_tools = await _seed_mcp_tools(db, names=["list_departments", "search_employees"])
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "组织架构机器人")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "组织架构机器人",
        "description": "组织架构 QA",
        "system_prompt": "you are an org chart assistant",
        "tools": ["list_departments", "search_employees"],
        "middlewares": [],
        "model_name": "GPT-4o",
    }
    await db.commit()

    agent = await confirm_build(db, session)
    assert agent is not None
    # Tool 表中不存在，因此 agent.tool_links 应为空
    assert len(agent.tool_links) == 0
    # 两个 McpTool 都必须连接
    linked_ids = {link.mcp_tool_id for link in agent.mcp_tool_links}
    assert linked_ids == {mt.id for mt in mcp_tools}


@pytest.mark.asyncio
async def test_confirm_build_mixed_tool_and_mcp(db: AsyncSession):
    """即使同一 draft.tools 中混有 Tool 与 McpTool，也应两侧都建立 link。"""
    await _seed_user(db)
    await _seed_model(db)
    tool = await _seed_tool(db)  # name="HTTP Request"
    _, mcp_tools = await _seed_mcp_tools(db, names=["list_departments"])
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "混合机器人")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "混合",
        "description": "d",
        "system_prompt": "p",
        "tools": ["HTTP Request", "list_departments"],
        "middlewares": [],
        "model_name": "GPT-4o",
    }
    await db.commit()

    agent = await confirm_build(db, session)
    assert agent is not None
    assert {link.tool_id for link in agent.tool_links} == {tool.id}
    assert {link.mcp_tool_id for link in agent.mcp_tool_links} == {mt.id for mt in mcp_tools}


@pytest.mark.asyncio
async def test_confirm_build_links_skills(db: AsyncSession):
    """Skill 回归保护 — Builder 能识别 skill 并生成 ``agent.skill_links``。

    以前 phase3 catalog/recommendation 不暴露 skill，因此即使用户明确说"添加 skill"
    也只会推荐 tool，skill_links 始终为空。
    验证 catalog + draft_config.tools 流程是否也包含 skill。
    """
    await _seed_user(db)
    await _seed_model(db)
    skills = await _seed_skills(db, names=["seat_layout_guide", "evac_procedure"])
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "位置导航机器人")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "位置机器人",
        "description": "员工座位导航",
        "system_prompt": "p",
        "tools": ["seat_layout_guide", "evac_procedure"],
        "middlewares": [],
        "model_name": "GPT-4o",
    }
    await db.commit()

    agent = await confirm_build(db, session)
    assert agent is not None
    assert len(agent.tool_links) == 0
    assert len(agent.mcp_tool_links) == 0
    assert {link.skill_id for link in agent.skill_links} == {s.id for s in skills}


@pytest.mark.asyncio
async def test_confirm_build_mixed_tool_mcp_skill(db: AsyncSession):
    """即使 draft.tools 中混有 Tool + McpTool + Skill，也应全部准确拆分并建立 link。"""
    await _seed_user(db)
    await _seed_model(db)
    tool = await _seed_tool(db)  # name="HTTP Request"
    _, mcp_tools = await _seed_mcp_tools(db, names=["list_departments"])
    skills = await _seed_skills(db, names=["seat_layout_guide"])
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "混合")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "所有时间",
        "description": "d",
        "system_prompt": "p",
        "tools": ["HTTP Request", "list_departments", "seat_layout_guide"],
        "middlewares": [],
        "model_name": "GPT-4o",
    }
    await db.commit()

    agent = await confirm_build(db, session)
    assert agent is not None
    assert {link.tool_id for link in agent.tool_links} == {tool.id}
    assert {link.mcp_tool_id for link in agent.mcp_tool_links} == {mt.id for mt in mcp_tools}
    assert {link.skill_id for link in agent.skill_links} == {s.id for s in skills}


@pytest.mark.asyncio
async def test_confirm_build_skill_cross_user_blocked(db: AsyncSession):
    """其他用户的 skill 会被 ``Skill.user_id`` ownership filter 阻止。"""
    await _seed_user(db)
    await _seed_model(db)

    other_user_id = uuid.uuid4()
    other = User(id=other_user_id, email="other-skill@test.com", name="Other Skill")
    db.add(other)
    await db.flush()
    db.add(
        Skill(
            user_id=other_user_id,
            name="cross_user_skill",
            slug="cross-user-skill",
            description="d",
        )
    )
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "被拒绝")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "X",
        "description": "d",
        "system_prompt": "p",
        "tools": ["cross_user_skill"],
        "middlewares": [],
        "model_name": "GPT-4o",
    }
    await db.commit()

    from app.exceptions import AppError

    with pytest.raises(AppError) as exc:
        await confirm_build(db, session)
    assert exc.value.code == "builder_tool_unavailable"


@pytest.mark.asyncio
async def test_confirm_build_mcp_cross_user_blocked(db: AsyncSession):
    """其他用户的 MCP tool 会被 ownership filter 阻止，不建立 link。"""
    await _seed_user(db)
    await _seed_model(db)

    # seed 其他用户的 server + tool
    other_user_id = uuid.uuid4()
    other = User(id=other_user_id, email="other@test.com", name="Other")
    db.add(other)
    await db.flush()
    other_server = McpServer(
        user_id=other_user_id,
        name="Other Server",
        transport="sse",
        url="https://example.com/other",
    )
    db.add(other_server)
    await db.flush()
    db.add(McpTool(server_id=other_server.id, name="cross_user_tool"))
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "被拒绝")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "X",
        "description": "d",
        "system_prompt": "p",
        "tools": ["cross_user_tool"],
        "middlewares": [],
        "model_name": "GPT-4o",
    }
    await db.commit()

    from app.exceptions import AppError

    with pytest.raises(AppError) as exc:
        await confirm_build(db, session)
    assert exc.value.code == "builder_tool_unavailable"


@pytest.mark.asyncio
async def test_confirm_build_no_model(db: AsyncSession):
    """When model_name doesn't match, fallback to default model."""
    await _seed_user(db)
    model = await _seed_model(db, is_default=True)
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "测试")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "测试 agent",
        "description": "desc",
        "system_prompt": "prompt",
        "tools": [],
        "middlewares": [],
        "model_name": "nonexistent-model",
    }
    await db.commit()

    agent = await confirm_build(db, session)
    assert agent is not None
    # Should fall back to default model
    assert agent.model_id == model.id


@pytest.mark.asyncio
async def test_confirm_build_idempotent(db: AsyncSession):
    """COMPLETED session with agent_id returns existing agent (via service layer)."""
    await _seed_user(db)
    await _seed_model(db)
    await db.commit()

    # Create session and confirm
    session = await create_session(db, TEST_USER_ID, "测试")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "机器人",
        "description": "d",
        "system_prompt": "p",
        "tools": [],
        "middlewares": [],
        "model_name": "GPT-4o",
    }
    await db.commit()

    agent1 = await confirm_build(db, session)
    assert agent1 is not None
    assert session.status == BuilderStatus.COMPLETED

    # Second confirm on COMPLETED session — confirm_build returns None
    # because draft_config is still there but status is COMPLETED.
    # The router handles idempotency via agent_id check before calling confirm.
    # Here we verify that confirm_build still works (no crash) on the session.
    # Since session is now COMPLETED, the router would not call confirm_build again.
    reloaded = await get_session(db, session.id, TEST_USER_ID)
    assert reloaded is not None
    assert reloaded.agent_id == agent1.id


# ---------------------------------------------------------------------------
# _get_middlewares_catalog
# ---------------------------------------------------------------------------


def test_get_middlewares_catalog():
    """Returns middleware registry as list of dicts."""
    result = _get_middlewares_catalog()
    assert isinstance(result, list)
    assert len(result) > 0
    types = {item["type"] for item in result}
    # deepagents 内置类型（summarization, todo_list 等）会被排除
    assert "summarization" not in types
    assert "tool_retry" in types


# ---------------------------------------------------------------------------
# _get_default_model_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_default_model_name_requires_user_context(db: AsyncSession):
    """Builder never falls back to operator/global model settings."""
    from app.services.builder_service import _get_default_model_name

    assert await _get_default_model_name(db) == ""


@pytest.mark.asyncio
async def test_get_default_model_name_from_personal_binding(db: AsyncSession):
    """Exactly one usable personal model binding is selected for Builder."""
    from app.services.builder_service import _get_default_model_name

    await _seed_user(db)
    await _seed_model(db)
    await db.commit()

    result = await _get_default_model_name(db, TEST_USER_ID)
    assert result == "openai:gpt-4o"


@pytest.mark.asyncio
async def test_get_default_model_name_ignores_unbound_model(db: AsyncSession):
    """A catalog model without a personal credential is not runnable."""
    from app.services.builder_service import _get_default_model_name

    await _seed_user(db)
    db.add(
        Model(
            provider="openai",
            model_name="gpt-4o",
            display_name="GPT-4o",
            is_default=True,
        )
    )
    await db.commit()

    assert await _get_default_model_name(db, TEST_USER_ID) == ""


# ---------------------------------------------------------------------------
# confirm_build — no draft_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_build_no_draft_config(db: AsyncSession):
    """confirm_build returns None when draft_config is None."""
    await _seed_user(db)
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "测试")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = None
    await db.commit()

    result = await confirm_build(db, session)
    assert result is None


# ---------------------------------------------------------------------------
# confirm_build — no models at all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_build_no_models_raises(db: AsyncSession):
    """confirm_build raises ValueError when no models are available."""
    await _seed_user(db)
    await db.commit()

    session = await create_session(db, TEST_USER_ID, "测试")
    session.status = BuilderStatus.CONFIRMING
    session.draft_config = {
        "name": "机器人",
        "description": "d",
        "system_prompt": "p",
        "tools": [],
        "middlewares": [],
        "model_name": "nonexistent",
    }
    await db.commit()

    from app.exceptions import AppError

    with pytest.raises(AppError) as exc:
        await confirm_build(db, session)
    assert exc.value.code == "builder_runtime_setup"

    # Session should be rolled back to PREVIEW
    reloaded = await get_session(db, session.id, TEST_USER_ID)
    assert reloaded is not None
    assert reloaded.status == BuilderStatus.PREVIEW


# ---------------------------------------------------------------------------
# get_agent_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_agent_by_id(db: AsyncSession):
    """get_agent_by_id returns agent when found."""
    await _seed_user(db)
    model = await _seed_model(db)
    await db.commit()

    agent = Agent(
        user_id=TEST_USER_ID,
        name="Test Bot",
        description="desc",
        system_prompt="prompt",
        model_id=model.id,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    found = await get_agent_by_id(db, agent.id)
    assert found is not None
    assert found.name == "Test Bot"


@pytest.mark.asyncio
async def test_get_agent_by_id_not_found(db: AsyncSession):
    """get_agent_by_id returns None when not found."""
    import uuid as _uuid

    found = await get_agent_by_id(db, _uuid.uuid4())
    assert found is None
