import {test} from 'node:test'
import assert from 'node:assert/strict'
import {runBriefing,resultStartingPoint,nextJourneyStep} from '../src/journey-guidance.js'
const ready={credential_status:'PRESENT',text_connection_status:'READY',configuration:{model:'answer',max_calls:100,role_overrides:{judge:{model:'judge'}}}}
const cases=[{partition:'DEBUG'},{partition:'HOLDOUT'},{}]
test('Request estimate separates local retrieval, answers, Judge and optional LLM stages',()=>{
 const input={session:ready,index:{knowledge_version:2},cases,config:{query_rewrite:true,rerank:true},verifyAnswers:true}
 const full=runBriefing(input)
 assert.equal(full.totalCalls,12);assert.deepEqual(full.calls,{rewrite:3,rerank:3,agent:3,judge:3})
 assert.equal(full.debug,2);assert.equal(full.holdout,1);assert.equal(full.answerModel,'answer');assert.equal(full.judgeModel,'judge')
 assert.equal(runBriefing({...input,config:{},verifyAnswers:false}).totalCalls,0)
})
const row=(id,rank)=>({case_id:id,query:id,status:'SUCCESS',relevant_document_ids:['doc'],metrics:{relevant_rank:rank},top_k:3})
const view=rows=>({run:{status:'COMPLETE',verify_answers:false,retrieval_config:{top_k:3},case_results:rows},effective_answer_results:[]})
test('Invalid acquisition is handled before quality conclusions',()=>{
 const v=view([row('valid',6),{...row('invalid',null),status:'INVALID'}])
 assert.equal(resultStartingPoint(v).caseId,'invalid');assert.equal(resultStartingPoint(v).kind,'INVALID')
})
test('Answer failure prioritizes actual effective results, never invents a failed answer',()=>{
 const v=view([row('outside',6),row('answer',1)]);v.run.verify_answers=true
 v.effective_answer_results=[{case_id:'answer',execution_status:'SUCCESS',judge_status:'SUCCESS',final_status:'FAIL'}]
 assert.equal(resultStartingPoint(v).caseId,'answer')
 v.effective_answer_results[0].judge_status='FAILED'
 assert.equal(resultStartingPoint(v).kind,'INVALID')
 v.effective_answer_results[0].judge_status='SUCCESS';v.effective_answer_results[0].final_status='PASS'
 assert.equal(resultStartingPoint(v).kind,'OUTSIDE_K')
})
test('Missing knowledge, cutoff and lower rank receive different next steps',()=>{
 assert.equal(resultStartingPoint(view([row('missing',null),row('outside',6)])).kind,'MISSING')
 const outside=resultStartingPoint(view([row('lower',2),row('outside',6)]))
 assert.equal(outside.caseId,'outside');assert.match(outside.explanation,/第 6 位/)
 assert.equal(resultStartingPoint(view([row('lower',2)])).kind,'LOWER_RANK')
 assert.match(resultStartingPoint(view([row('lower',2)])).explanation,/没有检查最终回答/)
})
test('Unlabeled rows and no-answer runs are not reported as successful answers',()=>{
 assert.equal(resultStartingPoint(view([{...row('no-label',null),relevant_document_ids:[]}])).kind,'UNLABELED')
 assert.match(resultStartingPoint(view([row('good',1)])).explanation,/没有检查回答/)
 const pending=view([row('good',1)]);pending.run.status='RUNNING'
 assert.equal(resultStartingPoint(pending),null)
})
test('First-use next action follows real prerequisites instead of a fixed route',()=>{
 assert.equal(nextJourneyStep(null,{}).id,'setup')
 assert.equal(nextJourneyStep(ready,{}).id,'knowledge')
 assert.equal(nextJourneyStep(ready,{index:{}}).id,'chat')
 assert.equal(nextJourneyStep(ready,{index:{},evalSet:{}}).id,'evaluate')
})
