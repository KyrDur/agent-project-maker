import asyncio
from pathlib import Path
import pytest
from core.skill_loader import SkillManager
from experiments.skills import skill_snapshot, skill_diff, one_body
from experiments.store import JsonStore
from experiments.service import ExperimentService
from test_experiment_service import setup, baseline, confirmed, applied, FixtureRuntime

def test_apply_real_reload_readback_and_rollback(tmp_path):
    service,ev,manager = setup(tmp_path)
    run = baseline(service,ev)
    decision,change = applied(service,run)
    assert change.implemented_status=="APPLIED"
    assert change.declared_diff==change.observed_diff
    assert one_body(change.observed_diff)
    assert change.application_evidence["reload"]
    assert change.after_hash==skill_snapshot(manager)["hash"]==change.verified_effective_version
    assert "payment" in manager.prompt_for("退款","billing")
    rolled = service.rollback(change.change_id)
    assert rolled.rollback_status=="ROLLED_BACK"
    assert rolled.application_evidence["rollback_reload"]
    assert skill_snapshot(manager)==run.skill_version
    with pytest.raises(ValueError):
        asyncio.run(service.run(ev.eval_set_id,"RETEST",run.run_id,decision.decision_id,[change.change_id]))

def test_before_mismatch_noop_and_unsupported(tmp_path):
    service,ev,manager = setup(tmp_path)
    run = baseline(service,ev)
    dec = confirmed(service,run)
    with pytest.raises(ValueError,match="before_hash"):
        service.propose_change(dec.decision_id,"refund.md","new","bad")
    noop = service.propose_change(dec.decision_id,"refund.md","Verify first.",run.skill_version["hash"])
    assert service.apply_change(noop.change_id).implemented_status=="NOOP"
    for kind in ("PROMPT","KNOWLEDGE"):
        other = service.propose_change(dec.decision_id,"refund.md","new",run.skill_version["hash"],change_type=kind)
        assert other.implemented_status=="UNSUPPORTED"
        with pytest.raises(ValueError):
            service.apply_change(other.change_id)
    change = service.propose_change(dec.decision_id,"refund.md","new body",run.skill_version["hash"])
    (manager.root_dir/"refund.md").write_text("different")
    with pytest.raises(ValueError):
        service.apply_change(change.change_id)

def test_strict_parse_failure_does_not_activate_half_collection(tmp_path):
    service,ev,manager = setup(tmp_path)
    run = baseline(service,ev)
    old_skills = manager.skills
    (manager.root_dir/"broken.json").write_text("{bad json")
    with pytest.raises(Exception):
        manager.load_strict()
    assert manager.skills==old_skills
    dec = confirmed(service,run)
    change = service.propose_change(dec.decision_id,"refund.md","new body",run.skill_version["hash"])
    with pytest.raises(Exception):
        service.apply_change(change.change_id)
    assert manager.skills==old_skills

def test_reload_failure_compensates_disk_and_active_collection(tmp_path,monkeypatch):
    service,ev,manager = setup(tmp_path)
    run = baseline(service,ev)
    dec = confirmed(service,run)
    change = service.propose_change(dec.decision_id,"refund.md","new body",run.skill_version["hash"])
    before_bytes = (manager.root_dir/"refund.md").read_bytes()
    original = manager.load_strict
    monkeypatch.setattr(manager,"load_strict",lambda: (_ for _ in ()).throw(RuntimeError("reload failure")))
    with pytest.raises(ValueError,match="Apply failed"):
        service.apply_change(change.change_id)
    assert (manager.root_dir/"refund.md").read_bytes()==before_bytes
    assert skill_snapshot(manager)==run.skill_version
    assert service.store.get("changes",change.change_id).implemented_status=="FAILED"
    monkeypatch.setattr(manager,"load_strict",original)

def test_one_id_cannot_smuggle_matching_heading_or_budget(tmp_path):
    service,ev,manager = setup(tmp_path)
    run = baseline(service,ev)
    dec = confirmed(service,run)
    # The serializer preserves an inferred name heading independently of rule body.
    root = tmp_path/"other"
    root.mkdir()
    (root/"plain.md").write_text("# Original\nBody")
    other = SkillManager(str(root))
    other.load_strict()
    from experiments.skills import SkillController
    after,diff = SkillController(other).propose(skill_snapshot(other),"plain.md","# Injected\nbody")
    assert after["skills"][0]["name"] == "Original" and one_body(diff)
    change = service.propose_change(dec.decision_id,"refund.md","new body",run.skill_version["hash"])
    data = change.model_dump()
    data["after_snapshot"]["max_prompt_chars"] = 10
    from experiments.models import Change
    service.store.put("changes",Change.model_validate(data))
    with pytest.raises(ValueError):
        service.apply_change(change.change_id)

def test_retest_same_evalset_applied_required_and_restart_relations(tmp_path):
    service,ev,manager = setup(tmp_path)
    a = baseline(service,ev)
    dec,change = applied(service,a)
    service.runtime.score=.95
    b = asyncio.run(service.run(ev.eval_set_id,"RETEST",a.run_id,dec.decision_id,[change.change_id]))
    assert b.status=="COMPLETE" and b.parent_run_id==a.run_id
    assert b.case_results[0].original_status=="PASS"
    restarted = ExperimentService(JsonStore(tmp_path/"store"),manager,credential="test-private-credential",runtime=FixtureRuntime())
    assert restarted.store.get("runs",b.run_id).applied_change_ids==[change.change_id]
    assert restarted.store.get("changes",change.change_id).decision_id==dec.decision_id
    assert restarted.store.get("decisions",dec.decision_id).related_run_id==a.run_id
    different = restarted.create_eval_set([{"case_id":"a","input":"different"}])
    with pytest.raises(ValueError):
        asyncio.run(restarted.run(different.eval_set_id,"RETEST",a.run_id,dec.decision_id,[change.change_id]))
    # A new ordinary baseline may bind a different EvalSet.
    assert asyncio.run(restarted.run(different.eval_set_id)).run_type=="BASELINE"
