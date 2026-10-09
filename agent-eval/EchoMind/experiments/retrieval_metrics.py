"""Binary user relevance labels; no LLM-generated ground truth or raw-score deltas."""
import math
from statistics import mean

METRICS = ('hit_at_1','hit_at_3','recall_at_k','precision_at_k','mrr','ndcg_at_k')

def case_metrics(case, results, k, ranked_candidates=None):
    documents = case.relevant_document_ids
    labels = set(documents or case.relevant_chunk_ids)
    granularity = 'document' if documents else 'chunk' if labels else 'unavailable'
    if not labels:
        return {**dict.fromkeys(METRICS), 'relevant_rank':None, 'ground_truth_granularity':granularity,
                'unavailable_reason':'NO_RELEVANCE_LABELS'}
    # For document labels, repeated chunks receive relevance credit only once.
    # Rank remains the actual chunk position. Duplicate chunks consume positions
    # and precision slots; they cannot inflate recall, DCG, or MRR.
    seen = set(); gains = []; relevant_ranks = []
    for rank, result in enumerate(results[:k],1):
        identity = result['document_id'] if documents else result['chunk_id']
        gain = int(identity in labels and identity not in seen)
        if gain: relevant_ranks.append(rank)
        gains.append(gain); seen.add(identity)
    candidates=results if ranked_candidates is None else ranked_candidates
    full_rank=next((i for i,r in enumerate(candidates,1)
                   if (r['document_id'] if documents else r['chunk_id']) in labels),None)
    dcg = sum(g/math.log2(i+2) for i,g in enumerate(gains))
    ideal = sum(1/math.log2(i+2) for i in range(min(len(labels),k)))
    return {'hit_at_1':float(full_rank==1),'hit_at_3':float(full_rank is not None and full_rank<=3),
            'recall_at_k':sum(gains)/len(labels),'precision_at_k':sum(gains)/k,
            'mrr':1/full_rank if full_rank else 0., 'ndcg_at_k':dcg/ideal if ideal else None,
            'relevant_rank':full_rank,'returned_relevant_rank':relevant_ranks[0] if relevant_ranks else None,
            'ground_truth_granularity':granularity,'rank_cutoff':len(candidates),
            'rank_scope':'FIXED_CANDIDATE_POOL','quality_cutoff':k,'unavailable_reason':None}

def aggregate(results, expected=None):
    valid = [r for r in results if r['status']=='SUCCESS']
    metrics = {}; denominators = {}
    for key in METRICS:
        values = [r['metrics'][key] for r in valid if r['metrics'].get(key) is not None]
        metrics[key] = mean(values) if values else None
        denominators[key] = len(values)
    return {**metrics,'denominators':denominators,'total':expected if expected is not None else len(results),
            'acquired':len(results),'valid':len(valid),'invalid':len(results)-len(valid),
            'unlabeled':sum(r['metrics'].get('unavailable_reason')=='NO_RELEVANCE_LABELS' for r in valid)}

def transition(before, after, blocker=None):
    if blocker: return 'NOT_COMPARABLE', blocker
    if before is None or after is None: return 'NOT_COMPARABLE','MISSING_RESULT'
    if before['status']!='SUCCESS' or after['status']!='SUCCESS': return 'NOT_COMPARABLE','INVALID_RETRIEVAL'
    if before['metrics']['mrr'] is None or after['metrics']['mrr'] is None:
        return 'NOT_COMPARABLE','NO_RELEVANCE_LABELS'
    # First relevant rank (MRR) takes precedence; recall breaks equal-rank ties.
    # Precision and raw vector/LLM scores never define improvement.
    a=(before['metrics']['mrr'],before['metrics']['recall_at_k'])
    b=(after['metrics']['mrr'],after['metrics']['recall_at_k'])
    return ('RETRIEVAL_IMPROVED' if b>a else 'RETRIEVAL_REGRESSED' if b<a else 'RETRIEVAL_UNCHANGED'), None

def answer_transition(before, after, blocker=None):
    if blocker or before is None or after is None or 'INVALID' in (before.final_status,after.final_status):
        return 'NOT_COMPARABLE'
    return before.final_status+'→'+after.final_status
