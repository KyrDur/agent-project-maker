"""All dialog quality aggregation uses this gate. Intent is a separate group."""
import statistics

from evaluation.models import DIMENSIONS


def dialog_metrics(results):
    valid = [r for r in results if not r.exclude_from_quality_metrics]
    scored = [r for r in valid if r.judge_status == "SUCCESS" and all(k in r.scores for k in DIMENSIONS)]
    passed = sum(r.final_status == "PASS" for r in valid)
    return {
        "total": len(results), "valid": len(valid), "passed": passed,
        "failed": sum(r.final_status == "FAIL" for r in valid),
        "invalid": len(results) - len(valid),
        "agent_errors": sum(r.execution_status == "FAILED" for r in results),
        "judge_errors": sum(r.judge_status == "FAILED" for r in results),
        "evaluation_errors": sum(r.evaluation_error is not None for r in results),
        "pending_human_reviews": sum(r.review_status == "PENDING" for r in results),
        "hard_rule_violations": sum(bool(r.hard_rule_violations) for r in results),
        "quality_scored_cases": len(scored),
        "pass_rate": passed / len(valid) if valid else None,
        "avg_scores": {k: statistics.mean(r.scores[k] for r in scored) for k in (*DIMENSIONS, "overall")}
            if scored else {},
    }
