# Python Retrieval Experiments

This path runs independently of historical Skill Runs. Skill experiments keep
`REDUCED_RUNTIME_KNOWLEDGE_DISABLED`; Retrieval artifacts use
`experiment_type=RETRIEVAL`, `runtime_scope=RAG_RETRIEVAL_ENABLED`.

## Frozen identities

Knowledge Dataset is versioned and immutable. Raw full document text has a SHA256,
while chunks use NFKC/lowercase/whitespace normalization and an overlapping
character window. Chunk ID hashes document ID + index + complete normalized text
hash. Chunk snapshot hashes configuration and complete chunk records.

The local `sha256-lexical-bigram-v1` model embeds English words and character
bigrams into 1024 buckets, then normalizes L2. This is lexical retrieval, not a
pretrained semantic neural model. Its version, source identity, dimension,
normalization, cosine distance and index generation are public snapshots.

Each dataset/version/chunk/embedding identity gets a private persistent collection
under the existing JsonStore's `retrieval-chroma` directory. It is never an online
HttpClient/knowledge_base collection. Supplied vectors prevent implicit embedding
downloads. The [Chroma Python API](https://docs.trychroma.com/reference/python)
provides the collection operations; indexing is pinned to Chroma 1.5.5. Collection
membership, documents, metadata, vectors, effective index configuration and source
identities verify before/after acquisition. Retrieval cache is always disabled.

## Metrics and transitions

Labels are user-supplied binary relevant document OR chunk IDs per Case. No labels
means unavailable, not an invented zero. Unknown labels and mixed granularity are
rejected. Repeated chunks of a relevant document consume positions but receive
relevance credit only once.

The fixed candidate pool has 20 positions by default and is separate from returned
Top K (1..20). Hit@1/Hit@3 and MRR use the final candidate order. Recall@K,
Precision@K, binary NDCG@K use returned Top K. Precision divides by configured K;
unfilled result slots get no credit. NDCG uses ideal min(number of labels, K).
Each aggregate records its own valid labeled denominator. INVALID rows do not
enter any mean. Scores and distances are evidence, never improvement rules.

Case movement compares `(MRR contribution, Recall@K)` lexicographically:
greater = RETRIEVAL_IMPROVED; smaller = RETRIEVAL_REGRESSED; equal = UNCHANGED.
Missing/invalid/unlabeled pair or changed control conditions = NOT_COMPARABLE.
PARTIAL acquisition alone is not a control-condition blocker; matched valid pairs
survive. True isolation drift invalidates acquired retrieval/answer evidence.

## Provider and answers

Rewrite and LLM rerank use the explicit general-role profile and versioned prompts.
Rewrite returns one query. Rerank must return every candidate ID once, finite
0..1 scores and descending order. Any provider/format error makes retrieval
INVALID; original query fallback is prohibited. Both original/effective queries,
pre/post candidate order, rank, scores, latency and model configuration persist.

Optional grounded answers are one fixed-prompt knowledge Agent, using only the
Run's actual returned chunks; they are not the original online multi-Agent stack.
Provider credential remains in the existing process vault. No server/environment
key fallback, disk key, key-derived fingerprint or new credential architecture.
The unchanged Phase 2 evaluator applies execution validity → hard rule → four
dimension Judge thresholds → Human Review. Answer and retrieval metrics remain
separate. Reviews append immutable evidence and keep original results; an existing
Comparison is immutable and must be recreated for a new review revision.

## Single-variable experiment

Only TOP_K_CHANGE, QUERY_REWRITE_TOGGLE, RERANK_TOGGLE are supported. Explicit
reason, selected acquired Cases, human confirmation and exactly one changed field
are required. Apply freezes the authorized Retest configuration; actual readback
becomes observed_diff. Nothing mutates global online retrieval settings.

Retest freezes EvalSet, Knowledge, chunk, embedding, index, cache, implementation,
provider roles, query-rewrite/rerank prompt parameters, execution order, answer
Agent and Judge protocol. The declared toggle/Top K is the sole permitted diff.
Knowledge update requires a new Baseline. No chunk/embedding/prompt/knowledge
intervention is allowed. Comparison reports control reasons, completeness,
matched pairs and separate answer transitions. Attribution remains false with
single-run and unknown external backend revision limitations.

## API

All routes use `/experiments` and the existing store/envelope/vault:

- POST/GET knowledge-datasets; POST knowledge-datasets/{id}/index
- GET knowledge-indices/{id}
- POST/GET retrieval-evalsets
- POST/GET retrieval-runs; POST retrieval-runs/{id}/reviews
- POST/GET retrieval-changes; POST retrieval-changes/{id}/apply
- POST/GET retrieval-comparisons
- POST retrieval-rewrite-preview (not a confirmed/applied Change)
- GET retrieval-history (stable EvalSet identity and chronological Run summaries)

Text/.txt/.md upload is converted by the browser to validated document JSON.
There are no PDF, shared online collection, commercial embedding, query cache,
Knowledge rollback, login, multi-tenant or Phase 5 material-generation features.
