// Keep definitions aligned with experiments/retrieval_metrics.py.
export const retrievalMetrics = [
  { id:'hit_at_1', label:'Hit@1', title:'首位命中率',
    description:'有多少道题，把相关知识排在候选池的第 1 位。越高，越容易第一条就找到依据。',
    example:'例如：8 道有效题中，2 道首位命中，结果就是 0.250（25%）。',
    scope:'按固定候选池排名计算，不随返回数量 K 改变。' },
  { id:'hit_at_3', label:'Hit@3', title:'前三位命中率',
    description:'有多少道题，在候选池前 3 位中至少找到一份相关知识。',
    example:'例如：8 道有效题中，6 道在前 3 位命中，结果就是 0.750（75%）。',
    scope:'按固定候选池排名计算。即使返回 K 小于 3，也检查候选池的前 3 位。' },
  { id:'mrr', label:'MRR', title:'平均倒数排名',
    description:'关注第一份相关知识出现得有多早。每题取首次命中排名的倒数，再对有效题求平均。',
    example:'第 1 位命中得 1，第 2 位得 0.5，第 3 位得约 0.333；候选池未命中得 0。',
    scope:'按固定候选池计算，取值 0–1；越高，首次命中越靠前。' },
  { id:'recall_at_k', label:'Recall@K', title:'相关知识召回率',
    description:'返回的前 K 条知识，覆盖了多少已标注的相关知识。关注是否漏掉应找到的依据。',
    example:'例如：一题标注了 2 份相关知识，前 K 条找到 1 份，这题得 0.5。',
    scope:'每题用命中的相关知识数 ÷ 标注的相关知识总数，再求平均；文档标注时重复片段只计一次命中。' },
  { id:'precision_at_k', label:'Precision@K', title:'返回知识准确率',
    description:'返回的 K 个位置中，有多少是相关知识。关注交给 Agent 的上下文是否夹杂无关资料。',
    example:'例如：K = 3，只有 1 条计为相关命中，这题得约 0.333。',
    scope:'每题用相关命中数 ÷ K，再求平均。返回不足 K 条仍以 K 为分母；同一标注文档只计一次命中。' },
  { id:'ndcg_at_k', label:'NDCG@K', title:'归一化排序质量',
    description:'既看前 K 条有没有相关知识，也看它们是否排得靠前。越靠前的相关命中，获得的权重越高。',
    example:'同样找到一份相关知识，排第 1 位通常比排第 3 位得分高。理想排序得 1。',
    scope:'按前 K 条计算，相对理想排序归一化到 0–1，再对有效题求平均；相关性来自用户标注。' },
]

export const retrievalMetricScope = '仅统计检索成功且有相关性标注的题目。检索指标不等于最终回答正确率。'
