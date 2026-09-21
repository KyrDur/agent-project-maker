from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, get_current_user, get_db, verify_csrf
from app.exceptions import AppError
from app.schemas.agent_project import (
    AgentProjectResponse,
    AgentProjectVersionResponse,
    AgentProjectVersionSummary,
    EvalCaseGenerationRequest,
    EvalGenerationRequest,
    EvalRunCreate,
    EvalRunResponse,
    EvalSetResponse,
    EvalSetWrite,
    VersionCreate,
    VersionCreated,
)
from app.schemas.agent_project_optimization import OptimizeRequest, ProposalDecision
from app.schemas.agent_project_portfolio import ResumeRequest
from app.schemas.agent_project_report import EvaluationReports
from app.services import agent_project_evaluation as evaluation
from app.services import agent_project_portfolio as portfolio
from app.services import agent_project_service as service

public_router = APIRouter(tags=["agent-project-shares"])


@public_router.get("/api/project-shares/{project_id}/{token}")
async def read_project_share(
    project_id: uuid.UUID, token: str, response: Response, db: AsyncSession = Depends(get_db)
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return await portfolio.public_share(db, project_id, token)


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


@router.post("/eval-sets/{set_id}/quality", response_model=EvalSetResponse)
async def judge_eval_set(
    agent_id: uuid.UUID,
    set_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await evaluation.judge_set(db, agent_id, user.id, set_id)


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
    body: EvalCaseGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services.agent_project_semantic import generate

    return await generate(
        db,
        agent_id,
        user.id,
        body.version_id,
        cases=True,
        evaluation_focus=body.evaluation_focus,
        evaluation_focus_reason=body.evaluation_focus_reason,
    )


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
    del agent_id, run_id, body, background, db, user
    raise AppError(
        code="optimization_requires_user_proposal_decision",
        message="Generate proposals, accept one, then run regression.",
        status=410,
    )


@router.post("/eval-runs/{run_id}/proposals")
async def generate_optimization_proposal(
    agent_id: uuid.UUID,
    run_id: uuid.UUID,
    body: OptimizeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services import agent_project_proposals

    return await agent_project_proposals.generate(db, agent_id, user.id, run_id, body.request_id)


@router.post("/eval-runs/{run_id}/proposals/{proposal_id}/decision")
async def decide_optimization_proposal(
    agent_id: uuid.UUID,
    run_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: ProposalDecision,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services import agent_project_proposals

    return await agent_project_proposals.decide(
        db,
        agent_id,
        user.id,
        run_id,
        proposal_id,
        body.decision,
        body.decision_reason,
    )


@router.post(
    "/eval-runs/{run_id}/proposals/{proposal_id}/regression",
    response_model=EvalRunResponse,
    status_code=202,
)
async def run_proposal_regression(
    agent_id: uuid.UUID,
    run_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: OptimizeRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services import agent_project_proposals

    row = await agent_project_proposals.regression(
        db,
        agent_id,
        user.id,
        run_id,
        proposal_id,
        body.request_id,
    )
    if row.status == "pending":
        background.add_task(evaluation.execute_run, row.id, agent_id, user.id)
    return row


@router.get("/report")
async def get_report(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await portfolio.report(db, agent_id, user.id)


@router.get("/evaluation-reports", response_model=EvaluationReports)
async def evaluation_reports(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services.agent_project_report import list_reports

    return await list_reports(db, agent_id, user.id)


@router.post("/report/generate")
async def generate_report(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await portfolio.report(db, agent_id, user.id, save=True)


@router.post("/resume/generate")
async def generate_resume(
    agent_id: uuid.UUID,
    body: ResumeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await portfolio.resume(db, agent_id, user.id, body.style)


@router.post("/share")
async def create_project_share(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await portfolio.share(db, agent_id, user.id)


@router.delete("/share")
async def revoke_project_share(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return await portfolio.share(db, agent_id, user.id, revoke=True)


@router.get("/export")
async def export_project(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services.agent_project_portfolio_export import export_zip

    return Response(
        await export_zip(db, agent_id, user.id),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="agent-project.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/bootstrap", status_code=202)
async def bootstrap_builder_project(
    agent_id: uuid.UUID,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.services import builder_project_lifecycle

    project = await service.require_project(db, agent_id, user.id)
    if project.builder_session_id:
        background.add_task(builder_project_lifecycle.bootstrap, agent_id, user.id)
    return {"accepted": bool(project.builder_session_id)}
