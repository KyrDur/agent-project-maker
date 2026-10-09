# Evidence-to-Career Artifacts (Python MVP)

Phase 5 reads existing sealed Agent/Skill or Retrieval experiments. It does not alter evaluation, comparison, attribution, metrics, prompts, knowledge or historical artifacts. It requires no API Key and makes no model requests.

## Entry point

Open **Career / Export** with the current experiment selected. Build Evidence, supply and explicitly confirm project background, contribution boundaries, real-user/deployment status, and optionally a personal reflection. Confirming context creates a new immutable Evidence version. Generate the material bundle explicitly.

## Schema and provenance

`career_models.py` defines `ProjectContext`, `EvidenceClaim`, `EvidenceObject`, `CareerSection`, `DefenseQuestion`, `CareerBundle`.

An Evidence Claim has type/text, before/after values, units, source type, source IDs, JSON Pointer evidence paths, confidence, allowed destinations and limitations. Source types distinguish recorded Run / Comparison evidence, user-confirmed decisions, user-entered context, derived summaries, human review, AI suggestions, historical context and missing information. Evidence contains frozen source snapshots and their hashes. Derived snapshots list their parents. User-confirmed statements are self-reports, not independent authentication of engineering contribution or business metrics.

Agent summaries use the existing `dialog_metrics` function and freeze the comparison's review revisions. Retrieval summaries use the actual paired metrics and their per-metric denominators and freeze the comparison's answer-review snapshot. Neither recomputes a new comparison nor mixes Intent and Dialog or Retrieval and Answer denominators. Unknown historical metrics never enter current metrics. Pending human review remains distinguishable from execution/Judge errors.

`career_store.py` owns only `<experiment store>/career/evidence` and `/career/materials`. Existing experiment groups are read-only to this subsystem. Writes are atomic, fsynced, transaction-serialized and immutable. Evidence has a semantic-content hash; every material binds ID/version/hash. Regeneration creates a new object; older files do not change.

## Generation and safety boundary

The first version uses deterministic evidence templates, without LLM storytelling. It generates a project introduction, 17 Case Study sections, 2–4 AI-product resume bullets, 3 general-product bullets, short 60/90-second stories, a product-language architecture explanation, technical details, contribution summary, reflection candidates and 15 project-specific defense cards (5 pressure questions).

Generated metric claims describe observed matched valid labeled cases, never strong causality. Local provider endpoints are `LOCAL_OR_UNVERIFIED`; remote endpoints are `REMOTE_UNVERIFIED`. Neither proves a commercial model's identity. Existing capability and AI coding implementation are separate from user judgments. Missing facts remain missing. Demo and self-reported background cannot become production results. Inspection exposes the immutable source paths for each material section.

Career lint checks unsupported numbers, strong causal wording, hidden regressions/INVALID, missing limitations, ambiguous contribution, existing capability ownership, unconfirmed AI suggestions, historical/current mixing, production and commercial-provider claims, invalid success counts, comparability/attribution confusion and unverified performance self-reports. This is a conservative deterministic check, not a general natural-language fact verifier. **Every freely edited section is marked USER_UNVERIFIED_CLAIM and Mixed (or Draft), even if no keyword/numeric violation was detected.** It cannot silently acquire Evidence-backed status. Re-generating that section from the frozen Evidence removes the user edit, without rewriting history. Missing retest, non-comparable comparison or zero usable pairs yields Draft.

Evidence-backed means the statement has the disclosed record source, not that the experiment proves causality, model identity, deployment, ownership, business value, or generalized quality.

## API

All endpoints have prefix `/experiments/career`:

- POST `/evidence`: build a snapshot, optional confirmed context / parent Evidence ID.
- GET `/evidence`, `/evidence/{id}`: historical summaries / full frozen facts.
- POST `/materials`: generate from a confirmed Evidence ID.
- GET `/materials`, `/materials/{id}`: material history / locked bundle.
- POST `/materials/{id}/edit`: new wording revision, FACT remains locked.
- POST `/materials/{id}/regenerate-section`: a new material version, one section re-rendered.
- GET `/materials/{id}/export`: Markdown, label and Evidence binding.

No PUT or DELETE is offered. The UI stores only object IDs, not context, documents, material text or credentials.

## Verification

`tests/test_career.py` exercises 34 contracts, including both experiment types, proof-source paths, immutable histories, review revisions, override evidence, partial/noncomparable/all-invalid cases and adversarial edits. The browser Golden Path uses newly acquired real Chroma results and HTTP backend artifacts with a clearly scripted local provider. It is a workflow verification, not commercial model quality evidence.

No accounts, job applications, JD matching, voice interviews, sharing, cloud tenancy, billing or new experiment abilities are included. The historical Java implementation is outside the current Python MVP scope.

## Phase 5.1 — explicit v2 generation

Existing `/career/materials` and v1 artifacts remain compatible. The product page
now explicitly uses `/career/materials/v2`; no historical artifact is upgraded.

`POST /career/narrative/preview` reads the frozen Evidence and returns normalized
claims, conflicts and at most three missing decision questions. It performs no
Provider calls and writes nothing. `POST /career/materials/v2` accepts
`evidence_object_id`, `project_focus`, `career_target`, `speech_rate` (180–300),
and confirmed `completions`. The sole supported generation mode is deterministic.
There is no implicit narrative LLM, credential lookup or fee.

New immutable artifacts are `career/views` and `career/narratives`. A material
binds the original Evidence hash/version, normalized view hash and plan hash.
Reads validate bindings and reconstruct normalized claims from frozen sources;
export reruns factual/format/readiness checks. Machine text is checked against
its purpose-specific renderer, not merely a whitelist of known numbers.
Free edits remain unverified new versions, never new experiment facts.

Missing root cause remains missing; a supplemented root cause remains INFERENCE
and cannot become independently verified just because a user confirms it.
Supplemental judgments are retrospective by default; already frozen decisions
and confirmed reflection cannot be silently overwritten. New background requires
explicit new Evidence. The current workbench context cannot stand in for customer
service application user research; application focus is a draft with an explicit gap.

Four independent renderers cover Case Study, two resume versions, independently
composed 30/60/90-second scripts, and six categories of evidence-backed interview
cards. Oral duration is an engineering estimate at an adjustable speech rate,
not a promise. No text is clipped to fit a duration. Main prose references exact
spans; the claim and raw-path mapping belongs to expandable evidence / Markdown
footnotes. `/career/materials/{id}/export?group=interview` (or `case_study`,
`resume_ai`, `resume_general`, `defense`) exports a single material family.

Readiness has seven qualitative dimensions. READY checks internal material
consistency; it does not predict interview success. Missing judgments leave the
current real sample Draft; the facts and usable script are still exportable.
Facts, user judgment, hypotheses, AI coding and existing repository capabilities
retain distinct provenance. Career routes never run an experiment or change its
comparison, evaluator, review or attribution semantics.

Phase5.1 regression evidence lives in `analysis/20261007-echomind/phase5.1`.
The fixed real fixture is the existing eight-case Rerank experiment, with actual
candidate pool 8, final Top K 3, candidate-pool MRR .478125→1.00, Hit@1 .25→1.00,
six improved and two unchanged. Answer evaluation was not run. Other scripted
browser fixtures do not substitute for this sample or commercial model validation.
