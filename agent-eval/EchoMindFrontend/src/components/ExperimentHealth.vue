<script setup>
import { computed, inject, ref } from 'vue'
const props=defineProps({view:Object})
const practice=inject('practice'),work=inject('workspace'),count=ref(2)
const partitions=computed(()=>['DEBUG','HOLDOUT'].map(id=>{
 const cases=props.view.run.case_results.filter(c=>(c.partition||'DEBUG')===id)
 const answers=props.view.effective_answer_results.filter(a=>cases.some(c=>c.case_id===a.case_id))
 const valid=answers.filter(a=>a.final_status==='PASS'||a.final_status==='FAIL')
 const retrieved=cases.filter(c=>c.status==='SUCCESS'&&c.metrics.hit_at_1!=null)
 return {id,name:id==='DEBUG'?'调试题':'保留测试',total:cases.length,labeled:retrieved.length,
  hit:retrieved.length?retrieved.reduce((s,c)=>s+c.metrics.hit_at_1,0)/retrieved.length:null,
  pass:valid.filter(a=>a.final_status==='PASS').length,valid:valid.length}
}))
</script>
<template>
 <section class="panel"><h2>检索与回答，分开判断</h2><div class="intro-cards"><section v-for="part in partitions" :key="part.id"><h3>{{part.name}} · {{part.total}} 道</h3><p>检索首位命中：{{part.hit==null?'无有效标注':(part.hit*100).toFixed(1)+'%'}} · 分母 {{part.labeled}}</p><p>回答通过：{{part.pass}} / {{part.valid}} 个有效结果</p></section></div><p class="muted">回答检查{{view.run.verify_answers?'已开启，请查看逐题判定并人工抽查':'未开启，检索分数不代表答案质量'}}。保留题在被查看和用于修改后，需要调整用途。</p><p>检索累计耗时 {{(view.run.case_results.reduce((s,c)=>s+c.latency_ms,0)/1000).toFixed(2)}} 秒 · 模型调用 {{view.run.provider_call_count}} 次。费用以模型服务账单为准。</p></section>
 <section class="panel"><h2>检查结果是否稳定</h2><p>使用本次冻结的知识、题目和配置独立重复运行。会增加模型调用；不把多次结果合并成一次改善结论。</p><div class="button-row"><label>重复次数<select v-model.number="count"><option :value="2">2 次</option><option :value="3">3 次</option><option :value="5">5 次</option></select></label><button class="secondary" :disabled="view.run.status!=='COMPLETE' || !!work.state.busy || work.state.session?.credential_status!=='PRESENT'" @click="practice.repeat(view.run.run_id,count)">运行稳定性检查</button></div>
  <template v-if="practice.state.repeat?.source_run_id===view.run.run_id"><p class="note positive">已保存 {{practice.state.repeat.repetitions}} 次独立运行 · {{practice.state.repeat.provider_call_count}} 次模型调用</p><p>Hit@1 范围：{{practice.state.repeat.summary.hit_at_1.minimum??'不可用'}} — {{practice.state.repeat.summary.hit_at_1.maximum??'不可用'}}；MRR 范围：{{practice.state.repeat.summary.mrr.minimum??'不可用'}} — {{practice.state.repeat.summary.mrr.maximum??'不可用'}}</p><details><summary>每次运行记录</summary><p v-for="a in practice.state.repeat.summary.attempts" :key="a.run_id">{{a.run_id}} · {{a.status}} · {{(a.latency_ms/1000).toFixed(2)}} 秒 · 回答有效 {{a.answer_metrics.valid??'未检查'}}</p></details></template>
 </section>
</template>
