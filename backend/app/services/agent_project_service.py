"""Project persistence only. No builder, runtime or evaluation execution."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.error_codes import agent_not_found
from app.exceptions import AppError
from app.marketplace.payloads import canonical_json_hash, scan_payload
from app.marketplace.redaction import is_sensitive_key
from app.models.agent import AGENT_RUNTIME_PROFILE_STANDARD, Agent
from app.models.agent_project import AgentProject, AgentProjectEvalSet, AgentProjectVersion, utcnow
from app.models.builder_session import BuilderSession
from app.models.model import Model
from app.schemas.agent_project import AgentProjectVersionResponse, VersionCreate, VersionCreated


def snapshot_value(value: Any, key: str = "") -> Any:
    """Copy JSON without credential values; reuse the existing secret scanner.

    UUIDs are local references, not credential payloads. Credential relationships
    are never loaded. Numeric configuration such as max_tokens remains intact.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if key == "credential_bindings" and isinstance(value, dict):
        bindings = {}
        for name, reference in value.items():
            try:
                bindings[str(name)] = str(uuid.UUID(str(reference)))
            except ValueError:
                bindings[str(name)] = "<redacted>"
        return bindings
    if is_sensitive_key(key) and not (
        key in {"max_tokens", "max_output_tokens", "max_completion_tokens"}
        and isinstance(value, int)
    ):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): snapshot_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [snapshot_value(v, key) for v in value]
    if isinstance(value, str) and scan_payload({key: value}):
        return "<redacted>"
    return value


async def owned_agent(db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID) -> Agent:
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.user_id == user_id,
            Agent.runtime_profile == AGENT_RUNTIME_PROFILE_STANDARD,
        )
    )
    if agent is None:
        raise agent_not_found()
    return agent


async def get_project(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID
) -> AgentProject | None:
    await owned_agent(db, agent_id, user_id)
    return await db.scalar(
        select(AgentProject).where(
            AgentProject.agent_id == agent_id, AgentProject.user_id == user_id
        )
    )


async def require_project(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID
) -> AgentProject:
    project = await get_project(db, agent_id, user_id)
    if project is None:
        raise AppError(code="agent_project_not_found", message="Project not found", status=404)
    return project


