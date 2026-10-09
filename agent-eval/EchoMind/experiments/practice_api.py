from fastapi import APIRouter
from pydantic import Field
from typing import Literal
from .api import Input, execute
from .retrieval_api import retrieval, acquire
from .retrieval_models import RetrievalConfig
from .practice_service import PracticeService
from .practice_models import InterviewAttempt

router=APIRouter(prefix='/experiments',tags=['Agent Eval Practice'])
def practice(): return PracticeService(retrieval())

class ChatInput(Input):
    provider_session_id: str
    index_id: str
    message: str = Field(min_length=1,max_length=5000)
    retrieval_config: RetrievalConfig = Field(default_factory=RetrievalConfig)
    conversation_id: str | None = Field(default=None,pattern=r'^[A-Za-z0-9_-]{1,128}$')

class CaseDraftInput(Input):
    expected_answer: str = Field(default='',max_length=5000)
    relevant_document_ids: list[str] = Field(default_factory=list,max_length=100)
    must_do: list[str] = Field(default_factory=list,max_length=20)
    must_not_do: list[str] = Field(default_factory=list,max_length=20)
    partition: Literal['DEBUG','HOLDOUT'] = 'DEBUG'
    confirmed: Literal[True]

class RepeatInput(Input):
    source_run_id: str
    provider_session_id: str
    repetitions: int = Field(default=2,ge=2,le=5,strict=True)

class ConclusionInput(Input):
    decision: Literal['KEEP','REVISE','REVERT']
    reason: str = Field(min_length=1,max_length=5000)
    user_confirmed: Literal[True]

@router.post('/retrieval-comparisons/{identifier}/conclusions')
def conclude(identifier:str,body:ConclusionInput): return execute(practice().conclude,identifier,**body.model_dump())

@router.get('/retrieval-comparisons/{identifier}/conclusions')
def conclusions(identifier:str):
    execute(retrieval().store.get,'retrieval_comparisons',identifier)
    return sorted((c for c in retrieval().store.list('experiment_conclusions') if c.comparison_id==identifier),key=lambda c:c.created_at)

@router.post('/chat-turns')
async def chat(body:ChatInput):
    return await acquire(practice().chat(**body.model_dump()))

@router.get('/chat-conversations/{identifier}')
def conversation(identifier:str): return execute(practice().conversation,identifier)

@router.post('/chat-turns/{identifier}/test-draft')
def draft(identifier:str,body:CaseDraftInput):
    return execute(practice().to_case,identifier,**body.model_dump())

@router.post('/retrieval-repeats')
async def repeat(body:RepeatInput): return await acquire(practice().repeat(**body.model_dump()))

@router.get('/repeat-reports/{identifier}')
def report(identifier:str): return execute(retrieval().store.get,'repeat_reports',identifier)

@router.get('/knowledge-library')
def library():
    datasets=sorted(retrieval().store.list('knowledge_datasets'),key=lambda d:(d.knowledge_dataset_id,d.version))
    indices=retrieval().store.list('knowledge_indices')
    return {'datasets':datasets,'indices':indices}

class InterviewInput(Input):
    material_id: str
    question_id: str
    answer: str = Field(min_length=1,max_length=10000)
    claim_ids: list[str] = Field(default_factory=list,max_length=50)
    limitations: str = Field(default='',max_length=5000)

def interview_attempt(body):
    from .career_service import CareerService
    rag=retrieval()
    material=CareerService(rag.experiments).career.get('materials',body.material_id)
    question=next(q for q in material.defense if q.question_id==body.question_id)
    if set(body.claim_ids)-set(question.claim_ids) or not body.answer.strip(): raise ValueError('Question evidence mismatch')
    attempt=InterviewAttempt(**body.model_dump(),checks={'answer_written':bool(body.answer.strip()),
        'evidence_referenced':bool(body.claim_ids),'limitations_written':bool(body.limitations.strip())})
    with rag.store.transaction(): return rag.store.put('interview_attempts',attempt)

@router.post('/interview-attempts')
def interview(body:InterviewInput): return execute(interview_attempt,body)
