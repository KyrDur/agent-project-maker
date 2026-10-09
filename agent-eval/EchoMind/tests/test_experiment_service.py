import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from core.skill_loader import SkillManager
from experiments.canonical import digest
from experiments.models import Run
from experiments.service import ExperimentService
from experiments.store import JsonStore
from test_evaluation import evaluator

class FixtureRuntime:
    """Exercise the real Phase 2 evaluator with a local injected transport."""
    def __init__(self,score=.2,limit=None,drift=False):
        self.score,self.limit,self.drift = score,limit,drift
    async def execute(self,run,credential,environment):
        ev,_ = evaluator(score=self.score)
        ev._config = __import__("evaluation.config",fromlist=["EvaluationConfig"]).EvaluationConfig.model_validate(run.evaluation_config_snapshot)
        cases = sorted(run.eval_set_snapshot["case_snapshot"],key=lambda c:c["case_id"])
        if self.limit is not None:
            cases = cases[:self.limit]
        report = await ev.run(dialog_cases=cases)
        actual = deepcopy(run.runtime_start_snapshot)
        if self.drift:
            actual["routing_config_version"]["monitor"] = "changed"
        return {"case_results":[r.model_dump() for r in report.results],"intent_metrics":{},
                "intent_sample_results":[],
                "runtime_end_check":{"drift_detected":self.drift,"reliable_isolation":True,"reasons":[],
                                     "actual_snapshot":actual}}

def setup(tmp_path,**kwargs):
    root = tmp_path/"skills"
    root.mkdir(exist_ok=True)
    (root/"refund.md").write_text("---\nname: Refund\nkeywords: 退款\nagents: billing\nenabled: true\n---\n# Refund\nVerify first.\n")
    manager = SkillManager(str(root))
    manager.load_strict()
    runtime = kwargs.pop("runtime",FixtureRuntime())
    service = ExperimentService(JsonStore(tmp_path/"store"),manager,credential="test-private-credential",runtime=runtime,**kwargs)
    ev = service.create_eval_set([{"case_id":"a","turns":["退款","order","time"]},
                                 {"case_id":"b","input":"other"}])
    return service,ev,manager

def baseline(service,ev):
    return asyncio.run(service.run(ev.eval_set_id))

def confirmed(service,run):
    draft = service.create_decision(run.run_id,["a"],root_cause_suggestion="AI hypothesis",
        strategy_suggestion="AI strategy")
    return service.confirm_decision(draft.decision_id,user_confirmed_root_cause="Missing guidance",
        root_cause_reason="Read evidence",selected_strategy="Clarify refund rule",selection_reason="Minimal",
        expected_benefit="More accurate",possible_side_effects="Longer answer",confirmed_by="user")

def applied(service,run):
    decision = confirmed(service,run)
    change = service.propose_change(decision.decision_id,"refund.md","Verify order and payment first.",run.skill_version["hash"])
    return decision,service.apply_change(change.change_id)

def test_run_frozen_deepcopy_seal_restart_credentials(tmp_path):
    service,ev,manager = setup(tmp_path)
    run = baseline(service,ev)
    assert run.status == "COMPLETE"
    assert len(run.case_results)==2 and len(run.case_results[0].turn_evidence)==3
    assert run.evaluation_protocol_hash == digest(run.evaluation_protocol_snapshot)
    assert run.inference_config_snapshot["agents"]["billing"]["temperature"]==0
    assert run.runtime_policy_snapshot["cache_policy"]["intent"]=="disabled"
    assert run.artifact_hash
    data = run.model_dump()
    data["case_results"]=[]
    with pytest.raises(ValueError,match="Immutable"):
        service.store.put("runs",Run.model_validate(data))
    run.case_results.clear() # Nested client object cannot mutate persisted evidence.
    assert len(service.store.get("runs",run.run_id).case_results)==2
    restarted = ExperimentService(JsonStore(tmp_path/"store"),manager,credential="test-private-credential",runtime=FixtureRuntime())
    assert restarted.store.get("runs",run.run_id).artifact_hash==run.artifact_hash
    for path in (tmp_path/"store").rglob("*.json"):
        assert "test-private-credential" not in path.read_text()

def test_runtime_drift_detected_and_partial_retained(tmp_path):
    service,ev,_ = setup(tmp_path,runtime=FixtureRuntime(limit=1,drift=True))
    run = baseline(service,ev)
    assert run.status=="PARTIAL"
    assert run.runtime_end_check["drift_detected"]
    assert "RUNTIME_CONFIG_DRIFT" in run.runtime_end_check["reasons"]
    assert len(run.case_results)==1

def test_review_is_append_only_and_cannot_erase_machine(tmp_path):
    service,ev,_ = setup(tmp_path)
    run = baseline(service,ev)
    before = service.store.path("runs",run.run_id).read_bytes()
    with pytest.raises(ValueError):
        service.review(run.run_id,"a","PASS","","user")
    record = service.review(run.run_id,"a","PASS","Evidence checked","user")
    assert record.revision==1 and record.original_status=="FAIL"
    assert service.store.path("runs",run.run_id).read_bytes()==before
    effective = service.result_view(run.run_id)
    assert effective["effective_results"][0]["final_status"]=="PASS"
    assert effective["effective_results"][0]["original_status"]=="FAIL"
    assert service.review(run.run_id,"a","FAIL","Second review","user").revision==2

def test_confirmed_decision_required_and_preserves_suggestion(tmp_path):
    service,ev,_ = setup(tmp_path)
    run = baseline(service,ev)
    draft = service.create_decision(run.run_id,["a"],root_cause_suggestion="Possible")
    assert draft.status=="DRAFT" and draft.user_confirmed_root_cause is None
    with pytest.raises(ValueError):
        service.propose_change(draft.decision_id,"refund.md","new",run.skill_version["hash"])
    with pytest.raises(ValueError):
        service.confirm_decision(draft.decision_id,confirmed_by="user")
    with pytest.raises(ValueError):
        service.create_decision(run.run_id,["unknown"])
    dec = confirmed(service,run)
    assert dec.root_cause_suggestion=="AI hypothesis" and dec.user_confirmed_root_cause=="Missing guidance"