async def build_snapshot(
    db: AsyncSession, agent: Agent, planned_tools: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    await db.refresh(agent, ["model", "tool_links", "skill_links", "mcp_tool_links"])
    # Retain native Agent field names. This is an observation, not a runtime config format.
    config = {
        name: getattr(agent, name)
        for name in (
            "id",
            "name",
            "description",
            "system_prompt",
            "runtime_name",
            "identity_mode",
            "model_id",
            "llm_credential_id",
            "model_params",
            "model_fallback_list",
            "middleware_configs",
            "runtime_policy",
            "opener_questions",
        )
    }
    fallback_ids = [uuid.UUID(value) for value in (agent.model_fallback_list or [])]
    models = list((await db.scalars(select(Model).where(Model.id.in_(fallback_ids)))).all())

    def model_config(model: Model) -> dict[str, Any]:
        return {
            name: getattr(model, name)
            for name in (
                "id",
                "provider",
                "model_name",
                "base_url",
                "default_credential_id",
                "context_window",
                "max_output_tokens",
            )
        }

    config["model"] = model_config(agent.model)
    config["fallback_models"] = [model_config(m) for m in sorted(models, key=lambda m: str(m.id))]
    config["tool_links"] = [
        {
            "tool_id": link.tool_id,
            "definition_key": link.tool.definition_key,
            "name": link.tool.name,
            "parameters": link.tool.parameters,
            "credential_id": link.tool.credential_id,
            "enabled": link.tool.enabled,
        }
        for link in sorted(agent.tool_links, key=lambda link: str(link.tool_id))
    ]
    config["skill_links"] = [
        {
            "skill_id": link.skill_id,
            "config": link.config,
            "slug": link.skill.slug,
            "version": link.skill.version,
            "current_revision_id": link.skill.current_revision_id,
            "content_hash": link.skill.content_hash,
            "execution_profile": link.skill.execution_profile,
        }
        for link in sorted(agent.skill_links, key=lambda link: str(link.skill_id))
    ]
    # MCP connection configuration can hold literal secrets. Keep references and
    # cached tool schemas; never serialize server headers, env, args or credentials.
    config["mcp_tool_links"] = [
        {
            "mcp_tool_id": link.mcp_tool_id,
            "server_id": link.mcp_tool.server_id,
            "name": link.mcp_tool.name,
            "input_schema": link.mcp_tool.input_schema,
            "enabled": link.mcp_tool.enabled,
        }
        for link in sorted(agent.mcp_tool_links, key=lambda link: str(link.mcp_tool_id))
    ]
    config["sub_agent_links"] = [
        {"sub_agent_id": link.sub_agent_id, "position": link.position}
        for link in agent.sub_agent_links
    ]
    if planned_tools:
        config["planned_tools"] = planned_tools
    return snapshot_value({"schema_version": 1, "agent": config})


async def create_project(db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID) -> AgentProject:
    agent = await owned_agent(db, agent_id, user_id)
    existing = await get_project(db, agent_id, user_id)
    if existing is not None:
        return existing
    builder_id = await db.scalar(
        select(BuilderSession.id)
        .where(BuilderSession.agent_id == agent_id, BuilderSession.user_id == user_id)
        .order_by(BuilderSession.created_at.desc())
        .limit(1)
    )
    planned_tools: list[dict[str, Any]] | None = None
    if builder_id:
        builder_session = await db.get(BuilderSession, builder_id)
        planned_tools = (
            (builder_session.draft_config or {}).get("planned_tools")
            if builder_session
            else None
        )
    snapshot = await build_snapshot(db, agent, planned_tools)
    # The unique agent_id constraint resolves concurrent creates. The savepoint
    # keeps project + V1 atomic and lets a losing request return the winner.
    try:
        async with db.begin_nested():
            project = AgentProject(
                agent_id=agent.id,
                user_id=agent.user_id,
                title=snapshot_value(agent.name),
                builder_session_id=builder_id,
            )
            db.add(project)
            await db.flush()
            db.add(
                AgentProjectVersion(
                    project_id=project.id,
                    version_number=1,
                    status="original",
                    snapshot_json=snapshot,
                    config_hash=canonical_json_hash(snapshot),
                )
            )
            await db.flush()
    except IntegrityError:
        existing = await get_project(db, agent_id, user_id)
        if existing is None:
            raise
        return existing
    await db.commit()
    return project


async def list_versions(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID
) -> list[AgentProjectVersion]:
    project = await require_project(db, agent_id, user_id)
    return list(
        (
            await db.scalars(
                select(AgentProjectVersion)
                .where(AgentProjectVersion.project_id == project.id)
                .order_by(AgentProjectVersion.version_number.desc())
            )
        ).all()
    )


async def get_version(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, version_id: uuid.UUID
) -> AgentProjectVersion:
    project = await require_project(db, agent_id, user_id)
    version = await db.scalar(
        select(AgentProjectVersion).where(
            AgentProjectVersion.id == version_id, AgentProjectVersion.project_id == project.id
        )
    )
    if version is None:
        raise AppError(
            code="agent_project_version_not_found", message="Version not found", status=404
        )
    return version


async def list_eval_sets(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID
) -> list[AgentProjectEvalSet]:
    project = await require_project(db, agent_id, user_id)
    return list(
        (
            await db.scalars(
                select(AgentProjectEvalSet)
                .where(AgentProjectEvalSet.project_id == project.id)
                .order_by(AgentProjectEvalSet.created_at)
            )
        ).all()
    )


async def save_eval_set(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    name: str,
    cases_json: list[dict[str, Any]],
    rubric_json: dict[str, Any] | None = None,
    frozen: bool = False,
    eval_set_id: uuid.UUID | None = None,
) -> AgentProjectEvalSet:
    project = await require_project(db, agent_id, user_id)
    if eval_set_id is None:
        row = AgentProjectEvalSet(project_id=project.id)
        db.add(row)
    else:
        row = await editable_eval_set(db, project.id, eval_set_id)
    row.name, row.cases_json, row.rubric_json, row.frozen = name, cases_json, rubric_json, frozen
    await db.commit()
    return row


async def editable_eval_set(
    db: AsyncSession, project_id: uuid.UUID, eval_set_id: uuid.UUID
) -> AgentProjectEvalSet:
    row = await db.scalar(
        select(AgentProjectEvalSet)
        .where(AgentProjectEvalSet.id == eval_set_id, AgentProjectEvalSet.project_id == project_id)
        .with_for_update()
    )
    if row is None:
        raise AppError(
            code="agent_project_eval_set_not_found", message="Eval set not found", status=404
        )
    if row.frozen:
        raise AppError(
            code="agent_project_eval_set_frozen", message="Eval set is frozen", status=409
        )
    return row


async def delete_eval_set(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, eval_set_id: uuid.UUID
) -> None:
    project = await require_project(db, agent_id, user_id)
    await db.delete(await editable_eval_set(db, project.id, eval_set_id))
    await db.commit()


async def lock_project(db: AsyncSession, project: AgentProject) -> None:
    # A real write lock also serializes SQLite, where SELECT FOR UPDATE is ignored.
    await db.execute(
        update(AgentProject).where(AgentProject.id == project.id).values(updated_at=utcnow())
    )


async def create_version(
    db: AsyncSession, agent_id: uuid.UUID, user_id: uuid.UUID, body: VersionCreate
) -> VersionCreated:
    project = await require_project(db, agent_id, user_id)
    await lock_project(db, project)
    prior = await db.scalar(
        select(AgentProjectVersion).where(
            AgentProjectVersion.project_id == project.id,
            AgentProjectVersion.request_id == body.request_id,
        )
    )
    if prior is not None:
        await db.commit()
        return VersionCreated(
            outcome="replayed", version=AgentProjectVersionResponse.model_validate(prior)
        )
    latest = await db.scalar(
        select(AgentProjectVersion)
        .where(AgentProjectVersion.project_id == project.id)
        .order_by(AgentProjectVersion.version_number.desc())
        .limit(1)
    )
    agent = await owned_agent(db, agent_id, user_id)
    await db.refresh(agent)
    planned_tools: list[dict[str, Any]] | None = None
    if project.builder_session_id:
        builder_session = await db.get(BuilderSession, project.builder_session_id)
        planned_tools = (
            (builder_session.draft_config or {}).get("planned_tools")
            if builder_session
            else None
        )
    snapshot = await build_snapshot(db, agent, planned_tools)
    digest = canonical_json_hash(snapshot)
    if latest is not None and latest.config_hash == digest:
        await db.commit()
        return VersionCreated(
            outcome="unchanged", version=AgentProjectVersionResponse.model_validate(latest)
        )
    version = await append_snapshot_version(
        db,
        project,
        snapshot,
        parent_id=latest.id if latest else None,
        request_id=body.request_id,
        summary=body.change_summary,
    )
    await db.commit()
    return VersionCreated(
        outcome="created", version=AgentProjectVersionResponse.model_validate(version)
    )


async def append_snapshot_version(
    db: AsyncSession,
    project: AgentProject,
    snapshot: dict[str, Any],
    *,
    parent_id: uuid.UUID | None,
    request_id: uuid.UUID,
    summary: str | None,
) -> AgentProjectVersion:
    """Caller holds the project write lock; never read or update a live Agent."""
    prior = await db.scalar(
        select(AgentProjectVersion).where(
            AgentProjectVersion.project_id == project.id,
            AgentProjectVersion.request_id == request_id,
        )
    )
    if prior is not None:
        return prior
    latest = await db.scalar(
        select(AgentProjectVersion)
        .where(
            AgentProjectVersion.project_id == project.id,
        )
        .order_by(AgentProjectVersion.version_number.desc())
        .limit(1)
    )
    version = AgentProjectVersion(
        project_id=project.id,
        version_number=latest.version_number + 1 if latest else 1,
        parent_version_id=parent_id,
        status="candidate",
        snapshot_json=snapshot,
        config_hash=canonical_json_hash(snapshot),
        request_id=request_id,
        change_summary=snapshot_value(summary),
    )
    db.add(version)
    await db.flush()
    return version
