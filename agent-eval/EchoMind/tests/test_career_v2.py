"""Phase5.1 regression uses the user's actual Rerank experiment, not Golden rewrite."""
import json,shutil,os
from pathlib import Path
from types import SimpleNamespace
import pytest
from experiments.career_service import CareerService
from experiments.store import JsonStore
from experiments.career_models import CareerBundle
from experiments.career_renderers import markdown_v2
from experiments.career_evidence import normalize,resolve
from experiments.career_narrative import plan
from experiments.career_renderers import generate
from experiments.canonical import digest

EID='9c262aad-8c12-449c-8728-7bb9a04ba706'
SOURCE=Path(os.environ.get('AGENT_EVAL_RERANK_FIXTURES', str(Path(__file__).resolve().parents[3]/'phase4/rag/user-preview/store')))
@pytest.fixture
def real(tmp_path):
    if not (SOURCE/'career/evidence'/f'{EID}.json').is_file():
        pytest.skip('Requires private historical fixtures: AGENT_EVAL_RERANK_FIXTURES')
    store=JsonStore(tmp_path/'store')
    # Only frozen source snapshots of a specific Evidence; fixture independent of new material history.
    e=json.loads((SOURCE/'career/evidence'/f'{EID}.json').read_text())['artifact']
    for source in e['source_map'].values():
        if source['group']=='SYSTEM_DERIVED': continue
        name=source['id']
        dest=store.root/source['group']/(name+'.json');dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps({'artifact':source['snapshot'],'sha256':source['sha256']},ensure_ascii=False))
    service=CareerService(SimpleNamespace(store=store));path=service.career.path('evidence',EID);path.parent.mkdir(parents=True)
    shutil.copyfile(SOURCE/'career/evidence'/f'{EID}.json',path)
    return service,service.career.get('evidence',EID)

def completion(field,text,state='USER_CONFIRMED'):
    return {'field':field,'text':text,'evidence_state':state,'confirmed':True}

def test_actual_l_regression_rank_protocol_and_answer_separation(real):
    s,e=real;m=s.generate_v2(EID);v=s.career.get('views',m.view_id)
    assert v.facts['count'].value==8
    for side,rows in v.facts['acquisition'].value.items():
        assert len(rows)==8
        assert all(r['initial_candidates']==8 and r['final_returned']==3 and r['rank_cutoff']==8 for r in rows)
        assert all(r['rerank_input']==(8 if side=='retest' else 0) for r in rows)
    assert v.facts['metric_mrr'].value=={'before':.478125,'after':1.,'denominator':8}
    assert v.facts['metric_hit_at_1'].value=={'before':.25,'after':1.,'denominator':8}
    assert v.facts['transitions'].value=={'RETRIEVAL_IMPROVED':6,'RETRIEVAL_UNCHANGED':2}
    assert len(e.retrieval_evidence['rank_movements'])==8
    assert all(x['answer_transition']=='NOT_COMPARABLE' for x in e.retrieval_evidence['rank_movements'])
    text=markdown_v2(m);assert '没有运行回答评测' in text and 'Rank 5 或 8' in text
    assert '实际初始召回 8 条' in text and '重排输入 8 条' in text
    assert '回答质量提升了' not in text
    assert m.label=='Draft' and not m.lint


def test_a_b_decision_completion_does_not_invent_or_reask(real):
    s,e=real;v=s.preview_v2(EID)
    assert {q['field'] for q in v.missing_questions}=={'root_cause','alternatives'}
    assert v.facts['root_cause'].evidence_state=='MISSING'
    before=s.career.path('evidence',EID).read_bytes()
    m=s.generate_v2(EID,completions=[completion('root_cause','可能是词汇匹配不足，需要对照检验。','INFERENCE'),completion('alternatives','本轮没有比较其他方案，仅先试重排。')])
    text=markdown_v2(m)
    assert '待验证根因假设' in text and '本轮没有比较' in text
    assert m.readiness['case_study']['decision_depth']['status']=='NEEDS_VERIFICATION'
    assert s.career.path('evidence',EID).read_bytes()==before
    with pytest.raises(ValueError):s.generate_v2(EID,completions=[completion('root_cause','已证明根因')])
    with pytest.raises(ValueError):s.generate_v2(EID,completions=[completion('interpretation','覆盖已有反思')])


