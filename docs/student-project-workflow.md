# Student Agent workflow — P0 and P1

This change targets college students building an internship portfolio, including
students with limited programming experience. External tools continue to execute
only in the existing mock sandbox. No Feishu or other production integration is
added.

## P0: explainable guided workflow

The main navigation has four stages: create, test, improve, materials. Version
administration, manual dataset editing, full scoring details and the previous
optimization workspace remain available as secondary/advanced views. The selected
version defaults to the newest accepted version when available.

- AI drafts the audience, problem, workflow and verifiable business criteria.
  Users confirm or edit it. A confirmed draft records `user_confirmed` or
  `user_edited`, an immutable content fingerprint, and brief history. Changed
  criteria invalidate future evaluation plans; historical datasets stay frozen.
- Before testing, users choose risks, read three typical cases, and explicitly
  confirm their direction. The platform checks structure and starts the full test
  in one action. A structural check does not establish correctness of the rubric.
- Results show requirement, actual output, failed checks and grading reasons,
  AI cause hypotheses, and optional user judgment with reason. Traces remain
  inspectable. Execution/Judge errors cannot be reported as valid quality scores.
- Accepting a guided proposal records the chosen rationale, saves a new version,
  and requests a regression. Server-generated reasons are marked `ai_confirmed`;
  authored reasons are marked `user_authored`. If regression submission fails,
  the accepted version remains recoverable and the request ID is reused.
- The iteration journal compares results only under matching nonnull comparison
  keys. The existing export remains available, with explicit platform/user
  participation wording. Platform-generated tests are not described as personally
  designed or implemented by the student.
- Interview materials contain 30-second and 2-minute introductions plus five
  answers: contribution, failure, decision, interpretation and next validation.
  Every answer must reference a real private evidence record. Unsupported refs
  are rejected; cache identity follows the evidence fingerprint. Materials remain
  AI drafts. Reference validity alone does not guarantee factual interpretation.
  Practice is optional; no quiz blocks export.

## P1: additional reliability evidence

### Reserved validation sets

`POST /reliability/holdout` generates 20 synthetic cases from the development
set's frozen original business contract, rubric and original Agent tool schema.
Candidate outputs, failure analyses, patches and prior validation results are not
passed to generation. IDs and normalized input text are checked for duplication
against existing project datasets; the set is then structurally checked and
frozen before evaluation. Rejected sets must be regenerated, rather than edited.

Reserved results cannot feed project failure analysis, automatic optimization or
proposal generation. They are new synthetic scenarios, **not an external or blind
benchmark**. Shared generator biases, semantic paraphrases, and manual adaptation
outside the optimizer remain possible. The UI states this boundary explicitly.

### Repeated and paired trials

`POST /eval-runs/{run_id}/repeat` creates 2–5 repetitions of a frozen run, copying
cases, rubric and pinned Judge configuration. `POST /reliability/validate` runs
both the original baseline and selected candidate on the same reserved cases,
2–5 times each (default 3, total 6). The first baseline trial is the shared Judge
anchor; it does not add an extra charged run. All paired trials are committed
atomically. Persisted jobs use the existing worker, lease recovery and cancellation.
Request IDs make replay safe and reject conflicting parameters.

Mean, minimum, maximum and population standard deviation describe complete,
comparable run-level pass rates. Incomplete/failed runs are counted separately;
they do not become zero scores. Repeating a case is not counted as additional
independent cases. No confidence interval or production-generalization claim is
made. Validation and repeat runs do not replace the development report's best
version with a single lucky result.

### Human grading review

Users label completion and give a reason from case evidence. The original results
and AI scores remain unchanged. The reliability view shows reviewed counts,
disagreements, and reasons; the private API also returns an agreement rate.
These are user reviews of automated aggregate verdicts, not an unbiased Judge
accuracy estimate. Small, self-selected review samples do not establish Judge
reliability. Reports export numeric summaries without private review reasons.

## Storage and compatibility

Existing JSON fields hold briefs, decisions, reviews, interview drafts and trial
metadata; no database migration is needed. All new routes reuse ownership checks,
authentication, CSRF protection and request-validation redaction. Live Agent
configuration and immutable version snapshots are not modified by learning aids.
Legacy projects remain readable; reserved-set generation requires a development
set with a frozen version-bound rubric. Generate a new guided set for old datasets
that lack that provenance.

## Verification

Controlled backend tests cover ownership, stale brief rejection, evidence-linked
interview caching, fabricated refs, duplicate validation inputs, frozen datasets,
pinned repeated runs, paired replay, no extra anchor, atomic rollback, and private
review exclusion from export. Frontend component tests cover the guided and legacy
flows, structural rejection, lost responses, proposal acceptance/recovery,
version scoping, changed requirements and later iterations.

No live LLM credentials or production integrations are used in these tests.
Production model behavior and wording quality still require a run with the user's
configured models. Browser capture could not be completed in this environment:
the Playwright Chromium download returned a truncated archive. Component tests and
the production frontend build provide the available UI validation.

Validated locally with Node 22: 47 frontend project tests, TypeScript and the
production Next build; 122 related backend tests, Ruff and focused Pyright.
Frontend lint, i18n, design-system, accessibility and architecture guards pass.
Existing warnings remain: TanStack Table React Compiler compatibility, 34
baselined accessibility warnings, and 42 legacy architecture advisories.
