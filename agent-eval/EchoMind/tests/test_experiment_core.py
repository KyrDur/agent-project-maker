"""Contracts of the accepted experiment design; no external services."""
from copy import deepcopy
import json
import pytest
from pydantic import ValidationError
from evaluation.config import EvaluationConfig
from experiments.canonical import create_eval_set, eval_set_semantics, digest, evaluation_protocol
from experiments.store import JsonStore

def sample():
    return [{"case_id":"a", "turns":["first","second"], "must_do":["verify"]},
            {"case_id":"b", "input":"other"}]

def test_canonical_display_key_case_order_and_numbers():
    ev = create_eval_set(sample())
    other = create_eval_set(list(reversed(sample())), metadata={"ui":"new"})
    assert ev.eval_set_hash == other.eval_set_hash
    data = sample()
    data[0]["title"] = "UI title"
    data[0]["scenario"] = "display scenario"
    assert create_eval_set(data).eval_set_hash == ev.eval_set_hash
    assert digest({"a":1.0,"b":.75}) == digest({"b":.75,"a":1})
    assert digest(evaluation_protocol()) == digest(dict(reversed(list(evaluation_protocol().items()))))

@pytest.mark.parametrize("field,value", [
    ("turns",["second","first"]), ("turns",["changed","second"]),
    ("test_conditions","offline"), ("must_do",["other"]),
    ("must_not_do",["fabricate"]), ("executable_rules",[{"type":"required_tool","tool":"check"}]),
    ("judge_method","human review"), ("user_id","other")])
def test_semantic_changes(field,value):
    data = sample()
    before = create_eval_set(data)
    data[0][field] = value
    assert create_eval_set(data).eval_set_hash != before.eval_set_hash

def test_threshold_protocol_and_audit_identity():
    before = create_eval_set(sample())
    cfg = EvaluationConfig(quality_thresholds={"accuracy":.8})
    assert create_eval_set(sample(),config=cfg).eval_set_hash != before.eval_set_hash
    changed = evaluation_protocol()
    changed["hard_rule_protocol_version"] = "next"
    assert create_eval_set(sample(),protocol=changed).eval_set_hash != before.eval_set_hash
    p = evaluation_protocol()
    assert digest(p) == digest(evaluation_protocol())  # source audit metadata is a separate identity
    assert digest({"protocol":p,"source_audit":"one"}) != digest({"protocol":p,"source_audit":"two"})
    with pytest.raises(ValueError):
        digest({"score":float("nan")})

def test_legacy_stable_ids_persist_restart_and_duplicate_rejection(tmp_path):
    store = JsonStore(tmp_path)
    ev = create_eval_set([{"question":"old"}, {"turns":["one","two"]}])
    assert all(not c.case_id.startswith("dialog_") for c in ev.case_snapshot)
    store.put("evalsets",ev)
    restored = JsonStore(tmp_path).get("evalsets",ev.eval_set_id)
    assert restored == ev
    assert restored.case_snapshot[0].legacy
    with pytest.raises(ValueError):
        store.put("evalsets",ev)
    with pytest.raises(ValidationError):
        create_eval_set([{"case_id":"a","input":"one"},{"case_id":"a","input":"two"}])

def test_atomic_failure_leaves_previous_and_no_credentials(tmp_path,monkeypatch):
    import experiments.store as module
    store = JsonStore(tmp_path, forbidden_values=("test-private-credential",))
    ev = create_eval_set(sample())
    original = module.os.replace
    monkeypatch.setattr(module.os,"replace",lambda *args: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(OSError):
        store.put("evalsets",ev)
    assert not store.path("evalsets",ev.eval_set_id).exists()
    monkeypatch.setattr(module.os,"replace",original)
    for metadata in ({"api_key":"x"},{"content":"test-private-credential"},{"Authorization":"Bearer abc"}):
        with pytest.raises(ValueError):
            store.put("evalsets",create_eval_set(sample(),metadata=metadata))
    store.put("evalsets",ev)
    envelope = json.loads(store.path("evalsets",ev.eval_set_id).read_text())
    envelope["artifact"]["eval_set_hash"] = "tampered"
    store.path("evalsets",ev.eval_set_id).write_text(json.dumps(envelope))
    with pytest.raises(ValueError,match="integrity"):
        store.get("evalsets",ev.eval_set_id)
