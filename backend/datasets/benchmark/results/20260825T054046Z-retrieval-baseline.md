# Benchmark run 20260825T054046Z-retrieval-baseline

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
| recall@6 | 0.731 | 0.806 | +0.074 |
| MRR | 0.561 | 0.708 | +0.147 |

hit@6 (any gold page retrieved): **0.843** over 121 answerable questions.

## Answering

_Not measured: OPENROUTER_API_KEY is not set. Grounded answering needs an LLM; add a key to .env or configure a different LLM_PROVIDER._

## Citations

_Not measured: OPENROUTER_API_KEY is not set. Grounded answering needs an LLM; add a key to .env or configure a different LLM_PROVIDER._

## Faithfulness

_Not measured: OPENROUTER_API_KEY is not set. Grounded answering needs an LLM; add a key to .env or configure a different LLM_PROVIDER._

## Latency

| Stage | p50 | p95 |
|---|---|---|
| retrieve | 14 ms | — |
| rerank | 1048 ms | — |
| LLM | 0 ms | 0 ms |
| **end to end** | **1065 ms** | **1372 ms** |
