<script setup>
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { createWorkspace } from './workspace.js'
import SetupPage from './pages/SetupPage.vue'
import DefinePage from './pages/DefinePage.vue'
import EvaluatePage from './pages/EvaluatePage.vue'
import ImprovePage from './pages/ImprovePage.vue'
import ComparePage from './pages/ComparePage.vue'
import StatusBadge from './components/StatusBadge.vue'
import RetrievalPage from './pages/RetrievalPage.vue'
import { createRetrievalWorkspace } from './retrieval-workspace.js'
import { createCareerWorkspace } from './career-workspace.js'
import CareerPage from './pages/CareerPage.vue'
import { prepareWorkspace,api } from './api.js'
import { createPracticeWorkspace } from './practice-workspace.js'
import JourneyGuide from './components/JourneyGuide.vue'
import {createAiAssistance,restoreAiDrafts} from './ai-assistance.js'
import ChatPage from './pages/ChatPage.vue'
import KnowledgePage from './pages/KnowledgePage.vue'
import PracticeTestsPage from './pages/PracticeTestsPage.vue'
const anonymousWorkspace = ref(false)
provide('anonymousWorkspace', anonymousWorkspace)
const work = createWorkspace(), { state } = work
const rag = createRetrievalWorkspace(work)
const ai=createAiAssistance();provide('ai',ai)
const mode = ref(localStorage.getItem('echomind.experiment-mode') === 'AGENT_BEHAVIOR' ? 'AGENT_BEHAVIOR' : 'RETRIEVAL')
const practice=createPracticeWorkspace(work,rag)
provide('practice',practice)
const career=createCareerWorkspace(work,rag,mode)
provide('career',career)
let ragReady=false
watch(()=>state.session?.provider_session_id,()=>{if(mode.value==='RETRIEVAL' && ragReady)rag.persist()})
provide('workspace', work)
provide('retrieval', rag)
provide('experimentMode', mode)
onMounted(async () => {
  const identity = await work.action('建立浏览器工作区', () => prepareWorkspace())
  if (state.error) return
  anonymousWorkspace.value = !!identity?.isolated
  await work.initialize()
  if(mode.value==='RETRIEVAL'){await rag.action('恢复检索实验',rag.restore);ragReady=true}
  await work.action('读取聊天与知识库',practice.restore)
  await work.action('恢复 AI 生成草稿',()=>restoreAiDrafts(ai,api))
}); onUnmounted(work.dispose)
async function switchMode(){localStorage.setItem('echomind.experiment-mode',mode.value);showHistory.value=false;
  ragReady=false;if(mode.value==='RETRIEVAL'){await rag.action('读取检索实验',rag.restore);ragReady=true}}
async function navigate(step){if(['chat','knowledge'].includes(step) && mode.value!=='RETRIEVAL'){mode.value='RETRIEVAL';await switchMode()}work.go(step)}
async function sync(){if(mode.value==='RETRIEVAL')await rag.action('同步检索状态',rag.restore);else await work.action('同步后端状态',work.restore)}
function reset(){if(mode.value==='RETRIEVAL'){rag.reset();work.go('define')}else work.reset();showHistory.value=false}
const showHistory = ref(false)
const navigation = [ ['chat','体验','直接与电商 Agent 聊天'], ['knowledge','知识库','补充自己的资料'], ['setup', 'Setup', '配置模型'], ['define', 'Define', '定义目标与测试'],
  ['evaluate', 'Evaluate', '运行与找问题'], ['improve', 'Improve', '判断与修改'], ['compare', 'Compare', '查看前后变化'], ['career','Career / Export','复盘与求职材料'] ]
