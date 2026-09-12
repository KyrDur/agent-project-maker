from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, get_current_user, get_db, verify_csrf
from app.exceptions import AppError
from app.schemas.agent_project import (
    AgentProjectResponse,
    AgentProjectVersionResponse,
    AgentProjectVersionSummary,
    EvalGenerationRequest,
    EvalRunCreate,
    EvalRunResponse,
    EvalSetResponse,
    EvalSetWrite,
    VersionCreate,
    VersionCreated,
)
from app.schemas.agent_project_optimization import OptimizeRequest
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_service as service


class ProjectRoute(APIRoute):
    """Validation errors must not echo authored cases or configuration values."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                raise AppError(
                    code="VALIDATION_ERROR", message="Invalid project request", status=422
                ) from exc

        return safe_handler


router = APIRouter(
    route_class=ProjectRoute,
    prefix="/api/agents/{agent_id}/project",
    tags=["agent-projects"],
    dependencies=[Depends(verify_csrf)],
)


@router.get("", response_model=AgentProjectResponse | None)
async def get_project(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.get_project(db, agent_id, user.id)


@router.post("/create", response_model=AgentProjectResponse)
async def create_project(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.create_project(db, agent_id, user.id)


@router.get("/versions", response_model=list[AgentProjectVersionSummary])
async def list_versions(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services.agent_project_optimization import version_responses

    rows = await service.list_versions(db, agent_id, user.id)
    return await version_responses(db, agent_id, user.id, rows)


@router.get("/versions/{version_id}", response_model=AgentProjectVersionResponse)
async def get_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services.agent_project_optimization import version_responses

    row = await service.get_version(db, agent_id, user.id, version_id)
    return (await version_responses(db, agent_id, user.id, [row]))[0]


@router.post("/versions", response_model=VersionCreated)
async def create_version(
    agent_id: uuid.UUID,
    body: VersionCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.create_version(db, agent_id, user.id, body)


@router.get("/compare")
async def compare_versions(
    agent_id: uuid.UUID,
    left: uuid.UUID,
    right: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await evaluation.compare_versions(db, agent_id, user.id, left, right)


@router.get("/eval-sets", response_model=list[EvalSetResponse])
async def list_eval_sets(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.list_eval_sets(db, agent_id, user.id)


@router.post("/eval-sets", response_model=EvalSetResponse, status_code=201)
async def create_eval_set(
    agent_id: uuid.UUID,
    body: EvalSetWrite,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await evaluation.write_set(db, agent_id, user.id, body)


@router.put("/eval-sets/{set_id}", response_model=EvalSetResponse)
async def update_eval_set(
    agent_id: uuid.UUID,
    set_id: uuid.UUID,
    body: EvalSetWrite,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await evaluation.write_set(db, agent_id, user.id, body, set_id)


@router.delete("/eval-sets/{set_id}", status_code=204)
async def delete_eval_set(
    agent_id: uuid.UUID,
    set_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    await evaluation.remove_set(db, agent_id, user.id, set_id)


@router.post("/eval-runs", response_model=EvalRunResponse, status_code=202)
async def create_eval_run(
    agent_id: uuid.UUID,
    body: EvalRunCreate,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    row = await evaluation.create_run(db, agent_id, user.id, body)
    if row.status == "pending":
        background.add_task(evaluation.execute_run, row.id, agent_id, user.id)
    return row


@router.get("/eval-runs", response_model=list[EvalRunResponse])
async def list_eval_runs(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await evaluation.list_runs(db, agent_id, user.id)


@router.get("/eval-runs/{run_id}", response_model=EvalRunResponse)
async def get_eval_run(
    agent_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await evaluation.get_run(db, agent_id, user.id, run_id)


@router.post("/eval-spec/generate")
async def generate_eval_spec(
    agent_id: uuid.UUID,
    body: EvalGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services.agent_project_semantic import generate

    return await generate(db, agent_id, user.id, body.version_id)


@router.post("/eval-sets/generate", response_model=EvalSetResponse, status_code=201)
async def generate_eval_set(
    agent_id: uuid.UUID,
    body: EvalGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services.agent_project_semantic import generate

    return await generate(db, agent_id, user.id, body.version_id, cases=True)


@router.post("/eval-runs/{run_id}/analyze")
async def analyze_eval_run(
    agent_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services.agent_project_optimization import analyze

    return await analyze(db, agent_id, user.id, run_id)


@router.post("/eval-runs/{run_id}/optimize", status_code=202)
async def optimize_eval_run(
    agent_id: uuid.UUID,
    run_id: uuid.UUID,
    body: OptimizeRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services.agent_project_optimization import execute_optimization, start

    state, schedule = await start(db, agent_id, user.id, run_id, body.request_id)
    if schedule:
        background.add_task(
            execute_optimization, agent_id, user.id, uuid.UUID(state["root_run_id"])
        )
    return state
