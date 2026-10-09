import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createPracticeWorkspace } from '../src/practice-workspace.js'
function setup(client, initial={}){
 const items=new Map(Object.entries(initial)),storage={getItem:k=>items.get(k)||null,setItem:(k,v)=>items.set(k,v)}
 const work={state:{session:{provider_session_id:'session_1'}},action:async(_,fn)=>fn(),go:step=>{work.step=step}}
 const rag={state:{knowledge:null,index:null},persist:()=>{}}
 return {work,rag,storage,items,practice:createPracticeWorkspace(work,rag,storage,client)}
}
test('Chat failure stays a failed record and never substitutes an answer',async()=>{
 const env=setup({post:async()=>({turn_id:'t1',conversation_id:'c1',status:'FAILED',answer:'',error:'TIMEOUT'})})
 await env.practice.send({index_id:'i1',message:'问题'})
 assert.equal(env.practice.state.turns[0].status,'FAILED')
 assert.equal(env.practice.state.turns[0].answer,'')
 assert.deepEqual(JSON.parse(env.items.get('agenteval.practice.v1')),{conversationId:'c1',drafts:[]})
})
test('Confirmed case draft keeps server provenance and navigates to review',async()=>{
 const calls=[],caseRow={case_id:'chat_t1',query:'用户问题',source_chat_turn_id:'t1',expected_answer:'用户确认的标准'}
 const env=setup({post:async(path,body)=>{calls.push({path,body});return caseRow}})
 await env.practice.draft('t1',{expected_answer:'用户确认的标准',confirmed:true})
 assert.equal(env.work.step,'define');assert.deepEqual(env.practice.state.drafts,[caseRow])
 assert.equal(calls[0].path,'/chat-turns/t1/test-draft');assert.equal(calls[0].body.confirmed,true)
})
test('Selecting a historical knowledge index fetches its exact version and starts fresh conversation',async()=>{
 const calls=[],env=setup({get:async path=>{calls.push(path);return {knowledge_dataset_id:'k1',version:2}}})
 env.practice.state.conversationId='previous';env.practice.state.turns=[{turn_id:'old'}]
 await env.practice.useIndex({index_id:'i2',knowledge_dataset_id:'k1',knowledge_version:2})
 assert.deepEqual(calls,['/knowledge-datasets/k1?version=2'])
 assert.equal(env.rag.state.index.index_id,'i2');assert.equal(env.practice.state.conversationId,null)
 assert.deepEqual(env.practice.state.turns,[])
})
test('Restoring conversation reads saved server evidence instead of a local answer cache',async()=>{
 const calls=[],env=setup({get:async path=>{calls.push(path);return path==='/knowledge-library'?{datasets:[],indices:[]}:[{turn_id:'actual'}]}},
  {'agenteval.practice.v1':JSON.stringify({conversationId:'c1',drafts:[]})})
 await env.practice.restore();assert.equal(env.practice.state.turns[0].turn_id,'actual')
 assert.ok(calls.includes('/chat-conversations/c1'))
})

// Vue state is a Proxy and cannot be passed directly to structuredClone.
test('Reactive evidence copies preserve provenance and remain independently editable',async()=>{
 const { reactive }=await import('vue')
 const { cloneArtifact }=await import('../src/practice-data.js')
 const original=reactive({cases:[{case_id:'chat_t1',source_chat_turn_id:'t1',context:[{role:'user',content:'原问题'}]}]})
 const draft=cloneArtifact(original)
 draft.cases[0].context[0].content='编辑后的标准'
 assert.equal(original.cases[0].context[0].content,'原问题')
 assert.equal(draft.cases[0].source_chat_turn_id,'t1')
})
