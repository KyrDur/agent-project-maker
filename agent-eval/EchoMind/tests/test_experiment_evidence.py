"""Additional audit contracts for evidence, recovery and controlled runtime drift."""
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from experiments.models import Run, Change, uid, now
from experiments.store import JsonStore
from experiments.service import ExperimentService
from test_experiment_service import setup, baseline, applied, confirmed, FixtureRuntime
from test_experiment_comparison import clone
from test_evaluation import evaluator, Orch
from evaluation.evaluator import IntentTestCase

class ErrorRuntime(FixtureRuntime):
    def __init__(self,kind):
        self.kind=kind
    async def execute(self,run,credential,environment):
        ev,_=evaluator(judge_error=RuntimeError("private") if self.kind=="judge" else None,
                       orch=Orch(status="FAILED") if self.kind=="agent" else None)
        report=await ev.run(dialog_cases=run.eval_set_snapshot["case_snapshot"])
        return {"case_results":[r.model_dump() for r in report.results],"intent_metrics":{},"intent_sample_results":[],
                "runtime_end_check":{"drift_detected":False,"reliable_isolation":True,"reasons":[],
                    "actual_snapshot":run.runtime_start_snapshot}}

@pytest.mark.parametrize("kind",["judge","agent"])
def test_invalid_any_pair_and_no_human_fabrication(tmp_path,kind):
    service,ev,_=setup(tmp_path,runtime=ErrorRuntime(kind))
    a=baseline(service,ev)
    assert a.status=="COMPLETE" and a.case_results[0].original_status=="INVALID"
    for status in ("PASS","FAIL"):
        with pytest.raises(ValueError):
            service.review(a.run_id,"a",status,"Cannot invent execution","user")
    b=baseline(service,ev)
    comp=service.compare(a.run_id,b.run_id)
    assert comp.comparable
    assert all(p["machine_transition"]==p["effective_transition"]=="NOT_COMPARABLE" for p in comp.case_comparisons)
    view=service.result_view(a.run_id)
    assert view["dialog_case_metrics"]["valid"]==0

def test_hard_rule_override_retains_all_evidence(tmp_path):
    service,_,_=setup(tmp_path)
    ev=service.create_eval_set([{"case_id":"a","input":"refund",
        "executable_rules":[{"type":"required_tool","tool":"required_but_absent"}]}])
    a=baseline(service,ev)
    dec,change=applied(service,a)
    b=asyncio.run(service.run(ev.eval_set_id,"RETEST",a.run_id,dec.decision_id,[change.change_id]))
    before=service.store.path("runs",a.run_id).read_bytes()
    review=service.review(a.run_id,"a","PASS","Human verified external evidence","user")
    assert review.hard_rule_override
    comp=service.compare(a.run_id,b.run_id)
    p=comp.case_comparisons[0]
    assert p["machine_transition"]=="STILL_FAIL" and p["effective_transition"]=="REGRESSED"
    assert p["hard_rule_violations_a"] and p["hard_rule_override_a"] and p["human_reason_a"]
    assert service.store.path("runs",a.run_id).read_bytes()==before

def test_drift_and_missing_snapshots_are_global_blockers(tmp_path):
    service,ev,_=setup(tmp_path)
    a=baseline(service,ev)
    service.runtime.drift=True
    b=baseline(service,ev)
    comp=service.compare(a.run_id,b.run_id)
    assert not comp.comparable and "RUNTIME_CONFIG_DRIFT" in comp.comparability_reasons
    missing=clone(service,a,knowledge_version={})
    comp=service.compare(a.run_id,missing.run_id)
    assert not comp.comparable and "MISSING_REQUIRED_SNAPSHOT" in comp.comparability_reasons

def test_store_run_lease_restart_live_vs_interrupted_and_journal(tmp_path):
    service,ev,manager=setup(tmp_path)
    sealed=baseline(service,ev)
    data=sealed.model_dump()
    data.update(run_id=uid(),status="RUNNING",artifact_hash=None,finished_at=None)
    active=service.store.put("runs",Run.model_validate(data))
    lease=service.store.acquire_run_lease(active.run_id)
    other=ExperimentService(JsonStore(tmp_path/"store"),manager,runtime=FixtureRuntime())
    assert other.store.get("runs",active.run_id).status=="RUNNING"
    lease.close()
    restarted=ExperimentService(JsonStore(tmp_path/"store"),manager,runtime=FixtureRuntime())
    recovered=restarted.store.get("runs",active.run_id)
    assert recovered.status=="FAILED" and "PROCESS_INTERRUPTED" in recovered.warnings
    dec=confirmed(service,sealed)
    change=service.propose_change(dec.decision_id,"refund.md","new body",sealed.skill_version["hash"])
    service.store.put("changes",Change.model_validate({**change.model_dump(),"implemented_status":"APPLYING"}))
    recovered_service=ExperimentService(JsonStore(tmp_path/"store"),manager,runtime=FixtureRuntime())
    assert recovered_service.store.get("changes",change.change_id).implemented_status=="FAILED"

