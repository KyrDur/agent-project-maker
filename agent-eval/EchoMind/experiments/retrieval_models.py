"""Retrieval artifacts are separate from historical RAG-disabled Skill Runs."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer
from evaluation.models import CaseResult, ExecutableRule
from .models import Artifact, uid

class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)

class DocumentInput(InputModel):
    document_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    title: str = Field(default='', max_length=200)
    text: str = Field(min_length=1, max_length=200000)
    metadata: dict = Field(default_factory=dict)

class KnowledgeDataset(Artifact):
    knowledge_dataset_id: str = Field(default_factory=uid)
    version: int = Field(ge=1)
    name: str
    documents: list[dict]
    knowledge_hash: str
    metadata: dict = Field(default_factory=dict)

class ChunkConfig(InputModel):
    chunk_size: int = Field(default=500, ge=50, le=2000, strict=True)
    chunk_overlap: int = Field(default=50, ge=0, strict=True)
    algorithm: Literal['normalized-character-window-v1'] = 'normalized-character-window-v1'

    @model_validator(mode='after')
    def valid_overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError('Overlap must be smaller than chunk size')
        return self

class KnowledgeIndex(Artifact):
    index_id: str
    knowledge_dataset_id: str
    knowledge_version: int
    knowledge_hash: str
    chunk_config: ChunkConfig
    chunks: list[dict]
    chunk_snapshot_hash: str
    embedding_snapshot: dict
    index_configuration: dict
    collection_name: str
    index_generation: str
    status: Literal['READY'] = 'READY'

class RetrievalCase(InputModel):
    case_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=5000)
    relevant_document_ids: list[str] = Field(default_factory=list)
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    expected_answer: str | None = None
    scenario: str | None = None
    source: Literal['user_created','user_modified','demo','ai_generated'] = 'user_created'
    generation: dict = Field(default_factory=dict)
    must_do: list[str] = Field(default_factory=list)
    must_not_do: list[str] = Field(default_factory=list)
    executable_rules: list[ExecutableRule] = Field(default_factory=list)
    partition: Literal['DEBUG','HOLDOUT'] = 'DEBUG'
    context: list[dict] = Field(default_factory=list, max_length=20)
    source_chat_turn_id: str | None = None
    allow_missing_knowledge: bool = False

    @model_serializer(mode='wrap')
    def legacy_serialization(self,handler):
        data=handler(self)
        if not self.generation:data.pop('generation',None)
        return data

    @model_validator(mode='after')
    def labels(self):
        if not self.query.strip(): raise ValueError('Query is empty')
        if self.relevant_document_ids and self.relevant_chunk_ids:
            raise ValueError('Choose document OR chunk ground truth per Case')
        for labels in [self.relevant_document_ids, self.relevant_chunk_ids]:
            if len(labels) != len(set(labels)): raise ValueError('Duplicate relevance label')
        if any(set(m) != {'role','content'} or m['role'] not in {'user','assistant'}
               or not isinstance(m['content'],str) or len(m['content'])>10000 for m in self.context):
            raise ValueError('Invalid conversation context')
        if sum(len(m['content']) for m in self.context)>50000:
            raise ValueError('Conversation context too large')
        return self

class RetrievalEvalSet(Artifact):
    retrieval_eval_set_id: str = Field(default_factory=uid)
    version: int = Field(default=1, ge=1)
    eval_set_hash: str
    index_id: str
    name: str
    cases: list[RetrievalCase] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_ids(self):
        ids = [c.case_id for c in self.cases]
        if len(ids)!=len(set(ids)): raise ValueError('Duplicate Case ID')
        return self

class RetrievalConfig(InputModel):
    top_k: int = Field(default=3, ge=1, le=20, strict=True)
    query_rewrite: bool = Field(default=False, strict=True)
    rerank: bool = Field(default=False, strict=True)
    # Candidate pool is fixed across rerank OFF/ON. Top K is the display cutoff.
    candidate_pool_size: int = Field(default=20, ge=20, le=100, strict=True)
    cache_enabled: Literal[False] = False
    cache_namespace: None = None
    cache_policy: Literal['DISABLED'] = 'DISABLED'

class RetrievalRun(Artifact):
    run_id: str = Field(default_factory=uid)
    experiment_type: Literal['RETRIEVAL'] = 'RETRIEVAL'
    runtime_scope: Literal['RAG_RETRIEVAL_ENABLED'] = 'RAG_RETRIEVAL_ENABLED'
    run_type: Literal['BASELINE','RETEST']
    parent_run_id: str | None = None
    change_id: str | None = None
    status: Literal['RUNNING','COMPLETE','PARTIAL','FAILED'] = 'RUNNING'
    finished_at: str | None = None
    provider_session_id: str
    provider_configuration_snapshot: dict
    provider_readiness_snapshot: dict
    controls: dict
    retrieval_config: RetrievalConfig
    execution_order: list[str]
    verify_answers: bool = False
    case_results: list[dict] = Field(default_factory=list)
    answer_results: list[CaseResult] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    answer_metrics: dict = Field(default_factory=dict)
    provider_observations: list[dict] = Field(default_factory=list)
    provider_call_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    runtime_end_check: dict = Field(default_factory=dict)

class RetrievalChange(Artifact):
    change_id: str = Field(default_factory=uid)
    baseline_run_id: str
    change_type: Literal['TOP_K_CHANGE','QUERY_REWRITE_TOGGLE','RERANK_TOGGLE','KNOWLEDGE_UPDATE']
    target_index_id: str | None = None
    target_eval_set_id: str | None = None
    reason: str = Field(min_length=1, max_length=3000)
    selected_case_ids: list[str] = Field(min_length=1)
    user_confirmed: Literal[True]
    confirmed_at: str
    before_config: RetrievalConfig
    after_config: RetrievalConfig
    declared_diff: list[dict]
    observed_diff: list[dict] = Field(default_factory=list)
    implemented_status: Literal['PROPOSED','APPLIED'] = 'PROPOSED'
    applied_at: str | None = None
    application_evidence: dict = Field(default_factory=dict)

class RetrievalComparison(Artifact):
    comparison_id: str = Field(default_factory=uid)
    baseline_run_id: str
    retest_run_id: str
    comparable: bool
    comparability_reasons: list[str]
    comparison_completeness: Literal['FULL','PARTIAL']
    expected_case_count: int
    matched_case_count: int
    single_recorded_change: bool
    attributable: Literal[False] = False
    attribution_status: str = 'INSUFFICIENT_EVIDENCE'
    warnings: list[str]
    case_pairs: list[dict]
    metrics_before: dict
    metrics_after: dict
    paired_metrics: dict
    answer_review_snapshot: dict = Field(default_factory=dict)

class RetrievalReview(Artifact):
    review_id: str = Field(default_factory=uid)
    run_id: str
    case_id: str
    revision: int
    effective_result: CaseResult
