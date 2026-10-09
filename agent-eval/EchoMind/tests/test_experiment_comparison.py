import asyncio
from copy import deepcopy
import pytest
from experiments.models import Run, Change, uid, now
from experiments.store import JsonStore
from experiments.service import ExperimentService
from test_experiment_service import setup, baseline, applied, FixtureRuntime

def clone(service,run,**updates):
    data = run.model_dump()
    data.update({"run_id":uid(),"created_at":now(),"artifact_hash":None,**updates})
    # A different configuration gets its own genuine frozen start/readback evidence.
    for key in data["runtime_start_snapshot"]:
        if key in data:
            data["runtime_start_snapshot"][key]=deepcopy(data[key])
    data["runtime_end_check"]["actual_snapshot"]=deepcopy(data["runtime_start_snapshot"])
    return service.store.put("runs",Run.model_validate(data))

def pair(service,ev,score_a=.2,score_b=.95,limit=None):
    service.runtime.score=score_a
    a=baseline(service,ev)
    dec,change=applied(service,a)
    service.runtime.score=score_b
    service.runtime.limit=limit
    b=asyncio.run(service.run(ev.eval_set_id,"RETEST",a.run_id,dec.decision_id,[change.change_id]))
    return a,b,dec,change

@pytest.mark.parametrize("a_score,b_score,expected",[(.2,.95,"IMPROVED"),(.95,.2,"REGRESSED"),
                                                      (.95,.95,"STILL_PASS"),(.2,.2,"STILL_FAIL")])
def test_transitions_legitimate_single_change_and_restart(tmp_path,a_score,b_score,expected):
    service,ev,manager=setup(tmp_path)
    a,b,_,change=pair(service,ev,a_score,b_score)
    result=service.compare(a.run_id,b.run_id)
    assert result.comparable and not result.attributable and result.single_recorded_change
    assert result.attribution_status=="INSUFFICIENT_EVIDENCE"
    assert "MODEL_BACKEND_REVISION_UNVERIFIED" in result.attribution_warnings
    assert result.comparison_completeness=="FULL"
    assert all(p["effective_transition"]==expected for p in result.case_comparisons)
    assert result.direct_comparison is result.comparable
    assert "direct_comparison" not in result.model_dump()
    assert "SINGLE_RUN_RANDOMNESS_NOT_CAUSAL_PROOF" in result.attribution_warnings
    reopened=ExperimentService(JsonStore(tmp_path/"store"),manager,credential="test-private-credential",runtime=FixtureRuntime())
    assert reopened.store.get("comparisons",result.comparison_id)==result
    # Later rollback doesn't rewrite the historical comparison or make old after current.
    service.rollback(change.change_id)
    assert reopened.store.get("comparisons",result.comparison_id)==result

def test_partial_retains_valid_pairs_and_no_fullset_claim(tmp_path):
    service,ev,_=setup(tmp_path)
    a,b,_,_=pair(service,ev,limit=1)
    comp=service.compare(a.run_id,b.run_id)
    assert comp.comparable and not comp.attributable and comp.single_recorded_change
    assert comp.comparison_completeness=="PARTIAL"
    assert comp.expected_case_count==2 and comp.matched_case_count==1
    assert comp.case_comparisons[0]["effective_transition"]=="IMPROVED"
    missing=comp.case_comparisons[1]
    assert missing["effective_transition"]=="NOT_COMPARABLE"
    assert "MISSING_RETEST_RESULT" in missing["not_comparable_reasons"]
    assert comp.group_metrics["dialog_case_metrics"]["scope"]=="MATCHED_VALID_CASES"
    assert "full EvalSet" in comp.group_metrics["claim_scope"]

def test_invalid_pending_and_review_revisions(tmp_path):
    service,ev,_=setup(tmp_path)
    # Human review is valid execution awaiting a conclusion, not a runtime error.
    ev=service.create_eval_set([{"case_id":"a","input":"refund","judge_method":"human review"}])
    a,b,_,_=pair(service,ev)
    pending=service.compare(a.run_id,b.run_id)
    assert pending.comparable
    assert pending.case_comparisons[0]["effective_transition"]=="NOT_COMPARABLE"
    assert "PENDING_HUMAN_REVIEW" in pending.case_comparisons[0]["not_comparable_reasons"]
    before=service.store.path("comparisons",pending.comparison_id).read_bytes()
    service.review(a.run_id,"a","FAIL","Needs detail","reviewer")
    service.review(b.run_id,"a","PASS","Evidence acceptable","reviewer")
    comp=service.compare(a.run_id,b.run_id)
    assert comp.case_comparisons[0]["machine_transition"]=="NOT_COMPARABLE"
    assert comp.case_comparisons[0]["effective_transition"]=="IMPROVED"
    assert comp.review_revision_a==comp.review_revision_b==1
    assert service.store.path("comparisons",pending.comparison_id).read_bytes()==before

