# Benchmark run 20260825T055154Z-retrieval-final

150 questions (121 answerable, 29 unanswerable) · 0 error(s)

## Configuration

| Setting | Value |
|---|---|
| candidate k (pre-rerank) | 20 |
| evidence k (post-rerank) | 6 |
| chunk size / overlap | 600 / 80 tokens |
| reranker | `jinaai/jina-reranker-v1-turbo-en` |
| LLM | _not run_ |

## Retrieval

Gold labels are page-level. "Before" is the raw semantic candidate order,
"after" is post-rerank, both measured at k=6.

| Metric | Before rerank | After rerank | Lift |
|---|---|---|---|
| recall@6 | 0.742 | 0.821 | +0.079 |
| MRR | 0.585 | 0.719 | +0.134 |

hit@6 (any gold page retrieved): **0.876** over 121 answerable questions.

**Evidence sufficiency: 0.884** — the fraction of questions whose assembled evidence blocks actually contain every required
answer term. This is the ceiling on answer correctness: no model can ground an answer in evidence it was never handed, so the gap between this and
correctness below is the model's own contribution, and the gap between this and 1.0 is retrieval's.

## Answering

_Not measured: OPENROUTER_API_KEY is not set. Grounded answering needs an LLM; add a key to .env or configure a different LLM_PROVIDER._

## Citations

_Not measured: OPENROUTER_API_KEY is not set. Grounded answering needs an LLM; add a key to .env or configure a different LLM_PROVIDER._

## Faithfulness

_Not measured: OPENROUTER_API_KEY is not set. Grounded answering needs an LLM; add a key to .env or configure a different LLM_PROVIDER._

## Latency

| Stage | p50 | p95 |
|---|---|---|
| retrieve | 13 ms | — |
| rerank | 1221 ms | — |
| LLM | 0 ms | 0 ms |
| **end to end** | **1239 ms** | **1573 ms** |
