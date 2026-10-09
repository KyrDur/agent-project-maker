import {test} from 'node:test'
import assert from 'node:assert/strict'
import {appendGeneratedCases,estimateTestCalls,restoreAiDrafts,createAiAssistance} from '../src/ai-assistance.js'
import {runBriefing} from '../src/journey-guidance.js'
test('AI cases append without overwriting manual cases or duplicating confirmed imports',()=>{
 const original=[{case_id:'manual',query:'原题'}],incoming=[{case_id:'ai',query:'新题',generation:{draft_id:'record'}}]
 const next=appendGeneratedCases(original,incoming,'index','index')
 assert.equal(next.length,2);assert.equal(original.length,1)
 next[1].generation.draft_id='edited';assert.equal(incoming[0].generation.draft_id,'record')
 assert.equal(appendGeneratedCases(next,incoming,'index','index').length,2)
})
test('AI cases cannot enter an eval set with another knowledge index',()=>{
 assert.throws(()=>appendGeneratedCases([],[],'current','old'),/索引已变化/)
 assert.equal(estimateTestCalls(8),2);assert.equal(estimateTestCalls(12),3)
})
test('Run briefing names the actual independent Judge instead of the answering model',()=>{
 const brief=runBriefing({session:{configuration:{model:'answer',judge_provider_configuration:{model:'independent'}}},cases:[],config:{}})
 assert.equal(brief.judgeModel,'independent')
})
test('Refresh restores server drafts and source identity without restoring confirmation or credentials',async()=>{
 const ai=createAiAssistance()
 const draft={draft_id:'draft',content:{name:'模拟',scenario:'模拟电商',documents:[{document_id:'a',text:'原始规则'}]},sources:{facts:'用户提供规则'}}
 const client={get:async path=>path==='/ai/drafts'?[{draft_id:'draft',kind:'KNOWLEDGE'}]:draft}
 await restoreAiDrafts(ai,client)
 assert.equal(ai.knowledge.scenario,'模拟电商');assert.equal(ai.knowledge.confirmed,false)
 ai.knowledge.documents[0].text='编辑';assert.equal(draft.content.documents[0].text,'原始规则')
 assert.equal(ai.modelSession,'');assert.equal(ai.tests.confirmed,false)
})
