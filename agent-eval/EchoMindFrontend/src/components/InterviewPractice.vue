<script setup>
import { inject, ref } from 'vue'
import { api } from '../api.js'
const props=defineProps({materialId:String,question:Object})
const career=inject('career')
const claimLabel=id=>career?.state.evidence?.claims.find(c=>c.claim_id===id)?.claim_text || id
const work=inject('workspace'),answer=ref(''),limits=ref(''),citations=ref([]),result=ref(null)
async function save(){await work.action('保存面试练习与自检',async()=>{result.value=await api.post('/interview-attempts',{material_id:props.materialId,question_id:props.question.question_id,answer:answer.value,limitations:limits.value,claim_ids:citations.value})})}
</script>
<template>
 <div class="practice-review"><label>先写你的回答<textarea v-model="answer" rows="4" placeholder="说明自己的判断、操作和结果，再对照参考提纲。" /></label><div><p>这段回答引用了哪些实验事实？</p><label class="check" v-for="id in question.claim_ids" :key="id"><input v-model="citations" type="checkbox" :value="id" />{{claimLabel(id)}}<small class="muted">来源 {{id}}</small></label></div><label>哪些地方仍不能下结论？<textarea v-model="limits" rows="2" /></label><button class="secondary" :disabled="!answer.trim() || !!work.state.busy" @click="save">保存练习并检查完整性</button><p v-if="result" class="note">{{result.checks.evidence_referenced?'已选择事实引用':'待补充：引用具体实验事实'}}；{{result.checks.limitations_written?'已填写结论边界':'待补充：说明证据局限'}}。此检查只确认填写完整性，不判定回答正确或预测面试结果。</p></div>
</template>
