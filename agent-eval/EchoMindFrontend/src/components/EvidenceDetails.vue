<script setup>
import { computed, ref, watch } from 'vue'
const props=defineProps({ data: [Object, Array], title: { type: String, default: '实验详情 · Evidence' }, copyable: {type:Boolean,default:false} })
const json=computed(()=>JSON.stringify(props.data,null,2) || '')
const copying=ref(false),copied=ref(false),notice=ref('')
watch(json,()=>{copied.value=false;notice.value=''})
async function copy(){
  if(copying.value || !json.value)return
  copying.value=true;copied.value=false;notice.value=''
  try{
    await navigator.clipboard.writeText(json.value)
    copied.value=true;notice.value='完整原始轨迹 JSON 已复制。'
  }catch{
    notice.value='无法访问剪贴板，请选中下方 JSON 手动复制。'
  }finally{copying.value=false}
}
</script>
<template>
  <details class="evidence">
    <summary>{{ title }} <span>高级信息</span></summary>
    <div class="evidence-toolbar"><p class="muted">以下为 Python API 返回的原始证据，仅供核验。</p><button v-if="copyable" type="button" class="secondary" :aria-label="`${title} · 复制完整 JSON`" :disabled="copying || !json" @click="copy">{{copying?'复制中…':copied?'✓ 已复制':'复制 JSON'}}</button></div>
    <p v-if="notice" class="copy-status" :class="{'copy-failed':!copied}" role="status">{{notice}}</p>
    <pre>{{json}}</pre>
  </details>
</template>
<style scoped>
.evidence-toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:15px}
.evidence-toolbar p{margin:0;flex:1}
.evidence-toolbar button{flex-shrink:0}
.copy-status{font-size:12px;color:var(--green);margin:10px 0}
.copy-status.copy-failed{color:#8c784a}
@media(max-width:480px){.evidence-toolbar{align-items:flex-start;flex-wrap:wrap}}
</style>
