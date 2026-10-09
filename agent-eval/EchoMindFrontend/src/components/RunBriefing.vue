<script setup>
import { computed } from 'vue'
import { runBriefing } from '../journey-guidance.js'
import { embeddingLabel } from '../embedding-models.js'
const props=defineProps({session:Object,index:Object,cases:Array,config:Object,verifyAnswers:Boolean})
const brief=computed(()=>runBriefing(props))
</script>
<template>
 <section class="run-briefing" aria-label="运行前确认"><h3>开始前，确认这次会做什么</h3>
  <dl class="briefing-facts"><div><dt>回答 / Judge 模型</dt><dd>{{verifyAnswers?`${brief.answerModel} / ${brief.judgeModel}`:'本次不生成或检查最终回答'}}</dd></div><div><dt>知识与检索</dt><dd>知识 v{{brief.knowledgeVersion ?? '尚未建立'}} · {{embeddingLabel(index)}}</dd></div><div><dt>评测范围</dt><dd>{{brief.count}} 道题 · 调试 {{brief.debug}} · 保留 {{brief.holdout}}</dd></div><div><dt>本次配置</dt><dd>返回前 {{config?.top_k}} 条 · 改写{{config?.query_rewrite?'开启':'关闭'}} · 重排{{config?.rerank?'开启':'关闭'}} · 回答检查{{verifyAnswers?'开启':'关闭'}}</dd></div></dl>
  <p class="call-estimate">预计 <strong>{{brief.totalCalls}}</strong> 次远程模型请求 <span v-if="brief.totalCalls">· 改写 {{brief.calls.rewrite}} / 重排 {{brief.calls.rerank}} / 回答 {{brief.calls.agent}} / Judge {{brief.calls.judge}}</span></p>
  <p class="muted">按每道题一次成功请求估算，不含连接测试、改写预览、重试或独立重复运行。本地检索不产生远程模型请求；费用取决于输入输出长度与服务商账单。</p>
  <p v-if="brief.budget!=null && brief.totalCalls>brief.budget" class="note warning">预计请求数超过本次配置的 {{brief.budget}} 次调用上限，请减少范围或到模型高级设置调整预算。</p>
  <p v-if="!verifyAnswers" class="muted">这次只检查能否找到正确知识，结果不能说明 Agent 的回答质量。</p>
 </section>
</template>
