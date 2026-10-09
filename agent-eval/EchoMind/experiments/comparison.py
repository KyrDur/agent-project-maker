"""Comparability is a control fact; completeness and attribution are independent."""
from collections import Counter
from copy import deepcopy
from .models import Comparison, EvalSet
from .canonical import digest, eval_set_semantics, verify_eval_set
from .skills import skill_diff, one_body
from .store import TERMINAL

CONTROL_KEYS = ("evaluation_config_snapshot","evaluation_protocol_snapshot","evaluation_protocol_hash",
                "agent_config_snapshot","inference_config_snapshot","prompt_version","knowledge_version",
                "routing_config_version","runtime_policy_snapshot","execution_order")

def transition(a,b,reasons=()):
    if reasons or a not in {"PASS","FAIL"} or b not in {"PASS","FAIL"}:
        return "NOT_COMPARABLE"
    return {("FAIL","PASS"):"IMPROVED",("PASS","FAIL"):"REGRESSED",
            ("PASS","PASS"):"STILL_PASS",("FAIL","FAIL"):"STILL_FAIL"}[(a,b)]

def active_at(change,run):
    return (change.implemented_status == "APPLIED" and change.applied_at
            and change.applied_at <= run.started_at
            and (change.rollback_status == "NOT_REQUESTED" or
                 (change.rollback_status == "ROLLED_BACK" and change.rollback_at > run.started_at)))