const completed=computed(()=>{const r=mode.value==='RETRIEVAL'?rag.state:state;return [state.session?.text_connection_status==='READY'&&state.session?.credential_status==='PRESENT',mode.value==='RETRIEVAL'?!!r.index:!!r.evalSet,!!r.evalSet,!!r.baseline,mode.value==='RETRIEVAL'?!!r.change:!!r.decision,r.change?.implemented_status==='APPLIED',!!r.retest,!!r.comparison]})
const progress=computed(()=>{const next=completed.value.findIndex(v=>!v);return next<0?8:next})
const steps = ['配置模型','定义目标','创建测试','Baseline','找问题','修改','Retest','看结果']
const projectName = run => state.evalSets.find(e => e.eval_set_id === run.eval_set_id)?.metadata.objective?.name || '电商客服实验'
async function open(id) { if(mode.value==='RETRIEVAL'){await rag.action('打开检索实验',()=>rag.open(id));work.go('evaluate')}else await work.action('打开历史实验', () => work.openHistory(id)); showHistory.value = false }
async function history() { if(mode.value==='RETRIEVAL')await rag.action('读取检索历史',rag.restore);else await work.action('读取历史实验', work.history); showHistory.value = true }
const visibleHistory=computed(()=>mode.value==='RETRIEVAL'?rag.state.history:state.history)
const projectTitle=computed(()=>mode.value==='RETRIEVAL' ? rag.state.evalSet?.name || rag.state.knowledge?.name || '新检索实验' : state.evalSet?.metadata.objective?.name || '新产品实验')
</script>
<template>
  <div class="workspace-shell">
    <aside class="sidebar"><button class="brand" @click="work.go('welcome')"><span class="brand-symbol">AE<span /></span><strong>Agent Eval<small>体验 · 评测 · 项目实践</small></strong></button>
      <label class="experiment-mode">实验路径<select v-model="mode" :disabled="!!state.busy" @change="switchMode"><option value="AGENT_BEHAVIOR">电商 Agent 行为 / Skill</option><option value="RETRIEVAL">电商 Agent · RAG 知识</option></select></label><div class="workspace-label"><span class="eyebrow">我的实验工作台</span><p>{{ projectTitle }}</p></div>
      <nav aria-label="主导航"><button v-for="([id, english, label], index) in navigation" :key="id" :class="{ selected: state.step === id }" :disabled="!!state.busy" @click="navigate(id)"><span class="nav-number">0{{ index + 1 }}</span><span><strong>{{ english }}</strong><small>{{ label }}</small></span><span v-if="state.step === id" class="nav-dot" /></button></nav>
      <div class="sidebar-bottom"><button class="secondary" :disabled="!!state.busy" @click="reset()">＋ 开始新实验</button><button class="text-button" :disabled="!!state.busy" @click="history">历史实验 <span>↗</span></button><div class="scope-chip"><span class="tiny-dot" />{{mode === 'RETRIEVAL' ? '受控 RAG 检索实验' : '受控 Agent / Skill 实验'}}<p>{{mode === 'RETRIEVAL' ? '固定知识与索引，缓存关闭' : '此路径保持 RAG / Memory 关闭'}}</p></div></div>
    </aside>
    <div class="workspace-body"><header class="topbar"><div><span class="breadcrumb">WORKSPACE</span><span class="separator">/</span><strong>{{ projectTitle }}</strong></div><button class="sync" :disabled="!!state.busy" @click="sync">↻ 同步状态</button></header>
      <div class="progress-strip" aria-label="实验进度"><div v-for="(label, index) in steps" :key="label" :class="{ done: completed[index], current: index === progress }"><span>{{ completed[index] ? '✓' : index + 1 }}</span><small>{{ label }}</small></div></div>
      <main>
        <div v-if="anonymousWorkspace" class="note" role="status"><strong>此浏览器的独立工作区 · 无需注册</strong><p>API Key、实验、知识库和材料仅在本工作区使用。浏览器身份保留 90 天；清除 Cookie、使用无痕模式或换设备后，旧记录无法自动找回。服务器重启后需要重新输入模型 Key。</p></div>
        <div v-if="state.error" class="error-banner" role="alert"><div><small v-if="state.error.operation">{{ state.error.operation }} · </small><strong>{{ state.error.title }}</strong><p>{{ state.error.message }}</p></div><button class="text-button" @click="state.error = null">关闭</button></div>
        <div v-if="state.notice" class="note positive" role="status">{{ state.notice }}</div>
        <p v-if="state.busy" class="busy-label" role="status"><span class="spinner small" />{{ state.busy }}</p>
        <JourneyGuide v-if="mode==='RETRIEVAL' && !showHistory" :key="state.step" :step="state.step" @navigate="navigate" />
        <section v-if="showHistory" class="panel history-panel"><div class="section-heading"><div><span class="eyebrow">SAVED EXPERIMENTS</span><h2>真实保存的实验</h2></div><button class="text-button" @click="showHistory = false">返回工作台</button></div><p class="muted">从 Python 后端读取记录，刷新不会丢失已保存的实验。模型 Key 需要重新输入时，会单独提醒。</p>
          <p v-if="!visibleHistory.length" class="empty">还没有保存的 Run，开始第一次实验吧。</p><button v-for="run in visibleHistory" :key="run.run_id" class="history-row" :disabled="!!state.busy" @click="open(run.run_id)"><span><strong>{{ mode === 'RETRIEVAL' ? run.name : projectName(run) }}</strong><small>{{ run.run_type === 'BASELINE' ? 'Baseline · 修改前' : 'Retest · 修改后' }} / {{ new Date(run.created_at).toLocaleString('zh-CN') }}</small></span><StatusBadge :status="run.status" /><span>→</span></button>
        </section>
        <template v-else-if="state.step === 'welcome'">
          <section class="welcome"><div class="welcome-copy"><div class="eyebrow welcome-tag"><span class="tiny-dot" />AI PRODUCT PRACTICE</div><h1>先用 Agent。<br /><em>再用证据</em> 改进它。</h1><p>用自己的电商知识聊天，找到具体问题，<br class="desktop-only" />通过评测验证修改，整理成能讲清楚的项目。</p><button class="primary large" :disabled="!!state.busy" @click="work.go('setup')">连接自己的模型 <span>→</span></button><button class="secondary large" :disabled="!!state.busy" @click="navigate('chat')">体验电商 Agent →</button><small class="welcome-caption">你来做产品判断，每一步都有证据。</small></div>
            <div class="welcome-art" aria-hidden="true"><div class="art-top"><span class="tiny-dot" /> 一个可以解释的优化过程 <span>↗</span></div><div class="art-stage"><span class="stage-icon">01</span><div><small>BEFORE</small><h3>先聊天，发现具体问题</h3></div><span class="art-label">Baseline</span></div><div class="art-connector">↓</div><div class="art-stage selected-stage"><span class="stage-icon">02</span><div><small>YOUR DECISION</small><h3>补知识或调整检索策略</h3></div></div><div class="art-connector">↓</div><div class="art-stage"><span class="stage-icon">03</span><div><small>AFTER</small><h3>看到改善，也看到退化</h3></div><span class="art-label">Retest</span></div><div class="art-footer"><span>每个 Case</span><strong>都有可追溯的判定依据</strong></div></div>
          </section>
          <div class="intro-cards"><section><span class="intro-icon">↗</span><h3>让目标可以被验证</h3><p>把“回答更好”写成具体测试与期望行为。</p></section><section><span class="intro-icon">◎</span><h3>练习真正的产品判断</h3><p>依据失败证据选择方案，明确预期与副作用。</p></section><section><span class="intro-icon">⇄</span><h3>用前后对照说清结果</h3><p>哪题变好、哪题退化、哪些还不能比较。</p></section></div><p class="welcome-scope">当前仅提供一个电商 Agent，基于 RAG 回答知识库范围内的问题。支持自有知识、真实对话、受控评测，以及项目复盘、简历草稿和面试材料。</p>
        </template>
        <ChatPage v-else-if="state.step === 'chat'" /><KnowledgePage v-else-if="state.step === 'knowledge'" /><PracticeTestsPage v-else-if="state.step === 'define' && mode === 'RETRIEVAL'" /><CareerPage v-else-if="state.step === 'career'" /><SetupPage v-else-if="state.step === 'setup'" /><RetrievalPage v-else-if="mode === 'RETRIEVAL'" :step="state.step" /><DefinePage v-else-if="state.step === 'define'" /><EvaluatePage v-else-if="state.step === 'evaluate'" /><ImprovePage v-else-if="state.step === 'improve'" /><ComparePage v-else-if="state.step === 'compare'" />
      </main><footer class="workspace-footer"><span>Agent Eval · 每次判断，都有依据。</span><span>{{ anonymousWorkspace ? '此浏览器的独立工作区' : '本地工作区' }}</span></footer>
    </div>
  </div>
</template>
