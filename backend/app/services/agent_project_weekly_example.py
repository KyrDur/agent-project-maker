"""Frozen Feishu contract for a real-model weekly-report acceptance run.

No Feishu credentials or network access. Install the planned tools on the Agent
before creating its project snapshot. Results and scores are never precomputed.
"""

from copy import deepcopy

from app.schemas.agent_project import EvalSetWrite

TOOLS = [
    {
        "name": "feishu_read",
        "description": "Read a page of weekly team activity.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {k: {"type": "string"} for k in ("group", "week", "page")},
            "required": ["group", "week", "page"],
        },
    },
    {
        "name": "feishu_publish",
        "description": "Publish the weekly report to a group.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {k: {"type": "string"} for k in ("group", "body")},
            "required": ["group", "body"],
        },
    },
]


def dataset() -> EvalSetWrite:
    first = {"group": "team-a", "week": "2026-W39", "page": "1"}
    second = {**first, "page": "2"}
    base = {
        "name": "Weekly report with pagination",
        "input": (
            "Read team-a activity for 2026-W39, all pages. Summarize completed and blocked work, "
            "then publish to team-a. Never invent missing facts."
        ),
        "expected": {
            "answer": (
                "Report Search shipped and Billing blocked on review; "
                "publish to team-a only after reading all pages."
            ),
            "required_tools": ["feishu_read", "feishu_publish"],
            "tool_assertions": [
                {"name": "feishu_read", "arguments": first},
                {"name": "feishu_read", "arguments": second},
                {"name": "feishu_read", "min_calls": 2, "max_calls": 2},
                {
                    "name": "feishu_publish",
                    "argument_equals": {"group": "team-a"},
                    "argument_contains": {"body": "Search shipped"},
                    "min_calls": 1,
                    "max_calls": 1,
                },
                {
                    "name": "feishu_publish",
                    "argument_equals": {"group": "team-a"},
                    "argument_contains": {"body": "Billing blocked on review"},
                    "min_calls": 1,
                    "max_calls": 1,
                },
            ],
            "tool_sequence": ["feishu_read", "feishu_read", "feishu_publish"],
        },
        "mock_tool_data": {
            "feishu_read": {
                "rules": [
                    {
                        "arguments": first,
                        "responses": [{"result": {"items": ["Search shipped"], "next_page": "2"}}],
                    },
                    {
                        "arguments": second,
                        "responses": [
                            {"result": {"items": ["Billing blocked on review"], "next_page": None}}
                        ],
                    },
                ]
            },
            "feishu_publish": {"result": {"message_id": "synthetic-report-1"}},
        },
        "tags": ["normal"],
    }
    retry = deepcopy(base)
    retry["name"] = "Transient timeout then recovery"
    retry["tags"] = ["tool_failure"]
    retry["mock_tool_data"]["feishu_read"]["rules"][0]["responses"].insert(0, {"error": "timeout"})
    retry["expected"]["tool_assertions"][0].update(min_calls=2, max_calls=2)
    retry["expected"]["tool_assertions"][2].update(min_calls=3, max_calls=3)
    retry["expected"]["tool_sequence"].insert(0, "feishu_read")
    denied = deepcopy(base)
    denied["name"] = "Permission denied"
    denied["tags"] = ["tool_failure"]
    denied["mock_tool_data"]["feishu_read"]["rules"] = [
        {"arguments": first, "responses": [{"error": "permission_denied"}]}
    ]
    denied["expected"] = {
        "answer": "Explain permission is denied. Do not invent a report or publish anything.",
        "required_tools": ["feishu_read"],
        "forbidden_tools": ["feishu_publish"],
        "tool_assertions": [{"name": "feishu_read", "arguments": first}],
        "tool_sequence": ["feishu_read"],
    }
    empty = deepcopy(denied)
    empty["name"] = "No records this week"
    empty["tags"] = ["missing_information"]
    empty["mock_tool_data"]["feishu_read"]["rules"][0]["responses"] = [
        {"result": {"items": [], "next_page": None}}
    ]
    empty["expected"]["answer"] = (
        "Explain that this week has no records; do not invent or publish a report."
    )
    missing = deepcopy(empty)
    missing["name"] = "Source records unavailable"
    missing["mock_tool_data"]["feishu_read"]["rules"][0]["responses"] = [
        {"result": {"items": None, "missing": True, "next_page": None}}
    ]
    missing["expected"]["answer"] = (
        "Explain source records are missing; do not invent or publish a report."
    )
    timeout = deepcopy(denied)
    timeout["name"] = "Persistent timeout, stop after one retry"
    timeout["mock_tool_data"]["feishu_read"]["rules"][0]["responses"] = [
        {"error": "timeout"},
        {"error": "timeout"},
    ]
    timeout["expected"]["tool_assertions"][0].update(min_calls=2, max_calls=2)
    timeout["expected"]["tool_sequence"] = ["feishu_read", "feishu_read"]
    timeout["expected"]["answer"] = (
        "Explain the timeout after one retry; do not publish or invent a report."
    )
    cases = [base, retry, denied, empty, missing, timeout]
    for case in cases:
        case["input"] += (
            " Retry a timeout once only. Do not retry permission denial. "
            "Do not publish when records are empty or missing. Preserve source wording "
            "for completed and blocked items in the published body."
        )
    return EvalSetWrite.model_validate({"name": "Feishu weekly report acceptance", "cases": cases})


def rubric() -> dict:
    return {
        "metrics": [
            {
                "name": "task_completion",
                "type": "llm_judge",
                "weight": 0.4,
                "criteria": "Complete weekly reporting or explain missing data/errors.",
            },
            {
                "name": "tool_correctness",
                "type": "deterministic",
                "weight": 0.3,
                "criteria": "Use correct group/week/pages, retry bounds and publication body.",
            },
            {
                "name": "groundedness",
                "type": "llm_judge",
                "weight": 0.3,
                "criteria": "Every reported fact must be supported by actual tool responses.",
            },
        ],
        "pass_threshold": 0.7,
    }
