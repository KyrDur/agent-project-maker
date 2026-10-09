"""Phase 4 adds read-only history summaries, not evaluation/change semantics."""
from secrets import token_hex
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from experiments.api import configure,router,install_validation_handler
from api import main
from experiments.providers import ProviderConfig
from experiments.canonical import evaluation_protocol
from test_experiment_service import setup,baseline,confirmed

def client_for(service):
    configure(lambda:service)
    app=FastAPI();app.include_router(router);install_validation_handler(app)
    return TestClient(app)

def test_read_only_paginated_history_preserves_bytes_semantics_and_secret_boundaries(tmp_path):
    service,ev,_=setup(tmp_path)
    key=token_hex(24)
    session=service.providers.create(ProviderConfig(model='user'),key)
    run=baseline(service,ev)
    decision=confirmed(service,run)
    review=service.review(run.run_id,'a','PASS','Read evidence','user')
    before={str(p):p.read_bytes() for p in (tmp_path/'store').rglob('*.json')}
    try:
        with client_for(service) as client:
            for group in ('provider_sessions','evalsets','runs','decisions','changes','comparisons','reviews'):
                result=client.get('/experiments/artifacts/'+group)
                assert result.status_code==200 and key not in result.text and 'masked_fingerprint' not in result.text
                assert result.json()['offset']==0 and result.json()['limit']==50
            assert client.get('/experiments/artifacts/provider_sessions').json()['items'][0]['credential_status']=='PRESENT'
            assert client.get('/experiments/artifacts/runs').json()['items'][0]['run_id']==run.run_id
            assert 'skill_version' not in client.get('/experiments/artifacts/runs').json()['items'][0]
            assert client.get('/experiments/artifacts/decisions').json()['items'][0]['decision_id']==decision.decision_id
            assert client.get('/experiments/artifacts/reviews').json()['items'][0]['review_id']==review.review_id
            assert client.get('/experiments/artifacts/evalsets?offset=1&limit=1').json()['items']==[]
            assert client.get('/experiments/artifacts/unknown').status_code==404
            assert client.post('/experiments/artifacts/runs',json={}).status_code==405
            assert client.get('/experiments/runs/'+run.run_id).json()['effective_results'][0]['original_status']=='FAIL'
    finally:configure(main._experiments)
    assert before=={str(p):p.read_bytes() for p in (tmp_path/'store').rglob('*.json')}
    assert run.evaluation_protocol_snapshot==evaluation_protocol()
    service.providers._keys.clear()
    try:
        with client_for(service) as client:
            unavailable=client.get('/experiments/artifacts/provider_sessions').json()['items'][0]
            assert unavailable['status']=='CREDENTIAL_UNAVAILABLE' and unavailable['credential_status']=='UNAVAILABLE'
    finally:configure(main._experiments)

@pytest.mark.parametrize('query',['limit=0','limit=101','offset=-1','limit=invalid'])
def test_history_pagination_validated_without_echoing_input(tmp_path,query):
    service,_,_=setup(tmp_path)
    try:
        with client_for(service) as client:
            result=client.get('/experiments/artifacts/runs?'+query)
            assert result.status_code==422 and result.json()=={'detail':'Invalid request'}
    finally:configure(main._experiments)
