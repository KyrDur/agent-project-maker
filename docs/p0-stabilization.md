# P0 lifecycle stabilization

Production target remains `https://agent.softcue.xyz`, linux/amd64, Alibaba Cloud 2C2G.
This change does not deploy production. Both backend and frontend images must be rebuilt
and redeployed after the release gate passes. No schema migration or data reset is required.

## Verified causes and repairs

| Failure | Cause | Repair |
| --- | --- | --- |
| Builder ends in ordinary chat | Completion redirects to chat; project creation and evaluation are separate manual actions | Completion opens Project. Finalization atomically saves Agent, Project and immutable V1. A recoverable bootstrap generates the plan, exactly 20 cases and baseline. |
| An unusable provider is selected | Builder uses the global default/first model without checking the user's personal provider credentials | Enumerate visible models with active, decryptable, compatible personal credentials. Zero choices blocks with setup links; one binds automatically; multiple require selection. Revalidate at confirmation. |
| Settings Test does not test the Agent | Test invokes the Assistant stream | Use `streamStartConversation` and `streamChat`, with the normal conversation ID, toolkit, run callbacks and human-approval context. Fix Assistant remains separate. |
| Generic test warning | No readiness check or specific remediation | Read-only, ownership-checked readiness endpoint and localized credential/model/tool setup links. Real chat still performs its own runtime checks. |
| First-party Korean catalog leaks | Templates expose seed strings directly; middleware display text is Korean; template sorting assumes Korean | Stable catalog keys and localized read-only display adapters for zh-CN/en/ko. Use active locale for sorting and cache keys. Preserve external/user-authored content. |
| Missing Project key / incorrect empty copy | Missing zh-CN key and generic catalog wording | Add the Project action and domain-specific Tools/Skills empty-state copy. |
| Refresh/retry can lose the workflow | Builder session ID and interrupt are not restored; lifecycle has no recovery coordinator | Persist session ID in the URL; restore owned checkpoint messages and interrupt without restarting. Serialize bootstrap per Agent and reuse deterministic benchmark/run IDs. |
| Benchmark editable after baseline starts | Cases were copied to the run but the source EvalSet remained editable | Freeze the EvalSet in the same transaction that creates the baseline run. Regression keeps the same dataset and hash. |
| Builder middleware breaks sandbox startup | Snapshot execution rejects every middleware; legacy tool-call limit uses an obsolete constructor argument | Permit the bounded safe middleware constructors in snapshot execution and normalize the legacy limit argument. The full Settings middleware catalog remains accessible. Unsupported snapshot capabilities still fail closed. |

## Safety and recovery

- System LLM configuration remains separate. Builder may use operator inference, but a
  completed Agent binds only a compatible personal runtime credential. No token values
  are copied into snapshots, progress, reports or logs.
- Agent + Project + V1 are committed together. Confirmation locks the Builder session and
  returns the existing Agent after duplicate confirmation.
- Bootstrap uses a PostgreSQL session advisory lock; its connection release after worker
  failure permits an authenticated reconnect to resume. SQLite tests use a local lock.
- The EvalSet UUID and baseline request UUID are derived from the Project UUID. Retries
  retain the same V1, frozen benchmark and run; a disconnected running baseline is resumed
  only after obtaining the exclusive bootstrap lock.
- Evaluation tools are synthetic sandbox tools. Production tool factories are not invoked.
  Settings Test intentionally uses real Agent conversations and tools, and explains this
  behavior in the panel.
- Existing optimizer limits, immutable versions, evidence-based acceptance and Best
  selection, frozen regression cases, report/share/export and authentication remain intact.
- Existing templates are adapted at read time; historical conversations and database rows
  are not rewritten. Legal attribution, deployment architecture and visual design are unchanged.

## Validation

Local relevant backend suite: 124 passing tests, including ownership, 0/1/multiple personal
bindings, duplicate confirmation, immutable V1, frozen EvalSet, project evaluation,
optimization, reports, Builder i18n and Builder topology.

Local relevant frontend suite: 56 passing tests, including restored Builder interrupts,
completion navigation, real Test stream selection and approvals, actionable Chinese errors,
Chinese automatic project progress, templates and API hooks.

