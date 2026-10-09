<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { retrievalMetricScope } from '../retrieval-metric-help.js'
defineProps({ metric:{type:Object,required:true} })
const tooltipId=useId(),button=ref(null),tooltip=ref(null),open=ref(false),focused=ref(false)
const left=ref(0),above=ref(false)
const placement=computed(()=>({left:`${left.value}px`,...(above.value?{bottom:'100%'}:{top:'100%'})}))
function position(){
  if(!button.value || !tooltip.value)return
  const anchor=button.value.getBoundingClientRect(),width=tooltip.value.offsetWidth,height=tooltip.value.offsetHeight
  left.value=Math.max(16,Math.min(anchor.left,window.innerWidth-width-16))-anchor.left
  above.value=anchor.bottom+height>window.innerHeight-12 && anchor.top>=height+12
}
watch(open,async visible=>{if(visible){await nextTick();position()}})
onMounted(()=>window.addEventListener('resize',position))
onUnmounted(()=>window.removeEventListener('resize',position))
</script>
<template>
  <span class="metric-help" @mouseenter="open=true" @mouseleave="!focused && (open=false)">
    <button ref="button" type="button" class="metric-help-button" :aria-label="`${metric.label} 指标说明`" :aria-describedby="open?tooltipId:undefined"
      @focus="focused=true;open=true" @blur="focused=false;open=false" @click="open=true" @keydown.esc.stop="open=false">
      <span aria-hidden="true">?</span>
    </button>
    <span v-show="open" :id="tooltipId" ref="tooltip" role="tooltip" class="metric-help-popup" :class="{'above':above}" :style="placement">
      <span class="metric-help-content">
        <span class="metric-help-title">{{metric.title}}</span>
        <span>{{metric.description}}</span>
        <span class="metric-help-example">{{metric.example}}</span>
        <span class="metric-help-scope">{{metric.scope}}<br />{{retrievalMetricScope}}</span>
      </span>
    </span>
  </span>
</template>
<style scoped>
.metric-help{position:relative;display:inline-flex;vertical-align:middle;flex-shrink:0}
.metric-help-button{display:inline-grid;place-items:center;width:24px;height:24px;padding:0;border-radius:50%;color:#8b9a92}
.metric-help-button>span{display:grid;place-items:center;width:16px;height:16px;border:1px solid currentColor;border-radius:50%;font-size:11px;font-weight:600;line-height:1}
.metric-help-button:hover,.metric-help-button:focus-visible{color:var(--green);background:#edf3ef}
.metric-help-popup{position:absolute;z-index:40;display:block;width:min(304px,calc(100vw - 32px));padding-top:8px;text-align:left;white-space:normal;font-size:12px;font-weight:400;line-height:1.75;color:#3e5147}
.metric-help-popup.above{padding-top:0;padding-bottom:8px}
.metric-help-content{display:grid;gap:9px;background:#fff;border:1px solid #dce6df;border-radius:10px;padding:16px;box-shadow:0 8px 28px #24382c1c}
.metric-help-title{font-size:13px;font-weight:650;color:#2c4937}
.metric-help-example{background:#f1f6f3;border-radius:6px;padding:8px 10px;color:#486452}
.metric-help-scope{border-top:1px solid #e8eeea;padding-top:9px;color:#79877f;font-size:11px}
</style>
