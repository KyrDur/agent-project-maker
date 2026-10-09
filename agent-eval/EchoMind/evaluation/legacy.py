"""Read-only adapters. Never rewrite the source Case or historical report."""
import re
from copy import deepcopy

from evaluation.models import CaseResult, EvaluationCase, QualityScores, TurnEvidence, DIMENSIONS


def adapt_case(raw, index=0):
    if isinstance(raw, EvaluationCase):
        return raw
    data = deepcopy(raw)
    legacy = "question" in data or "case_id" not in data
    if "question" in data:
        if data.get("question") is not None and not data.get("turns"):
            data["input"] = data["question"]
        data.pop("question")
    if data.get("turns") is None:
        data.pop("turns", None)
    data.setdefault("case_id", f"dialog_{index}")
    data["legacy"] = data.get("legacy", legacy)
    return EvaluationCase.model_validate(data)


def adapt_results(raw_results):
    groups = {}
    intent_metrics = {}
    results = []
    for raw in raw_results:
        if "original_status" in raw:
            data = {k: v for k, v in raw.items() if k in CaseResult.model_fields}
            results.append(CaseResult.model_validate(data))
            continue
        test_id = raw.get("case_id", raw.get("test_id", ""))
        if test_id == "intent_recognition":
            intent_metrics = {**raw.get("metadata", {}), **raw.get("scores", {})}
            continue
        key = re.sub(r"_turn_\d+$", "", test_id)
        groups.setdefault(key, []).append(deepcopy(raw))
    for case_id, rows in groups.items():
        judge_failed = any(r.get("metadata", {}).get("judge_failed")
                           or r.get("judge_failed") or r.get("exclude_from_quality_metrics") for r in rows)
        evidence = []
        for i, row in enumerate(rows):
            m = row.get("metadata", {})
            response = m.get("response", "")
            # Historical reports lack explicit execution status. Do not invent it.
            execution = m.get("execution_status", "UNKNOWN")
            evidence.append(TurnEvidence(turn=i, question=m.get("question", ""),
                                         response=response, execution_status=execution))
        execution = "SUCCESS" if all(e.execution_status == "SUCCESS" for e in evidence) else "UNKNOWN"
        qualities = [QualityScores(**{k: row.get("scores", {}).get(k) for k in DIMENSIONS}) for row in rows]
        quality_valid = all(q.valid for q in qualities)
        status = "INVALID" if judge_failed or not quality_valid or execution != "SUCCESS" else (
            "PASS" if all(r.get("passed") is True for r in rows) else "FAIL")
        notice = ("Legacy Invalid Judge Result：旧版评测结果：Judge 失败时曾写入占位分数，该分数不应作为有效质量结果。"
                  if judge_failed else "旧版结果缺少可验证的执行状态，不能形成有效质量结论。" if execution != "SUCCESS" else "旧版逐轮结果已按 Case 合并。")
        scores = {}
        if status != "INVALID":
            scores = {k: sum(q.to_scores()[k] for q in qualities) / len(qualities)
                      for k in (*DIMENSIONS, "overall")}
        results.append(CaseResult(case_id=case_id, execution_status=execution,
            judge_status="FAILED" if judge_failed or not quality_valid else "SUCCESS" if execution == "SUCCESS" else "NOT_RUN",
            original_status=status, original_reason=notice, scores=scores,
            turn_evidence=evidence, legacy=True, legacy_notice=notice, legacy_original_results=rows))
    return results, intent_metrics
