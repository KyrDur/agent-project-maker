# Weekly Report Agent demo

Goal: generate a weekly work report from structured work records. Use synthetic
records, not private Feishu/GitHub content. The full automated demo below is controlled:
the examinee, planner fixtures and judge responses are substitutes. Its metrics are
not evidence of real model quality or production deployment.

## Interview walkthrough

1. Describe the weekly-report requirement to the existing builder, or use its existing
   manual Agent configuration. Explain which records the Agent should summarize.
2. Create an Agent Project. V1 freezes the configuration without modifying the live Agent.
3. Generate/review the Eval Spec and 20-case EvalSet. Include normal, missing-information,
   ambiguous, tool-failure, edge and hallucination scenarios.
4. Evaluate with frozen mock tool data. Explain deterministic tool checks separately
   from semantic judge metrics.
5. Inspect failing cases and their observable evidence. Root causes are analysis, not
   hidden model reasoning.
6. Propose minimal instruction or frozen Skill changes. Unsupported historical Skill
   content is explicitly deferred.
7. Evaluate each immutable candidate on the same frozen cases, mocks, thresholds and
   judge roles. Inspect both fixes and regressions.
8. Select Best Version from stored decisions. A newer rejected version must not replace it.
9. Present the deterministic report and resume bullets, create a sanitized share,
   download the portfolio ZIP, then revoke the share. Trying the live Agent does not
   promote Best Version.

## Reproduce the controlled API/data workflow

```text
Existing builder / manual configuration
                 |
              Live Agent ----> immutable Project versions
                                      |
Frozen Eval Spec + cases/mocks ---> existing evaluator ---> stored runs
                                      |
Bad-case analysis ---> bounded patches ---> candidates ---> regression ---> Best
                                                                          |
Stored project evidence <-------------------------------------------------+
          |
     Report / resume ---> sanitized share / ZIP
```

```sh
cd backend
uv run python scripts/validate_agent_project_release.py
```

This reuses the Phase 4 controlled fixture plus Phase 5 services/public ASGI routes.
It creates the Agent and V1 programmatically; it does not exercise the conversational
builder UI or generate plans with a real LLM. It verifies the remaining project
persistence, frozen evaluation, bad-case/optimization, report/resume/share/export path.

Expected evidence:

| Version | Passed | Outcome |
| --- | --- | --- |
| V1 | 15/20 (75%) | Baseline |
| V2 | 18/20 (90%) | Accepted, Best Version |
| V3 | 17/20 (85%) | Rejected |

The benchmark intentionally makes V2 fix four cases and regress one. V3 regresses
again. This demonstrates transparent selection rather than promising every optimization
will improve an Agent. The exported README identifies the controlled demo.

Artifacts: `output/agent-project-release-demo/project_report.md`, `resume.txt`,
`agent-project.zip`, and `validation.json`. The temporary SQLite database is discarded;
the public share is verified via ASGI and revoked before the command exits. No persistent
internet link is published.

## Pending real browser walkthrough

On the supported Linux/Docker instance, follow the same existing workspace actions:
open/create Project, generate plan/cases, run controlled evaluation if configured, inspect
Bad Cases, Results, Report, Resume, Share and Export. Verify anonymous share read and
revocation in a separate browser context. Do not describe component tests or ASGI requests
as a browser end-to-end test. Do not run the full paid optimization loop without approval.

Current executed checks and blockers are in [the release record](agent-project-release.md).
