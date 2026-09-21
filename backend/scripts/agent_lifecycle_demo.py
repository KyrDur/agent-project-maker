"""Exercise a deployed lifecycle using an existing real Agent and user-owned model.

No sample scores or model mocks. Each review action is an explicit CLI invocation.
Credentials: APM_DEMO_EMAIL / APM_DEMO_PASSWORD environment variables.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from typing import Any

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["baseline", "propose", "accept", "reject", "regress", "report"]
    )
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--agent-id", required=True, type=uuid.UUID)
    parser.add_argument("--run-id", type=uuid.UUID)
    parser.add_argument("--proposal-id", type=uuid.UUID)
    parser.add_argument(
        "--request-id",
        type=uuid.UUID,
        default=None,
        help="Reuse the printed ID after a network failure to avoid duplicate work",
    )
    parser.add_argument("--timeout", type=int, default=2400)
    args = parser.parse_args()
    if args.action in {"propose", "accept", "reject", "regress"} and not args.run_id:
        parser.error("--run-id is required for this action")
    if args.action in {"accept", "reject", "regress"} and not args.proposal_id:
        parser.error("--proposal-id is required for this action")
    email, password = os.getenv("APM_DEMO_EMAIL"), os.getenv("APM_DEMO_PASSWORD")
    if not email or not password:
        parser.error("Set APM_DEMO_EMAIL and APM_DEMO_PASSWORD for an existing account")
    request_id = str(args.request_id or uuid.uuid4())
    print(f"request_id={request_id}", flush=True)
    path = f"/api/agents/{args.agent_id}/project"
    with httpx.Client(base_url=args.base_url, timeout=210) as client:

        def call(method: str, url: str, body: Any = None) -> Any:
            response = client.request(method, url, **({"json": body} if body is not None else {}))
            if response.is_error:
                raise RuntimeError(f"Request failed: HTTP {response.status_code} ({url})")
            return response.json()

        auth = call("POST", "/api/auth/login", {"email": email, "password": password})
        client.headers["X-CSRF-Token"] = auth["csrf_token"]

        def wait(run: dict[str, Any]) -> dict[str, Any]:
            print(f"run_id={run['id']}", flush=True)
            deadline = time.monotonic() + args.timeout
            while run["status"] in {"pending", "running"}:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Timed out waiting; inspect the saved run in the Project page"
                    )
                time.sleep(2)
                run = call("GET", f"{path}/eval-runs/{run['id']}")
            if run["status"] != "completed":
                raise RuntimeError(
                    f"Evaluation failed; inspect run {run['id']} in the Project page"
                )
            return run

        if args.action == "baseline":
            call("POST", path + "/create")
            version = call("POST", path + "/versions", {"request_id": request_id})["version"]
            body = {"version_id": version["id"]}
            call("POST", path + "/eval-spec/generate", body)
            dataset = call(
                "POST",
                path + "/eval-sets/generate",
                {
                    **body,
                    "evaluation_focus": ["tool_correctness", "groundedness"],
                    "evaluation_focus_reason": (
                        "Demo baseline: verify tool use and grounded answers."
                    ),
                },
            )
            quality = call("POST", f"{path}/eval-sets/{dataset['id']}/quality")
            if quality["quality_report_json"]["status"] != "approved":
                raise RuntimeError(
                    "Eval set rejected by quality review; edit or regenerate in the UI"
                )
            wait(
                call(
                    "POST",
                    path + "/eval-runs",
                    {
                        "request_id": request_id,
                        "version_id": version["id"],
                        "eval_set_id": dataset["id"],
                    },
                )
            )
        elif args.action == "propose":
            proposal = call(
                "POST", f"{path}/eval-runs/{args.run_id}/proposals", {"request_id": request_id}
            )
            print(json.dumps(proposal, ensure_ascii=False, indent=2))
            print("Review the proposal before explicitly invoking accept or reject.")
        elif args.action in {"accept", "reject", "regress"}:
            endpoint = f"{path}/eval-runs/{args.run_id}/proposals/{args.proposal_id}"
            if args.action == "regress":
                wait(call("POST", endpoint + "/regression", {"request_id": request_id}))
            else:
                result = call(
                    "POST",
                    endpoint + "/decision",
                    {
                        "decision": "accepted" if args.action == "accept" else "rejected",
                        "decision_reason": f"CLI {args.action} command",
                    },
                )
                print(json.dumps({k: result[k] for k in ("id", "status", "version_id")}, indent=2))
        reports = call("GET", path + "/evaluation-reports")
        print(
            json.dumps(
                {
                    "best_run_ids": reports["best_run_ids"],
                    "reports": [
                        {
                            k: report[k]
                            for k in (
                                "version_id",
                                "evaluation_run_id",
                                "score",
                                "metrics",
                                "bad_case_count",
                            )
                        }
                        for report in reports["reports"]
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
