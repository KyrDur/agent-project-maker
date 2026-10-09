"""Python-only Retrieval API on the existing artifact store and credential vault."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import Field
from typing import Literal
from .api import service, execute, Input
from .providers import ProviderFailure
from .retrieval_models import DocumentInput, ChunkConfig, RetrievalCase, RetrievalConfig
from .retrieval_service import RetrievalService
from .retrieval_embeddings import EmbeddingFailure

router=APIRouter(prefix='/experiments',tags=['Retrieval Experiments'])

def retrieval():
    instance=service()
    if not hasattr(instance,'retrieval'): instance.retrieval=RetrievalService(instance)
    return instance.retrieval

async def acquire(coroutine):
    try: return await coroutine
    except EmbeddingFailure as error: raise HTTPException(409,str(error)) from None
    except ProviderFailure as error: raise HTTPException(409,error.code) from None
    except FileNotFoundError: raise HTTPException(404,'Artifact not found') from None
    except (ValueError,TypeError): raise HTTPException(409,'Retrieval lifecycle or frozen configuration rejected') from None

class KnowledgeInput(Input):
    documents: list[DocumentInput] = Field(min_length=1,max_length=100)
    name: str = Field(min_length=1,max_length=200)
    knowledge_dataset_id: str | None = None
    metadata: dict = Field(default_factory=dict)

class IndexInput(Input):
    version: int = Field(ge=1)
    chunk_config: ChunkConfig | None = None
    embedding_model: Literal['all-MiniLM-L6-v2','sha256-lexical-bigram-v1'] = 'all-MiniLM-L6-v2'

class EvalSetInput(Input):
    index_id: str
    name: str = Field(min_length=1,max_length=200)
    cases: list[RetrievalCase] = Field(min_length=1,max_length=100)
    retrieval_eval_set_id: str | None = None

class RunInput(Input):
    provider_session_id: str
    retrieval_eval_set_id: str
    version: int | None = Field(default=None,ge=1)
    run_type: Literal['BASELINE','RETEST'] = 'BASELINE'
    parent_run_id: str | None = None
    change_id: str | None = None
    retrieval_config: RetrievalConfig | None = None
    verify_answers: bool = False

class ChangeInput(Input):
    baseline_run_id: str
    change_type: Literal['TOP_K_CHANGE','QUERY_REWRITE_TOGGLE','RERANK_TOGGLE','KNOWLEDGE_UPDATE']
    target_index_id: str | None = None
    after_config: RetrievalConfig
    reason: str = Field(min_length=1,max_length=3000)
    selected_case_ids: list[str] = Field(min_length=1)
    user_confirmed: Literal[True]

class ComparisonInput(Input):
    baseline_run_id: str
    retest_run_id: str

class PreviewInput(Input):
    provider_session_id: str
    query: str = Field(min_length=1,max_length=5000)

class ReviewInput(Input):
    case_id: str
    human_final_status: Literal['PASS','FAIL','INVALID']
    human_reason: str

@router.post('/knowledge-datasets')
def create_knowledge(body:KnowledgeInput):
    return execute(retrieval().knowledge.create,[d.model_dump() for d in body.documents],body.name,
                   body.knowledge_dataset_id,body.metadata)

@router.get('/knowledge-datasets/{identifier}')
def knowledge(identifier:str,version:int|None=Query(default=None,ge=1)):
    return execute(retrieval().store.get,'knowledge_datasets',identifier,version)

@router.post('/knowledge-datasets/{identifier}/index')
def index(identifier:str,body:IndexInput):
    return execute(retrieval().knowledge.build,identifier,body.version,body.chunk_config.model_dump() if body.chunk_config else None,body.embedding_model)

@router.get('/knowledge-indices/{identifier}')
def get_index(identifier:str): return execute(retrieval().store.get,'knowledge_indices',identifier)

@router.post('/retrieval-evalsets')
def create_evalset(body:EvalSetInput):
    return execute(retrieval().create_evalset,body.index_id,body.name,[c.model_dump() for c in body.cases],body.retrieval_eval_set_id)

@router.get('/retrieval-evalsets/{identifier}')
def evalset(identifier:str,version:int|None=Query(default=None,ge=1)):
    return execute(retrieval().store.get,'retrieval_evalsets',identifier,version)

@router.post('/retrieval-runs')
async def run(body:RunInput):
    return await acquire(retrieval().run(**body.model_dump()))

@router.get('/retrieval-runs/{identifier}')
def get_run(identifier:str): return execute(retrieval().view,identifier)

@router.post('/retrieval-changes')
def create_change(body:ChangeInput): return execute(retrieval().propose_change,**body.model_dump())

@router.post('/retrieval-changes/{identifier}/apply')
def apply(identifier:str): return execute(retrieval().apply,identifier)

@router.get('/retrieval-changes/{identifier}')
def get_change(identifier:str): return execute(retrieval().store.get,'retrieval_changes',identifier)

@router.post('/retrieval-comparisons')
def compare(body:ComparisonInput): return execute(retrieval().compare,body.baseline_run_id,body.retest_run_id)

@router.get('/retrieval-comparisons/{identifier}')
def get_comparison(identifier:str): return execute(retrieval().store.get,'retrieval_comparisons',identifier)

@router.post('/retrieval-rewrite-preview')
async def preview(body:PreviewInput): return await acquire(retrieval().preview_rewrite(body.provider_session_id,body.query))

@router.post('/retrieval-runs/{identifier}/reviews')
def review(identifier:str,body:ReviewInput):
    return execute(retrieval().review,identifier,body.case_id,body.human_final_status,body.human_reason)

@router.get('/retrieval-history')
def history():
    return [{'run_id':r.run_id,'run_type':r.run_type,'parent_run_id':r.parent_run_id,'status':r.status,
             'created_at':r.created_at,'name':r.controls['eval_set_snapshot']['name'],
             'retrieval_eval_set_id':r.controls['eval_set_snapshot']['retrieval_eval_set_id'],
             'version':r.controls['eval_set_snapshot']['version']}
            for r in sorted(retrieval().store.list('retrieval_runs'),key=lambda r:r.created_at)]