def test_h_three_targets_keep_same_facts_and_separate_focus(real):
    s,e=real;views=[];texts=[]
    for target in ['AI_APPLICATION_PM','AI_EVALUATION_PLATFORM_PM','GENERAL_PM']:
        m=s.generate_v2(EID,career_target=target);v=s.career.get('views',m.view_id)
        views.append({k:(f.value,f.evidence_state) for k,f in v.facts.items()});texts.append(m.sections['resume_ai'][0].text)
    assert views[0]==views[1]==views[2] and len(set(texts))==3
    app=s.generate_v2(EID,project_focus='CUSTOMER_SERVICE_APP');text=markdown_v2(app,'case_study')
    assert '客服应用' in text and app.readiness['case_study']['ownership_clarity']['status']=='NEEDS_INPUT'
    assert '准备求职' not in text.split('## 证据附录')[0]


def test_i_j_content_quality_and_granular_citations(real):
    s,e=real;m=s.generate_v2(EID)
    for sections in m.sections.values():
        for section in sections:
            assert '…' not in section.text and '...' not in section.text and '我负责我' not in section.text
            assert 'claim_' not in section.text
            for c in section.citations:
                assert c['text_span'] in section.text and c['fact_ids'] and c['evidence_paths']
                for path in c['evidence_paths']:
                    if not path.startswith('view'):resolve(e,path)
    scripts={x.section_id:x for x in m.sections['interview']}
    assert scripts['story30'].text not in scripts['story60'].text
    assert scripts['story60'].text not in scripts['story90'].text
    for name in ['story60','story90']:
        text=scripts[name].text
        assert text.startswith('我做的项目') and '工程代码与测试由 Codex' in text and '本次 8 道' in text
        assert text.endswith('。') and scripts[name].timing['estimated_seconds']>40
    assert len(m.sections['resume_ai'])==len(m.sections['resume_general'])==3
    assert len({q.category for q in m.defense})==6
    assert all(q.supporting_evidence and q.possible_follow_up for q in m.defense)
    assert any(q.missing_information for q in m.defense)


@pytest.mark.parametrize('group',['case_study','resume_ai','resume_general','interview','defense'])
def test_export_reload_edit_and_regenerate(real,group,tmp_path):
    s,e=real;m=s.generate_v2(EID);before=s.career.path('materials',m.material_id).read_bytes()
    exported=s.export(m.material_id,group);p=tmp_path/'output.md';p.write_text(exported['markdown']);assert p.read_text()==exported['markdown']
    restored=s.career.get('materials',m.material_id);assert restored==m
    if group!='defense':
        section=m.sections[group][0];edit=s.edit(m.material_id,group,section.section_id,'我手写全部系统，回答质量提升了，DAU 999。')
        assert edit.label=='Mixed' and 'FREE_EDIT_UNVERIFIED' in {l['code'] for l in edit.lint}
        assert s.export(edit.material_id,group)['label']=='Mixed'
        regenerated=s.regenerate_section(edit.material_id,group,section.section_id)
        assert regenerated.sections[group][0].text==section.text and not regenerated.user_edits
        assert regenerated.label=='Draft'
    assert s.career.path('materials',m.material_id).read_bytes()==before


def mutate_evidence(e,**data):
    result=e.model_copy(update=data);body=result.model_dump(mode='json');body['evidence_hash']=digest({k:v for k,v in body.items() if k!='evidence_hash'})
    return e.model_validate(body)