Changed Python files pass Pyright and Ruff. Frontend TypeScript, ESLint, static i18n,
design-system, strict architecture, type-safety and E2E hygiene guards are checked. The
existing 34-item JSX accessibility baseline has no new findings. ESLint retains the existing
TanStack Table React Compiler warning. Production build uses the unchanged production URL
and `NEXT_PUBLIC_CHAT_RUNTIME=langgraph_v3`.

`.github/workflows/p0-release-gate.yml` runs on Ubuntu on every main push/PR and manually.
It runs `pytest --noconftest tests/test_p0_readiness.py tests/test_p0_golden_path.py -q`.
The gate requires the real Linux runtime imports and graph factory; it does not stub Unix
filesystem primitives. Only model outputs are fake. The end-to-end test executes:

Builder → Agent → Project/V1 → plan → 20 cases → baseline failures → optimizer → immutable
V2 → identical benchmark regression → evidence-selected Best → report → share → export.

The gate is required evidence before calling this P0 complete. Local Windows cannot run
the production runtime's Unix filesystem imports. No paid live provider call is part of
this deterministic gate; external provider/network availability still requires valid user
configuration.

## Files

The complete implementation file list is recorded below; paths are repository-relative.

- `.github/workflows/p0-release-gate.yml`
- `backend/app/agent_runtime/builder_locales/en.json`
- `backend/app/agent_runtime/builder_locales/ko.json`
- `backend/app/agent_runtime/builder_locales/zh-CN.json`
- `backend/app/agent_runtime/builder_v3/graph.py`
- `backend/app/agent_runtime/builder_v3/nodes/phase8_build.py`
- `backend/app/agent_runtime/builder_v3/state.py`
- `backend/app/agent_runtime/credential_resolution.py`
- `backend/app/agent_runtime/middleware_registry.py`
- `backend/app/catalog_i18n.py`
- `backend/app/catalog_locales/en.json`
- `backend/app/catalog_locales/ko.json`
- `backend/app/catalog_locales/zh-CN.json`
- `backend/app/routers/agent_projects.py`
- `backend/app/routers/agents.py`
- `backend/app/routers/builder.py`
- `backend/app/routers/templates.py`
- `backend/app/schemas/template.py`
- `backend/app/services/agent_project_evaluation.py`
- `backend/app/services/agent_project_executor.py`
- `backend/app/services/agent_project_semantic.py`
- `backend/app/services/builder_project_lifecycle.py`
- `backend/app/services/builder_runtime_readiness.py`
- `backend/app/services/builder_service.py`
- `backend/tests/test_agent_project_phase3.py`
- `backend/tests/test_p0_golden_path.py`
- `backend/tests/test_p0_readiness.py`
- `docs/p0-stabilization.md`
- `frontend/messages/en.json`
- `frontend/messages/ko.json`
- `frontend/messages/zh-CN.json`
- `frontend/src/app/agents/[agentId]/project/_components/project-workbench.test.tsx`
- `frontend/src/app/agents/[agentId]/project/_components/project-workbench.tsx`
- `frontend/src/app/agents/[agentId]/project/_hooks/use-agent-project.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-api.ts`
- `frontend/src/app/agents/[agentId]/project/_lib/agent-project-types.ts`
- `frontend/src/app/agents/[agentId]/settings/_components/right-panel/test-chat-panel.tsx`
- `frontend/src/app/agents/new/conversational/page.tsx`
- `frontend/src/app/agents/new/template/page.tsx`
- `frontend/src/lib/api/builder.ts`
- `frontend/src/lib/api/middlewares.ts`
- `frontend/src/lib/api/templates.ts`
- `frontend/src/lib/hooks/use-middlewares.ts`
- `frontend/src/lib/hooks/use-templates.ts`
- `frontend/src/lib/query-keys/agents.ts`
- `frontend/src/lib/query-keys/middlewares.ts`
- `frontend/src/lib/query-keys/templates.ts`
- `frontend/tests/components/agent/p0-test-runtime.test.tsx`
- `frontend/tests/pages/p0-builder-resume.test.tsx`
- `frontend/tests/unit/hooks/use-templates.test.tsx`