def test_rollback_exact_original_raw_bytes_no_newline(tmp_path):
    service,_,manager=setup(tmp_path)
    path=manager.root_dir/"refund.md"
    raw="---\nname: Refund\nkeywords: 退款\nagents: billing\n---\n# Refund\n\nOld rule  "
    path.write_text(raw)
    manager.load_strict()
    ev=service.create_eval_set([{"case_id":"a","input":"refund"}])
    a=baseline(service,ev)
    _,change=applied(service,a)
    service.rollback(change.change_id)
    assert path.read_text()==raw and service.skills.current()==a.skill_version

def test_atomic_write_failure_and_readback_mismatch_no_applied(tmp_path,monkeypatch):
    service,ev,manager=setup(tmp_path)
    a=baseline(service,ev)
    dec=confirmed(service,a)
    c=service.propose_change(dec.decision_id,"refund.md","new body",a.skill_version["hash"])
    import experiments.skills as module
    original=module.atomic_text
    monkeypatch.setattr(module,"atomic_text",lambda *args: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(ValueError):
        service.apply_change(c.change_id)
    assert service.skills.current()==a.skill_version
    assert service.store.get("changes",c.change_id).implemented_status=="FAILED"
    monkeypatch.setattr(module,"atomic_text",original)
    c=service.propose_change(dec.decision_id,"refund.md","new body",a.skill_version["hash"])
    original_load=manager.load_strict
    def corrupted_reload():
        original_load()
        manager._skills[0].content="unexpected actual version"
    monkeypatch.setattr(manager,"load_strict",corrupted_reload)
    with pytest.raises(ValueError):
        service.apply_change(c.change_id)
    assert service.skills.current()==a.skill_version
    assert service.store.get("changes",c.change_id).implemented_status=="FAILED"

def test_worker_detects_actual_agent_model_mutation_and_denies_reload(tmp_path,monkeypatch):
    import agents.agent_orchestrator as agents
    from experiments.worker import execute
    from evaluation.evaluator import LLMJudge
    from core.intent_recognizer import IntentRecognizer
    service,ev,_=setup(tmp_path)
    a=baseline(service,ev)
    async def recognize(self,*args,**kwargs):
        from core.intent_recognizer import IntentCategory
        return SimpleNamespace(intent=IntentCategory.REFUND,intent_group="billing",urgency=None,
            confidence=1,entities={},reasoning="fixture")
    async def judge(self,*args,**kwargs):
        from evaluation.models import QualityScores
        return QualityScores(.95,.95,.95,.95)
    denied=[]
    async def handle(self,req):
        try:
            self._skill_manager.reload()
        except RuntimeError:
            denied.append(True)
        self._model="drifted-model"
        return agents.AgentResponse(agent_type=self.agent_type,content="valid output",success=True)
    monkeypatch.setattr(IntentRecognizer,"recognize",recognize)
    monkeypatch.setattr(LLMJudge,"judge",judge)
    monkeypatch.setattr(agents.BillingAgent,"handle",handle)
    # Same service object is not passed to worker; only a serialized immutable Run.
    output=asyncio.run(execute({"run":a.model_dump(mode="json"),"credential":"local"}))
    assert denied and output["runtime_end_check"]["drift_detected"]
    assert "RUNTIME_CONFIG_DRIFT" in output["runtime_end_check"]["reasons"]
    assert output["runtime_end_check"]["actual_snapshot"]["inference_config_snapshot"]["agents"]["billing"]["model"]=="drifted-model"

def test_evalset_revisions_are_separate_immutable_and_retest_pins_parent(tmp_path):
    service,ev,_=setup(tmp_path)
    a=baseline(service,ev)
    second=service.create_eval_set([{"case_id":"a","input":"new input"}],
        eval_set_id=ev.eval_set_id,eval_set_version=2)
    assert service.store.get("evalsets",ev.eval_set_id,1)==ev
    assert service.store.get("evalsets",ev.eval_set_id,2)==second
    assert service.store.get("evalsets",ev.eval_set_id)==second
    with pytest.raises(ValueError):
        service.store.put("evalsets",second)
    _,change=applied(service,a)
    dec=service.store.get("decisions",change.decision_id)
    b=asyncio.run(service.run(ev.eval_set_id,"RETEST",a.run_id,dec.decision_id,[change.change_id]))
    assert b.eval_set_snapshot["eval_set_version"]==1 and b.eval_set_hash==a.eval_set_hash

def test_protocol_identity_excludes_real_raw_code_audit_change(tmp_path,monkeypatch):
    import experiments.snapshots as snapshots
    from evaluation.config import EvaluationConfig
    from experiments.canonical import digest
    service,_,manager=setup(tmp_path)
    original=snapshots.capture(manager,EvaluationConfig())
    root=tmp_path/"audit-source"
    for relative in snapshots.SOURCE_FILES:
        target=root/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text((snapshots.ROOT/relative).read_text()+"\n# harmless audit-only comment\n")
    monkeypatch.setattr(snapshots,"ROOT",root)
    changed=snapshots.capture(manager,EvaluationConfig())
    assert original["runtime_policy_snapshot"]["implementation_guard"] != changed["runtime_policy_snapshot"]["implementation_guard"]
    assert digest(original["evaluation_protocol_snapshot"]) == digest(changed["evaluation_protocol_snapshot"])
