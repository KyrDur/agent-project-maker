import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readRetrievalPointers, createRetrievalWorkspace } from '../src/retrieval-workspace.js'
import { demoDocuments, demoCases } from '../src/rag-demo.js'
test('Retrieval Demo contains human relevance labels but no ranks or metrics',()=>{
  assert.equal(demoCases.length,8)
  const ids=new Set(demoDocuments.map(d=>d.document_id))
  for(const c of demoCases){assert.equal(c.source,'demo');assert.ok(c.relevant_document_ids.every(id=>ids.has(id)));assert.equal(c.metrics,undefined)}
})
test('Retrieval pointers discard all data and credential fields',()=>{
  const storage={getItem:()=>JSON.stringify({baseline:'run_1',session:'session_1',api_key:'secret',knowledge:{text:'body'},query:'bad',retest:'../../file'})}
  assert.deepEqual(readRetrievalPointers(storage),{baseline:'run_1',session:'session_1'})
})
test('Retrieval workspace persists only IDs, not user knowledge or labels',async()=>{
  let saved
  const storage={setItem:(k,v)=>saved=v,getItem:()=>null}
  const work={state:{session:{provider_session_id:'public_id'}},action:async(l,fn)=>fn(),go:()=>{}}
  const client={post:async()=>({knowledge_dataset_id:'knowledge_id',version:1,documents:[{text:'private business'}]})}
  const w=createRetrievalWorkspace(work,storage,client)
  await w.saveKnowledge({documents:demoDocuments})
  assert.deepEqual(JSON.parse(saved),{knowledge:'knowledge_id',session:'public_id'})
  assert.ok(!saved.includes('private business'))
})
test('Restoring a same-named new EvalSet cannot attach an older experiment',async()=>{
  const calls=[]
  const storage={getItem:()=>JSON.stringify({evalSet:'new_set'}),setItem:()=>{}}
  const work={state:{session:null},action:async(l,fn)=>fn(),go:()=>{}}
  const client={get:async p=>{calls.push(p);if(p==='/retrieval-history')return [{run_id:'old',run_type:'BASELINE',name:'same',retrieval_eval_set_id:'old_set',version:1,created_at:'2026'}]
    if(p==='/retrieval-evalsets/new_set')return {retrieval_eval_set_id:'new_set',version:1,name:'same',index_id:'new_index'}
    if(p==='/knowledge-indices/new_index')return {index_id:'new_index',knowledge_dataset_id:'knowledge',knowledge_version:2}
    if(p==='/knowledge-datasets/knowledge?version=2')return {knowledge_dataset_id:'knowledge',version:2};throw Error(p)}}
  const w=createRetrievalWorkspace(work,storage,client);await w.restore()
  assert.equal(w.state.baseline,null);assert.ok(!calls.some(p=>p.startsWith('/retrieval-runs/')))
  assert.equal(w.state.knowledge.version,2)
})
test('New index clears a test set bound to the previous index',async()=>{
  const storage={getItem:()=>null,setItem:()=>{}}
  const work={state:{session:null},action:async(l,fn)=>fn(),go:()=>{}}
  const w=createRetrievalWorkspace(work,storage,{post:async()=>({index_id:'new_index'})})
  w.state.knowledge={knowledge_dataset_id:'k',version:1};w.state.index={index_id:'old_index'};w.state.evalSet={index_id:'old_index'}
  await w.buildIndex({});assert.equal(w.state.evalSet,null);assert.equal(w.state.index.index_id,'new_index')
})
test('Restore retains an explicit current ProviderSession after historical Run load',async()=>{
  const storage={getItem:()=>JSON.stringify({baseline:'baseline',session:'current_session'}),setItem:()=>{}}
  const work={state:{session:null},action:async(l,fn)=>fn(),go:()=>{}}
  const run={run:{run_id:'baseline',run_type:'BASELINE',provider_session_id:'historical_session',controls:{
    knowledge_snapshot:{knowledge_dataset_id:'k',version:1},index_snapshot:{index_id:'i'},eval_set_snapshot:{retrieval_eval_set_id:'e',version:1}}}}
  const client={get:async p=>{
    if(p==='/retrieval-history')return []
    if(p==='/retrieval-runs/baseline')return run
    if(p.startsWith('/provider-sessions/'))return {provider_session_id:p.split('/').at(-1)}
    if(p.startsWith('/knowledge-datasets/'))return {knowledge_dataset_id:'k',version:1}
    if(p.startsWith('/knowledge-indices/'))return {index_id:'i'}
    if(p.startsWith('/retrieval-evalsets/'))return {retrieval_eval_set_id:'e'};throw Error(p)}}
  const w=createRetrievalWorkspace(work,storage,client);await w.restore()
  assert.equal(work.state.session.provider_session_id,'current_session')
})

test('Knowledge retest keeps its cloned criteria bound to the new index for preview and refresh',async()=>{
 const storage={getItem:()=>null,setItem:()=>{}}
 const work={state:{session:{provider_session_id:'s'}},action:async(_,fn)=>fn(),go:()=>{}}
 const calls=[], view={run:{run_id:'r',run_type:'RETEST',verify_answers:true}}
 const client={post:async(_,body)=>{calls.push(body);return {run_id:'r'}},get:async path=>{
  if(path==='/retrieval-runs/r')return view
  if(path==='/retrieval-history')return []
  if(path==='/retrieval-evalsets/new_criteria?version=1')return {retrieval_eval_set_id:'new_criteria',version:1,index_id:'new_index'}
  throw Error(path)
 }}
 const w=createRetrievalWorkspace(work,storage,client)
 w.state.baseline={run:{run_id:'b',verify_answers:true}}
 w.state.change={change_id:'c',target_eval_set_id:'new_criteria'}
 w.state.evalSet=null
 await w.run('RETEST',null,true)
 assert.equal(calls[0].retrieval_eval_set_id,'new_criteria')
 assert.equal(w.state.evalSet.index_id,'new_index')
 assert.equal(w.state.retest.run.run_id,'r')
})
