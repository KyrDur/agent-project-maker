"""Select propositions and order by purpose, independently of language rendering."""
from .career_models import NarrativePlan
from .canonical import digest

def plan(view,speech_rate=240):
    beats={'value':['project_name','target_users','user_problem'], 'ownership':['user_contribution','system_contribution','existing_capabilities'],
      'discovery':['selected','rank_movements'] if 'rank_movements' in view.facts else ['selected','answer_before'],
      'judgment':['decision','root_cause','alternatives'], 'control':['change','config_before','config_after','acquisition'] if 'acquisition' in view.facts else ['change'],
      'result':['metric_hit_at_1','metric_mrr','transitions','comparison'] if 'transitions' in view.facts else ['answer_before','answer_after','comparison'],
      'boundary':['answers','regressions','invalid_cases','real_users','deployed','limitations'], 'reflection':['interpretation']}
    beats={key:[p for p in ps if p in view.facts] for key,ps in beats.items()}
    # Different target selects emphasis, never changes values or evidence identity.
    emphasis='value' if view.career_target=='GENERAL_PM' else 'control' if view.career_target=='AI_EVALUATION_PLATFORM_PM' else 'discovery'
    return NarrativePlan(view_id=view.view_id,view_hash=digest(view.model_dump(mode='json')),beats=beats,speech_rate=speech_rate,
      material_orders={'case_study':['value','ownership','discovery','judgment','control','result','boundary','reflection'],
       'resume_ai':['ownership',emphasis,'result'], 'resume_general':['value','ownership','result'],
       'story30':['value','ownership','boundary'],'story60':['value','ownership','discovery','judgment','result','reflection'],
       'story90':['value','ownership','discovery','judgment','control','result','boundary','reflection']})
