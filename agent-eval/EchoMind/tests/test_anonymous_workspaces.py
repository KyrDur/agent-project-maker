"""Two real browser cookie jars must never share objects or Provider vaults."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
from pathlib import Path
import secrets

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from experiments.api import configure, router, install_validation_handler
from experiments.retrieval_api import router as retrieval_router
from experiments.career_api import router as career_router
from experiments.workspaces import (WorkspaceRegistry, WorkspaceMiddleware,
                                   request_service, public_provider_endpoint)
from experiments.providers import ProviderConfig
from test_experiment_service import baseline, confirmed

ORIGIN = 'https://workspace.test'
COOKIE = '__Host-echomind_workspace'
SKILLS = Path(__file__).resolve().parents[1] / 'skills'

@pytest.fixture
def environment(tmp_path):
    from experiments import api
    previous = api._service_provider
    registry = WorkspaceRegistry(tmp_path/'workspaces', SKILLS, ORIGIN)
    @asynccontextmanager
    async def lifespan(app):
        configure(lambda: request_service.get())
        yield
        registry.close()
        api._service_provider = previous
    app = FastAPI(lifespan=lifespan)
    app.state.workspaces = registry
    app.add_middleware(WorkspaceMiddleware)
    app.include_router(career_router)
    app.include_router(retrieval_router)
    app.include_router(router)
    install_validation_handler(app)
    # Same-process sync + async endpoints exercise ContextVar propagation.
    @app.get('/experiments/context-sync')
    def context_sync(): return {'root': str(request_service.get().store.root)}
    @app.get('/experiments/context-async')
    async def context_async():
        before = request_service.get()
        await asyncio.sleep(.01)
        assert request_service.get() is before
        return {'root': str(before.store.root)}
    with TestClient(app, base_url=ORIGIN) as first:
        second = TestClient(app, base_url=ORIGIN)
        yield app, registry, first, second

def boot(client):
    response = client.get('/experiments/workspace')
    assert response.status_code == 200
    return response

def provider(client):
    key = secrets.token_hex(24)
    response = client.post('/experiments/provider-sessions', json={
        'provider': 'openai-compatible', 'base_url': 'https://api.deepseek.com/v1',
        'model': 'user-model', 'api_key': key})
    assert response.status_code == 200
    return response.json()['provider_session_id'], key

def evalset(client):
    response = client.post('/experiments/evalsets', json={
        'dialog_cases': [{'case_id': 'a', 'question': '我想退款'}]})
    assert response.status_code == 200
    return response.json()['eval_set_id']

def test_cookie_bootstrap_private_flags_and_no_bearer_in_body_or_files(environment):
    _, registry, a, b = environment
    assert a.get('/experiments/artifacts/runs').status_code == 401
    ra, rb = boot(a), boot(b)
    cookie = ra.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=lax' in cookie
    assert 'Path=/' in cookie and 'Domain=' not in cookie
    assert 'Max-Age=7776000' in cookie
    token = a.cookies.get(COOKIE)
    assert token != b.cookies.get(COOKIE)
    assert token not in ra.text
    assert ra.json()['workspace_ref'] == hashlib.sha256(token.encode()).hexdigest()
    assert boot(a).json()['created'] is False
    assert token not in ''.join(p.read_text() for p in registry.root.rglob('*.json'))
    assert a.get('/healthz').json() == {'status':'ok'}
    assert a.get('/docs').status_code == 404

def test_history_objects_and_model_vault_are_isolated_in_both_directions(environment):
    _, registry, a, b = environment
    boot(a); boot(b)
    sa, ka = provider(a); sb, kb = provider(b)
    ea, eb = evalset(a), evalset(b)
    for own, other, sid, ev in [(a,b,sa,ea),(b,a,sb,eb)]:
        assert own.get('/experiments/provider-sessions/'+sid).json()['credential_status'] == 'PRESENT'
        assert other.get('/experiments/provider-sessions/'+sid).status_code == 404
        assert other.delete('/experiments/provider-sessions/'+sid).status_code == 404
        assert other.post('/experiments/provider-sessions/'+sid+'/test').status_code == 404
        assert other.get('/experiments/evalsets/'+ev).status_code == 404
        assert other.post('/experiments/runs',json={'eval_set_id':ev,'provider_session_id':sid}).status_code == 404
        assert [x['eval_set_id'] for x in own.get('/experiments/artifacts/evalsets').json()['items']] == [ev]
    va = registry.get(registry.known(a.cookies.get(COOKIE)))
    vb = registry.get(registry.known(b.cookies.get(COOKIE)))
    assert va.providers._keys == {sa:ka} and vb.providers._keys == {sb:kb}
    assert va.skills.manager.root_dir != vb.skills.manager.root_dir
    assert va.retrieval.knowledge.path != vb.retrieval.knowledge.path
    assert ka not in ''.join(p.read_text() for p in registry.root.rglob('*.json'))
    assert kb not in ''.join(p.read_text() for p in registry.root.rglob('*.json'))

def test_knowledge_and_career_routes_use_private_store(environment):
    _, registry, a, b = environment
    boot(a); boot(b)
    knowledge = a.post('/experiments/knowledge-datasets',json={
        'name':'private refund policy','documents':[{'document_id':'refund','title':'退款','text':'核验后退款。'}]}).json()
    identity = knowledge['knowledge_dataset_id']
    assert b.get('/experiments/knowledge-datasets/'+identity).status_code == 404
    assert b.post('/experiments/knowledge-datasets/'+identity+'/index',json={'version':1}).status_code == 404
    assert b.get('/experiments/retrieval-history').json() == []
    assert a.get('/experiments/career/evidence').json() == []
    assert b.get('/experiments/career/materials').json() == []
    # Career artifacts live underneath each private experiment store.
    from experiments.career_store import CareerStore
    assert CareerStore(registry.get(registry.known(a.cookies.get(COOKIE))).store).root != CareerStore(registry.get(registry.known(b.cookies.get(COOKIE))).store).root

def test_shared_legacy_records_are_never_imported_or_rewritten(environment):
    _, registry, a, b = environment
    legacy = registry.root.parent/'artifacts'/'runs'
    legacy.mkdir(parents=True)
    path = legacy/'private-history.json'; path.write_bytes(b'old private bytes')
    boot(a); boot(b)
    assert a.get('/experiments/artifacts/runs').json()['total'] == 0
    assert b.get('/experiments/artifacts/runs').json()['total'] == 0
    assert path.read_bytes() == b'old private bytes'

@pytest.mark.parametrize('value', ['../artifacts', 'a'*43, 'f'*64, '', 'invalid!'])
def test_client_chosen_cookie_or_public_ref_cannot_select_workspace(environment,value):
    _, _, a, b = environment
    original = boot(a).json()['workspace_ref']
    b.cookies.set(COOKIE, value)
    assert b.get('/experiments/artifacts/runs').status_code == 401
    assert boot(b).json()['workspace_ref'] != original

@pytest.mark.parametrize('headers', [{'Origin':'https://evil.test'}, {'Sec-Fetch-Site':'cross-site'}, {'Origin':'null'}])
def test_cross_site_requests_cannot_create_identity_or_mutate(environment,headers):
    _, registry, a, _ = environment
    assert a.get('/experiments/workspace',headers=headers).status_code == 403
    assert registry.services == {}
    boot(a)
    assert a.post('/experiments/evalsets',json={},headers=headers).status_code == 403
    assert a.get('/experiments/artifacts/evalsets').json()['total'] == 0

@pytest.mark.parametrize('url', ['http://127.0.0.1:8000','https://169.254.169.254',
    'https://evil.test','https://api.deepseek.com.evil.test/v1','https://api.deepseek.com:8443/v1'])
def test_public_provider_target_allowlist_before_storing_key(environment,url):
    _, registry, a, _ = environment
    boot(a)
    response = a.post('/experiments/provider-sessions',json={
        'provider':'openai-compatible','base_url':url,'model':'user','api_key':secrets.token_hex(24)})
    assert response.status_code == 422
    assert a.get('/experiments/artifacts/provider_sessions').json()['total'] == 0
    assert registry.get(registry.known(a.cookies.get(COOKIE))).providers._keys == {}

def test_existing_presets_allowed():
    for host in ['api.deepseek.com','api.openai.com','api.anthropic.com','dashscope.aliyuncs.com','api.moonshot.cn']:
        public_provider_endpoint(ProviderConfig(provider='openai-compatible',model='user',base_url='https://'+host+'/v1'))

def test_simultaneous_requests_keep_async_and_threadpool_contexts_separate(environment):
    app, registry, a, b = environment
    boot(a); boot(b)
    async def acquire():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            values = await asyncio.gather(*[client.get('/experiments/context-'+kind,
                headers={'Cookie':COOKIE+'='+browser.cookies.get(COOKIE)})
                for browser in (a,b) for kind in ('sync','async')])
        return [value.json()['root'] for value in values]
    values = asyncio.run(acquire())
    assert values[0] == values[1] and values[2] == values[3] and values[0] != values[2]
    assert request_service.get() is None

def test_restart_preserves_own_records_but_drops_all_model_keys(environment):
    _, registry, a, b = environment
    boot(a); boot(b)
    sid, _ = provider(a); ev = evalset(a)
    registry.close()
    assert a.get('/experiments/evalsets/'+ev).status_code == 200
    session = a.get('/experiments/provider-sessions/'+sid).json()
    assert session['credential_status'] == 'UNAVAILABLE' and session['status'] == 'CREDENTIAL_UNAVAILABLE'
    assert b.get('/experiments/evalsets/'+ev).status_code == 404

def test_skill_activation_and_agent_results_are_private(environment):
    _, registry, a, b = environment
    boot(a); boot(b)
    first = registry.get(registry.known(a.cookies.get(COOKIE)))
    second = registry.get(registry.known(b.cookies.get(COOKIE)))
    from test_experiment_service import FixtureRuntime
    first.runtime = FixtureRuntime()
    first.credential = 'local-fixture-only-not-a-provider-key'
    ev = first.create_eval_set([{'case_id':'a','question':'hello'}])
    run = baseline(first,ev)
    decision = first.create_decision(run.run_id, ['a'])
    decision = first.confirm_decision(decision.decision_id,
        user_confirmed_root_cause='Rule needs order verification', root_cause_reason='Observed case',
        selected_strategy='Add verification', selection_reason='One rule body',
        expected_benefit='Avoid premature claim', possible_side_effects='Longer reply', confirmed_by='user')
    before = second.skills.current()
    skill = next(s for s in run.skill_version['skills'] if s['rule_body'])
    change = first.propose_change(decision.decision_id,skill['skill_id'],skill['rule_body']+'\n先核验订单。',run.skill_version['hash'])
    first.apply_change(change.change_id)
    assert first.skills.current()['hash'] != before['hash']
    assert second.skills.verify_disk() == before
    assert b.get('/experiments/runs/'+run.run_id).status_code == 404
    assert b.post('/experiments/changes/'+change.change_id+'/apply').status_code == 404
    assert b.get('/experiments/artifacts/runs').json()['total'] == 0

    from test_career import CONTEXT
    evidence = a.post('/experiments/career/evidence',json={
        'experiment_type':'AGENT_BEHAVIOR','baseline_run_id':run.run_id,'context':CONTEXT})
    assert evidence.status_code == 200
    eid = evidence.json()['evidence_object_id']
    material = a.post('/experiments/career/materials',json={'evidence_object_id':eid})
    assert material.status_code == 200
    mid = material.json()['material_id']
    assert b.get('/experiments/career/evidence').json() == []
    assert b.get('/experiments/career/evidence/'+eid).status_code == 404
    assert b.get('/experiments/career/materials').json() == []
    assert b.get('/experiments/career/materials/'+mid).status_code == 404
    assert b.get('/experiments/career/materials/'+mid+'/export').status_code == 404
    assert b.post('/experiments/career/materials/'+mid+'/edit',json={
        'group':'interview','section_id':'story_60','text':'cannot edit another visitor'}).status_code == 404

def test_anonymous_standalone_entrypoint_and_capacity(tmp_path,monkeypatch):
    from experiments import api
    from experiments.app import app
    previous = api._service_provider
    monkeypatch.setenv('ECHOMIND_ANONYMOUS_WORKSPACES','1')
    monkeypatch.setenv('ECHOMIND_WORKSPACE_DIR',str(tmp_path/'private'))
    monkeypatch.setenv('ECHOMIND_PUBLIC_ORIGIN',ORIGIN)
    try:
        with TestClient(app,base_url=ORIGIN) as client:
            boot(client)
            assert client.get('/experiments/artifacts/runs').json()['total'] == 0
            registry = app.state.workspaces
            registry.max_loaded = 1
            other = TestClient(app,base_url=ORIGIN)
            assert other.get('/experiments/workspace').status_code == 503
            assert client.get('/experiments/artifacts/runs').status_code == 200
        assert registry.services == {}
    finally:
        api._service_provider = previous