def test_c_missing_retest_draft_no_gain(real):
    s,e=real;r={**e.retrieval_evidence,'config_after':None,'paired_metrics':{},'rank_movements':[]}
    e=mutate_evidence(e,retest_run_id=None,comparison={},retrieval_evidence=r,change={})
    # Deliberately incomplete new snapshot; the frozen baseline still records acquisition.
    v=normalize(e,'EVALUATION_WORKBENCH','GENERAL_PM');p=plan(v);m=generate(e,v,p,1)
    assert m.label=='Draft' and '不能宣称优化有效' in markdown_v2(m)
    assert '从 0.25' not in markdown_v2(m)


def test_d_regression_and_invalid_not_hidden(real):
    s,e=real;e=mutate_evidence(e,regressions=[{'case_id':'rag_1','transition':'RETRIEVAL_REGRESSED'}],invalid_cases=[{'case_id':'rag_8','category':'judge failure'}])
    v=normalize(e,'EVALUATION_WORKBENCH','GENERAL_PM');m=generate(e,v,plan(v),1)
    assert '1 个退化 Case、1 个无效' in markdown_v2(m)


def test_g_configuration_conflict_is_blocked(real):
    s,e=real;r={**e.retrieval_evidence,'config_before':{**e.retrieval_evidence['config_before'],'top_k':9}}
    e=mutate_evidence(e,retrieval_evidence=r);v=normalize(e,'EVALUATION_WORKBENCH','GENERAL_PM')
    assert v.conflicts
    m=generate(e,v,plan(v),1)
    assert m.label=='Mixed' and 'CONFIGURATION_CONFLICT' in {x['code'] for x in m.lint}
    assert '不能宣称优化有效' in markdown_v2(m)


def test_k_f_invalid_personal_performance_and_no_real_users(real):
    s,e=real;m=s.generate_v2(EID);text=markdown_v2(m)
    assert '没有真实用户' in text and '未上线' in text
    bad=e.context.model_copy(update={'user_contribution':'我手写全部系统，上线后 DAU 99999。'})
    e=mutate_evidence(e,context=bad);v=normalize(e,'EVALUATION_WORKBENCH','GENERAL_PM');m=generate(e,v,plan(v),1)
    assert {'PERSONAL_CONTRIBUTION_AMBIGUOUS','USER_UNVERIFIED_PERFORMANCE_NUMBER'}<={i['code'] for i in m.lint}


def test_api_v2_and_legacy_readable(real):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from experiments.career_api import router
    from experiments.api import configure,install_validation_handler
    s,e=real;configure(lambda:s.experiments);app=FastAPI();app.include_router(router);install_validation_handler(app);client=TestClient(app)
    body={'evidence_object_id':EID}
    assert client.post('/experiments/career/narrative/preview',json=body).status_code==200
    res=client.post('/experiments/career/materials/v2',json=body);assert res.status_code==200,res.text
    m=res.json();assert client.get('/experiments/career/views/'+m['view_id']).status_code==200
    assert client.get('/experiments/career/narratives/'+m['narrative_id']).status_code==200
    assert client.get('/experiments/career/materials/'+m['material_id']+'/export?group=interview').status_code==200
    # Legacy model defaults do not rewrite the original envelope.
    old=SOURCE/'career/materials/8423a263-a792-4059-abcb-f27e0a008221.json';dest=s.career.path('materials',old.stem);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(old,dest)
    raw=dest.read_bytes();assert s.export(old.stem)['markdown'];assert dest.read_bytes()==raw


def test_speech_rate_and_tampered_bindings(real):
    s,e=real;a=s.generate_v2(EID,speech_rate=180);b=s.generate_v2(EID,speech_rate=300)
    assert a.sections['interview'][0].text==b.sections['interview'][0].text
    assert a.sections['interview'][0].timing['estimated_seconds']>b.sections['interview'][0].timing['estimated_seconds']
    path=s.career.path('narratives',a.narrative_id);env=json.loads(path.read_text());env['artifact']['speech_rate']=240;env['sha256']=digest(env['artifact']);path.write_text(json.dumps(env))
    with pytest.raises(ValueError):s.export(a.material_id)