def compare(service,baseline_id,retest_id):
    a,b = service.store.get("runs",baseline_id),service.store.get("runs",retest_id)
    reasons,warnings,diff = [],["SINGLE_RUN_RANDOMNESS_NOT_CAUSAL_PROOF",
                              "MODEL_BACKEND_REVISION_UNVERIFIED"],[]
    runtime_scope = "Controlled Agent/Skill experiment."
    if any(run.knowledge_version.get("mode") == "disabled"
           or run.runtime_policy_snapshot.get("knowledge_mode") == "disabled" for run in (a,b)):
        warnings.append("REDUCED_RUNTIME_KNOWLEDGE_DISABLED")
        runtime_scope = ("Knowledge/RAG, query rewrite and rerank are disabled. Results describe "
                         "Agent/Skill behavior in this controlled runtime, not full online RAG service effects.")
    if a.run_id == b.run_id:
        reasons.append("SAME_RUN")
    if a.status not in TERMINAL or b.status not in TERMINAL:
        reasons.append("RUN_NOT_SEALED")
    if a.eval_set_hash != b.eval_set_hash:
        reasons.append("EVALSET_CHANGED")
    for run in (a,b):
        try:
            ev = verify_eval_set(EvalSet.model_validate(run.eval_set_snapshot))
            if ev.eval_set_hash != run.eval_set_hash or ev.eval_set_id != run.eval_set_id:
                reasons.append("EVALSET_SNAPSHOT_MISMATCH")
        except ValueError:
            reasons.append("MISSING_OR_INVALID_EVALSET_SNAPSHOT")
        if (digest(run.evaluation_protocol_snapshot) != run.evaluation_protocol_hash
                or not run.evaluation_protocol_snapshot):
            reasons.append("MISSING_OR_INVALID_PROTOCOL_SNAPSHOT")
        if not all(getattr(run,key) for key in CONTROL_KEYS) or not run.skill_version:
            reasons.append("MISSING_REQUIRED_SNAPSHOT")
        if (not run.runtime_policy_snapshot.get("reliable_isolation")
                or not run.runtime_end_check.get("reliable_isolation")):
            reasons.append("EXPERIMENT_STATE_NOT_ISOLATED")
        if run.runtime_end_check.get("drift_detected"):
            reasons.append("RUNTIME_CONFIG_DRIFT")
        if run.runtime_end_check.get("actual_snapshot") != run.runtime_start_snapshot:
            reasons.append("MISSING_OR_DRIFTED_RUNTIME_READBACK")
    labels = {"evaluation_config_snapshot":"EVALUATION_PROTOCOL_CHANGED",
              "evaluation_protocol_snapshot":"EVALUATION_PROTOCOL_CHANGED","evaluation_protocol_hash":"EVALUATION_PROTOCOL_CHANGED",
              "agent_config_snapshot":"AGENT_CONFIG_CHANGED","inference_config_snapshot":"MODEL_PROVIDER_INFERENCE_CHANGED",
              "prompt_version":"PROMPT_CHANGED","knowledge_version":"KNOWLEDGE_CHANGED",
              "routing_config_version":"ROUTING_CHANGED","runtime_policy_snapshot":"RUNTIME_POLICY_CHANGED",
              "execution_order":"EXECUTION_ORDER_CHANGED"}
    for key in CONTROL_KEYS:
        if getattr(a,key) != getattr(b,key):
            reasons.append(labels[key])
            diff.append({"path":key,"before_hash":digest(getattr(a,key)),"after_hash":digest(getattr(b,key))})
    observed_models = lambda run: {(o["stage"],o["response_model_identifier"]) for o in run.provider_observations}
    if observed_models(a) != observed_models(b):
        warnings.append("RESPONSE_MODEL_IDENTIFIER_CHANGED")
    if any("RESPONSE_MODEL_IDENTIFIER_DIFFERS_FROM_REQUEST" in run.warnings for run in (a,b)):
        warnings.append("RESPONSE_MODEL_IDENTIFIER_DIFFERS_FROM_REQUEST")
    for run in (a,b):
        for warning in run.warnings:
            if warning in {'TOOL_CALL_CAPABILITY_UNKNOWN','TOOL_CALL_CAPABILITY_FAILED'} and warning not in warnings:
                warnings.append(warning)
    actual_skill_diff = skill_diff(a.skill_version,b.skill_version)
    diff.extend(actual_skill_diff)
    changes = []
    incomplete_chain = False
    component_violation = False
    for cid in b.applied_change_ids:
        try:
            changes.append(service.store.get("changes",cid))
        except FileNotFoundError:
            incomplete_chain = True
    current = a.skill_version
    for change in changes:
        if not one_body(change.observed_diff) or change.change_scope != "ONE_SKILL_RULE_BODY" or change.change_type != "SKILL_RULE":
            component_violation = True
        if (not active_at(change,b) or change.before_snapshot != current
                or change.before_hash != current["hash"] or change.after_hash != change.after_snapshot.get("hash")
                or change.verified_effective_version != change.after_hash
                or change.observed_diff != change.declared_diff
                or skill_diff(change.before_snapshot,change.after_snapshot) != change.observed_diff
                or not all(change.application_evidence.get(k) for k in ("strict_parse","atomic_write","reload","disk_matches_loaded"))
                or change.application_evidence.get("readback_hash") != change.after_hash):
            incomplete_chain = True
        try:
            decision = service.store.get("decisions",change.decision_id)
            source = service.store.get("runs",change.baseline_run_id)
            if decision.status != "CONFIRMED" or decision.related_run_id != source.run_id or source.skill_version != change.before_snapshot:
                incomplete_chain = True
        except FileNotFoundError:
            incomplete_chain = True
        current = change.after_snapshot
    if changes and current != b.skill_version:
        incomplete_chain = True
    if actual_skill_diff and not changes:
        reasons.append("UNRECORDED_CHANGE")
    if incomplete_chain:
        reasons.append("UNVERIFIED_CHANGE_CHAIN")
    if component_violation:
        reasons.append("MULTI_COMPONENT_CHANGE")
    # Include intervening apply/rollback events, even when net snapshots happen to match.
    unexplained_events = []
    for event in service.store.list("changes"):
        for timestamp in (event.applied_at,event.rollback_at):
            if timestamp and a.finished_at and b.started_at and a.finished_at < timestamp <= b.started_at:
                if event.change_id not in b.applied_change_ids or timestamp == event.rollback_at:
                    unexplained_events.append(event.change_id)
    if unexplained_events:
        reasons.append("UNRECORDED_CHANGE")
        warnings.append("UNEXPLAINED_APPLY_OR_ROLLBACK")
    revisions = service.store.list("reviews")
    ra = max([r.revision for r in revisions if r.run_id == a.run_id],default=0)
    rb = max([r.revision for r in revisions if r.run_id == b.run_id],default=0)
    ea = {r.case_id:r for r in service.effective_results(a,ra)}
    eb = {r.case_id:r for r in service.effective_results(b,rb)}
    expected = {c["case_id"] for c in a.eval_set_snapshot["case_snapshot"]}
    expected |= {c["case_id"] for c in b.eval_set_snapshot["case_snapshot"]}
    pairs = []
    reasons = sorted(set(reasons))
    for cid in sorted(expected|set(ea)|set(eb)):
        x,y = ea.get(cid),eb.get(cid)
        local = list(reasons)
        if x is None:
            local.append("MISSING_BASELINE_RESULT")
        if y is None:
            local.append("MISSING_RETEST_RESULT")
        if any(r and r.review_status == "PENDING" for r in (x,y)):
            local.append("PENDING_HUMAN_REVIEW")
        if any(r and r.exclude_from_quality_metrics for r in (x,y)):
            local.append("INVALID_EVALUATION")
        pairs.append({"case_id":cid,"machine_status_a":x.original_status if x else None,
            "machine_status_b":y.original_status if y else None,
            "effective_status_a":x.final_status if x else None,"effective_status_b":y.final_status if y else None,
            "machine_transition":transition(x.original_status if x else None,y.original_status if y else None,reasons),
            "effective_transition":transition(x.final_status if x else None,y.final_status if y else None,local),
            "review_status_a":x.review_status if x else None,"review_status_b":y.review_status if y else None,
            "hard_rule_violations_a":x.hard_rule_violations if x else [],
            "hard_rule_violations_b":y.hard_rule_violations if y else [],
            "hard_rule_override_a":x.hard_rule_override if x else False,
            "hard_rule_override_b":y.hard_rule_override if y else False,
            "human_reason_a":x.human_reason if x else None,"human_reason_b":y.human_reason if y else None,
            "original_reason_a":x.original_reason if x else None,"original_reason_b":y.original_reason if y else None,
            "quality_scores_a":x.scores if x else {},"quality_scores_b":y.scores if y else {},
            "not_comparable_reasons":sorted(set(local))})
    ia = {c["case_id"]:c for c in a.intent_sample_results}
    ib = {c["case_id"]:c for c in b.intent_sample_results}
    intent_expected = {c["case_id"] for c in a.eval_set_snapshot["intent_case_snapshot"] + b.eval_set_snapshot["intent_case_snapshot"]}
    intent_pairs = []
    for cid in sorted(intent_expected):
        x,y = ia.get(cid),ib.get(cid)
        local = reasons + (["MISSING_BASELINE_RESULT"] if x is None else []) + (["MISSING_RETEST_RESULT"] if y is None else [])
        correct_a = x["predicted"] == x["expected"] if x else None
        correct_b = y["predicted"] == y["expected"] if y else None
        intent_pairs.append({"case_id":cid,"correct_a":correct_a,"correct_b":correct_b,
            "transition": "NOT_COMPARABLE" if local else
                {(False,True):"CORRECTED",(True,False):"REGRESSED",(True,True):"STILL_CORRECT",(False,False):"STILL_WRONG"}[(correct_a,correct_b)],
            "not_comparable_reasons":local})
    matched = len(set(ea)&set(eb)) + len(set(ia)&set(ib))
    expected_count = len(expected)+len(intent_expected)
    partial = matched != expected_count or a.status != "COMPLETE" or b.status != "COMPLETE"
    if partial:
        warnings.append("PARTIAL_MATCHED_VALID_CASES_ONLY")
    comparable = not reasons
    if component_violation:
        attribution = "MULTI_COMPONENT_CHANGE"
    elif "UNRECORDED_CHANGE" in reasons:
        attribution = "UNRECORDED_CHANGE"
    elif not comparable:
        attribution = "INSUFFICIENT_EVIDENCE" if incomplete_chain else "NOT_COMPARABLE"
    elif len(changes)>1:
        attribution = "MULTI_CHANGE"
    elif not changes or not actual_skill_diff:
        attribution = "NO_CHANGE"
    else:
        change = changes[0]
        decision = service.store.get("decisions",change.decision_id)
        attribution = ("SINGLE_CHANGE_ELIGIBLE" if b.parent_run_id == a.run_id
            and b.run_type == "RETEST" and b.decision_id == decision.decision_id
            and change.baseline_run_id == a.run_id and one_body(actual_skill_diff)
            else "INSUFFICIENT_EVIDENCE")
    single_recorded_change = attribution == "SINGLE_CHANGE_ELIGIBLE"
    # Formal v1 has no backend identity attestation/verification adapter. Model names,
    # response model labels, user metadata, or a caller-supplied 'verified' string cannot
    # prove actual backend revision equality. Until such a verifier exists, even a fully
    # recorded single intervention cannot receive strong attribution. Historical
    # artifacts are retained; new comparisons always use this conservative boundary.
    if single_recorded_change:
        attribution = "INSUFFICIENT_EVIDENCE"
    valid_pairs = [p for p in pairs if p["effective_transition"] != "NOT_COMPARABLE"]
    group_metrics = {"dialog_case_metrics":{"scope":"MATCHED_VALID_CASES","valid_pair_count":len(valid_pairs),
        "passed_a":sum(p["effective_status_a"]=="PASS" for p in valid_pairs),
        "passed_b":sum(p["effective_status_b"]=="PASS" for p in valid_pairs),
        "transitions":dict(Counter(p["effective_transition"] for p in pairs))},
        "intent_metrics":{"scope":"MATCHED_INTENT_SAMPLES","sample_pairs":intent_pairs},
        "claim_scope":"Matched valid Case subset; no full EvalSet improvement claim"}
    return Comparison(baseline_run_id=a.run_id,retest_run_id=b.run_id,comparable=comparable,
        comparability_reasons=reasons,comparison_completeness="PARTIAL" if partial else "FULL",
        completeness_reasons=["MISSING_RESULTS_OR_INCOMPLETE_RUN"] if partial else [],
        expected_case_count=expected_count,matched_case_count=matched,
        attributable=False,attribution_status=attribution,
        single_recorded_change=single_recorded_change,runtime_scope=runtime_scope,
        attribution_warnings=warnings,observed_config_diff=diff,applied_change_ids=b.applied_change_ids,
        review_revision_a=ra,review_revision_b=rb,case_comparisons=pairs,group_metrics=group_metrics)
