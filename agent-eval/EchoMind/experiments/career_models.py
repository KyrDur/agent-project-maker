"""Phase 5 facts and texts are separate, immutable, versioned artifacts."""
from typing import Any, Literal
from pydantic import Field, model_validator
from .models import Artifact, uid

SourceType = Literal['RUN_EVIDENCE','COMPARISON_EVIDENCE','USER_CONFIRMED_DECISION',
    'USER_ENTERED_CONTEXT','SYSTEM_DERIVED','HUMAN_REVIEW','HISTORICAL_CONTEXT','MISSING','AI_SUGGESTION']

class ProjectContext(Artifact):
    project_name: str = Field(min_length=1,max_length=120)
    project_context: Literal['PERSONAL_PROJECT','INTERNSHIP','COURSE','COMPETITION','OTHER']
    motivation: str = Field(min_length=1,max_length=1500)
    target_users: str = Field(min_length=1,max_length=500)
    user_problem: str = Field(min_length=1,max_length=1500)
    why_ai: str = Field(min_length=1,max_length=1000)
    user_roles: list[str] = Field(min_length=1,max_length=10)
    user_contribution: str = Field(min_length=1,max_length=1500)
    system_contribution: str = Field(min_length=1,max_length=1500)
    existing_capabilities: str = Field(min_length=1,max_length=1500)
    real_users: bool
    deployed: bool
    reflection: str = Field(default='',max_length=1500)
    reflection_confirmed: bool = False
    confirmed: Literal[True]

    @model_validator(mode='after')
    def explicit_facts(self):
        for key in ['project_name','motivation','target_users','user_problem','why_ai',
                    'user_contribution','system_contribution','existing_capabilities']:
            if not getattr(self,key).strip(): raise ValueError('Context fields need explicit user confirmation')
        if any(not role.strip() for role in self.user_roles): raise ValueError('Empty role')
        if self.reflection_confirmed and not self.reflection.strip(): raise ValueError('Reflection missing')
        return self

class EvidenceClaim(Artifact):
    claim_id: str
    claim_type: str
    claim_text: str
    value_before: Any = None
    value_after: Any = None
    unit: str = ''
    source_type: SourceType
    source_ids: list[str] = Field(default_factory=list)
    evidence_path: list[str] = Field(default_factory=list)
    confidence: Literal['RECORDED','USER_CONFIRMED','DERIVED','UNVERIFIED','MISSING']
    allowed_for_resume: bool = False
    allowed_for_case_study: bool = True
    allowed_for_interview: bool = True
    limitations: list[str] = Field(default_factory=list)

class EvidenceObject(Artifact):
    evidence_object_id: str = Field(default_factory=uid)
    evidence_version: int = Field(ge=1)
    evidence_hash: str
    parent_evidence_id: str | None = None
    experiment_type: Literal['AGENT_BEHAVIOR','RETRIEVAL']
    baseline_run_id: str
    retest_run_id: str | None = None
    comparison_id: str | None = None
    project_identity: dict
    problem_definition: dict
    baseline: dict
    diagnosis: dict
    user_decision: dict
    change: dict
    retest: dict
    comparison: dict
    retrieval_evidence: dict
    answer_evidence: dict
    regressions: list[dict]
    invalid_cases: list[dict]
    human_reviews: list[dict]
    limitations: list[str]
    user_contribution: dict
    system_contribution: dict
    historical_context: dict
    missing_evidence: list[str]
    source_map: dict
    claims: list[EvidenceClaim]
    context: ProjectContext | None = None
    reflection_candidates: list[str]
    generated_at: str

class CareerSection(Artifact):
    section_id: str
    title: str
    text: str
    claim_ids: list[str] = Field(default_factory=list)
    source_type: str = 'SYSTEM_DERIVED'
    risk: list[str] = Field(default_factory=list)
    possible_follow_up: list[str] = Field(default_factory=list)
    safe_wording: str = ''
    citations: list[dict] = Field(default_factory=list)
    timing: dict = Field(default_factory=dict)

class DefenseQuestion(Artifact):
    question_id: str
    category: str
    question: str
    suggested_answer_outline: str
    claim_ids: list[str]
    supporting_evidence: list[str]
    risk: list[str]
    missing_information: list[str]
    pressure: bool = False
    possible_follow_up: list[str] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)

class CareerBundle(Artifact):
    material_id: str = Field(default_factory=uid)
    evidence_object_id: str
    evidence_version: int
    evidence_hash: str
    material_version: int = Field(ge=1)
    parent_material_id: str | None = None
    generator_version: str = 'deterministic-evidence-templates-v1'
    introduction: str
    sections: dict[str,list[CareerSection]]
    defense: list[DefenseQuestion]
    contribution_summary: list[dict]
    reflection_candidates: list[str]
    lint: list[dict]
    label: Literal['Evidence-backed','Mixed','Draft']
    user_edits: list[dict] = Field(default_factory=list)
    view_id: str | None = None
    view_hash: str | None = None
    narrative_id: str | None = None
    narrative_hash: str | None = None
    readiness: dict = Field(default_factory=dict)

# Version 2 adds artifacts; original Evidence and v1 texts remain immutable.
class DecisionCompletion(Artifact):
    field: Literal['root_cause','alternatives','interpretation']
    text: str = Field(min_length=1,max_length=1500)
    evidence_state: Literal['USER_CONFIRMED','INFERENCE']
    temporal_scope: Literal['AT_EXPERIMENT','RETROSPECTIVE'] = 'RETROSPECTIVE'
    confirmed: Literal[True]

    @model_validator(mode='after')
    def judgment_not_measurement(self):
        if not self.text.strip(): raise ValueError('Judgment needs explicit text')
        if self.field=='root_cause' and self.evidence_state!='INFERENCE':
            raise ValueError('Root cause without independent validation must remain a hypothesis')
        return self

class NarrativeFact(Artifact):
    fact_id: str
    value: Any
    evidence_state: Literal['VERIFIED_RECORD','USER_CONFIRMED','INFERENCE','MISSING','CONTRADICTED']
    owner: Literal['USER','AI_CODING_PLATFORM','EXISTING_CAPABILITY','RECORD'] = 'RECORD'
    subject_scope: Literal['APP','WORKBENCH','SHARED'] = 'SHARED'
    claim_ids: list[str] = Field(default_factory=list)
    evidence_paths: list[str] = Field(default_factory=list)

class CareerEvidenceView(Artifact):
    view_id: str = Field(default_factory=uid)
    evidence_object_id: str
    evidence_version: int
    evidence_hash: str
    project_focus: Literal['CUSTOMER_SERVICE_APP','EVALUATION_WORKBENCH']
    career_target: Literal['AI_APPLICATION_PM','AI_EVALUATION_PLATFORM_PM','GENERAL_PM']
    facts: dict[str,NarrativeFact]
    completions: list[DecisionCompletion] = Field(default_factory=list)
    missing_questions: list[dict] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)

class NarrativePlan(Artifact):
    narrative_id: str = Field(default_factory=uid)
    view_id: str
    view_hash: str
    beats: dict[str,list[str]]
    material_orders: dict[str,list[str]]
    speech_rate: int = Field(default=240,ge=180,le=300)
    generation_mode: Literal['DETERMINISTIC'] = 'DETERMINISTIC'
