import { reactive } from 'vue'
import { api } from './api.js'
export const contextDefaults=()=>({project_name:'',project_context:'PERSONAL_PROJECT',motivation:'',target_users:'',user_problem:'',why_ai:'',
 user_roles:[],user_contribution:'',system_contribution:'',existing_capabilities:'',real_users:null,deployed:null,reflection:'',reflection_confirmed:false,confirmed:false})
export function createCareerWorkspace(work,rag,mode,storage=globalThis.localStorage,client=api){
 const state=reactive({evidence:null,material:null,evidenceHistory:[],materialHistory:[],view:null,tab:'Evidence'})
 function persist(){storage.setItem('echomind.career.v1',JSON.stringify({evidence:state.evidence?.evidence_object_id,material:state.material?.material_id}))}
 async function history(){[state.evidenceHistory,state.materialHistory]=await Promise.all([client.get('/career/evidence'),client.get('/career/materials')])}
 async function restore(){await history();let p={};try{p=JSON.parse(storage.getItem('echomind.career.v1')||'{}')}catch{}
  if(!p || typeof p!=='object' || Array.isArray(p))p={}
  if(typeof p.evidence==='string' && /^[\w-]{1,128}$/.test(p.evidence))state.evidence=await client.get('/career/evidence/'+p.evidence)
  if(typeof p.material==='string' && /^[\w-]{1,128}$/.test(p.material))state.material=await client.get('/career/materials/'+p.material)
  await loadView()
 }
 async function loadView(){state.view=state.material?.view_id?await client.get('/career/views/'+state.material.view_id):null}
 function selection(){const s=mode.value==='RETRIEVAL'?rag.state:work.state
  return {experiment_type:mode.value,baseline_run_id:s.baseline?.run.run_id,retest_run_id:s.retest?.run.run_id||null,comparison_id:s.comparison?.comparison_id||null}}
 return {state,restore,selection,
  async build(context=null){return work.action('整理实验事实',async()=>{const selected=selection();if(!selected.baseline_run_id)throw new Error('Select baseline')
   const same=state.evidence?.baseline_run_id===selected.baseline_run_id && state.evidence?.experiment_type===selected.experiment_type
   state.evidence=await client.post('/career/evidence',{...selected,context,parent_evidence_id:same?state.evidence.evidence_object_id:null});state.material=null;state.view=null;persist();await history();state.tab='Evidence';return state.evidence})},
  async generate(){return work.action('从已确认 Evidence 生成材料',async()=>{state.material=await client.post('/career/materials',{evidence_object_id:state.evidence.evidence_object_id});persist();await history()})},
  async preview(options={}){return work.action('检查叙事证据与缺口',async()=>{state.view=await client.post('/career/narrative/preview',{evidence_object_id:state.evidence.evidence_object_id,...options});return state.view})},
  async generateV2(options={}){return work.action('根据已确认的证据生成材料',async()=>{state.material=await client.post('/career/materials/v2',{evidence_object_id:state.evidence.evidence_object_id,...options});await loadView();persist();await history()})},
  async openEvidence(id){return work.action('读取锁定证据',async()=>{state.evidence=await client.get('/career/evidence/'+id);state.material=null;state.view=null;persist()})},
  async openMaterial(id){return work.action('读取历史材料',async()=>{state.material=await client.get('/career/materials/'+id);state.evidence=await client.get('/career/evidence/'+state.material.evidence_object_id);await loadView();persist()})},
  async edit(group,section_id,text){return work.action('保存文案新版本',async()=>{state.material=await client.post('/career/materials/'+state.material.material_id+'/edit',{group,section_id,text,edit_type:'WORDING'});persist();await history()})},
  async regenerate(group,section_id){return work.action('重新生成段落',async()=>{state.material=await client.post('/career/materials/'+state.material.material_id+'/regenerate-section',{group,section_id});persist();await history()})},
  export:(group=null)=>client.get('/career/materials/'+state.material.material_id+'/export'+(group?'?group='+encodeURIComponent(group):'')),
 }
}
