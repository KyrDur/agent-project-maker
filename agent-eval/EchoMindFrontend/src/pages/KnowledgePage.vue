<script setup>
import { embeddingLabel, semanticModel, lexicalModel } from '../embedding-models.js'
import { cloneArtifact } from '../practice-data.js'
import { inject, ref, watch, computed } from 'vue'
import { demoDocuments } from '../rag-demo.js'
import KnowledgeGenerator from '../components/KnowledgeGenerator.vue'
const work=inject('workspace'),rag=inject('retrieval'),practice=inject('practice')
const embeddingModel=ref(semanticModel),chunkSize=ref(200),chunkOverlap=ref(20)
watch([embeddingModel,()=>rag.state.baseline],()=>{
 const baselineIndex=rag.state.baseline?.run.controls.index_snapshot
 const config=baselineIndex?.embedding_snapshot.model===embeddingModel.value ? baselineIndex.chunk_config : {chunk_size:200,chunk_overlap:20}
 chunkSize.value=config.chunk_size;chunkOverlap.value=config.chunk_overlap
})
const name=ref('我的电商知识库'),documents=ref([]),error=ref(''),ack=ref(false),dirty=ref(false)
const editorDoc=(doc,expanded=false)=>({...doc,_editorKey:crypto.randomUUID(),_expanded:expanded})
const blank=()=>editorDoc({document_id:'doc_'+crypto.randomUUID().replaceAll('-',''),title:'',text:'',metadata:{source:'USER_PROVIDED',applicability:''}},true)
watch(()=>rag.state.knowledge,k=>{name.value=k?.name || '我的电商知识库';documents.value=k?cloneArtifact(k.documents).map(({document_id,title,text,metadata})=>editorDoc({document_id,title,text,metadata},k.documents.length===1)): [blank()];dirty.value=false},{immediate:true})
const mixed=computed(()=>documents.value.some(d=>d.metadata.purpose==='DEMO_POLICY_NOT_BUSINESS_COMMITMENT') && documents.value.some(d=>d.metadata.purpose!=='DEMO_POLICY_NOT_BUSINESS_COMMITMENT'))
const indices=computed(()=>practice.state.library.indices.filter(i=>i.knowledge_dataset_id===rag.state.knowledge?.knowledge_dataset_id).sort((a,b)=>b.knowledge_version-a.knowledge_version))
function demo(){documents.value=cloneArtifact(demoDocuments).map(d=>editorDoc(d));name.value='Demo · 电商知识库';dirty.value=true;ack.value=false}
function empty(){documents.value=[blank()];name.value='我的电商知识库';dirty.value=true;ack.value=false}
async function importFiles(event){error.value='';const incoming=[]
 try{for(const file of event.target.files){if(!/\.(txt|md)$/i.test(file.name) || file.size>200000)throw new Error('仅支持不超过 200 KB 的 .txt / .md 文件。');const text=await file.text();if(!text.trim())throw new Error('文件内容为空，请检查。');incoming.push({...blank(),title:file.name,text,metadata:{filename:file.name,source:'USER_UPLOADED',applicability:''}})}
  if(documents.value.length===1 && !documents.value[0].text.trim())documents.value=incoming;else documents.value.push(...incoming);dirty.value=true;ack.value=false
 }catch(e){error.value=e.message}event.target.value=''
}
async function save(){error.value='';const ids=documents.value.map(d=>d.document_id)
 if(new Set(ids).size!==ids.length){error.value='文档 ID 重复，请合并或使用不同 ID。';return}
 if(mixed.value&&!ack.value){error.value='请先确认 Demo 与自有知识的适用范围。';return}
 await rag.saveKnowledge({name:name.value,documents:documents.value.map(({document_id,title,text,metadata})=>({document_id,title,text,metadata})),...(rag.state.knowledge?{knowledge_dataset_id:rag.state.knowledge.knowledge_dataset_id}:{}),metadata:{generation_ids:[...new Set(documents.value.map(d=>d.metadata.generation_id).filter(Boolean))],source:documents.value.every(d=>d.metadata.source==='AI_GENERATED_SIMULATION')?'AI_GENERATED_SIMULATION':mixed.value?'MIXED':documents.value.every(d=>d.metadata.purpose==='DEMO_POLICY_NOT_BUSINESS_COMMITMENT')?'DEMO':'USER_PROVIDED'}})
 if(!work.state.error){dirty.value=false;await work.action('刷新知识版本',practice.library)}
}
async function build(){
 await rag.buildIndex({chunk_size:chunkSize.value,chunk_overlap:chunkOverlap.value},embeddingModel.value);if(!work.state.error)await work.action('读取知识索引',practice.library)
}
async function choose(index){await practice.useIndex(index)}
function add(){documents.value.push(blank());dirty.value=true;ack.value=false}
function adoptGenerated(draft){name.value=draft.name;documents.value=draft.documents.map(d=>editorDoc(d));dirty.value=true;ack.value=false;work.state.notice='AI 草稿已带入。请核对并保存为新版本，再建立索引。'}
</script>
<template>
 <div class="page-heading"><div><p class="eyebrow">我的知识库</p><h1>让 Agent 用上你的资料。</h1><p>补充商品说明、售后政策和常见问题，保存版本后建立索引。</p></div><button class="secondary" :disabled="!rag.state.index || !!work.state.busy" @click="work.go('chat')">去聊天体验 →</button></div>
 <p v-if="error" class="note danger" role="alert">{{error}}</p>
 <KnowledgeGenerator @adopt="adoptGenerated" />
 <section class="panel"><div class="section-heading"><h2>知识资料</h2><div class="button-row"><button class="secondary" :disabled="!!work.state.busy" @click="demo">使用 8 份 Demo 知识</button><button class="secondary" :disabled="!!work.state.busy" @click="empty">用自己的资料替换</button></div></div>
  <p class="muted">可以先体验 Demo，也可以自由新增或替换资料。这里更新知识，不会覆盖已保存实验的原始证据。</p>
  <fieldset :disabled="!!work.state.busy" @input="dirty=true;ack=false"><label>知识库名称<input v-model="name" maxlength="200" /></label><label>导入文件（.txt / .md，每个最多 200 KB）<input type="file" accept=".txt,.md" multiple @change="importFiles" /></label>
   <details v-for="(doc,i) in documents" :key="doc._editorKey" class="builder-card" :open="doc._expanded" @toggle="doc._expanded=$event.target.open"><summary>{{doc.title || `知识文档 ${i+1}`}} · {{doc.metadata.source==='AI_GENERATED_SIMULATION'?'AI 模拟知识':doc.metadata.purpose==='DEMO_POLICY_NOT_BUSINESS_COMMITMENT'?'Demo':'自有资料'}}</summary>
    <div class="form-row"><label>文档 ID<input v-model="doc.document_id" pattern="[A-Za-z0-9_-]+" /></label><label>标题<input v-model="doc.title" maxlength="200" /></label></div><label>内容<textarea v-model="doc.text" rows="6" maxlength="200000" /></label><div class="form-row"><label>资料来源<input v-model="doc.metadata.source" placeholder="如：人工整理的售后规则" /></label><label>适用条件<input v-model="doc.metadata.applicability" placeholder="如：普通商品，2026 年 10 月规则" /></label></div>
    <button class="text-button" @click="documents.splice(i,1);dirty=true">从新版本中移除</button>
   </details><div class="button-row"><button class="secondary" @click="add">＋ 添加知识</button><button class="primary" :disabled="!name.trim() || !documents.length || documents.some(d=>!d.text.trim() || !/^[A-Za-z0-9_-]+$/.test(d.document_id)) || (mixed&&!ack)" @click="save">{{rag.state.knowledge?'保存为新版本':'保存知识库'}}</button></div>
  </fieldset>
  <label class="check note warning" v-if="mixed"><input v-model="ack" type="checkbox" />我已检查 Demo 与自有政策的适用范围和冲突。系统不会自动判定哪条政策正确。</label>
  <p v-if="rag.state.knowledge" class="note positive">已保存 v{{rag.state.knowledge.version}} · {{rag.state.knowledge.documents.length}} 份资料{{dirty?' · 当前还有未保存编辑':''}}</p>
 </section>
 <section class="panel"><h2>让新资料可被检索</h2><p class="muted">聊天和评测共用所选检索模型。本地语义模型无需额外 API Key 或模型调用费；首次使用需要下载，中文效果需通过实际测试判断。</p><label>检索方式<select v-model="embeddingModel" :disabled="!!work.state.busy"><option :value="semanticModel">语义检索 · 原有 MiniLM 模型（默认）</option><option :value="lexicalModel">词汇检索 · 保留对照</option></select></label><div class="form-row"><label>每段最大字符数<input type="number" v-model.number="chunkSize" min="50" max="2000" :disabled="!!work.state.busy" /></label><label>片段重叠字符数<input type="number" v-model.number="chunkOverlap" min="0" :max="chunkSize-1" :disabled="!!work.state.busy" /></label></div><p class="muted">语义模型每段最多 256 Token；超限会提示缩短，不会静默截断。切换模型请另建测试和初测；旧实验保留原索引，不能把模型变化算成仅知识更新。</p><button class="primary" :disabled="!rag.state.knowledge || dirty || !Number.isInteger(chunkSize) || chunkSize<50 || chunkSize>2000 || !Number.isInteger(chunkOverlap) || chunkOverlap<0 || chunkOverlap>=chunkSize || !!work.state.busy" @click="build">建立当前版本索引</button><p v-if="rag.state.index" class="note positive">{{embeddingLabel(rag.state.index)}} · 索引可用 · 知识 v{{rag.state.index.knowledge_version}} · {{rag.state.index.chunks.length}} 个片段</p>
  <div class="button-row"><button class="secondary" v-for="index in indices" :key="index.index_id" :disabled="!!work.state.busy" @click="choose(index)">选用 v{{index.knowledge_version}} · {{index.embedding_snapshot.model===semanticModel?'语义':'词汇'}}{{rag.state.index?.index_id===index.index_id?' · 当前':''}}</button></div>
 </section>
 <section class="panel" v-if="rag.state.baseline"><h2>验证这次知识补充</h2><p>初测使用知识 v{{rag.state.baseline.run.controls.knowledge_snapshot.version}}。知识补充实验保留原题与检索配置，比较这次资料更新的影响。</p><p v-if="rag.state.index && rag.state.index.embedding_snapshot.model!==rag.state.baseline.run.controls.embedding_snapshot.model" class="note warning">检索模型已变化。请到「测试集」另存测试并建立新初测，不能作为这轮仅知识更新的复测。</p><p class="muted">若政策变化使正确答案也变了，请另建测试和初测，并注明原因。</p><button class="primary" :disabled="!rag.state.index || rag.state.index.index_id===rag.state.baseline.run.controls.index_snapshot.index_id || rag.state.index.embedding_snapshot.model!==rag.state.baseline.run.controls.embedding_snapshot.model || !!work.state.busy" @click="rag.state.preferredChange='KNOWLEDGE_UPDATE';work.go('improve')">记录知识补充判断 →</button></section>
</template>
