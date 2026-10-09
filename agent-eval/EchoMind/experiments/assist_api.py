from fastapi import APIRouter
from pydantic import Field
from .api import Input, execute, service
from .retrieval_api import retrieval, acquire
from .assist import AssistService, TYPES

router=APIRouter(prefix='/experiments',tags=['AI Assistance'])

class AssistInput(Input):
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    provider_session_id: str

class KnowledgeInput(AssistInput):
    scenario: str = Field(min_length=5,max_length=1500)
    facts: str = Field(default='',max_length=12000)

class TestsInput(AssistInput):
    index_id: str
    count: int = Field(default=8,ge=1,le=12,strict=True)
    question_types: list[str] = Field(min_length=1,max_length=5)

class TraceInput(AssistInput):
    case_id: str
    run_id: str | None = None
    comparison_id: str | None = None

class BindingInput(Input):
    judge_provider_session_id: str | None = None

@router.get('/ai/provider-options')
def options():
    providers=service().providers
    return [providers.public(providers.get(s.provider_session_id)) for s in providers.store.list('provider_sessions') if s.status!='DELETED']

@router.post('/provider-sessions/{identifier}/judge')
def bind(identifier:str,body:BindingInput):
    providers=service().providers
    return providers.public(execute(providers.bind_judge,identifier,body.judge_provider_session_id))

@router.post('/ai/knowledge')
async def knowledge(body:KnowledgeInput):
    return await acquire(AssistService(retrieval()).knowledge(**body.model_dump()))

@router.post('/ai/tests')
async def tests(body:TestsInput):
    if not set(body.question_types)<=set(TYPES):
        from fastapi import HTTPException
        raise HTTPException(422,'Unsupported question type')
    return await acquire(AssistService(retrieval()).tests(**body.model_dump()))

@router.post('/ai/trace')
async def trace(body:TraceInput):
    return await acquire(AssistService(retrieval()).trace(**body.model_dump()))

@router.get('/ai/drafts')
def history():
    return [{'draft_id':d.draft_id,'kind':d.kind,'created_at':d.created_at} for d in
            sorted(retrieval().store.list('ai_drafts'),key=lambda d:d.created_at,reverse=True)[:50]]

@router.get('/ai/drafts/{identifier}')
def draft(identifier:str):
    return execute(retrieval().store.get,'ai_drafts',identifier)
