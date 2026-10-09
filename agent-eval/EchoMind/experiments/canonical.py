"""Semantic identities exclude display metadata and raw source audit hashes."""
import hashlib
import json
from copy import deepcopy
from evaluation.config import DEFAULT_CONFIG, EvaluationConfig
from evaluation.evaluator import LLMJudge
from evaluation.legacy import adapt_case
from evaluation.models import DIMENSIONS
from .models import EvalSet, IntentCase, uid

def canonical(value):
    # Normalize equal JSON numeric expressions, reject non-finite numbers.
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, float):
        import math
        if not math.isfinite(value):
            raise ValueError("Non-finite snapshot")
        return int(value) if value.is_integer() else value
    return value

def encoded(value):
    return json.dumps(canonical(value), sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")

def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()

def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def evaluation_protocol(config=DEFAULT_CONFIG):
    return {
        "schema_version": "1",
        "status_semantics": {"execution_error": "INVALID", "hard_rule_fail": "FAIL", "judge_failure": "INVALID"},
        "precedence": ["execution_validity", "hard_rule", "quality_judge", "human_review"],
        "judge_prompt_hash": text_hash(LLMJudge.JUDGE_PROMPT),
        "required_quality_dimensions": list(DIMENSIONS),
        "quality_thresholds": config.quality_thresholds.model_dump(),
        "quality_pass": "ALL_REQUIRED_DIMENSIONS_GTE_THRESHOLD",
        "hard_rule_protocol_version": "phase2-1",
        "legacy_adapter_semantics_version": "phase2-1",
        "human_review_semantics": {"reason_required": True, "invalid_execution_override": False,
            "hard_rule_override_explicit": True, "original_evidence_preserved": True,
            "pending_excluded_from_errors": True},
        "metrics": {"groups": ["intent", "dialog"], "dialog_denominator": "VALID_CASES",
                   "invalid_excluded": True, "one_case_one_result": True,
                   "pending_separate": True, "quality_average": "VALID_QUALITY_SCORES_ONLY"},
    }

def eval_set_semantics(eval_set):
    cases = []
    for c in sorted(eval_set.case_snapshot, key=lambda c: c.case_id):
        cases.append({"case_id": c.case_id, "turns": c.questions,
            "test_conditions": c.test_conditions, "must_do": c.must_do,
            "must_not_do": c.must_not_do,
            "executable_rules": [r.model_dump() for r in c.executable_rules],
            "judge_method": c.judge_method, "user_id": c.user_id, "conv_id": c.conv_id})
    return {"hash_protocol_version": eval_set.hash_protocol_version,
            "dialog": cases,
            "intent": [c.model_dump() for c in sorted(eval_set.intent_case_snapshot, key=lambda c: c.case_id)],
            "pass_criteria": eval_set.pass_criteria_snapshot}

def create_eval_set(dialog_cases, intent_cases=None, config=DEFAULT_CONFIG, metadata=None,
                    eval_set_id=None, eval_set_version=1, protocol=None):
    if eval_set_id and "--v" in eval_set_id:
        raise ValueError("EvalSet ID contains reserved revision separator")
    cases = []
    for raw in dialog_cases:
        data = raw.model_dump() if hasattr(raw, "model_dump") else deepcopy(raw)
        legacy = "question" in data or "case_id" not in data
        data.setdefault("case_id", uid())  # Assign once at import, never by runtime position.
        data.setdefault("legacy", legacy)
        cases.append(adapt_case(data))
    intents = []
    for raw in intent_cases or []:
        data = deepcopy(raw)
        data.setdefault("case_id", uid())
        intents.append(IntentCase.model_validate(data))
    ev = EvalSet(case_snapshot=cases, intent_case_snapshot=intents, eval_set_hash="",
        pass_criteria_snapshot={"evaluation_config": config.model_dump(),
                                "evaluation_protocol": protocol or evaluation_protocol(config)},
        metadata=metadata or {}, eval_set_version=eval_set_version,
        **({"eval_set_id": eval_set_id} if eval_set_id else {}))
    return EvalSet.model_validate({**ev.model_dump(), "eval_set_hash": digest(eval_set_semantics(ev))})

def verify_eval_set(ev):
    if digest(eval_set_semantics(ev)) != ev.eval_set_hash:
        raise ValueError("EvalSet semantic hash mismatch")
    return ev
