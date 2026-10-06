"""Readable case cards selected only from recorded runs, with explicit authorship."""

from __future__ import annotations

from typing import Any


def decision_author(decision: dict[str, Any]) -> str:
    if decision.get("author") in {"user", "codex_demo", "system"}:
        return decision["author"]
    if "Codex" in str(decision.get("reason", "")) and "演示" in str(decision.get("reason", "")):
        return "codex_demo"
    # Existing decision records are human confirmations; never treat generated text as authored.
    return "user_confirmed"


def case_cards(
    runs: list[Any],
    versions: dict[str, Any],
    selected: list[str],
    reviews: list[dict[str, Any]],
    decisions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    histories: dict[str, list[dict[str, Any]]] = {}
    for i, run in enumerate(runs, 1):
        frozen = {c["id"]: c for c in run.cases_snapshot_json or []}
        for j, result in enumerate(run.results_json or [], 1):
            case = frozen.get(result["case_id"], {})
            ref = f"experiment-{i}/case-{j}"
            timeline = []
            for k, event in enumerate(result.get("tool_trace", []), 1):
                timeline.append(
                    {
                        "event": f"{ref}/tool-{k}",
                        "tool": event.get("name"),
                        "arguments": event.get("arguments"),
                        "returned_facts": event.get("output"),
                        "error": event.get("error"),
                        "state_before": event.get("state_before"),
                        "state_after": event.get("state_after"),
                    }
                )
            histories.setdefault(result["case_id"], []).append(
                {
                    "reference": ref,
                    "version": versions[str(run.version_id)].version_number,
                    "trial": result.get("trial", 1),
                    "scope": {
                        k: (run.comparison_json or {}).get(k)
                        for k in ("requirements_hash", "spec_hash", "repetitions", "purpose")
                    },
                    "name": case.get("name", result.get("name")),
                    "user_request": case.get("input"),
                    "initial_state": case.get("initial_state"),
                    "success_conditions": case.get("expected", {}).get("answer"),
                    "judgment_basis": case.get("judgment_basis"),
                    "actual_answer": result.get("output"),
                    "status": result.get("status"),
                    "termination": result.get("termination_reason"),
                    "final_state": result.get("final_state"),
                    "timeline": timeline,
                    "checks": result.get("assertions", []),
                    "judgments": result.get("metric_scores", {}),
                    "fact_check": result.get("fact_check"),
                    "model_calls": [
                        {
                            "event": f"{ref}/model-{k}",
                            "model": m.get("model"),
                            "status": m.get("status"),
                        }
                        for k, m in enumerate(result.get("model_calls", []), 1)
                    ],
                    "error": result.get("error"),
                }
            )
    reviewed = {str(r.get("case_id")) for r in reviews}

    def priority(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, int]:
        cid, trials = item
        return (int(cid in reviewed), sum(t["status"] != "passed" for t in trials))

    ordered = selected or [cid for cid, _ in sorted(histories.items(), key=priority, reverse=True)]
    cards = []
    signatures: set[str] = set()
    for cid in ordered:
        trials = histories.get(cid)
        if not trials:
            continue
        signature = ",".join(sorted({e.get("tool", "") for t in trials for e in t["timeline"]}))
        if not selected and cid not in reviewed and signature in signatures and len(cards) == 1:
            continue
        signatures.add(signature)
        changes = []
        for run in runs:
            for proposal in (run.comparison_json or {}).get("proposals", []):
                if proposal.get("status") == "accepted" and cid in proposal.get(
                    "targeted_case_ids", []
                ):
                    changes.append(
                        {
                            "title": proposal.get("title"),
                            "reason": proposal.get("decision_reason"),
                            "author": decision_author({"reason": proposal.get("decision_reason")}),
                            "diffs": proposal.get("diffs", []),
                            "source": f"experiment-{runs.index(run) + 1}",
                        }
                    )
        cards.append(
            {
                "reference": f"case-card-{len(cards) + 1}",
                "case_id": cid,
                "title": trials[0]["name"],
                "history": trials,
                "changes": changes,
                "reviews": [r for r in reviews if str(r.get("case_id")) == cid],
                "personal_task": (
                    "\n".join(
                        "个人已确认"
                        + {"requirements": "需求", "capabilities": "能力方案"}.get(
                            str(d.get("stage")), "决策"
                        )
                        + f"：{d.get('choice')}；理由原文：{d.get('reason')}。"
                        for d in decisions or []
                        if decision_author(d) in {"user", "user_confirmed"}
                        and d.get("stage") in {"requirements", "capabilities"}
                    )
                    or "没有保存本人的场景分析或职责记录，需要本人补充；不代写个人经历。"
                ),
                "system_task": "模型 B 设计模拟测试，A 执行与提出修改，C 自动判定与分析。",
                "limitations": [
                    "模拟数据，非真实客户日志。",
                    "旧判定与复核分别保留；单次试验不能证明稳定性。",
                    "调用尝试、操作成功、问题解决分别判断；缺少状态证据不声称业务成功。",
                ],
            }
        )
        cards[-1]["star"] = {
            "situation": {
                "user_request": trials[0]["user_request"],
                "initial_state": trials[0]["initial_state"],
                "source": trials[0]["reference"],
            },
            "task": {
                "success_conditions": trials[0]["success_conditions"],
                "personal": cards[-1]["personal_task"],
                "system": cards[-1]["system_task"],
            },
            "action": changes
            or [
                {
                    "author": "system",
                    "description": "记录实际执行与判定；本场景没有保存对应的确认改动。",
                }
            ],
            "result": [
                {
                    "version": t["version"],
                    "trial": t["trial"],
                    "status": t["status"],
                    "source": t["reference"],
                }
                for t in trials
            ],
            "limitations": cards[-1]["limitations"],
        }
        if len(cards) == 2:
            break
    # Some projects have only one root cause/tool; use the next actual scenario, never a template.
    if len(cards) < 2 and not selected:
        remaining = [cid for cid in histories if cid not in {c["case_id"] for c in cards}]
        if remaining:
            extra = case_cards(runs, versions, remaining[:1], reviews, decisions)
            if extra:
                extra[0]["reference"] = "case-card-2"
                cards.extend(extra)
    return cards
