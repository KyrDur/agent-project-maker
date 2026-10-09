import { reactive } from 'vue'
import { api } from './api.js'
const key = 'agenteval.practice.v1'
export function createPracticeWorkspace(work, rag, storage = globalThis.localStorage, client = api) {
  const state=reactive({turns:[],conversationId:null,library:{datasets:[],indices:[]},drafts:[],repeat:null,conclusions:[],chatSource:'current'})
  function persist(){storage.setItem(key,JSON.stringify({conversationId:state.conversationId,drafts:state.drafts}))}
  async function library(){state.library=await client.get('/knowledge-library')}
  async function restore(){
    await library()
    let saved={};try{saved=JSON.parse(storage.getItem(key)||'{}')}catch{ /* Start empty. */ }
    if(Array.isArray(saved.drafts))state.drafts=saved.drafts
    if(typeof saved.conversationId==='string' && /^[A-Za-z0-9_-]{1,128}$/.test(saved.conversationId)){
      state.turns=await client.get('/chat-conversations/'+saved.conversationId);state.conversationId=saved.conversationId
    }
  }
  function newChat(){state.turns=[];state.conversationId=null;persist()}
  return {state,restore,library,newChat,persist,
    conclude:(id,body)=>work.action('记录实验结论',async()=>{const result=await client.post(`/retrieval-comparisons/${id}/conclusions`,body);state.conclusions.push(result);return result}),
    loadConclusions:async id=>{state.conclusions=await client.get(`/retrieval-comparisons/${id}/conclusions`)},
    send:body=>work.action('电商 Agent 正在回答',async()=>{
      const result=await client.post('/chat-turns',{...body,provider_session_id:work.state.session.provider_session_id,
        conversation_id:state.conversationId});state.turns.push(result);state.conversationId=result.conversation_id;persist();return result
    }),
    draft:(id,body)=>work.action('确认对话测试草稿',async()=>{
      const result=await client.post(`/chat-turns/${id}/test-draft`,body)
      state.drafts=state.drafts.filter(c=>c.case_id!==result.case_id);state.drafts.push(result);persist();work.go('define')
      work.state.notice='对话已加入测试草稿。保存前请检查标签、上下文与预期行为。'
    }),
    repeat:(runId,count)=>work.action(`重复运行 ${count} 次，请等待真实结果`,async()=>{
      state.repeat=await client.post('/retrieval-repeats',{source_run_id:runId,
        provider_session_id:work.state.session.provider_session_id,repetitions:count});return state.repeat
    }),
    useIndex:index=>work.action('切换知识版本',async()=>{
      rag.state.index=index;rag.state.knowledge=await client.get(`/knowledge-datasets/${index.knowledge_dataset_id}?version=${index.knowledge_version}`)
      rag.persist();newChat();work.state.notice=`已选用知识 v${index.knowledge_version}。历史实验仍使用原冻结版本。`
    }),
  }
}
