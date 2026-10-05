"""Explicit authored decisions for existing controlled experiment fixtures."""

import uuid
from copy import deepcopy

from app.schemas.agent_project import ProjectDecision, ProjectRequirements
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_practice as practice
from app.services import agent_project_service as projects
from app.services.system_credential_resolver import ResolvedSystemModel


async def fixed_judge(*_args):
    return ResolvedSystemModel(
        provider="openai", model_name="controlled-judge", api_key="test-only", base_url=None
    )


async def fixed_examinee(*_args):
    from app.agent_runtime.model_factory import create_chat_model

    return create_chat_model(
        "openai", "test", api_key="controlled-test-only", allow_env_fallback=False
    ), "controlled-test-only"


async def author_practice(db, agent, user_id, dataset_id=None, version_id=None):
    project = await projects.require_project(db, agent.id, user_id)
    saved_spec = deepcopy(project.eval_spec_json)
    if not practice.requirements(project):
        await practice.write_requirements(
            db,
            agent.id,
            user_id,
            ProjectRequirements(
                goal="Complete the supplied task",
                inputs="Frozen test input",
                deliverables="Task answer",
                business_rules="Follow explicit test rules",
                success_conditions="Satisfy the stored expectations",
            ),
        )
    if saved_spec is not None:
        project.eval_spec_json = saved_spec
        await db.commit()
    version = next(
        v
        for v in await projects.list_versions(db, agent.id, user_id)
        if v.id == version_id or (version_id is None and v.version_number == 1)
    )
    for stage in ("requirements", "capabilities"):
        await practice.record_decision(
            db,
            agent.id,
            user_id,
            ProjectDecision(
                stage=stage,
                choice="Use the frozen task and capability design",
                reason="Controlled experiment fixture",
                version_id=version.id,
            ),
        )
    if dataset_id:
        dataset = await evaluation.get_set(db, project.id, uuid.UUID(str(dataset_id)))
        await practice.record_decision(
            db,
            agent.id,
            user_id,
            ProjectDecision(
                stage="case_review",
                choice="Reviewed the stored expectations",
                reason="Each case has a concrete success condition",
                version_id=version.id,
                eval_set_id=dataset.id,
                case_ids=[uuid.UUID(c["id"]) for c in dataset.cases_json if c.get("enabled", True)],
            ),
        )
