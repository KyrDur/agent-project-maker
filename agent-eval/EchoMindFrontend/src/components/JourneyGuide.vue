<script setup>
import { computed, inject, ref } from 'vue'
import { journey, nextJourneyStep } from '../journey-guidance.js'
const props=defineProps({step:String})
const emit=defineEmits(['navigate'])
const work=inject('workspace'),rag=inject('retrieval')
const expanded=ref(['welcome','setup','knowledge','chat','define','improve','career'].includes(props.step)),showRoute=ref(false)
const current=computed(()=>journey.find(s=>s.id===props.step))
const next=computed(()=>nextJourneyStep(work.state.session,rag.state))
</script>
<template>
 <section class="journey-guide" aria-label="操作引导">
  <div class="guide-heading"><div><p class="guide-kicker">{{current?'本页操作引导':'第一次使用，从这里开始'}}</p><h2>{{current?.goal || '连接模型 → 准备知识 → 聊天 → 评测 → 整理材料'}}</h2></div><button class="text-button" :aria-expanded="expanded" @click="expanded=!expanded">{{expanded?'收起说明':'展开详细说明'}} <span aria-hidden="true">{{expanded?'−':'＋'}}</span></button></div>
  <div v-if="expanded" class="guide-body">
   <ol v-if="current" class="guide-steps"><li v-for="(text,i) in current.steps" :key="text"><span>{{i+1}}</span><p>{{text}}</p></li></ol>
   <p v-else>当前只有电商知识问答场景。你提供 API Key 与知识，自己定义测试标准、选择修改；系统保存真实结果，并帮助生成项目复盘、简历草稿和面试材料。</p>
   <p v-if="current" class="guide-tip">{{current.tip}}</p>
   <div class="button-row"><button v-if="!current" class="primary" :disabled="!!work.state.busy" @click="emit('navigate',next.id)">{{next.label}} →</button><button class="text-button" :aria-expanded="showRoute" @click="showRoute=!showRoute">{{showRoute?'收起完整流程':'查看完整使用流程'}} →</button></div>
   <ol v-if="showRoute" class="journey-route"><li v-for="(stage,i) in journey" :key="stage.id"><span>{{i+1}}</span><div><button class="text-button" :disabled="!!work.state.busy" @click="emit('navigate',stage.id)">{{stage.label}} →</button><p>{{stage.goal}}</p></div></li></ol>
   <details class="guide-glossary"><summary>几个容易混淆的词</summary><dl><dt>知识与索引</dt><dd>知识是原始资料；索引是用这份资料建立的检索表示。先保存，再建索引，才能用于聊天。</dd><dt>Embedding 与聊天模型</dt><dd>Embedding 负责找相关知识；聊天模型负责回答。本地 MiniLM 不消耗聊天 API 调用额度。</dd><dt>Baseline / Retest</dt><dd>第一次评测／修改后的同题复测。比较时必须核对冻结条件。</dd><dt>Judge / INVALID</dt><dd>Judge 是检查回答的模型，判定仍需核验。INVALID 是执行或采集无效，不能当作质量失败。</dd></dl></details>
  </div>
 </section>
</template>
