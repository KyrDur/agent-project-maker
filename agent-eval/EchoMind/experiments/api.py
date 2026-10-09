"""Small backend routes; requests never accept credentials or observed evidence."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from evaluation.config import EvaluationConfig
from .models import Status
from .providers import ProviderSessionInput, ProviderFailure

router = APIRouter(prefix="/experiments",tags=["Experiments"])
_service_provider = None

def configure(provider):
    global _service_provider
    _service_provider = provider

def service():
    if _service_provider is None:
        raise HTTPException(503,"Experiment backend not initialized")
    try:
        return _service_provider()
    except ValueError:
        raise HTTPException(409,"Experiment backend configuration invalid") from None

def execute(fn,*args,**kwargs):
    from .retrieval_embeddings import EmbeddingFailure
    try:
        return fn(*args,**kwargs)
    except EmbeddingFailure as error:
        raise HTTPException(409,str(error)) from None
    except ProviderFailure as error:
        raise HTTPException(409,error.code) from None
    except FileNotFoundError:
        raise HTTPException(404,"Artifact not found") from None
    except (ValueError,StopIteration) as error:
        if str(error) == 'PUBLIC_PROVIDER_ENDPOINT_NOT_ALLOWED':
            raise HTTPException(422, 'PUBLIC_PROVIDER_ENDPOINT_NOT_ALLOWED') from None
        raise HTTPException(409,"Experiment validation or lifecycle constraint rejected") from None

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class EvalSetInput(Input):
    eval_set_id: str | None = None
    eval_set_version: int = Field(default=1,ge=1)
    dialog_cases: list[dict] = Field(default_factory=list)
    intent_cases: list[dict] = Field(default_factory=list)
    config: EvaluationConfig = Field(default_factory=EvaluationConfig)
    metadata: dict = Field(default_factory=dict)

class RunInput(Input):
    provider_session_id: str
    eval_set_id: str
    eval_set_version: int | None = Field(default=None,ge=1)
    run_type: Literal["BASELINE","RETEST"] = "BASELINE"
    parent_run_id: str | None = None
    decision_id: str | None = None
    change_ids: list[str] = Field(default_factory=list)

class DecisionInput(Input):
    related_run_id: str
    selected_case_ids: list[str]
    root_cause_suggestion: str | None = None
    strategy_suggestion: str | None = None
    alternatives: list[dict] = Field(default_factory=list)

class ConfirmationInput(Input):
    user_confirmed_root_cause: str
    root_cause_reason: str
    alternatives: list[dict] = Field(default_factory=list)
    selected_strategy: str
    selection_reason: str
    expected_benefit: str
    possible_side_effects: str
    confirmed_by: str

class ChangeInput(Input):
    decision_id: str
    skill_id: str
    rule_body: str
    before_hash: str
    change_type: Literal["SKILL_RULE","PROMPT","KNOWLEDGE"] = "SKILL_RULE"
    change_scope: str = "ONE_SKILL_RULE_BODY"

class ReviewInput(Input):
    case_id: str
    human_final_status: Status
    human_reason: str
    reviewer: str

class ComparisonInput(Input):
    baseline_run_id: str
    retest_run_id: str

@router.post("/provider-sessions")
def create_provider_session(body:ProviderSessionInput):
    providers=service().providers
    return providers.public(execute(providers.create,body.model_dump(exclude={"api_key"}),body.api_key.get_secret_value()))

@router.get("/provider-sessions/{identifier}")
def get_provider_session(identifier:str):
    providers=service().providers
    return providers.public(execute(providers.get,identifier))

@router.delete("/provider-sessions/{identifier}")
def delete_provider_session(identifier:str):
    providers=service().providers
    return providers.public(execute(providers.delete,identifier))

@router.post("/provider-sessions/{identifier}/test")
async def test_provider_session(identifier:str):
    try:
        return await service().providers.test(identifier)
    except FileNotFoundError:
        raise HTTPException(404,"ProviderSession not found") from None

@router.post("/provider-sessions/{identifier}/test-tools")
async def test_provider_tools(identifier:str):
    try:
        return await service().providers.test_tools(identifier)
    except FileNotFoundError:
        raise HTTPException(404,"ProviderSession not found") from None
    except ProviderFailure as error:
        raise HTTPException(409,error.code) from None

@router.post("/evalsets")
def create_evalset(body:EvalSetInput):
    return execute(service().create_eval_set,**body.model_dump(exclude={"config"}),config=body.config)

@router.get("/evalsets/{identifier}")
def get_evalset(identifier:str,version:int | None=None):
    return execute(service().store.get,"evalsets",identifier,version)

@router.post("/runs")
async def create_run(body:RunInput):
    try:
        return await service().run(**body.model_dump())
    except ProviderFailure as error:
        raise HTTPException(409,error.code) from None
    except FileNotFoundError:
        raise HTTPException(404,"Artifact not found") from None
    except ValueError:
        raise HTTPException(409,"Run creation constraints rejected") from None

@router.get("/runs/{identifier}")
def get_run(identifier:str):
    return execute(service().result_view,identifier)

@router.post("/decisions")
def create_decision(body:DecisionInput):
    data=body.model_dump()
    run_id=data.pop("related_run_id")
    return execute(service().create_decision,run_id,**data)

@router.post("/decisions/{identifier}/confirm")
def confirm_decision(identifier:str,body:ConfirmationInput):
    return execute(service().confirm_decision,identifier,**body.model_dump())

@router.post("/changes")
def create_change(body:ChangeInput):
    return execute(service().propose_change,**body.model_dump())

@router.post("/changes/{identifier}/apply")
def apply_change(identifier:str):
    return execute(service().apply_change,identifier)

@router.post("/changes/{identifier}/rollback")
def rollback_change(identifier:str):
    return execute(service().rollback,identifier)

@router.post("/runs/{identifier}/reviews")
def create_review(identifier:str,body:ReviewInput):
    return execute(service().review,identifier,body.case_id,body.human_final_status,body.human_reason,body.reviewer)

@router.post("/comparisons")
def create_comparison(body:ComparisonInput):
    return execute(service().compare,body.baseline_run_id,body.retest_run_id)

@router.get("/artifacts/{group}")
def list_artifacts(group:str,offset:int=Query(default=0,ge=0),limit:int=Query(default=50,ge=1,le=100)):
    """Read-only summaries for UI recovery; no new experimental semantics."""
    if group not in {'provider_sessions','evalsets','runs','decisions','changes','comparisons','reviews'}:
        raise HTTPException(404,'Unknown artifact group')
    backend=service()
    objects=execute(backend.store.list,group)
    objects.sort(key=lambda obj:obj.created_at,reverse=True)
    fields={
        'evalsets':('eval_set_id','eval_set_version','created_at','metadata'),
        'runs':('run_id','run_type','created_at','status','eval_set_id','provider_session_id',
                'parent_run_id','decision_id','applied_change_ids','started_at','finished_at'),
        'decisions':('decision_id','related_run_id','created_at','status'),
        'changes':('change_id','decision_id','baseline_run_id','affected_component','created_at',
                   'implemented_status','rollback_status'),
        'comparisons':('comparison_id','baseline_run_id','retest_run_id','created_at',
                      'comparable','comparison_completeness'),
        'reviews':('review_id','run_id','case_id','revision','created_at'),
    }
    items=[]
    for obj in objects[offset:offset+limit]:
        if group=='provider_sessions':
            item=backend.providers.public(backend.providers.get(obj.provider_session_id))
        else:
            data=obj.model_dump(mode='json')
            item={key:data[key] for key in fields[group]}
        items.append(item)
    return {'items':items,'total':len(objects),'offset':offset,'limit':limit}

@router.get("/{group}/{identifier}")
def get_artifact(group:str,identifier:str):
    if group not in {"decisions","changes","reviews","comparisons"}:
        raise HTTPException(404,"Unknown artifact group")
    return execute(service().store.get,group,identifier)


def install_validation_handler(app):
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request,error):
        # Default FastAPI errors echo rejected input values, which may include a Key.
        return JSONResponse(status_code=422,content={"detail":"Invalid request"})
