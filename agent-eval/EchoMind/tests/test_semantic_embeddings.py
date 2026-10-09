"""Real local ONNX vectors and frozen-index compatibility, not mocked embeddings."""
import asyncio
import pytest
from experiments.store import JsonStore
from experiments.retrieval_knowledge import FrozenKnowledge
from experiments.retrieval_embeddings import SEMANTIC, LEXICAL, snapshot, EmbeddingFailure
from experiments.retrieval_lexical_v1 import FrozenKnowledge as OriginalFrozenKnowledge
from experiments.retrieval_api import IndexInput
from experiments.retrieval_models import KnowledgeIndex
from experiments.practice_service import PracticeService
from test_retrieval import fixture, DOCS, CASES

@pytest.fixture(scope='module')
def knowledge(tmp_path_factory):
    return FrozenKnowledge(JsonStore(tmp_path_factory.mktemp('real-semantic')/'store'))

@pytest.fixture(scope='module')
def semantic_index(knowledge):
    dataset=knowledge.create(DOCS,'Semantic model integration test')
    return knowledge.build(dataset.knowledge_dataset_id,1)

def test_real_default_model_and_query_share_vector_space(knowledge,semantic_index):
    index=semantic_index
    assert IndexInput(version=1).embedding_model==SEMANTIC
    assert index.embedding_snapshot['model']==SEMANTIC
    assert index.embedding_snapshot['dimension']==384
    assert index.embedding_snapshot['external_backend_revision']==snapshot()['external_backend_revision']
    rows=knowledge.search(index,'退款审核通过 原付款方式 到账时间',20)
    assert rows[0]['document_id']=='refund'
    collection=knowledge.verify(index)
    assert len(collection.get(include=['embeddings'])['embeddings'][0])==384

def test_original_saved_index_still_verifies_and_queries(knowledge):
    original=OriginalFrozenKnowledge(knowledge.store)
    dataset=original.create(DOCS,'Before upgrade')
    old=original.build(dataset.knowledge_dataset_id,1)
    assert knowledge.verify(old)
    assert knowledge.search(old,'钱什么时候回到卡里？',8)==original.search(old,'钱什么时候回到卡里？',8)
    path=knowledge.store.path('knowledge_indices',old.index_id);before=path.read_bytes()
    assert knowledge.build(dataset.knowledge_dataset_id,1,embedding_model=LEXICAL).index_id==old.index_id
    assert path.read_bytes()==before
    assert knowledge.build(dataset.knowledge_dataset_id,1).index_id!=old.index_id

def test_weight_identity_and_stored_vector_drift_rejected(knowledge,semantic_index):
    data=semantic_index.model_dump()
    data['embedding_snapshot']['external_backend_revision']='changed'
    with pytest.raises(ValueError,match='Embedding implementation changed'):
        knowledge.verify(KnowledgeIndex.model_validate(data))
    d=knowledge.create([{'document_id':'a','text':'退款流程与付款方式。'}],'Tamper')
    index=knowledge.build(d.knowledge_dataset_id,1)
    c=knowledge.client().get_collection(index.collection_name,embedding_function=None)
    c.update(ids=[index.chunks[0]['chunk_id']],embeddings=[[0.0]*384])
    with pytest.raises(ValueError,match='content/vector drift'):knowledge.verify(index)

def test_overlength_is_rejected_instead_of_truncated_or_fallback(knowledge,semantic_index):
    with pytest.raises(EmbeddingFailure,match='EMBEDDING_INPUT_TOO_LONG'):
        knowledge.search(semantic_index,'退款 '*600,3)
    d=knowledge.create([{'document_id':'long','text':'refund '*400}],'Overlong chunk')
    with pytest.raises(EmbeddingFailure,match='EMBEDDING_INPUT_TOO_LONG'):
        knowledge.build(d.knowledge_dataset_id,1,{'chunk_size':2000,'chunk_overlap':0})

def test_chat_and_evaluation_use_same_real_semantic_index(fixture):
    rag,sid,_,_,_,_=fixture
    d=rag.knowledge.create(DOCS,'Semantic chat and evaluation')
    index=rag.knowledge.build(d.knowledge_dataset_id,1)
    ev=rag.create_evalset(index.index_id,'Semantic integration',CASES[:1])
    run=asyncio.run(rag.run(sid,ev.retrieval_eval_set_id,retrieval_config={'top_k':3}))
    turn=asyncio.run(PracticeService(rag).chat(sid,index.index_id,CASES[0]['query']))
    assert run.case_results[0]['status']=='SUCCESS'
    assert turn.status=='SUCCESS'
    assert run.controls['embedding_snapshot']['model']==SEMANTIC
    assert turn.retrieval['pre_rerank_results']==run.case_results[0]['pre_rerank_results']
    assert turn.provider_call_count==1 and run.provider_call_count==0
    newer=rag.knowledge.create(DOCS,'New version',d.knowledge_dataset_id)
    legacy=rag.knowledge.build(newer.knowledge_dataset_id,2,embedding_model=LEXICAL)
    with pytest.raises(ValueError):
        rag.propose_change(run.run_id,'KNOWLEDGE_UPDATE',run.retrieval_config.model_dump(),
            'Only knowledge update',['rag_1'],True,target_index_id=legacy.index_id)
