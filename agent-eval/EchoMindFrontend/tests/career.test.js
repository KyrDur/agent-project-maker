import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createCareerWorkspace,contextDefaults} from '../src/career-workspace.js'
function fixture(client={}){
 let saved={};const storage={getItem:k=>saved[k]||null,setItem:(k,v)=>saved[k]=v}
 const work={state:{baseline:{run:{run_id:'agent_base'}},retest:{run:{run_id:'agent_retest'}},comparison:{comparison_id:'agent_comp'}},action:async(_,fn)=>fn()}
 const rag={state:{baseline:{run:{run_id:'rag_base'}},retest:{run:{run_id:'rag_retest'}},comparison:{comparison_id:'rag_comp'}}};const mode={value:'RETRIEVAL'}
 return {work,rag,mode,storage,saved,c:createCareerWorkspace(work,rag,mode,storage,client)}
}
test('Career context does not fabricate background, roles, users or deployment',()=>{
 const d=contextDefaults();assert.equal(d.motivation,'');assert.deepEqual(d.user_roles,[]);assert.equal(d.real_users,null);assert.equal(d.deployed,null);assert.equal(d.confirmed,false)
})
test('Career source selection follows active path, not similarly named project',()=>{
 const f=fixture();assert.equal(f.c.selection().baseline_run_id,'rag_base');f.mode.value='AGENT_BEHAVIOR';assert.equal(f.c.selection().baseline_run_id,'agent_base')
})
test('Career persistence contains only IDs, no context or text',async()=>{
 const f=fixture({get:async()=>[],post:async()=>({evidence_object_id:'e_1',context:{motivation:'private input'}})})
 await f.c.build();assert.deepEqual(JSON.parse(f.saved['echomind.career.v1']),{evidence:'e_1'});assert.ok(!f.saved['echomind.career.v1'].includes('private'))
})
test('New Evidence clears displayed material, never rewrites old material',async()=>{
 const posts=[];const f=fixture({get:async()=>[],post:async(p,b)=>{posts.push([p,b]);return {evidence_object_id:'new'}}})
 f.c.state.evidence={evidence_object_id:'old',baseline_run_id:'rag_base',experiment_type:'RETRIEVAL'};f.c.state.material={material_id:'saved'}
 await f.c.build();assert.equal(f.c.state.material,null);assert.equal(posts[0][1].parent_evidence_id,'old');assert.equal(posts.length,1)
})
test('Opening old material restores its own locked Evidence',async()=>{
 const calls=[];const f=fixture({get:async p=>{calls.push(p);return p.includes('/materials/')?{material_id:'old',evidence_object_id:'frozen'}:{evidence_object_id:'frozen'}}})
 await f.c.openMaterial('old');assert.deepEqual(calls,['/career/materials/old','/career/evidence/frozen'])
})
test('Editing text posts only wording and persists new material ID',async()=>{
 const posts=[];const f=fixture({get:async()=>[],post:async(p,b)=>{posts.push([p,b]);return {material_id:'new_m'}}})
 f.c.state.evidence={evidence_object_id:'e_1'};f.c.state.material={material_id:'m_1'}
 await f.c.edit('resume_ai','ai_eval','80道题');assert.equal(posts[0][1].edit_type,'WORDING');assert.equal(f.c.state.material.material_id,'new_m')
})
test('Phase5.1 explicitly previews and generates with target; no LLM or experiment mutation',async()=>{
 const posts=[];const f=fixture({get:async p=>p.includes('/views/')?{view_id:'view',facts:{}}:[],post:async(p,b)=>{posts.push([p,b]);return p.includes('/v2')?{material_id:'v2',view_id:'view'}:{missing_questions:[]}}})
 f.c.state.evidence={evidence_object_id:'e1'}
 await f.c.preview({project_focus:'EVALUATION_WORKBENCH',career_target:'GENERAL_PM'})
 await f.c.generateV2({career_target:'GENERAL_PM',speech_rate:240,completions:[]})
 assert.deepEqual(posts.map(p=>p[0]),['/career/narrative/preview','/career/materials/v2'])
 assert.equal(posts[1][1].evidence_object_id,'e1');assert.equal(f.c.state.material.material_id,'v2')
 assert.ok(!f.saved['echomind.career.v1'].includes('GENERAL_PM'))
})
test('Phase5.1 independent Markdown export passes a safely encoded group',async()=>{
 const calls=[];const f=fixture({get:async p=>{calls.push(p);return {markdown:'result'}}});f.c.state.material={material_id:'v2'}
 await f.c.export('resume_ai');assert.equal(calls[0],'/career/materials/v2/export?group=resume_ai')
})
