"""Only Phase 5 artifacts can be written by these routes."""
from typing import Literal
from pydantic import Field
from fastapi import APIRouter, HTTPException
from .api import Input, service, execute
from .career_models import ProjectContext, DecisionCompletion
from .career_service import CareerService
from .career_render import markdown

router=APIRouter(prefix='/experiments/career',tags=['Career Evidence'])
def career(): return CareerService(service())

class EvidenceInput(Input):
    experiment_type: Literal['AGENT_BEHAVIOR','RETRIEVAL']
    baseline_run_id: str
    retest_run_id: str | None = None
    comparison_id: str | None = None
    context: ProjectContext | None = None
    parent_evidence_id: str | None = None

class GenerateInput(Input):
    evidence_object_id: str

class NarrativeInput(GenerateInput):
    project_focus: Literal['CUSTOMER_SERVICE_APP','EVALUATION_WORKBENCH'] = 'EVALUATION_WORKBENCH'
    career_target: Literal['AI_APPLICATION_PM','AI_EVALUATION_PLATFORM_PM','GENERAL_PM'] = 'AI_EVALUATION_PLATFORM_PM'
    completions: list[DecisionCompletion] = Field(default_factory=list)
    speech_rate: int = Field(default=240,ge=180,le=300)

@router.post('/narrative/preview')
def preview(body:NarrativeInput):
    data=body.model_dump();identifier=data.pop('evidence_object_id');data.pop('speech_rate')
    return execute(career().preview_v2,identifier,**data)

@router.post('/materials/v2')
def generate_v2(body:NarrativeInput):
    data=body.model_dump();identifier=data.pop('evidence_object_id')
    try: return career().generate_v2(identifier,**data)
    except ValueError: raise HTTPException(409,'NARRATIVE_VALIDATION_FAILED') from None

@router.get('/views/{identifier}')
def view(identifier:str): return execute(career().career.get,'views',identifier)

@router.get('/narratives/{identifier}')
def narrative(identifier:str): return execute(career().career.get,'narratives',identifier)

class EditInput(Input):
    group: Literal['case_study','resume_ai','resume_general','interview']
    section_id: str
    text: str = Field(min_length=1,max_length=10000)
    edit_type: Literal['WORDING','USER_UNVERIFIED_CLAIM'] = 'WORDING'

class RegenerateInput(Input):
    group: str
    section_id: str

@router.post('/evidence')
def build(body:EvidenceInput): return execute(career().build,**body.model_dump())

@router.get('/evidence')
def evidence_list():
    return [{'evidence_object_id':e.evidence_object_id,'evidence_version':e.evidence_version,
             'experiment_type':e.experiment_type,'baseline_run_id':e.baseline_run_id,
             'comparison_id':e.comparison_id,'created_at':e.created_at,'project_name':e.project_identity['name']}
            for e in career().career.list('evidence')]

@router.get('/evidence/{identifier}')
def evidence(identifier:str): return execute(career().career.get,'evidence',identifier)

@router.post('/materials')
def generate(body:GenerateInput): return execute(career().generate,body.evidence_object_id)

@router.get('/materials')
def materials():
    return [{'material_id':m.material_id,'evidence_object_id':m.evidence_object_id,'evidence_version':m.evidence_version,
             'material_version':m.material_version,'label':m.label,'created_at':m.created_at}
            for m in career().career.list('materials')]

@router.get('/materials/{identifier}')
def material(identifier:str): return execute(career().career.get,'materials',identifier)

@router.post('/materials/{identifier}/edit')
def edit(identifier:str,body:EditInput): return execute(career().edit,identifier,**body.model_dump())

@router.post('/materials/{identifier}/regenerate-section')
def regenerate(identifier:str,body:RegenerateInput): return execute(career().regenerate_section,identifier,**body.model_dump())

@router.get('/materials/{identifier}/export')
def export(identifier:str, group:str | None = None):
    return execute(career().export,identifier,group)
