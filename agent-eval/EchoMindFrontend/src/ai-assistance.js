import {reactive} from 'vue'
export const questionTypes=['常规','口语','边界','多条件','知识范围外']
export const copy=value=>JSON.parse(JSON.stringify(value))
export const estimateTestCalls=count=>Math.ceil(count/4)
export function appendGeneratedCases(current,incoming,indexId,draftIndexId){
 if(indexId!==draftIndexId)throw new Error('知识索引已变化，请按当前版本重新生成测试。')
 const ids=new Set(current.map(c=>c.case_id))
 return [...current,...incoming.filter(c=>!ids.has(c.case_id)).map(copy)]
}
export function createAiAssistance(){return reactive({knowledge:{scenario:'',facts:'',draft:null,documents:[],name:'',selected:[],confirmed:false},tests:{count:8,types:[...questionTypes],draft:null,cases:[],selected:[],confirmed:false},analyses:{},providerOptions:[],modelSession:''})}
export async function restoreAiDrafts(ai,client){
 const history=await client.get('/ai/drafts')
 for(const kind of ['KNOWLEDGE','TESTS']){
  const record=history.find(d=>d.kind===kind);if(!record)continue
  const draft=await client.get('/ai/drafts/'+record.draft_id)
  if(kind==='KNOWLEDGE')Object.assign(ai.knowledge,{draft,scenario:draft.content.scenario,facts:draft.sources.facts||'',name:draft.content.name,documents:copy(draft.content.documents),selected:draft.content.documents.map(d=>d.document_id),confirmed:false})
  else Object.assign(ai.tests,{draft,cases:copy(draft.content.cases),selected:draft.content.cases.map(c=>c.case_id),confirmed:false})
 }
 for(const record of history.filter(d=>d.kind==='TRACE').slice(0,5)){
  const draft=await client.get('/ai/drafts/'+record.draft_id)
  const source=draft.sources.comparison||draft.sources.run
  const id=source?.comparison_id||source?.run_id,caseId=source?.pair?.case_id||source?.case?.case_id
  if(id&&caseId&&!ai.analyses[`${id}:${caseId}`])ai.analyses[`${id}:${caseId}`]=draft
 }
}