@pytest.mark.parametrize("key,patch,reason",[
    ("eval_set_hash","different","EVALSET_CHANGED"),
    ("evaluation_protocol_hash","different","EVALUATION_PROTOCOL_CHANGED"),
    ("inference_config_snapshot",{"changed":"judge model"},"MODEL_PROVIDER_INFERENCE_CHANGED"),
    ("agent_config_snapshot",{"changed":"agent model"},"AGENT_CONFIG_CHANGED"),
    ("prompt_version",{"changed":"prompt"},"PROMPT_CHANGED"),
    ("routing_config_version",{"changed":"routing"},"ROUTING_CHANGED"),
    ("runtime_policy_snapshot",{"reliable_isolation":False},"EXPERIMENT_STATE_NOT_ISOLATED")])
def test_global_control_blockers(tmp_path,key,patch,reason):
    service,ev,_=setup(tmp_path)
    a,b,_,_=pair(service,ev)
    changed=clone(service,b,**{key:patch})
    comp=service.compare(a.run_id,changed.run_id)
    assert not comp.comparable and not comp.attributable
    assert reason in comp.comparability_reasons
    assert all(p["effective_transition"]=="NOT_COMPARABLE" for p in comp.case_comparisons)

def test_unrecorded_and_declared_observed_mismatch(tmp_path):
    service,ev,_=setup(tmp_path)
    a,b,_,change=pair(service,ev)
    undocumented=clone(service,b,applied_change_ids=[])
    result=service.compare(a.run_id,undocumented.run_id)
    assert result.attribution_status=="UNRECORDED_CHANGE" and not result.comparable
    # Preserve the original recorded intervention; a forged second ID cannot replace evidence.
    forged=Change.model_validate({**change.model_dump(),"change_id":uid(),"observed_diff":[]})
    service.store.put("changes",forged)
    modified=clone(service,b,applied_change_ids=[forged.change_id])
    result=service.compare(a.run_id,modified.run_id)
    assert not result.attributable and not result.comparable
    assert result.attribution_status=="MULTI_COMPONENT_CHANGE"

def test_one_change_multiple_components_not_attributable(tmp_path):
    service,ev,_=setup(tmp_path)
    a,b,_,change=pair(service,ev)
    data=change.model_dump()
    data.update(change_id=uid(),observed_diff=[*change.observed_diff,{"path":"max_prompt_chars","before_hash":"a","after_hash":"b"}])
    data["declared_diff"]=data["observed_diff"]
    forged=service.store.put("changes",Change.model_validate(data))
    b=clone(service,b,applied_change_ids=[forged.change_id])
    comp=service.compare(a.run_id,b.run_id)
    assert not comp.attributable and comp.attribution_status=="MULTI_COMPONENT_CHANGE"

def test_multiple_recorded_changes_comparable_but_not_single_attribution(tmp_path):
    service,ev,_=setup(tmp_path)
    a,b,first_dec,first=pair(service,ev)
    # The intermediate sealed Run gives the next Decision a genuine effective before version.
    from test_experiment_service import confirmed
    second_dec=confirmed(service,b)
    second=service.propose_change(second_dec.decision_id,"refund.md","Another body",b.skill_version["hash"])
    second=service.apply_change(second.change_id)
    from experiments.models import Run
    chain=asyncio.run(service.run(ev.eval_set_id,"RETEST",a.run_id,first_dec.decision_id,[first.change_id,second.change_id]))
    comp=service.compare(a.run_id,chain.run_id)
    assert comp.comparable
    assert not comp.attributable and comp.attribution_status=="MULTI_CHANGE"

def test_missing_baseline_pair_and_no_change(tmp_path):
    service,ev,_=setup(tmp_path)
    a=baseline(service,ev)
    service.runtime.limit=1
    b=baseline(service,ev)
    comp=service.compare(b.run_id,a.run_id)
    assert comp.comparable and comp.attribution_status=="NO_CHANGE"
    assert "MISSING_BASELINE_RESULT" in comp.case_comparisons[1]["not_comparable_reasons"]
