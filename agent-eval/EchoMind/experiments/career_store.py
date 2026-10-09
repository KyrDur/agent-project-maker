"""Phase 5 store owns only new artifacts; no experiment files are written."""
import json, os, re, tempfile
from pathlib import Path
from .canonical import digest, encoded
from .store import safe_artifact
from .career_models import EvidenceObject, CareerBundle, CareerEvidenceView, NarrativePlan

class CareerStore:
    def __init__(self, experiment_store):
        self.base = experiment_store
        self.root = experiment_store.root / 'career'

    def path(self, group, identifier):
        if group not in {'evidence','materials','views','narratives'} or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',identifier):
            raise ValueError('Invalid career identity')
        return self.root/group/(identifier+'.json')

    def get(self, group, identifier):
        envelope=json.loads(self.path(group,identifier).read_text())
        data=envelope['artifact']
        if digest(data)!=envelope['sha256']: raise ValueError('Career integrity mismatch')
        model={'evidence':EvidenceObject,'materials':CareerBundle,'views':CareerEvidenceView,'narratives':NarrativePlan}[group]
        obj=model.model_validate(data)
        if group=='evidence' and obj.evidence_hash!=digest({k:v for k,v in data.items() if k!='evidence_hash'}):
            raise ValueError('Evidence fact lock mismatch')
        if group in {'materials','views'}:
            evidence=self.get('evidence',obj.evidence_object_id)
            if (obj.evidence_hash,obj.evidence_version)!=(evidence.evidence_hash,evidence.evidence_version):
                raise ValueError('Material fact lock mismatch')
        if group=='views':
            from .career_evidence import normalize
            expected=normalize(evidence,obj.project_focus,obj.career_target,[c.model_dump(mode='json') for c in obj.completions],schema_version=obj.schema_version)
            def semantic_facts(view):
                return {k:f.model_dump(mode='json',exclude={'created_at'}) for k,f in view.facts.items()}
            if semantic_facts(obj)!=semantic_facts(expected) or obj.conflicts!=expected.conflicts or obj.missing_questions!=expected.missing_questions:
                raise ValueError('Normalized claims do not match frozen Evidence')
        if group=='materials' and obj.view_id:
            view=self.get('views',obj.view_id);plan=self.get('narratives',obj.narrative_id)
            if obj.view_hash!=digest(view.model_dump(mode='json')) or obj.narrative_hash!=digest(plan.model_dump(mode='json')) or plan.view_id!=obj.view_id:
                raise ValueError('Material narrative binding mismatch')
        if group=='narratives':
            view=self.get('views',obj.view_id)
            if obj.view_hash!=digest(view.model_dump(mode='json')): raise ValueError('Plan view binding mismatch')
        return obj

    def list(self, group):
        return [self.get(group,p.stem) for p in sorted((self.root/group).glob('*.json'))]

    def put(self, group, obj):
        identifier=getattr(obj,{'evidence':'evidence_object_id','materials':'material_id','views':'view_id','narratives':'narrative_id'}[group])
        path=self.path(group,identifier)
        if path.exists(): raise ValueError('Career artifacts are immutable')
        data=obj.model_dump(mode='json')
        safe_artifact(data,self.base.forbidden_values)
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix='.write-',dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(encoded({'sha256':digest(data),'artifact':data}));stream.flush();os.fsync(stream.fileno())
            os.replace(tmp,path)
            dfd=os.open(path.parent,os.O_RDONLY)
            try: os.fsync(dfd)
            finally: os.close(dfd)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        return self.get(group,identifier)