def test_rehashed_material_text_cannot_masquerade_as_fact(real):
    s,e=real;m=s.generate_v2(EID);path=s.career.path('materials',m.material_id);env=json.loads(path.read_text())
    env['artifact']['sections']['resume_ai'][1]['text']='回答质量提升了 99%。'
    env['sha256']=digest(env['artifact']);path.write_text(json.dumps(env))
    exported=s.export(m.material_id,'resume_ai')
    assert exported['label']=='Mixed' and 'EVIDENCE_TEXT_MISMATCH' in exported['markdown']


def test_generation_rejects_unsafe_context_without_storing_material(real):
    s,e=real;ctx=e.context.model_copy(update={'user_contribution':'我手写全部系统，上线后 DAU 99999。'})
    e=mutate_evidence(e,context=ctx,evidence_object_id='unsafe');s.career.put('evidence',e)
    before=list(s.career.root.rglob('*.json'))
    with pytest.raises(ValueError):s.generate_v2('unsafe')
    assert list(s.career.root.rglob('*.json'))==before

def test_historical_phase_evidence_byte_hashes_are_unchanged():
    import hashlib
    archive=os.environ.get('AGENT_EVAL_ARCHIVE_ROOT')
    if not archive:
        pytest.skip('Requires private integrity manifests: AGENT_EVAL_ARCHIVE_ROOT')
    root=Path(archive);phase=root/'analysis/20261007-echomind/phase5'
    manifests=[(root,json.loads((phase/'preserved-before.json').read_text())),(phase,json.loads((phase/'evidence-sha256.json').read_text()))]
    audit=json.loads((phase.parent/'phase5.1/read-only-audit.json').read_text())
    manifests.append((root,audit['current_store_sha256']))
    for base,manifest in manifests:
        for name,expected in manifest.items():
            assert hashlib.sha256((base/name).read_bytes()).hexdigest()==expected,name

def test_agent_path_v2_preserves_original_evaluation_semantics(tmp_path):
    from test_career import CONTEXT,build_agent
    from test_experiment_service import setup,baseline,applied
    import asyncio
    service,ev,_=setup(tmp_path);a=baseline(service,ev);decision,change=applied(service,a)
    b=asyncio.run(service.run(ev.eval_set_id,'RETEST',a.run_id,decision.decision_id,[change.change_id]));comp=service.compare(a.run_id,b.run_id)
    s=CareerService(service);e=build_agent((s,a,b,comp));before={p:p.read_bytes() for p in s.store.root.rglob('*.json')}
    m=s.generate_v2(e.evidence_object_id)
    assert not m.lint and 'RAG 和 Memory' in s.export(m.material_id)['markdown']
    assert len({q.category for q in m.defense})==6
    assert all(p.read_bytes()==content for p,content in before.items())


def test_normalized_claim_tampering_rejected_even_with_new_envelope_hash(real):
    s,e=real;m=s.generate_v2(EID);p=s.career.path('views',m.view_id);env=json.loads(p.read_text())
    env['artifact']['facts']['metric_mrr']['value']['after']=.99;env['sha256']=digest(env['artifact']);p.write_text(json.dumps(env))
    with pytest.raises(ValueError):s.export(m.material_id)

def test_free_edit_never_reuses_machine_sentence_citation(real):
    s,e=real;m=s.generate_v2(EID);section=m.sections['resume_ai'][0]
    edited=s.edit(m.material_id,'resume_ai',section.section_id,'我的自由编辑文案。')
    after=edited.sections['resume_ai'][0]
    assert after.safe_wording==section.text and not after.citations
    assert after.source_type=='USER_UNVERIFIED_CLAIM'
    assert edited.readiness['resume_ai']['evidence_integrity']['status']=='NEEDS_VERIFICATION'
